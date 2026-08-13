"""
finishing/eyelet_engine.py
-----------------------------
아일렛(그로밋) 좌표 계산 엔진.

기존 frontend/js/canvas-manager.js 에 있던 아일렛 표시 로직은:
  - 배너는 무조건 4개 코너에 하드코딩된 12px 위치
  - 현수막은 500mm 고정 간격을 캔버스 픽셀에 대충 매핑
  - 화면 표시용일 뿐, 실제 mm 좌표를 Preflight/Production Manifest 어디에도 넘기지 않음
이었다. 이 모듈은 이를 대체하는 "진짜" 계산 엔진이다:
  - 상품 프로필(EyeletSpec)에 정의된 정책에 따라 실제 mm 좌표 배열을 계산한다.
  - 현수막 크기가 바뀌면(가로/세로 mm 변경) 호출할 때마다 자동 재계산된다
    (상태를 들고 있지 않는 순수 함수이므로 캐시/동기화 문제가 없다).
  - Preflight 의 Eyelet Collision 검사, Production Manifest 출력에 재사용된다.

좌표계: 출력 캔버스(=Trim 영역) 좌상단을 원점 (0,0) 으로 하는 mm 좌표.
        음수 좌표는 없다. x: 0~width_mm, y: 0~height_mm.
"""

from __future__ import annotations

import math

from ..models import EyeletPlacementPolicy, EyeletPoint, EyeletSpec


class EyeletLayoutError(Exception):
    pass


def calculate_eyelet_positions(
    width_mm: float, height_mm: float, spec: EyeletSpec
) -> list[EyeletPoint]:
    """
    상품 사이즈(width_mm, height_mm)와 EyeletSpec 정책에 따라
    실제 아일렛 mm 좌표 배열을 계산한다.

    호출할 때마다 새로 계산하므로, 현수막 사이즈가 바뀌면 이 함수를 다시 호출하는 것만으로
    자동으로 최신 좌표가 반영된다 (별도 캐시 무효화 로직 불필요).
    """
    if width_mm <= 0 or height_mm <= 0:
        raise EyeletLayoutError(f"사이즈가 유효하지 않습니다: {width_mm}x{height_mm}mm")

    if not spec.enabled or spec.placement_policy == EyeletPlacementPolicy.NONE:
        return []

    if spec.margin_mm < 0:
        raise EyeletLayoutError("margin_mm 은 0 이상이어야 합니다.")
    if spec.interval_mm <= 0 and spec.placement_policy in (
        EyeletPlacementPolicy.TOP_BOTTOM,
        EyeletPlacementPolicy.LEFT_RIGHT,
        EyeletPlacementPolicy.ALL_EDGES,
        EyeletPlacementPolicy.CUSTOM_INTERVAL,
    ):
        raise EyeletLayoutError("interval_mm 은 0보다 커야 합니다.")

    m = spec.margin_mm

    if spec.placement_policy == EyeletPlacementPolicy.FOUR_CORNERS:
        return [
            EyeletPoint(x_mm=m, y_mm=m, edge="corner"),
            EyeletPoint(x_mm=width_mm - m, y_mm=m, edge="corner"),
            EyeletPoint(x_mm=m, y_mm=height_mm - m, edge="corner"),
            EyeletPoint(x_mm=width_mm - m, y_mm=height_mm - m, edge="corner"),
        ]

    if spec.placement_policy == EyeletPlacementPolicy.TOP_BOTTOM:
        edges = {"top", "bottom"}
    elif spec.placement_policy == EyeletPlacementPolicy.LEFT_RIGHT:
        edges = {"left", "right"}
    elif spec.placement_policy in (
        EyeletPlacementPolicy.ALL_EDGES,
        EyeletPlacementPolicy.CUSTOM_INTERVAL,
    ):
        edges = {"top", "bottom", "left", "right"}
    else:
        raise EyeletLayoutError(f"알 수 없는 아일렛 배치 정책: {spec.placement_policy}")

    points: list[EyeletPoint] = []
    seen: set[tuple[float, float]] = set()

    def _add(x: float, y: float, edge: str) -> None:
        key = (round(x, 3), round(y, 3))
        if key in seen:
            return
        seen.add(key)
        points.append(EyeletPoint(x_mm=x, y_mm=y, edge=edge))

    if "top" in edges or "bottom" in edges:
        xs = _spaced_points_along_edge(width_mm, m, spec.interval_mm)
        for x in xs:
            if "top" in edges:
                _add(x, m, "top")
            if "bottom" in edges:
                _add(x, height_mm - m, "bottom")

    if "left" in edges or "right" in edges:
        ys = _spaced_points_along_edge(height_mm, m, spec.interval_mm)
        for y in ys:
            if "left" in edges:
                _add(m, y, "left")
            if "right" in edges:
                _add(width_mm - m, y, "right")

    points.sort(key=lambda p: (round(p.y_mm, 3), round(p.x_mm, 3)))
    return points


def _spaced_points_along_edge(length_mm: float, margin_mm: float, interval_mm: float) -> list[float]:
    """
    한 변(길이 length_mm)을 따라 margin_mm 안쪽부터 시작해서, interval_mm 을 넘지 않는
    "균등 간격"으로 점을 배치한다. 양 끝(margin 위치)은 항상 포함된다.

    고정폭 스텝으로 단순 반복하면 마지막 구간 간격이 흐트러지는(짧아지거나 끝점을
    벗어나는) 문제가 생기므로, 필요한 점 개수를 먼저 계산한 뒤 균등 분할한다.
    """
    usable = length_mm - 2 * margin_mm
    if usable <= 0:
        # 캔버스가 margin*2 보다 작음 -> 물리적으로 여유가 없는 경우.
        # 중앙 1개로 축소 (완전히 계산 불가능한 상태를 피하기 위한 방어적 폴백).
        # Preflight 의 EYELET_LAYOUT_DEGENERATE 경고가 이 상황을 사용자에게 알려야 한다.
        mid = max(0.0, min(length_mm, length_mm / 2))
        return [mid]

    count = max(2, math.ceil(usable / interval_mm) + 1)
    step = usable / (count - 1)
    return [margin_mm + i * step for i in range(count)]


def is_layout_degenerate(width_mm: float, height_mm: float, spec: EyeletSpec) -> bool:
    """캔버스가 너무 작아 margin*2 를 확보하지 못하는 경우를 사전 판별 (Preflight용)."""
    if not spec.enabled or spec.placement_policy == EyeletPlacementPolicy.NONE:
        return False
    return (width_mm - 2 * spec.margin_mm) <= 0 or (height_mm - 2 * spec.margin_mm) <= 0
