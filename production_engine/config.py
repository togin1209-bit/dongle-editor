"""
config.py
-----------
ProductProfile 저장소.

지금은 JSON 시드 파일에서 로드하지만, 인터페이스(ProductProfileRepository)를
그대로 유지한 채 구현체만 DB 조회로 교체하면 된다.
GPT 쪽에서 실제 DB(Postgres 등) 연동 시:
  - product_profiles 테이블 스키마를 이 JSON 구조와 동일하게 설계하고
  - JsonProductProfileRepository 를 DbProductProfileRepository 로 교체하면
  - 이 파일을 사용하는 다른 모든 코드(pipeline.py 등)는 수정할 필요가 없다.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Optional

from .models import (
    EyeletPlacementPolicy,
    EyeletSpec,
    FitPolicy,
    ProductionStatus,
    ProductProfile,
    ProductProfileStub,
    SafeZoneSpec,
    SourceInfo,
)


class ProductProfileRepository(ABC):
    @abstractmethod
    def get(self, product_id: str) -> ProductProfile:
        ...

    @abstractmethod
    def list_all(self) -> list[ProductProfile]:
        ...


class ProductProfileNotFound(Exception):
    pass


class JsonProductProfileRepository(ProductProfileRepository):
    def __init__(self, json_path: str):
        self._json_path = json_path
        self._cache: Optional[dict[str, ProductProfile]] = None

    def _load(self) -> dict[str, ProductProfile]:
        if self._cache is not None:
            return self._cache
        with open(self._json_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        profiles: dict[str, ProductProfile] = {}
        for p in raw["profiles"]:
            sz = SafeZoneSpec(**p["safe_zone"])
            eyelet_raw = p.get("eyelet") or {}
            eyelet = EyeletSpec(
                enabled=eyelet_raw.get("enabled", False),
                diameter_mm=eyelet_raw.get("diameter_mm", 8.0),
                margin_mm=eyelet_raw.get("margin_mm", 20.0),
                interval_mm=eyelet_raw.get("interval_mm", 500.0),
                placement_policy=EyeletPlacementPolicy(eyelet_raw.get("placement_policy", "NONE")),
            )
            profiles[p["product_id"]] = ProductProfile(
                product_id=p["product_id"],
                product_name=p["product_name"],
                category=p["category"],
                width_mm=p["width_mm"],
                height_mm=p["height_mm"],
                custom_size_allowed=p.get("custom_size_allowed", True),
                min_width_mm=p["min_width_mm"],
                max_width_mm=p["max_width_mm"],
                min_height_mm=p["min_height_mm"],
                max_height_mm=p["max_height_mm"],
                safe_zone=sz,
                dpi_warning_below=p["dpi_warning_below"],
                dpi_error_below=p["dpi_error_below"],
                default_fit_policy=FitPolicy(p["default_fit_policy"]),
                color_mode_target=p["color_mode_target"],
                icc_profile_name=p.get("icc_profile_name"),
                pdf_standard=p.get("pdf_standard", "PDF/X-1a"),
                finishing=p.get("finishing", []),
                eyelet=eyelet,
                related_products=p.get("related_products", []),
                production_status=ProductionStatus(p.get("production_status", "GUIDE_REQUIRED")),
                source=SourceInfo(**p["source"]) if p.get("source") else SourceInfo(),
                is_dev_default=p.get("is_dev_default", False),
                size_presets=p.get("size_presets", []),
                material=p.get("material"),
                print_method=p.get("print_method"),
                stand_option_available=p.get("stand_option_available"),
                verified_fields=p.get("verified_fields", []),
                size_constraint_mode=p.get("size_constraint_mode", "RECTANGULAR_AXES"),
                capabilities=p.get("capabilities", []),
                cutline_offset_mm=p.get("cutline_offset_mm"),
                minimum_cut_radius_mm=p.get("minimum_cut_radius_mm"),
                hole_diameter_mm=p.get("hole_diameter_mm"),
                hole_edge_margin_mm=p.get("hole_edge_margin_mm"),
                material_thickness_mm=p.get("material_thickness_mm"),
                stand_tab_width_mm=p.get("stand_tab_width_mm"),
                stand_tab_height_mm=p.get("stand_tab_height_mm"),
                stand_slot_width_mm=p.get("stand_slot_width_mm"),
                stand_slot_clearance_mm=p.get("stand_slot_clearance_mm"),
                white_choke_mm=p.get("white_choke_mm"),
                white_spread_mm=p.get("white_spread_mm"),
            )
        self._cache = profiles
        return profiles

    def get(self, product_id: str) -> ProductProfile:
        profiles = self._load()
        if product_id not in profiles:
            raise ProductProfileNotFound(product_id)
        return profiles[product_id]

    def list_all(self) -> list[ProductProfile]:
        return list(self._load().values())


def load_profile_stubs(directory: str) -> list[ProductProfileStub]:
    """
    v1.4b: product_profiles/<category>/<product_id>.json 구조를 재귀적으로 읽어
    ProductProfileStub 리스트로 반환한다 (카테고리별 하위 폴더 지원).

    "status": "CONFIRMED_IN_V1_3_SEED" 로 표시된 항목(배너/현수막)은 실제로는
    JsonProductProfileRepository 쪽 확정 프로필을 써야 하므로 여기서는 건너뛴다.
    "_" 로 시작하는 파일(_ui_groups.json 등 보조 스펙 파일)도 건너뛴다.

    각 stub 은 로드 직후 validate_production_status() 를 통과해야 한다 - 잘못된
    VERIFIED 라벨이 조용히 섞여 들어오는 것을 방지한다.
    """
    stubs: list[ProductProfileStub] = []
    if not os.path.isdir(directory):
        return stubs

    for root, _dirs, files in os.walk(directory):
        for filename in sorted(files):
            if not filename.endswith(".json") or filename.startswith("_"):
                continue
            with open(os.path.join(root, filename), "r", encoding="utf-8") as f:
                raw = json.load(f)

            # "status" 필드가 있으면(CONFIRMED_IN_V1_3_SEED, CONFIRMED_IN_V1_9_SEED 등,
            # 버전에 무관하게) 이미 JsonProductProfileRepository 쪽에서 확정 프로필로
            # 관리되고 있다는 뜻이므로 stub 목록에서 제외한다. 정확한 버전 문자열을
            # 하드코딩하지 않고, "status" 키 존재 자체를 기준으로 판단해 향후 버전에서도
            # 매번 이 조건을 갱신할 필요가 없게 했다 (v1.9에서 실제로 이 문제를 겪고 수정함:
            # CONFIRMED_IN_V1_3_SEED 문자열만 체크하다 CONFIRMED_IN_V1_9_SEED 파일을
            # 걸러내지 못한 버그가 있었다).
            status_value = raw.get("status", "")
            if isinstance(status_value, str) and status_value.startswith("CONFIRMED_IN_"):
                continue

            stub = _stub_from_dict(raw)
            stub.validate_production_status()
            stubs.append(stub)
    return stubs


def _stub_from_dict(raw: dict) -> ProductProfileStub:
    source_raw = raw.get("source") or {}
    source = SourceInfo(
        provider=source_raw.get("provider"),
        url=source_raw.get("url"),
        verified=source_raw.get("verified", False),
        verified_at=source_raw.get("verified_at"),
        notes=source_raw.get("notes"),
    )
    return ProductProfileStub(
        product_id=raw["product_id"],
        category=raw["category"],
        product_name=raw["product_name"],
        variant=raw.get("variant"),
        capabilities=raw.get("capabilities", []),
        trim_width_mm=raw.get("trim_width_mm"),
        trim_height_mm=raw.get("trim_height_mm"),
        work_width_mm=raw.get("work_width_mm"),
        work_height_mm=raw.get("work_height_mm"),
        bleed_mm=raw.get("bleed_mm"),
        min_width_mm=raw.get("min_width_mm"),
        max_width_mm=raw.get("max_width_mm"),
        min_height_mm=raw.get("min_height_mm"),
        max_height_mm=raw.get("max_height_mm"),
        custom_size_allowed=raw.get("custom_size_allowed"),
        recommended_dpi=raw.get("recommended_dpi"),
        minimum_dpi=raw.get("minimum_dpi"),
        color_mode=raw.get("color_mode"),
        icc_profile=raw.get("icc_profile"),
        safe_margin_mm=raw.get("safe_margin_mm"),
        cutline_required=raw.get("cutline_required"),
        cutline_type=raw.get("cutline_type"),
        white_ink_required=raw.get("white_ink_required"),
        white_ink_rule=raw.get("white_ink_rule"),
        eyelet_enabled=raw.get("eyelet_enabled"),
        finishing=raw.get("finishing", []),
        front_back=raw.get("front_back"),
        supported_source_formats=raw.get("supported_source_formats", []),
        production_notes=raw.get("production_notes"),
        needs_confirmation=raw.get("needs_confirmation", True),
        unconfirmed_fields=raw.get("unconfirmed_fields", []),
        source_urls=raw.get("source_urls", []),
        related_products=raw.get("related_products", []),
        source=source,
        production_status=ProductionStatus(raw.get("production_status", "GUIDE_REQUIRED")),
        cutline_offset_mm=raw.get("cutline_offset_mm"),
        minimum_cut_radius_mm=raw.get("minimum_cut_radius_mm"),
        hole_diameter_mm=raw.get("hole_diameter_mm"),
        hole_edge_margin_mm=raw.get("hole_edge_margin_mm"),
        material_thickness_mm=raw.get("material_thickness_mm"),
        stand_tab_width_mm=raw.get("stand_tab_width_mm"),
        stand_tab_height_mm=raw.get("stand_tab_height_mm"),
        stand_slot_width_mm=raw.get("stand_slot_width_mm"),
        stand_slot_clearance_mm=raw.get("stand_slot_clearance_mm"),
        white_choke_mm=raw.get("white_choke_mm"),
        white_spread_mm=raw.get("white_spread_mm"),
        size_presets=raw.get("size_presets", []),
        material=raw.get("material"),
        print_method=raw.get("print_method"),
        stand_option_available=raw.get("stand_option_available"),
        verified_fields=raw.get("verified_fields", []),
    )
