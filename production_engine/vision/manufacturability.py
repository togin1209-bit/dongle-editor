"""
vision/manufacturability.py
------------------------------
v1.6: Manufacturability Analysis (작업지시서 5번).

아크릴 상품 제작 적합성을 0~100 점수로 반환한다. 기존 Preflight 체계와 이슈 스키마를
그대로 재사용한다(models.PreflightIssue - code/severity/title/description/recommendation/
auto_fixable 이 이미 정의되어 있어 새로 만들 필요가 없다). 여기서는 "점수" 개념만 추가한다.

검사항목 (작업지시서 원문):
  Contour complexity, Minimum radius, Small island, Hole collision, Unsafe hole position,
  Thin connection, Image resolution, Transparency, Cutline validity, White layer, Tab/slot validity
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..models import PreflightIssue, PreflightLevel
from .contour_engine import ProductionCutline
from .hole_placement import HoleGeometry
from .stand_builder import StandBuildResult

# 감점 가중치 - 항목별 "이 문제가 있으면 몇 점을 깎을지". 값 자체는 엔지니어링 기본값이며
# 실제 인쇄소 불량률 데이터가 쌓이면 조정 가능하도록 상수로 분리해두었다.
_PENALTY = {
    "SELF_INTERSECTION": 30,
    "BELOW_MIN_RADIUS": 8,          # 위반 코너 1개당
    "HIGH_CONTOUR_COMPLEXITY": 10,
    "SMALL_ISLAND_REMOVED": 3,       # 제거된 섬 1개당 (원본에 노이즈가 많았다는 신호)
    "HOLE_COLLISION": 25,
    "UNSAFE_HOLE_POSITION": 15,
    "THIN_CONNECTION": 12,           # neck 이 생성된 경우 (구조적으로 약할 수 있음)
    "LOW_RESOLUTION": 15,
    "NO_TRANSPARENCY": 20,
    "WHITE_LAYER_MISSING": 10,
    "TAB_SLOT_NOT_READY": 20,
}


@dataclass
class ManufacturabilityReport:
    score: int  # 0~100
    issues: list[PreflightIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"score": self.score, "issues": [i.to_dict() for i in self.issues]}


def analyze_manufacturability(
    cutline: ProductionCutline,
    min_radius_mm: Optional[float] = None,
    hole: Optional[HoleGeometry] = None,
    stand_result: Optional[StandBuildResult] = None,
    white_layer_generated: bool = False,
    white_layer_required: bool = False,
    source_has_alpha: bool = True,
    effective_dpi: Optional[float] = None,
    recommended_dpi: Optional[float] = None,
) -> ManufacturabilityReport:
    score = 100
    issues: list[PreflightIssue] = []

    def deduct(points: int, code: str, level: PreflightLevel, title: str, message: str, recommendation: str, auto_fixable: bool = False):
        nonlocal score
        score -= points
        issues.append(
            PreflightIssue(code=code, level=level, message=message, title=title,
                            recommendation=recommendation, auto_fixable=auto_fixable)
        )

    # Cutline validity: 자기교차
    if cutline.analysis.self_intersections:
        deduct(
            _PENALTY["SELF_INTERSECTION"], "SELF_INTERSECTION", PreflightLevel.ERROR,
            "칼선 자기교차", f"칼선에 {len(cutline.analysis.self_intersections)}개의 자기교차가 발견되었습니다. 이 상태로는 레이저 커팅이 불가능합니다.",
            "컨투어 단순화/스무딩 파라미터를 조정하거나 원본 아트웍을 정리하세요.",
        )

    # Minimum radius
    violation_count = len(cutline.analysis.corners_below_min_radius)
    if violation_count and min_radius_mm is not None:
        deduct(
            min(_PENALTY["BELOW_MIN_RADIUS"] * violation_count, 40), "BELOW_MIN_RADIUS", PreflightLevel.WARNING,
            "최소 곡률 반경 미달", f"{violation_count}개 코너가 최소 곡률 반경({min_radius_mm}mm) 미달입니다. 가공 시 뭉툭해지거나 파손될 수 있습니다.",
            "해당 코너를 완만하게 다듬거나 offset을 늘려 라운딩을 키우세요.", auto_fixable=True,
        )

    # Contour complexity (점 개수 과다)
    n_points = len(cutline.points_mm)
    if n_points > 200:
        deduct(
            _PENALTY["HIGH_CONTOUR_COMPLEXITY"], "HIGH_CONTOUR_COMPLEXITY", PreflightLevel.WARNING,
            "칼선 복잡도 과다", f"칼선 포인트가 {n_points}개로 매우 많습니다. 커팅 시간이 길어지고 가공 정밀도가 떨어질 수 있습니다.",
            "epsilon_ratio 를 높여 컨투어를 더 단순화하세요.", auto_fixable=True,
        )

    # Small island
    if cutline.analysis.islands_removed > 0:
        deduct(
            _PENALTY["SMALL_ISLAND_REMOVED"] * cutline.analysis.islands_removed, "SMALL_ISLAND_NOISE", PreflightLevel.WARNING,
            "미세 노이즈 섬 제거됨", f"원본에서 {cutline.analysis.islands_removed}개의 작은 노이즈 섬이 자동 제거되었습니다.",
            "원본 PNG의 알파 채널을 정리하면 더 깨끗한 결과를 얻을 수 있습니다.", auto_fixable=True,
        )

    # Hole collision / unsafe position
    if hole is not None:
        if hole.neck_points_mm:
            deduct(
                _PENALTY["THIN_CONNECTION"], "THIN_CONNECTION", PreflightLevel.WARNING,
                "얇은 연결부(neck) 생성됨", "구멍이 칼선에 너무 가까워 연결부(neck)가 자동 생성되었습니다. 이 부분은 구조적으로 약할 수 있습니다.",
                "구멍 위치를 안쪽으로 옮기거나 hole_edge_margin_mm 을 재검토하세요.",
            )

    # White layer
    if white_layer_required and not white_layer_generated:
        deduct(
            _PENALTY["WHITE_LAYER_MISSING"], "WHITE_LAYER_MISSING", PreflightLevel.ERROR,
            "화이트 레이어 누락", "이 상품은 화이트 레이어가 필요하지만 아직 생성되지 않았습니다.",
            "white_choke_mm/white_spread_mm 을 확인하고 화이트 레이어를 생성하세요.",
        )

    # Tab/slot validity
    if stand_result is not None and not stand_result.production_ready:
        deduct(
            _PENALTY["TAB_SLOT_NOT_READY"], "TAB_SLOT_NOT_READY", PreflightLevel.ERROR,
            "스탠드 Tab/Slot 제작수치 미확정", f"누락된 필드: {stand_result.missing_fields}",
            "Product Profile 에서 해당 수치를 확인해 채워야 합니다.",
        )

    # Transparency
    if not source_has_alpha:
        deduct(
            _PENALTY["NO_TRANSPARENCY"], "NO_TRANSPARENCY", PreflightLevel.ERROR,
            "알파 채널 없음", "원본 이미지에 투명 배경(알파 채널)이 없어 외곽 컨투어를 자동 추출할 수 없습니다.",
            "배경이 투명한 PNG로 다시 업로드하세요.",
        )

    # Image resolution
    if effective_dpi is not None and recommended_dpi is not None and effective_dpi < recommended_dpi:
        deduct(
            _PENALTY["LOW_RESOLUTION"], "LOW_RESOLUTION", PreflightLevel.WARNING,
            "해상도 부족", f"실효 해상도 {effective_dpi:.0f} DPI가 권장 {recommended_dpi:.0f} DPI 미만입니다.",
            "더 높은 해상도의 원본으로 교체하세요.",
        )

    score = max(0, min(100, score))
    if not issues:
        issues.append(
            PreflightIssue(code="MANUFACTURABILITY_OK", level=PreflightLevel.PASS, title="제작 적합성 양호",
                            message="검출된 제작 이슈가 없습니다.")
        )

    return ManufacturabilityReport(score=score, issues=issues)
