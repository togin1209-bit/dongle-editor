"""
vision/production_part.py
-------------------------
v1.9.8 (GEMINI track): 아크릴 Production Part — Local Geometry / World Transform 분리.

작업지시서(#13~#20, #31, #32)의 핵심 계약을 구현한다:

  * Local Geometry : 이미지의 로컬 좌표(mm) 기준 cutline/tab 형상. **이동/확대/회전
    시에도 절대 다시 계산하지 않는다.** (contour 재추출 금지 - #15, 성능 #28)
  * World Transform : translate/scale/rotate 만 담는다.
    WorldPoint = Transform × LocalPoint  (#14)
  * Slot 은 Base 에 속한다 → Tab 의 X 만 따라가고(회전 X, Y 고정), Base 밖으로
    나가면 clamp 한다 (#8, #17).
  * ProductionPart 관계에 ID 를 부여하고 (#8) JSON 직렬화 가능하게 만들어
    Undo/Redo 가 관계를 잃지 않게 한다 (#20).
  * 화면 Preview 와 Export 가 **동일한 geometry 소스**를 쓰도록 한다 (#32).

좌표 단위 계약(#21, #22):
  - Local/World geometry 는 전부 **mm** 로 다룬다. DPI 는 raster mask 처리에만 쓰고,
    이 모듈의 어떤 계산도 DPI 에 종속되지 않는다.
  - Fabric.js(px) ↔ mm 변환은 프론트엔드 + coordinates.py 의 책임이며, 이 모듈은
    순수 mm 기하만 계산한다 (UI DOM 코드와 분리 - #31).

이 모듈은 순수 함수/데이터클래스만 포함한다 (numpy/cv2 불필요). 따라서 결정적이고
단위 테스트가 쉽다.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Optional

Point = tuple[float, float]


# ---------------------------------------------------------------------------
# 순수 기하 헬퍼
# ---------------------------------------------------------------------------

def clamp(value: float, lo: float, hi: float) -> float:
    if hi < lo:  # base 가 슬롯보다 좁은 비정상 상황 - 중앙으로 접어버린다
        return (lo + hi) / 2.0
    return max(lo, min(hi, value))


def bbox_of(points: list[Point]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def polygon_centroid_x(points: list[Point]) -> float:
    """단순 평균이 아니라 x 범위 중앙 (bbox center-x) — tab 앵커 기준과 동일하게."""
    x0, _, x1, _ = bbox_of(points)
    return (x0 + x1) / 2.0


# ---------------------------------------------------------------------------
# World Transform (#13, #14)
# ---------------------------------------------------------------------------

@dataclass
class Transform2D:
    """
    이미지의 월드 변환. 적용 순서: Scale → Rotate(원점 기준) → Translate.
    이 순서를 cutline/tab 모든 로컬 포인트에 **동일하게** 적용하므로 항상 함께 움직인다.

    angle_deg : 시계방향(스크린 좌표계, Y 아래로 증가) 회전 각도.
    """

    tx_mm: float = 0.0
    ty_mm: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    angle_deg: float = 0.0

    def apply(self, points: list[Point]) -> list[Point]:
        c = math.cos(math.radians(self.angle_deg))
        s = math.sin(math.radians(self.angle_deg))
        out: list[Point] = []
        for x, y in points:
            sx = x * self.scale_x
            sy = y * self.scale_y
            rx = sx * c - sy * s
            ry = sx * s + sy * c
            out.append((rx + self.tx_mm, ry + self.ty_mm))
        return out

    def apply_point(self, p: Point) -> Point:
        return self.apply([p])[0]

    # --- 불변식 스타일 변경자 (기존 로컬 형상은 절대 안 건드림) ---
    def translated(self, dx_mm: float, dy_mm: float) -> "Transform2D":
        return Transform2D(self.tx_mm + dx_mm, self.ty_mm + dy_mm,
                           self.scale_x, self.scale_y, self.angle_deg)

    def scaled(self, factor_x: float, factor_y: Optional[float] = None) -> "Transform2D":
        fy = factor_x if factor_y is None else factor_y
        return Transform2D(self.tx_mm, self.ty_mm,
                           self.scale_x * factor_x, self.scale_y * fy, self.angle_deg)

    def rotated(self, delta_deg: float) -> "Transform2D":
        return Transform2D(self.tx_mm, self.ty_mm, self.scale_x, self.scale_y,
                           self.angle_deg + delta_deg)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Transform2D":
        return cls(
            tx_mm=float(d.get("tx_mm", 0.0)),
            ty_mm=float(d.get("ty_mm", 0.0)),
            scale_x=float(d.get("scale_x", 1.0)),
            scale_y=float(d.get("scale_y", 1.0)),
            angle_deg=float(d.get("angle_deg", 0.0)),
        )


# ---------------------------------------------------------------------------
# Local Geometry (#13) — 한 번만 계산, 재계산 금지
# ---------------------------------------------------------------------------

@dataclass
class LocalGeometry:
    """이미지 로컬 좌표(mm) 기준 형상. contour 엔진 산출물을 로컬 원점 기준으로 저장."""

    cutline_points_mm: list[Point]          # 오프셋 적용된 칼선 (로컬)
    artwork_points_mm: list[Point] = field(default_factory=list)  # 오프셋 전 원본 외곽
    source_width_px: int = 0                # raster 원본 크기 (참고/역산용, geometry 계산엔 미사용)
    source_height_px: int = 0
    dpi: float = 300.0                       # raster 기준 DPI (geometry 비종속, 기록용)

    def bbox(self) -> tuple[float, float, float, float]:
        return bbox_of(self.cutline_points_mm)

    def width_mm(self) -> float:
        x0, _, x1, _ = self.bbox()
        return x1 - x0

    def height_mm(self) -> float:
        _, y0, _, y1 = self.bbox()
        return y1 - y0

    def bottom_center_local(self) -> Point:
        """Tab 앵커: 로컬 bbox 하단 중앙 (Y 아래로 증가하므로 max y)."""
        x0, y0, x1, y1 = self.bbox()
        return ((x0 + x1) / 2.0, y1)

    def to_dict(self) -> dict:
        return {
            "cutline_points_mm": [list(p) for p in self.cutline_points_mm],
            "artwork_points_mm": [list(p) for p in self.artwork_points_mm],
            "source_width_px": self.source_width_px,
            "source_height_px": self.source_height_px,
            "dpi": self.dpi,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LocalGeometry":
        return cls(
            cutline_points_mm=[tuple(p) for p in d.get("cutline_points_mm", [])],
            artwork_points_mm=[tuple(p) for p in d.get("artwork_points_mm", [])],
            source_width_px=int(d.get("source_width_px", 0)),
            source_height_px=int(d.get("source_height_px", 0)),
            dpi=float(d.get("dpi", 300.0)),
        )


def detect_bottom_anchor_x(points: list[Point], band_ratio: float = 0.12) -> float:
    """
    #6: Tab 앵커 X. 단순 bbox 중앙이 아니라 **실제 하단 밴드의 안정적인 수평 영역**
    중앙을 찾는다. contour 하단(band_ratio 높이)에 걸치는 점들의 x 범위 중앙.
    하단이 비대칭인 캐릭터에서 탭이 바닥에 자연스럽게 붙도록 한다.
    복잡/불안정하면 bbox center 로 안전하게 fallback.
    """
    if not points:
        return 0.0
    x0, y0, x1, y1 = bbox_of(points)
    height = y1 - y0
    if height <= 0:
        return (x0 + x1) / 2.0
    band_top = y1 - height * band_ratio
    band_xs = [p[0] for p in points if p[1] >= band_top]
    if len(band_xs) < 2:
        return (x0 + x1) / 2.0
    return (min(band_xs) + max(band_xs)) / 2.0


def local_geometry_from_cutline(cutline, origin: str = "bbox") -> tuple["LocalGeometry", "Transform2D"]:
    """
    contour 엔진의 ProductionCutline(절대 mm) → (LocalGeometry, 초기 Transform2D).

    로컬 원점을 bbox 좌상단으로 옮기고, 초기 Transform 의 (tx,ty) 를 그 오프셋으로
    설정한다 → world_cutline_points() 가 원래 절대 좌표를 정확히 복원한다.
    이후 이동/확대/회전은 Transform 만 바꾸며 로컬 형상은 불변이다 (#13/#15).
    """
    pts = [tuple(p) for p in cutline.points_mm]
    art = [tuple(p) for p in getattr(cutline, "artwork_points_mm", []) or []]
    x0, y0, _, _ = bbox_of(pts) if pts else (0.0, 0.0, 0.0, 0.0)
    if origin == "bbox":
        local = [(x - x0, y - y0) for x, y in pts]
        local_art = [(x - x0, y - y0) for x, y in art]
        tx, ty = x0, y0
    else:
        local, local_art, tx, ty = pts, art, 0.0, 0.0
    geom = LocalGeometry(
        cutline_points_mm=local,
        artwork_points_mm=local_art,
        source_width_px=int(getattr(cutline, "image_width_px", 0) or 0),
        source_height_px=int(getattr(cutline, "image_height_px", 0) or 0),
        dpi=float(getattr(cutline, "dpi", 300.0) or 300.0),
    )
    return geom, Transform2D(tx_mm=tx, ty_mm=ty)


@dataclass
class PartTolerances:
    """파츠별 끼움 규격 + provisional 추적."""

    material_thickness_mm: Optional[float] = None
    tab_width_mm: Optional[float] = None
    tab_height_mm: Optional[float] = None
    slot_width_mm: Optional[float] = None
    slot_clearance_mm: Optional[float] = None
    using_provisional: bool = False
    provisional_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PartTolerances":
        return cls(
            material_thickness_mm=d.get("material_thickness_mm"),
            tab_width_mm=d.get("tab_width_mm"),
            tab_height_mm=d.get("tab_height_mm"),
            slot_width_mm=d.get("slot_width_mm"),
            slot_clearance_mm=d.get("slot_clearance_mm"),
            using_provisional=bool(d.get("using_provisional", False)),
            provisional_fields=list(d.get("provisional_fields", [])),
        )


# ---------------------------------------------------------------------------
# ProductionPart (#5, #10, #18, #19) — 관계 + ID
# ---------------------------------------------------------------------------

@dataclass
class ProductionPart:
    """
    하나의 아크릴 파츠 = 이미지 + 칼선 + 탭 + 슬롯의 논리적 그룹.
    Fabric 객체 ID 들을 함께 보관해 프론트엔드가 관계를 잃지 않게 한다 (#5).
    """

    id: str
    asset_id: str
    local: LocalGeometry
    transform: Transform2D = field(default_factory=Transform2D)
    tolerances: PartTolerances = field(default_factory=PartTolerances)
    # 프론트 Fabric 객체 관계 ID (백엔드에선 문자열만 보관/직렬화)
    image_object_id: Optional[str] = None
    cutline_object_id: Optional[str] = None
    tab_object_id: Optional[str] = None
    slot_object_id: Optional[str] = None
    base_object_id: Optional[str] = None

    # ---- World geometry (항상 로컬 × 트랜스폼) ----
    def world_cutline_points(self) -> list[Point]:
        return self.transform.apply(self.local.cutline_points_mm)

    def world_tab_points(self) -> list[Point]:
        """탭 로컬 사각형 → 월드. 탭은 로컬 하단 중앙에 붙어 이미지와 함께 변환된다."""
        return self.transform.apply(self._local_tab_points())

    def _local_tab_points(self) -> list[Point]:
        cx, by = self.local.bottom_center_local()
        tw = self.tolerances.tab_width_mm or 0.0
        th = self.tolerances.tab_height_mm or 0.0
        half = tw / 2.0
        return [(cx - half, by), (cx + half, by), (cx + half, by + th), (cx - half, by + th)]

    def tab_center_x_world(self) -> float:
        pts = self.world_tab_points()
        return polygon_centroid_x(pts)

    def effective_size_mm(self) -> tuple[float, float]:
        """#16: scale 반영된 실제 출력 크기 (mm)."""
        return (self.local.width_mm() * abs(self.transform.scale_x),
                self.local.height_mm() * abs(self.transform.scale_y))

    def effective_slot_width_mm(self) -> float:
        base = self.tolerances.slot_width_mm or 0.0
        clr = self.tolerances.slot_clearance_mm or 0.0
        return base + clr

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "local": self.local.to_dict(),
            "transform": self.transform.to_dict(),
            "tolerances": self.tolerances.to_dict(),
            "image_object_id": self.image_object_id,
            "cutline_object_id": self.cutline_object_id,
            "tab_object_id": self.tab_object_id,
            "slot_object_id": self.slot_object_id,
            "base_object_id": self.base_object_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProductionPart":
        return cls(
            id=d["id"],
            asset_id=d["asset_id"],
            local=LocalGeometry.from_dict(d["local"]),
            transform=Transform2D.from_dict(d.get("transform", {})),
            tolerances=PartTolerances.from_dict(d.get("tolerances", {})),
            image_object_id=d.get("image_object_id"),
            cutline_object_id=d.get("cutline_object_id"),
            tab_object_id=d.get("tab_object_id"),
            slot_object_id=d.get("slot_object_id"),
            base_object_id=d.get("base_object_id"),
        )

    def duplicated(self, new_id: str, new_asset_id: Optional[str] = None,
                   offset_mm: float = 6.0) -> "ProductionPart":
        """#19: 복제 시 새 ID 를 부여한 독립 ProductionPart 를 만든다 (관계 공유 금지)."""
        clone = ProductionPart.from_dict(self.to_dict())
        clone.id = new_id
        clone.asset_id = new_asset_id or f"{self.asset_id}__copy"
        clone.transform = self.transform.translated(offset_mm, offset_mm)
        # 새 관계 객체 ID 는 프론트가 채운다 (여기선 끊어둔다)
        clone.image_object_id = None
        clone.cutline_object_id = None
        clone.tab_object_id = None
        clone.slot_object_id = None
        return clone


# ---------------------------------------------------------------------------
# Base + Slot 추종 (#7, #8, #17)
# ---------------------------------------------------------------------------

@dataclass
class BaseRect:
    """받침대 영역 (월드 mm). 슬롯 X 는 이 안에서만 움직인다."""

    left_mm: float
    top_mm: float
    width_mm: float
    depth_mm: float

    @property
    def right_mm(self) -> float:
        return self.left_mm + self.width_mm

    def slot_line_y(self) -> float:
        """슬롯 기준선 Y (받침대 깊이 중앙). 슬롯 Y 는 여기에 고정된다 (#7)."""
        return self.top_mm + self.depth_mm / 2.0


def follow_slot_center_x(
    tab_center_x_world: float,
    base: BaseRect,
    slot_width_mm: float,
    edge_margin_mm: float = 5.0,
) -> float:
    """
    #7/#8/#17 핵심: Character X → Tab X → Slot X.
    슬롯 중앙 X(월드)를 Tab 중앙 X 에 맞추되, Base 안(여백 포함)으로 clamp 한다.
    슬롯 Y 는 건드리지 않는다 (호출부가 base.slot_line_y() 사용).
    """
    half = slot_width_mm / 2.0
    lo = base.left_mm + half + edge_margin_mm
    hi = base.right_mm - half - edge_margin_mm
    return clamp(tab_center_x_world, lo, hi)


def slot_rect_world(center_x_world: float, base: BaseRect,
                    slot_width_mm: float, slot_length_mm: float) -> list[Point]:
    """슬롯 사각형(월드 mm). Y 는 base 슬롯 기준선에 고정 (회전하지 않음)."""
    cy = base.slot_line_y()
    hw = slot_width_mm / 2.0
    hl = slot_length_mm / 2.0
    return [
        (center_x_world - hw, cy - hl),
        (center_x_world + hw, cy - hl),
        (center_x_world + hw, cy + hl),
        (center_x_world - hw, cy + hl),
    ]


# ---------------------------------------------------------------------------
# Scene (#10 멀티 파츠 + #8 슬롯 자동 정렬)
# ---------------------------------------------------------------------------

@dataclass
class ProductionScene:
    """N 파츠 + 1 받침대. 파츠 수 == 슬롯 수 를 구조적으로 보장한다 (#10)."""

    base: BaseRect
    parts: list[ProductionPart] = field(default_factory=list)

    def slot_count(self) -> int:
        return len(self.parts)

    def synced(self) -> bool:
        return len(self.parts) == self.slot_count()

    def slot_for(self, part: ProductionPart, edge_margin_mm: float = 5.0) -> dict:
        """단일 파츠의 슬롯(추종 결과)을 계산한다."""
        w = part.effective_slot_width_mm()
        thickness = part.tolerances.material_thickness_mm or 0.0
        clr = part.tolerances.slot_clearance_mm or 0.0
        slot_length = thickness + clr
        cx = follow_slot_center_x(part.tab_center_x_world(), self.base, w, edge_margin_mm)
        return {
            "part_id": part.id,
            "slot_id": part.slot_object_id or f"slot_{part.id}",
            "center_x_mm": cx,
            "center_y_mm": self.base.slot_line_y(),
            "slot_width_mm": w,
            "slot_length_mm": slot_length,
            "points_mm": slot_rect_world(cx, self.base, w, slot_length),
        }

    def slots(self, edge_margin_mm: float = 5.0) -> list[dict]:
        return [self.slot_for(p, edge_margin_mm) for p in self.parts]

    def auto_distribute_slots(self, spacing_mm: float = 15.0,
                              margin_mm: float = 10.0) -> list[dict]:
        """
        #8 '슬롯 자동 정렬': 선택 파츠 순서대로 동일 간격 + Base 중앙 정렬.
        (Tab 추종 대신 균등 배치를 원할 때 호출.)
        """
        n = len(self.parts)
        if n == 0:
            return []
        widths = [p.effective_slot_width_mm() for p in self.parts]
        item_w = max(widths)
        content = n * item_w + (n - 1) * spacing_mm
        usable = self.base.width_mm - 2 * margin_mm
        start = self.base.left_mm + margin_mm + (usable - content) / 2 + item_w / 2
        step = item_w + spacing_mm
        out = []
        for i, p in enumerate(self.parts):
            cx = start + i * step
            thickness = p.tolerances.material_thickness_mm or 0.0
            clr = p.tolerances.slot_clearance_mm or 0.0
            slot_length = thickness + clr
            w = widths[i]
            out.append({
                "part_id": p.id,
                "slot_id": p.slot_object_id or f"slot_{p.id}",
                "center_x_mm": cx,
                "center_y_mm": self.base.slot_line_y(),
                "slot_width_mm": w,
                "slot_length_mm": slot_length,
                "points_mm": slot_rect_world(cx, self.base, w, slot_length),
            })
        return out

    def to_dict(self) -> dict:
        return {
            "base": asdict(self.base),
            "parts": [p.to_dict() for p in self.parts],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProductionScene":
        b = d["base"]
        return cls(
            base=BaseRect(left_mm=b["left_mm"], top_mm=b["top_mm"],
                          width_mm=b["width_mm"], depth_mm=b["depth_mm"]),
            parts=[ProductionPart.from_dict(p) for p in d.get("parts", [])],
        )
