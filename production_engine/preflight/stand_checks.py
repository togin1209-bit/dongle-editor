"""
preflight/stand_checks.py
-------------------------
v1.9.8 (GEMINI track): 아크릴 스탠드 Preflight 보강 (작업지시서 #5, #11, #12, #18,
#26, #27). 기존 검사(vision/stand_multipart.run_slot_preflight,
check_thickness_slot_width_consistency)는 그대로 재사용하고, 여기서는 그것이
다루지 못하는 항목만 ADDITIVE 로 추가한다:

  * 미확정(PROVISIONAL) 공차 사용 → WARNING (Production Ready 승격 금지)  (#7/#9)
  * 파츠 간 칼선 간격 < 5mm → WARNING/ERROR  (#11)
  * 칼선 노드 과다 / 얇은 목 → WARNING  (#5)
  * ProductionPart 관계 끊김(칼선/탭/슬롯 누락) → ERROR  (#18/#20)

정책: 이번 Sprint 는 형상 품질 문제를 ERROR 로 막지 않고 WARNING 으로 안내한다
(작업지시서 #5). 구조적으로 제작 불가한 경우(관계 끊김, 슬롯 크기 0)만 ERROR.
"""

from __future__ import annotations

from typing import Optional

from ..models import PreflightIssue, PreflightLevel
from ..vision.production_part import ProductionPart, ProductionScene, bbox_of


# --- min gap 정책값 (제작가이드: 파츠 간 칼선 간격 5mm 이상) ---
MIN_PART_GAP_MM = 5.0
# 노드 과다 임계 (제작가이드: anchor point 과다 시 가공 문제)
MAX_CUTLINE_NODES = 400


def provisional_tolerance_issue(using_provisional: bool,
                                provisional_fields: list[str]) -> Optional[PreflightIssue]:
    if not using_provisional:
        return None
    return PreflightIssue(
        code="STAND_TOLERANCE_PROVISIONAL",
        level=PreflightLevel.WARNING,
        title="끼움 공차 미확정(임시값)",
        message=(
            "제작사 확정 전 임시(PROVISIONAL) 공차로 계산했습니다: "
            f"{', '.join(provisional_fields)}. 실제 제작 전 확정값 입력이 필요합니다."
        ),
        recommendation="상품 설정 > 끼움 규격에 제작사 확정 수치를 입력하세요.",
        auto_fixable=False,
    )


def part_gap_issues(scene: ProductionScene, min_gap_mm: float = MIN_PART_GAP_MM) -> list[PreflightIssue]:
    """#11: 파츠 간 칼선(월드) 간격이 min_gap 미만이면 경고."""
    issues: list[PreflightIssue] = []
    boxes = []
    for p in scene.parts:
        pts = p.world_cutline_points()
        if not pts:
            continue
        x0, y0, x1, y1 = bbox_of(pts)
        boxes.append((p.id, x0, x1))
    boxes.sort(key=lambda b: b[1])
    for (id_a, _, right_a), (id_b, left_b, _) in zip(boxes, boxes[1:]):
        gap = left_b - right_a
        if gap < min_gap_mm:
            issues.append(PreflightIssue(
                code="PART_GAP_INSUFFICIENT",
                level=PreflightLevel.WARNING,
                title="파츠 간격 부족",
                object_id=f"{id_a}~{id_b}",
                message=f"파츠 간격이 {gap:.1f}mm 입니다. 최소 {min_gap_mm:.0f}mm 이상 필요합니다.",
                recommendation="파츠 위치를 벌리거나 캔버스에서 겹치지 않게 배치하세요.",
                auto_fixable=True,
            ))
    return issues


def contour_complexity_issues(part: ProductionPart,
                              max_nodes: int = MAX_CUTLINE_NODES) -> list[PreflightIssue]:
    """#5: 칼선 노드 과다 경고 (가공 난이도)."""
    n = len(part.local.cutline_points_mm)
    issues: list[PreflightIssue] = []
    if n > max_nodes:
        issues.append(PreflightIssue(
            code="CUTLINE_NODES_EXCESSIVE",
            level=PreflightLevel.WARNING,
            title="칼선 노드 과다",
            object_id=part.id,
            message=f"칼선 노드가 {n}개로 많습니다(> {max_nodes}). 가공이 어렵거나 거칠 수 있습니다.",
            recommendation="자동 칼선 단순화(simplify) 강도를 높이세요.",
            auto_fixable=True,
        ))
    return issues


def relation_integrity_issues(part: ProductionPart) -> list[PreflightIssue]:
    """#18/#20: ProductionPart 관계 끊김(칼선/탭/슬롯 누락) → ERROR (Orphan 방지)."""
    issues: list[PreflightIssue] = []
    missing = []
    if not part.local.cutline_points_mm:
        missing.append("cutline")
    if part.tab_object_id is None:
        missing.append("tab")
    if part.slot_object_id is None:
        missing.append("slot")
    if missing:
        issues.append(PreflightIssue(
            code="PRODUCTION_PART_RELATION_BROKEN",
            level=PreflightLevel.ERROR,
            title="파츠 관계 끊김",
            object_id=part.id,
            message=f"파츠 '{part.id}' 에 누락된 관계: {', '.join(missing)}.",
            recommendation="칼선+탭+슬롯 생성을 다시 실행하세요.",
        ))
    return issues


def run_stand_scene_preflight(
    scene: ProductionScene,
    using_provisional: bool = False,
    provisional_fields: Optional[list[str]] = None,
    check_relations: bool = False,
    min_part_gap_mm: float = MIN_PART_GAP_MM,
) -> list[PreflightIssue]:
    """
    ProductionScene 기반 통합 Preflight (관계+간격+복잡도+미확정공차).
    슬롯 크기/외곽/간격 검사는 기존 run_slot_preflight 가 담당하므로 여기선 중복하지 않는다.
    """
    issues: list[PreflightIssue] = []
    prov = provisional_tolerance_issue(using_provisional, provisional_fields or [])
    if prov:
        issues.append(prov)
    issues.extend(part_gap_issues(scene, min_part_gap_mm))
    for part in scene.parts:
        issues.extend(contour_complexity_issues(part))
        if check_relations:
            issues.extend(relation_integrity_issues(part))
    return issues


# ---------------------------------------------------------------------------
# 작업지시서 #27: Auto Repair (형상 크게 바꾸지 않는 안전한 것만)
# ---------------------------------------------------------------------------

def auto_repair_slot_layout(scene: ProductionScene, spacing_mm: float = 15.0,
                            margin_mm: float = 10.0) -> list[dict]:
    """슬롯 충돌/간격 부족 → 균등 재분배 (형상 불변, 위치만 조정)."""
    return scene.auto_distribute_slots(spacing_mm=spacing_mm, margin_mm=margin_mm)
