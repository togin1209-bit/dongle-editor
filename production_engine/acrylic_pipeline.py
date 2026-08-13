"""
acrylic_pipeline.py
----------------------
v1.6: Acrylic Production Intelligence 오케스트레이션 + API Contract (작업지시서 2/9번).

기존 pipeline.ProductionPipeline(RECTANGULAR_PRINT)은 그대로 두고 건드리지 않는다.
이 모듈은 아크릴 전용 흐름(Contour/Hole/Stand/White/Manufacturability)을 별도로
오케스트레이션한다 - CUTLINE_PRINT/WHITE_INK_PRINT capability가 아직
pipeline_router.IMPLEMENTED_CAPABILITIES 에 없으므로, 이 파이프라인의 산출물은
"기존 Production PDF 파이프라인을 대체"하는 것이 아니라 "칼선/구멍/화이트 데이터를
생성하는 별도 단계"로 취급해야 한다. GPT 통합 시 라우팅 정책을 조율해야 한다
(README/보고서 참고).

=== API Contract (작업지시서 9번) ===
아래 엔드포인트 <-> 메서드 매핑을 그대로 구현하면 된다 (프레임워크는 GPT가 선택):

  POST /api/jobs/{job}/contour/analyze    -> AcrylicProductionPipeline.analyze_contour()
  POST /api/jobs/{job}/contour/generate   -> AcrylicProductionPipeline.generate_cutline()
  POST /api/jobs/{job}/hole/recommend     -> AcrylicProductionPipeline.recommend_hole()
  POST /api/jobs/{job}/stand/generate     -> AcrylicProductionPipeline.generate_stand()
  POST /api/jobs/{job}/white/generate     -> AcrylicProductionPipeline.generate_white_layer()
  POST /api/jobs/{job}/manufacturability  -> AcrylicProductionPipeline.analyze_manufacturability()

기존 API(v1.2~v1.5의 /api/jobs, /api/jobs/{job}/upload, /api/jobs/{job}/preflight,
/api/jobs/{job}/export 등)는 이 모듈이 전혀 건드리지 않는다 - 완전히 별도 진입점이다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from PIL import Image

from .models import ProductProfile
from .security.storage import JobStorage
from .vision.auto_repair import AutoRepairResult, auto_repair
from .vision.contour_engine import ContourEngineError, ProductionCutline, build_production_cutline
from .vision.hole_placement import HoleGeometry, HolePlacementMode, place_hole, recommend_hole_positions
from .vision.manufacturability import ManufacturabilityReport, analyze_manufacturability
from .vision.stand_builder import BaseShape, SlotPosition, StandBuildResult, StandParams, build_stand
from .vision.white_layer import WhiteLayerResult, generate_white_layer


class AcrylicPipelineError(Exception):
    pass


@dataclass
class AcrylicJobContext:
    job_id: str
    profile: ProductProfile
    source_rgba: Optional[np.ndarray] = None
    source_path: Optional[str] = None
    repaired_rgba: Optional[np.ndarray] = None
    repair_actions_summary: Optional[str] = None
    cutline: Optional[ProductionCutline] = None
    hole: Optional[HoleGeometry] = None
    stand_result: Optional[StandBuildResult] = None
    white_layer: Optional[WhiteLayerResult] = None
    manufacturability: Optional[ManufacturabilityReport] = None


class AcrylicProductionPipeline:
    def __init__(self, storage: JobStorage):
        self.storage = storage

    # ---- 공통: 원본 로드 (읽기 전용) ----
    def load_source(self, ctx: AcrylicJobContext, source_path: str) -> AcrylicJobContext:
        with Image.open(source_path) as img:
            if img.mode != "RGBA":
                raise AcrylicPipelineError(
                    f"아크릴 컨투어 추출에는 RGBA(투명 배경) 이미지가 필요합니다. "
                    f"현재 모드: {img.mode}"
                )
            rgba = np.array(img)
        ctx.source_path = source_path
        ctx.source_rgba = rgba
        return ctx

    # ---- POST /api/jobs/{job}/contour/analyze ----
    def analyze_contour(
        self, ctx: AcrylicJobContext, dpi: float, use_repaired: bool = True
    ) -> ProductionCutline:
        """분석만 수행(오프셋 없이 artwork 외곽만) - 자기교차/코너/노이즈 진단 목적."""
        rgba = self._active_rgba(ctx, use_repaired)
        offset_mm = 0.0  # 분석 단계는 순수 artwork 외곽 기준
        cutline = build_production_cutline(
            rgba, dpi=dpi, offset_mm=offset_mm,
            min_island_area_mm2=1.0,
            min_radius_mm=ctx.profile.minimum_cut_radius_mm,
        )
        ctx.cutline = cutline
        return cutline

    # ---- POST /api/jobs/{job}/contour/generate ----
    def generate_cutline(
        self, ctx: AcrylicJobContext, dpi: float, use_repaired: bool = True
    ) -> ProductionCutline:
        """실제 제작용 칼선 생성 - Product Profile의 cutline_offset_mm 을 반드시 사용한다."""
        if ctx.profile.cutline_offset_mm is None:
            raise AcrylicPipelineError(
                f"'{ctx.profile.product_id}' 상품의 cutline_offset_mm 이 아직 확인되지 않았습니다. "
                "제작 칼선을 생성할 수 없습니다 (needs_confirmation 상태)."
            )
        rgba = self._active_rgba(ctx, use_repaired)
        cutline = build_production_cutline(
            rgba, dpi=dpi, offset_mm=ctx.profile.cutline_offset_mm,
            min_island_area_mm2=1.0,
            min_radius_mm=ctx.profile.minimum_cut_radius_mm,
        )
        ctx.cutline = cutline
        return cutline

    # ---- POST /api/jobs/{job}/hole/recommend ----
    def recommend_hole(self, ctx: AcrylicJobContext, max_candidates: int = 3) -> list:
        if ctx.cutline is None:
            raise AcrylicPipelineError("먼저 contour/analyze 또는 contour/generate 를 호출해야 합니다.")
        if ctx.profile.hole_diameter_mm is None or ctx.profile.hole_edge_margin_mm is None:
            raise AcrylicPipelineError(
                f"'{ctx.profile.product_id}' 상품의 hole_diameter_mm/hole_edge_margin_mm 이 "
                "아직 확인되지 않았습니다."
            )
        return recommend_hole_positions(
            ctx.cutline.points_mm, ctx.profile.hole_diameter_mm, ctx.profile.hole_edge_margin_mm,
            max_candidates=max_candidates,
        )

    def place_hole_on_job(
        self, ctx: AcrylicJobContext, mode: HolePlacementMode,
        manual_x_mm: Optional[float] = None, manual_y_mm: Optional[float] = None,
    ) -> HoleGeometry:
        if ctx.cutline is None:
            raise AcrylicPipelineError("먼저 contour/generate 를 호출해야 합니다.")
        if ctx.profile.hole_diameter_mm is None or ctx.profile.hole_edge_margin_mm is None:
            raise AcrylicPipelineError("hole_diameter_mm/hole_edge_margin_mm 이 확인되지 않았습니다.")
        hole = place_hole(
            mode, ctx.cutline.points_mm, ctx.profile.hole_diameter_mm, ctx.profile.hole_edge_margin_mm,
            manual_x_mm=manual_x_mm, manual_y_mm=manual_y_mm,
        )
        ctx.hole = hole
        return hole

    # ---- POST /api/jobs/{job}/stand/generate ----
    def generate_stand(
        self, ctx: AcrylicJobContext, base_width_mm: float, base_depth_mm: float,
        base_shape: BaseShape = BaseShape.ROUNDED_RECTANGLE,
        slot_position: SlotPosition = SlotPosition.AUTO,
    ) -> StandBuildResult:
        if ctx.cutline is None:
            raise AcrylicPipelineError("먼저 contour/generate 를 호출해야 합니다.")
        params = StandParams(
            material_thickness_mm=ctx.profile.material_thickness_mm,
            tab_width_mm=ctx.profile.stand_tab_width_mm,
            tab_height_mm=ctx.profile.stand_tab_height_mm,
            slot_width_mm=ctx.profile.stand_slot_width_mm,
            slot_clearance_mm=ctx.profile.stand_slot_clearance_mm,
        )
        result = build_stand(ctx.cutline, params, base_width_mm, base_depth_mm, base_shape, slot_position)
        ctx.stand_result = result
        return result

    # ---- POST /api/jobs/{job}/white/generate ----
    def generate_white_layer(self, ctx: AcrylicJobContext, dpi: float, use_repaired: bool = True) -> WhiteLayerResult:
        rgba = self._active_rgba(ctx, use_repaired)
        result = generate_white_layer(
            rgba, dpi=dpi, choke_mm=ctx.profile.white_choke_mm, spread_mm=ctx.profile.white_spread_mm,
        )
        ctx.white_layer = result
        return result

    # ---- Auto Repair (working copy 전용) ----
    def auto_repair_source(self, ctx: AcrylicJobContext) -> AutoRepairResult:
        if ctx.source_rgba is None:
            raise AcrylicPipelineError("먼저 load_source() 를 호출해야 합니다.")
        result = auto_repair(ctx.source_rgba)  # ctx.source_rgba 는 절대 변경되지 않음 (auto_repair 내부에서 .copy())
        ctx.repaired_rgba = result.repaired_rgba
        ctx.repair_actions_summary = result.summary()
        return result

    def _active_rgba(self, ctx: AcrylicJobContext, use_repaired: bool) -> np.ndarray:
        if ctx.source_rgba is None:
            raise AcrylicPipelineError("먼저 load_source() 를 호출해야 합니다.")
        if use_repaired and ctx.repaired_rgba is not None:
            return ctx.repaired_rgba
        return ctx.source_rgba

    # ---- POST /api/jobs/{job}/manufacturability ----
    def analyze_manufacturability(
        self, ctx: AcrylicJobContext, effective_dpi: Optional[float] = None
    ) -> ManufacturabilityReport:
        if ctx.cutline is None:
            raise AcrylicPipelineError("먼저 contour/generate 를 호출해야 합니다.")

        white_required = ctx.profile.white_choke_mm is not None or ctx.profile.white_spread_mm is not None
        report = analyze_manufacturability(
            ctx.cutline,
            min_radius_mm=ctx.profile.minimum_cut_radius_mm,
            hole=ctx.hole,
            stand_result=ctx.stand_result,
            white_layer_generated=ctx.white_layer is not None,
            white_layer_required=white_required,
            source_has_alpha=ctx.source_rgba is not None,
            effective_dpi=effective_dpi,
            recommended_dpi=ctx.profile.recommended_dpi,
        )
        ctx.manufacturability = report
        return report
