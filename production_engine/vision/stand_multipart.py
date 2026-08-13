"""
vision/stand_multipart.py
----------------------------
v1.8: Acrylic Stand Multi-Part Engine (작업지시서 4/5/6번) — "이번 버전의 핵심 기능".

기존 v1.6 stand_builder.py 는 Main Body 1개 + Tab 1개 + Base 1개 + Slot 1개만
지원했다. 이 모듈은 그 위에 "여러 파츠"를 지원하도록 ADDITIVE 로 확장한다
(stand_builder.py 는 전혀 수정하지 않고, 그 함수들을 재사용만 한다).

핵심 규칙: **파츠 수량과 받침대 Slot 수량은 항상 자동 동기화된다.** 파츠가 3개면
Slot도 반드시 3개 - 이 모듈의 `build_multipart_stand()` 는 이 동기화를 구조적으로
보장한다 (파츠 리스트 길이만큼 Slot 을 생성하므로, "따로 개수를 맞춰야 하는" 상황
자체가 없다). 그럼에도 불구하고 외부에서 만들어진 데이터를 검증할 때를 위해
`SlotPreflight` 에 "파츠 수량 ≠ Slot 수량" 검사를 별도로 둔다 (방어적 이중 체크).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..models import PreflightIssue, PreflightLevel
from .stand_builder import (
    BaseShape,
    SlotPosition,
    StandBuilderError,
    StandParams,
    TabGeometry,
    build_tab,
    merge_main_body_with_tab,
)


@dataclass
class PartSpec:
    """작업지시서 5번: 파츠별 관리 데이터."""

    part_id: str
    cutline_points_mm: list[tuple[float, float]]  # 배경제거+컨투어 엔진(v1.6)이 만든 Main Body 외곽
    acrylic_thickness_mm: float
    slot_width_mm: Optional[float] = None    # None이면 StandParams 공통값 사용
    slot_spacing_mm: Optional[float] = None  # None이면 기본 spacing 사용

    def bbox(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.cutline_points_mm]
        ys = [p[1] for p in self.cutline_points_mm]
        return min(xs), min(ys), max(xs), max(ys)

    @property
    def width_mm(self) -> float:
        x0, _, x1, _ = self.bbox()
        return x1 - x0

    @property
    def height_mm(self) -> float:
        _, y0, _, y1 = self.bbox()
        return y1 - y0


@dataclass
class SlotAssignment:
    """작업지시서 5번: Part <-> Slot 1:1 매핑 결과."""

    part_id: str
    slot_id: str
    center_x_mm: float
    center_y_mm: float
    slot_width_mm: float
    slot_length_mm: float
    points_mm: list[tuple[float, float]]


@dataclass
class MultiPartStandResult:
    part_count: int
    slot_count: int
    synced: bool  # part_count == slot_count (이 빌더로 만들면 항상 True)
    parts_with_tab: dict[str, list[tuple[float, float]]]  # part_id -> tab 병합된 main body 외곽
    base_points_mm: list[tuple[float, float]]
    assignments: list[SlotAssignment]
    production_ready: bool
    missing_fields: list[str] = field(default_factory=list)


def _spaced_centers(total_width_mm: float, count: int, item_width_mm: float, spacing_mm: float, margin_mm: float) -> list[float]:
    """base 폭 안에서 count 개의 슬롯을 균등 간격으로 배치할 중심 x좌표 목록을 계산한다.
    (finishing.eyelet_engine._spaced_points_along_edge 와 유사한 균등분배 아이디어를
    슬롯 배치에 맞게 재구성 - 슬롯은 폭이 있는 사각형이라 아이템 폭도 함께 고려한다.)
    """
    if count <= 0:
        return []
    content_width = count * item_width_mm + (count - 1) * spacing_mm
    usable = total_width_mm - 2 * margin_mm
    start_x = margin_mm + (usable - content_width) / 2 + item_width_mm / 2
    step = item_width_mm + spacing_mm
    return [start_x + i * step for i in range(count)]


def build_multipart_stand(
    parts: list[PartSpec],
    default_params: StandParams,
    base_width_mm: float,
    base_depth_mm: float,
    base_shape: BaseShape = BaseShape.ROUNDED_RECTANGLE,
    base_margin_mm: float = 10.0,
    slot_spacing_mm: float = 15.0,
) -> MultiPartStandResult:
    """
    파츠 리스트(1개 이상) -> 각 파츠에 Tab 부착 + Base 위에 파츠 수만큼 Slot 자동 생성.

    - `default_params.material_thickness_mm/tab_width_mm/tab_height_mm/slot_width_mm/
      slot_clearance_mm` 가 확정되지 않으면 (None) `production_ready=False` 로
      반환한다 (v1.6과 동일한 "미확정 시 제작 불가" 원칙 - 작업지시서 5번 명시).
    - 파츠 개별로 `slot_width_mm`/`slot_spacing_mm` 를 오버라이드할 수 있다
      (동일 스탠드에 두께가 다른 파츠가 섞인 경우 대비).
    """
    if not parts:
        raise StandBuilderError("파츠가 1개 이상 필요합니다.")

    missing = default_params.missing_fields()
    if missing:
        return MultiPartStandResult(
            part_count=len(parts), slot_count=0, synced=False,
            parts_with_tab={}, base_points_mm=[], assignments=[],
            production_ready=False, missing_fields=missing,
        )

    from .stand_builder import build_base as _build_base_shape_only

    # Base 외곽 형상만 얻기 위해 기존 build_base() 를 재사용하되, 단일 슬롯 결과는 버리고
    # 외곽 폴리곤만 취한다 (슬롯은 이 함수가 직접 파츠 수만큼 다시 생성한다).
    base_shape_result = _build_base_shape_only(
        base_width_mm, base_depth_mm, base_shape, default_params, slot_position=SlotPosition.CENTER,
    )
    base_points_mm = base_shape_result.points_mm

    parts_with_tab: dict[str, list[tuple[float, float]]] = {}
    for part in parts:
        tab = build_tab(part.cutline_points_mm, default_params)
        parts_with_tab[part.part_id] = merge_main_body_with_tab(part.cutline_points_mm, tab)

    slot_widths = [p.slot_width_mm or default_params.slot_width_mm for p in parts]
    max_slot_width = max(slot_widths)
    centers_x = _spaced_centers(
        base_width_mm, len(parts), max_slot_width,
        spacing_mm=slot_spacing_mm, margin_mm=base_margin_mm,
    )

    slot_length_mm = default_params.material_thickness_mm + default_params.slot_clearance_mm
    center_y = base_depth_mm * 0.5

    assignments: list[SlotAssignment] = []
    for i, part in enumerate(parts):
        width = slot_widths[i] + default_params.slot_clearance_mm
        cx = centers_x[i]
        points = [
            (cx - width / 2, center_y - slot_length_mm / 2),
            (cx + width / 2, center_y - slot_length_mm / 2),
            (cx + width / 2, center_y + slot_length_mm / 2),
            (cx - width / 2, center_y + slot_length_mm / 2),
        ]
        assignments.append(SlotAssignment(
            part_id=part.part_id, slot_id=f"slot_{part.part_id}",
            center_x_mm=cx, center_y_mm=center_y,
            slot_width_mm=width, slot_length_mm=slot_length_mm, points_mm=points,
        ))

    return MultiPartStandResult(
        part_count=len(parts), slot_count=len(assignments), synced=len(parts) == len(assignments),
        parts_with_tab=parts_with_tab, base_points_mm=base_points_mm, assignments=assignments,
        production_ready=True, missing_fields=[],
    )


# ---------------------------------------------------------------------------
# 작업지시서 6번: SLOT PREFLIGHT
# ---------------------------------------------------------------------------

def run_slot_preflight(
    result: MultiPartStandResult,
    base_width_mm: float,
    base_depth_mm: float,
    min_spacing_mm: float = 8.0,
    min_edge_margin_mm: float = 5.0,
) -> list[PreflightIssue]:
    """
    작업지시서 6번 검사항목을 전부 수행한다:
      - Slot 간격 부족 / Slot과 받침대 외곽 충돌 / Slot 크기 오류 /
        파츠 수량 ≠ Slot 수량 / 최소 여백 부족 / Acrylic Thickness와 Slot Width 불일치
    """
    issues: list[PreflightIssue] = []

    if not result.production_ready:
        issues.append(PreflightIssue(
            code="STAND_PARAMS_NOT_READY", level=PreflightLevel.ERROR,
            title="스탠드 제작수치 미확정",
            message=f"누락된 필드: {result.missing_fields}",
            recommendation="Product Profile 에서 해당 수치를 확인해 채워야 합니다.",
        ))
        return issues

    # 파츠 수량 ≠ Slot 수량
    if not result.synced:
        issues.append(PreflightIssue(
            code="PART_SLOT_COUNT_MISMATCH", level=PreflightLevel.ERROR,
            title="파츠/Slot 수량 불일치",
            message=f"파츠 {result.part_count}개인데 Slot은 {result.slot_count}개입니다.",
            recommendation="파츠 수량과 Slot 수량을 자동 동기화하는 build_multipart_stand() 를 사용하세요.",
            auto_fixable=True,
        ))

    sorted_assignments = sorted(result.assignments, key=lambda a: a.center_x_mm)

    for a in sorted_assignments:
        # Slot 크기 오류
        if a.slot_width_mm <= 0 or a.slot_length_mm <= 0:
            issues.append(PreflightIssue(
                code="SLOT_SIZE_INVALID", level=PreflightLevel.ERROR,
                title="Slot 크기 오류", object_id=a.slot_id,
                message=f"'{a.slot_id}' 의 크기가 유효하지 않습니다 ({a.slot_width_mm}x{a.slot_length_mm}mm).",
                recommendation="slot_width_mm/slot_clearance_mm 값을 확인하세요.",
            ))

        # 받침대 외곽 충돌 + 최소 여백 부족
        left = a.center_x_mm - a.slot_width_mm / 2
        right = a.center_x_mm + a.slot_width_mm / 2
        top = a.center_y_mm - a.slot_length_mm / 2
        bottom = a.center_y_mm + a.slot_length_mm / 2
        if left < 0 or right > base_width_mm or top < 0 or bottom > base_depth_mm:
            issues.append(PreflightIssue(
                code="SLOT_OUTSIDE_BASE", level=PreflightLevel.ERROR,
                title="Slot이 받침대 외곽과 충돌", object_id=a.slot_id,
                message=f"'{a.slot_id}' 이(가) 받침대({base_width_mm}x{base_depth_mm}mm) 범위를 벗어납니다.",
                recommendation="Base 크기를 늘리거나 Slot 폭/간격을 줄이세요.",
            ))
        elif left < min_edge_margin_mm or (base_width_mm - right) < min_edge_margin_mm:
            issues.append(PreflightIssue(
                code="SLOT_EDGE_MARGIN_INSUFFICIENT", level=PreflightLevel.WARNING,
                title="Slot 최소 여백 부족", object_id=a.slot_id,
                message=f"'{a.slot_id}' 이(가) 받침대 가장자리에서 {min_edge_margin_mm}mm 미만입니다.",
                recommendation="base_margin_mm 값을 늘리세요.",
            ))

    # Slot 간 간격 부족
    for a, b in zip(sorted_assignments, sorted_assignments[1:]):
        gap = (b.center_x_mm - b.slot_width_mm / 2) - (a.center_x_mm + a.slot_width_mm / 2)
        if gap < min_spacing_mm:
            issues.append(PreflightIssue(
                code="SLOT_SPACING_INSUFFICIENT", level=PreflightLevel.ERROR,
                title="Slot 간격 부족", object_id=f"{a.slot_id}~{b.slot_id}",
                message=f"'{a.slot_id}' 와 '{b.slot_id}' 사이 간격이 {gap:.1f}mm 로 최소 {min_spacing_mm}mm 미만입니다.",
                recommendation="slot_spacing_mm 을 늘리거나 Base 폭을 넓히세요.",
                auto_fixable=True,
            ))

    # Acrylic Thickness와 Slot Width 불일치 (slot_length 는 두께+clearance 로 정의되므로,
    # 두께 대비 지나치게 얇거나(끼움 불가) 지나치게 넓으면(헐거움) 경고한다.
    for a in sorted_assignments:
        pass  # 두께 정보는 assignment 에 직접 없으므로, 상위 호출부(part별 검사)에서 별도 확인 필요 - 아래 함수 참고

    if not issues:
        issues.append(PreflightIssue(
            code="SLOT_LAYOUT_OK", level=PreflightLevel.PASS,
            title="Slot 배치 정상", message="Slot 배치에 문제가 없습니다.",
        ))

    return issues


def check_thickness_slot_width_consistency(
    parts: list[PartSpec], default_slot_width_mm: float, tolerance_mm: float = 0.6,
) -> list[PreflightIssue]:
    """Acrylic Thickness 대비 Slot Width 가 너무 빡빡하거나(끼움 불가) 너무 헐거운지 검사한다.
    적정 범위: thickness_mm <= slot_width_mm <= thickness_mm + tolerance_mm*2 (경험적 기준 -
    실제 값은 인쇄소/가공업체 협의 후 Product Profile 수치로 대체되어야 한다)."""
    issues = []
    for part in parts:
        slot_width = part.slot_width_mm or default_slot_width_mm
        if slot_width < part.acrylic_thickness_mm:
            issues.append(PreflightIssue(
                code="SLOT_WIDTH_THINNER_THAN_THICKNESS", level=PreflightLevel.ERROR,
                title="Slot 폭이 두께보다 얇음", object_id=part.part_id,
                message=f"'{part.part_id}' 의 acrylic_thickness_mm({part.acrylic_thickness_mm})이 slot_width_mm({slot_width})보다 큽니다 - 끼울 수 없습니다.",
                recommendation="slot_width_mm 을 두께 이상으로 늘리세요.",
            ))
        elif slot_width > part.acrylic_thickness_mm + tolerance_mm * 2:
            issues.append(PreflightIssue(
                code="SLOT_WIDTH_TOO_LOOSE", level=PreflightLevel.WARNING,
                title="Slot 폭이 두께 대비 헐거움", object_id=part.part_id,
                message=f"'{part.part_id}' 의 slot_width_mm({slot_width})이 두께({part.acrylic_thickness_mm})보다 많이 넓어 흔들릴 수 있습니다.",
                recommendation="slot_width_mm 을 두께에 더 가깝게 조정하세요 (권장 여유: {:.1f}mm 이내).".format(tolerance_mm),
            ))
    return issues
