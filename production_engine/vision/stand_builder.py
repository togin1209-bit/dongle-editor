"""
vision/stand_builder.py
--------------------------
v1.6: Acrylic Stand Builder (작업지시서 3번).

아크릴 스탠드 = Main Body(투명 PNG에서 추출한 캐릭터/이미지 컷) + Base(받침대) +
Tab(Main Body 하단, Base의 Slot에 꽂히는 돌출부) + Slot(Base에 뚫린 홈).

**중요**: material_thickness_mm / slot_width_mm / tab_width_mm / clearance_mm 는
전부 ProductProfile 에서 공급되어야 하며, 확정되지 않은 경우 이 모듈은 결과를
"production_ready=False" 로 명시하고 실제 좌표 대신 결측 사유를 반환한다
(하드코딩된 기본 제작값을 쓰지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Optional

import numpy as np

from .contour_engine import ProductionCutline


class BaseShape(str, Enum):
    RECTANGLE = "RECTANGLE"
    ROUNDED_RECTANGLE = "ROUNDED_RECTANGLE"
    OVAL = "OVAL"
    CUSTOM = "CUSTOM"


class SlotPosition(str, Enum):
    CENTER = "CENTER"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    AUTO = "AUTO"


class StandBuilderError(Exception):
    pass


@dataclass
class StandParams:
    """Product Profile 에서 읽어와야 하는 실제 제작수치. 전부 None 이면 미확정."""

    material_thickness_mm: Optional[float] = None
    tab_width_mm: Optional[float] = None
    tab_height_mm: Optional[float] = None
    slot_width_mm: Optional[float] = None
    slot_clearance_mm: Optional[float] = None

    REQUIRED: ClassVar[tuple] = (
        "material_thickness_mm", "tab_width_mm", "tab_height_mm", "slot_width_mm", "slot_clearance_mm",
    )

    def missing_fields(self) -> list[str]:
        return [f for f in self.REQUIRED if getattr(self, f) is None]

    def is_ready(self) -> bool:
        return len(self.missing_fields()) == 0


@dataclass
class TabGeometry:
    points_mm: list[tuple[float, float]]  # main body 하단에 추가된 tab 폴리곤 (main body에 병합됨)


@dataclass
class SlotGeometry:
    points_mm: list[tuple[float, float]]  # base 위에 뚫는 slot 폴리곤 (내곽, hole 로 취급)
    position: SlotPosition


@dataclass
class BaseGeometry:
    points_mm: list[tuple[float, float]]
    shape: BaseShape
    slot: SlotGeometry


@dataclass
class StandBuildResult:
    production_ready: bool
    missing_fields: list[str]
    main_body_points_mm: Optional[list[tuple[float, float]]] = None  # tab 포함된 최종 main body 외곽
    tab: Optional[TabGeometry] = None
    base: Optional[BaseGeometry] = None


def _bbox(points_mm: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    arr = np.array(points_mm)
    return float(arr[:, 0].min()), float(arr[:, 1].min()), float(arr[:, 0].max()), float(arr[:, 1].max())


def build_tab(main_body_points_mm: list[tuple[float, float]], params: StandParams) -> TabGeometry:
    """Main Body 하단 중앙에 사각형 tab을 자동 생성해 main body 외곽선에 추가한다."""
    x0, y0, x1, y1 = _bbox(main_body_points_mm)
    bottom_y = y1  # y가 아래로 증가하는 좌표계 가정 (다른 모듈과 일관)
    center_x = (x0 + x1) / 2
    half_w = params.tab_width_mm / 2

    tab_points = [
        (center_x - half_w, bottom_y),
        (center_x - half_w, bottom_y + params.tab_height_mm),
        (center_x + half_w, bottom_y + params.tab_height_mm),
        (center_x + half_w, bottom_y),
    ]
    return TabGeometry(points_mm=tab_points)


def merge_main_body_with_tab(
    main_body_points_mm: list[tuple[float, float]], tab: TabGeometry
) -> list[tuple[float, float]]:
    """
    main body 외곽 폴리곤에 tab 사각형을 이어붙인 최종 외곽선을 만든다.
    (기본 구현: main body의 최하단 근접 두 점 사이에 tab의 네 점을 삽입하는 단순 병합.
    실제 프로덕션에서는 두 폴리곤의 정확한 불리언 합집합(union)이 필요하지만, 이번
    버전에서는 "하단이 평평하다"고 가정하는 단순화된 병합을 제공하고 이 가정을
    명시한다 - 복잡한 하단 윤곽(예: 캐릭터 다리가 여러 개)에는 정확하지 않을 수 있다.)
    """
    x0, y0, x1, y1 = _bbox(main_body_points_mm)
    bottom_y = y1
    # main body 점들을 하단 y 근처(허용오차 내)와 나머지로 분리
    tol = (y1 - y0) * 0.02
    others = [p for p in main_body_points_mm if p[1] < bottom_y - tol]
    return others + tab.points_mm


def build_base(
    width_mm: float,
    depth_mm: float,
    shape: BaseShape,
    params: StandParams,
    slot_position: SlotPosition = SlotPosition.AUTO,
    custom_points_mm: Optional[list[tuple[float, float]]] = None,
) -> BaseGeometry:
    if shape == BaseShape.CUSTOM:
        if not custom_points_mm:
            raise StandBuilderError("BaseShape.CUSTOM 에는 custom_points_mm 이 필요합니다.")
        base_points = custom_points_mm
    elif shape == BaseShape.RECTANGLE:
        base_points = [(0, 0), (width_mm, 0), (width_mm, depth_mm), (0, depth_mm)]
    elif shape == BaseShape.ROUNDED_RECTANGLE:
        # 단순화: 모서리를 8각형 근사로 라운딩 (실제 곡선은 PDF/SVG 출력 단계에서 베지어로 대체 가능)
        r = min(width_mm, depth_mm) * 0.12
        base_points = [
            (r, 0), (width_mm - r, 0), (width_mm, r), (width_mm, depth_mm - r),
            (width_mm - r, depth_mm), (r, depth_mm), (0, depth_mm - r), (0, r),
        ]
    elif shape == BaseShape.OVAL:
        cx, cy = width_mm / 2, depth_mm / 2
        base_points = [
            (cx + (width_mm / 2) * np.cos(t), cy + (depth_mm / 2) * np.sin(t))
            for t in np.linspace(0, 2 * np.pi, 32, endpoint=False)
        ]
    else:
        raise StandBuilderError(f"알 수 없는 BaseShape: {shape}")

    resolved_position = slot_position
    if slot_position == SlotPosition.AUTO:
        resolved_position = SlotPosition.CENTER  # 자동 정책: 기본은 중앙 (필요 시 향후 무게중심 기반으로 고도화)

    # 조립 슬롯은 긴 방향이 tab 폭, 좁은 방향이 아크릴 두께(끼움폭)이다.
    # 기존 구현은 두 축을 모두 약 3mm로 만들어 슬롯이 정사각형/원형처럼 보였다.
    slot_width = params.tab_width_mm
    slot_depth = params.slot_width_mm + params.slot_clearance_mm

    if resolved_position == SlotPosition.CENTER:
        slot_cx = width_mm / 2
    elif resolved_position == SlotPosition.LEFT:
        slot_cx = width_mm * 0.25
    elif resolved_position == SlotPosition.RIGHT:
        slot_cx = width_mm * 0.75
    else:
        raise StandBuilderError(f"알 수 없는 SlotPosition: {resolved_position}")

    slot_cy = depth_mm * 0.5
    slot_points = [
        (slot_cx - slot_width / 2, slot_cy - slot_depth / 2),
        (slot_cx + slot_width / 2, slot_cy - slot_depth / 2),
        (slot_cx + slot_width / 2, slot_cy + slot_depth / 2),
        (slot_cx - slot_width / 2, slot_cy + slot_depth / 2),
    ]

    return BaseGeometry(
        points_mm=base_points, shape=shape,
        slot=SlotGeometry(points_mm=slot_points, position=resolved_position),
    )


def build_stand(
    main_body_cutline: ProductionCutline,
    params: StandParams,
    base_width_mm: float,
    base_depth_mm: float,
    base_shape: BaseShape = BaseShape.ROUNDED_RECTANGLE,
    slot_position: SlotPosition = SlotPosition.AUTO,
) -> StandBuildResult:
    """전체 오케스트레이션: Main Body + Tab + Base + Slot."""
    missing = params.missing_fields()
    if missing:
        return StandBuildResult(production_ready=False, missing_fields=missing)

    tab = build_tab(main_body_cutline.points_mm, params)
    merged_main_body = merge_main_body_with_tab(main_body_cutline.points_mm, tab)
    base = build_base(base_width_mm, base_depth_mm, base_shape, params, slot_position)

    return StandBuildResult(
        production_ready=True, missing_fields=[],
        main_body_points_mm=merged_main_body, tab=tab, base=base,
    )
