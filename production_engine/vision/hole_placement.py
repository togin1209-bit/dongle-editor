"""
vision/hole_placement.py
---------------------------
v1.6: Keyring Hole Placement Engine (작업지시서 2번).

지원 모드: AUTO_RECOMMEND / TOP_CENTER / TOP_LEFT / TOP_RIGHT / MANUAL

AUTO_RECOMMEND 는 다음을 고려해 최대 3개의 후보를 점수와 함께 반환한다:
  - object bounding box / centroid
  - top contour (상단부 윤곽 - 구멍은 보통 상단에 위치)
  - cutline과의 거리(hole_edge_margin_mm 확보 여부)
  - "중요 이미지 영역" 침범 여부 (간단한 휴리스틱: 중앙 영역을 중요 영역으로 간주)

Hole 자체와 별개로, 필요하면 CutContour에 연결되는 neck(연결부) geometry를 만들 수
있는 구조(HoleGeometry.neck_points_mm)를 함께 설계했다 - 실제 neck 생성 알고리즘은
상품별 디자인 재량이 커서 이번 버전에서는 "직선 연결부" 기본 구현만 제공한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np


class HolePlacementMode(str, Enum):
    AUTO_RECOMMEND = "AUTO_RECOMMEND"
    TOP_CENTER = "TOP_CENTER"
    TOP_LEFT = "TOP_LEFT"
    TOP_RIGHT = "TOP_RIGHT"
    MANUAL = "MANUAL"


class HolePlacementError(Exception):
    pass


@dataclass
class HoleCandidate:
    x_mm: float
    y_mm: float
    score: float           # 0~100, 높을수록 좋은 후보
    reason: str


@dataclass
class HoleGeometry:
    """최종 채택된 구멍 1개의 기하 정보."""

    center_x_mm: float
    center_y_mm: float
    diameter_mm: float
    neck_points_mm: list[tuple[float, float]] = field(default_factory=list)  # CutContour에 연결되는 연결부(선택)


def _bounding_box_mm(points_mm: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    arr = np.array(points_mm)
    return float(arr[:, 0].min()), float(arr[:, 1].min()), float(arr[:, 0].max()), float(arr[:, 1].max())


def _centroid_mm(points_mm: list[tuple[float, float]]) -> tuple[float, float]:
    arr = np.array(points_mm)
    return float(arr[:, 0].mean()), float(arr[:, 1].mean())


def _min_distance_to_contour_mm(x: float, y: float, points_mm: list[tuple[float, float]]) -> float:
    arr = np.array(points_mm)
    d = np.sqrt((arr[:, 0] - x) ** 2 + (arr[:, 1] - y) ** 2)
    return float(d.min())


def _fixed_position(
    mode: HolePlacementMode, points_mm: list[tuple[float, float]], hole_edge_margin_mm: float
) -> tuple[float, float]:
    x0, y0, x1, y1 = _bounding_box_mm(points_mm)
    width = x1 - x0
    margin = hole_edge_margin_mm
    y = y0 + margin
    if mode == HolePlacementMode.TOP_CENTER:
        x = x0 + width / 2
    elif mode == HolePlacementMode.TOP_LEFT:
        x = x0 + margin + width * 0.15
    elif mode == HolePlacementMode.TOP_RIGHT:
        x = x1 - margin - width * 0.15
    else:
        raise HolePlacementError(f"고정 위치 모드가 아닙니다: {mode}")
    return x, y


def recommend_hole_positions(
    cutline_points_mm: list[tuple[float, float]],
    hole_diameter_mm: float,
    hole_edge_margin_mm: float,
    max_candidates: int = 3,
    important_region_ratio: float = 0.6,
) -> list[HoleCandidate]:
    """
    AUTO_RECOMMEND: cutline 상단부를 따라 후보 지점을 스캔하고, 각 지점에 대해
    - cutline과의 최소 거리(hole_edge_margin_mm 확보 여부)
    - 중요 이미지 영역(중앙부) 침범 여부
    - 대칭축(centroid x)과의 근접도(중앙에 가까울수록 시각적으로 안정적)
    를 점수화해 상위 max_candidates 개를 반환한다.
    """
    if not cutline_points_mm:
        raise HolePlacementError("cutline_points_mm 이 비어있습니다.")

    x0, y0, x1, y1 = _bounding_box_mm(cutline_points_mm)
    width, height = x1 - x0, y1 - y0
    cx, cy = _centroid_mm(cutline_points_mm)

    # 상단 20% 영역에서 후보 x좌표를 스캔한다 (구멍은 보통 상단에 위치).
    top_band_y = y0 + height * 0.12
    scan_xs = np.linspace(x0 + width * 0.1, x1 - width * 0.1, 21)

    # 중요 이미지 영역: 중앙부 사각형 (important_region_ratio 비율)
    ir_half_w = width * important_region_ratio / 2
    ir_half_h = height * important_region_ratio / 2
    ir_x0, ir_x1 = cx - ir_half_w, cx + ir_half_w
    ir_y0, ir_y1 = cy - ir_half_h, cy + ir_half_h

    scored = []
    required_clear_mm = hole_edge_margin_mm + hole_diameter_mm / 2
    for x in scan_xs:
        y = top_band_y
        dist_to_cutline = _min_distance_to_contour_mm(x, y, cutline_points_mm)

        if dist_to_cutline < required_clear_mm:
            continue  # 물리적으로 배치 불가능한 후보는 아예 제외

        in_important_region = ir_x0 <= x <= ir_x1 and ir_y0 <= y <= ir_y1

        score = 100.0
        # 대칭축(centroid x)에서 멀수록 감점
        score -= min(40.0, abs(x - cx) / (width / 2 + 1e-6) * 40.0)
        # cutline과 여유가 빠듯할수록 감점 (여유가 required 의 2배 이상이면 만점)
        clearance_ratio = min(1.0, (dist_to_cutline - required_clear_mm) / max(required_clear_mm, 1e-6))
        score -= (1.0 - clearance_ratio) * 20.0
        # 중요 이미지 영역을 침범하면 큰 감점
        if in_important_region:
            score -= 50.0
        score = max(0.0, round(float(score), 1))

        reason_parts = [f"cutline까지 여유 {dist_to_cutline:.1f}mm(필요 {required_clear_mm:.1f}mm)"]
        reason_parts.append(f"중심축과의 거리 {abs(x-cx):.1f}mm")
        if in_important_region:
            reason_parts.append("중요 이미지 영역과 겹침(감점)")
        scored.append(HoleCandidate(x_mm=round(float(x), 2), y_mm=round(float(y), 2), score=score, reason=", ".join(reason_parts)))

    if not scored:
        raise HolePlacementError(
            "물리적으로 배치 가능한 구멍 후보를 찾지 못했습니다 (hole_edge_margin_mm/"
            "hole_diameter_mm 대비 오브젝트가 너무 작을 수 있습니다)."
        )

    scored.sort(key=lambda c: c.score, reverse=True)

    # 서로 너무 가까운 후보는 대표 1개만 남긴다 (다양성 확보)
    deduped: list[HoleCandidate] = []
    min_gap_mm = max(hole_diameter_mm * 2, width * 0.08)
    for cand in scored:
        if all(abs(cand.x_mm - d.x_mm) >= min_gap_mm for d in deduped):
            deduped.append(cand)
        if len(deduped) >= max_candidates:
            break

    return deduped


def place_hole(
    mode: HolePlacementMode,
    cutline_points_mm: list[tuple[float, float]],
    hole_diameter_mm: float,
    hole_edge_margin_mm: float,
    manual_x_mm: Optional[float] = None,
    manual_y_mm: Optional[float] = None,
) -> HoleGeometry:
    """모드에 따라 최종 구멍 1개의 geometry 를 결정한다."""
    if mode == HolePlacementMode.MANUAL:
        if manual_x_mm is None or manual_y_mm is None:
            raise HolePlacementError("MANUAL 모드에는 manual_x_mm/manual_y_mm 이 필요합니다.")
        x, y = manual_x_mm, manual_y_mm
    elif mode == HolePlacementMode.AUTO_RECOMMEND:
        candidates = recommend_hole_positions(cutline_points_mm, hole_diameter_mm, hole_edge_margin_mm, max_candidates=1)
        x, y = candidates[0].x_mm, candidates[0].y_mm
    else:
        x, y = _fixed_position(mode, cutline_points_mm, hole_edge_margin_mm)

    dist = _min_distance_to_contour_mm(x, y, cutline_points_mm)
    required = hole_edge_margin_mm + hole_diameter_mm / 2
    neck_points: list[tuple[float, float]] = []
    if dist < required:
        # 여유가 부족하면, cutline 상 가장 가까운 지점까지 짧은 직선 neck으로 연결해
        # 구조적으로 고리가 끊어지지 않게 한다 (기본 구현 - 실제 형태는 상품별 재량).
        arr = np.array(cutline_points_mm)
        d = np.sqrt((arr[:, 0] - x) ** 2 + (arr[:, 1] - y) ** 2)
        nearest = arr[int(d.argmin())]
        neck_points = [(x, y), (float(nearest[0]), float(nearest[1]))]

    return HoleGeometry(center_x_mm=x, center_y_mm=y, diameter_mm=hole_diameter_mm, neck_points_mm=neck_points)
