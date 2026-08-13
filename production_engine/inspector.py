"""
inspector.py
--------------
v1.7: Production Inspector 데이터 조립 (작업지시서 9번).

"일반 디자인 에디터와 차별화되는 핵심" — 현재 선택된 상품과 오브젝트를 기준으로
Effective DPI / RGB·CMYK / Bleed / Trim / Safe Zone / CutContour / WHITE / Hole / Eyelet
정보를 동적으로 조립해 Frontend Inspector 패널에 넘겨준다.

**핵심 설계 원칙**: 상품 종류에 따라 필요 없는 항목은 아예 payload에서 빠진다
(Frontend가 "빈 패널을 숨기는" 로직을 따로 만들 필요가 없도록, 백엔드가 미리
필터링해서 내려준다). 어떤 항목이 표시되는지는 ProductProfile.capabilities 를 본다.

이 모듈은 기존 preflight/pipeline/vision 모듈의 결과 객체를 그대로 받아 조립만 하고,
새로운 계산 로직을 추가하지 않는다 (단일 진실 소스 원칙 유지).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .imaging.dpi import calculate_effective_dpi
from .models import PreflightReport, ProductProfile


@dataclass
class ProductionInspectorPayload:
    """Frontend Production Inspector 패널이 그대로 렌더링할 수 있는 구조."""

    product_id: str
    product_name: str
    sections: dict  # 섹션 키 -> 데이터 dict. 상품에 필요 없는 섹션은 키 자체가 없음.

    def to_dict(self) -> dict:
        return {
            "product_id": self.product_id,
            "product_name": self.product_name,
            "sections": self.sections,
        }


def _capabilities_of(profile: ProductProfile) -> set:
    if profile.capabilities:
        return set(profile.capabilities)
    caps = {"RECTANGULAR_PRINT"}
    if profile.eyelet.enabled:
        caps.add("EYELET_FINISHING")
    return caps


def build_production_inspector(
    profile: ProductProfile,
    *,
    source_width_px: Optional[int] = None,
    source_height_px: Optional[int] = None,
    color_mode: str = "RGB",
    icc_profile_applied: Optional[str] = None,
    preflight_report: Optional[PreflightReport] = None,
    cutline=None,          # vision.contour_engine.ProductionCutline (선택)
    hole=None,              # vision.hole_placement.HoleGeometry (선택)
    white_layer=None,        # vision.white_layer.WhiteLayerResult (선택)
    eyelet_points: Optional[list] = None,
) -> ProductionInspectorPayload:
    caps = _capabilities_of(profile)
    sections: dict = {}

    # ---- DPI (원본 픽셀 크기를 알 때만 계산 가능) ----
    if source_width_px and source_height_px:
        dpi_result = calculate_effective_dpi(
            source_width_px, source_height_px, profile.width_mm, profile.height_mm
        )
        sections["dpi"] = {
            "effective_dpi_x": round(dpi_result.dpi_x, 1),
            "effective_dpi_y": round(dpi_result.dpi_y, 1),
            "min_dpi": round(dpi_result.min_dpi, 1),
            "recommended_dpi": profile.dpi_warning_below,
            "minimum_dpi": profile.dpi_error_below,
            "status": (
                "ok" if dpi_result.min_dpi >= profile.dpi_warning_below
                else "low" if dpi_result.min_dpi >= profile.dpi_error_below
                else "too_low"
            ),
        }

    # ---- Color Mode (항상 표시) ----
    sections["color"] = {
        "current_mode": color_mode,
        "target_mode": profile.color_mode_target,
        "icc_profile": profile.icc_profile_name,
        "icc_applied": icc_profile_applied,
    }

    # ---- Trim / Bleed / Safe Zone (항상 표시 - 모든 인쇄 상품 공통) ----
    sections["trim"] = {"width_mm": profile.width_mm, "height_mm": profile.height_mm,
                          "custom_size_allowed": profile.custom_size_allowed}
    sections["bleed"] = {"bleed_mm": profile.safe_zone.bleed_mm}
    sections["safe_zone"] = {
        "margin_mm": profile.safe_zone.safe_margin_mm,
        "extra_margin_by_edge_mm": profile.safe_zone.extra_margin_by_edge_mm,
    }

    # ---- CutContour (CUTLINE_PRINT 상품만) ----
    if "CUTLINE_PRINT" in caps:
        cutline_section = {
            "offset_mm": profile.cutline_offset_mm,
            "minimum_radius_mm": profile.minimum_cut_radius_mm,
            "configured": profile.cutline_offset_mm is not None,
        }
        if cutline is not None:
            cutline_section.update({
                "point_count": len(cutline.points_mm),
                "self_intersections": len(cutline.analysis.self_intersections),
                "below_min_radius_count": len(cutline.analysis.corners_below_min_radius),
                "islands_removed": cutline.analysis.islands_removed,
            })
        sections["cutline"] = cutline_section

    # ---- WHITE (WHITE_INK_PRINT 상품만) ----
    if "WHITE_INK_PRINT" in caps or "WHITE_INK" in caps:
        white_section = {
            "choke_mm": profile.white_choke_mm,
            "spread_mm": profile.white_spread_mm,
            "configured": profile.white_choke_mm is not None or profile.white_spread_mm is not None,
        }
        if white_layer is not None:
            white_section["coverage_ratio"] = white_layer.coverage_ratio
        sections["white"] = white_section

    # ---- Hole (구멍 규격이 있는 상품만 - 키링 등) ----
    if profile.hole_diameter_mm is not None or "keyring" in (profile.product_id or ""):
        hole_section = {
            "diameter_mm": profile.hole_diameter_mm,
            "edge_margin_mm": profile.hole_edge_margin_mm,
            "configured": profile.hole_diameter_mm is not None,
        }
        if hole is not None:
            hole_section.update({
                "center_x_mm": hole.center_x_mm, "center_y_mm": hole.center_y_mm,
                "has_neck_connector": bool(hole.neck_points_mm),
            })
        sections["hole"] = hole_section

    # ---- Eyelet (아일렛 활성화 상품만) ----
    if profile.eyelet.enabled or "EYELET" in caps or "EYELET_FINISHING" in caps:
        eyelet_section = {
            "policy": profile.eyelet.placement_policy.value,
            "diameter_mm": profile.eyelet.diameter_mm,
            "margin_mm": profile.eyelet.margin_mm,
            "interval_mm": profile.eyelet.interval_mm,
        }
        if eyelet_points is not None:
            eyelet_section["point_count"] = len(eyelet_points)
        sections["eyelet"] = eyelet_section

    # ---- Production Status (Preflight 결과 요약 - 항상 표시) ----
    if preflight_report is not None:
        sections["production_status"] = {
            "overall": preflight_report.overall.value,
            "blocking_issue_count": sum(1 for i in preflight_report.issues if i.blocking),
            "warning_count": sum(1 for i in preflight_report.issues if i.level.value == "WARNING"),
        }

    return ProductionInspectorPayload(
        product_id=profile.product_id, product_name=profile.product_name, sections=sections,
    )
