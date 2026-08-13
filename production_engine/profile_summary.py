"""
profile_summary.py
---------------------
v1.9: 상품 Production Profile 구조 정리 (작업지시서 3번).

기존 ProductProfile/ProductProfileStub 모델에 필드를 또 추가하지 않는다 (v1.4~v1.8을
거치며 이미 필요한 원본 데이터는 다 있다). 대신 이 모듈은 "표준화된 조회 뷰"만
새로 만든다 - 작업지시서 3번이 요구하는 정확한 필드 이름으로 통일해서 보여주는
어댑터 계층이다 (단일 진실 소스는 여전히 ProductProfile/Stub 원본 필드들).

이렇게 분리한 이유: 원본 필드(dpi_warning_below 등)를 요구사항 필드명(recommended_dpi
등)으로 강제로 리네임하면 v1.4~v1.8에서 이미 그 이름으로 만들어둔 하위 호환 별칭
프로퍼티, 테스트, guide_merge.py 의 OVERRIDABLE_FIELDS 전부를 다시 손봐야 한다.
표준화된 "보고서/조회용 뷰"만 새로 만드는 편이 ADDITIVE 원칙에 맞고 훨씬 안전하다.
"""

from __future__ import annotations

import os
from typing import Optional, Union

from .config import JsonProductProfileRepository, load_profile_stubs
from .models import ProductProfile, ProductProfileStub

SEED_PATH = "production_engine/product_profiles.seed.json"
STUB_DIR = "product_profiles"


def summarize_profile(p: Union[ProductProfile, ProductProfileStub]) -> dict:
    """작업지시서 3번 명시 필드명 그대로 표준화된 dict 뷰를 만든다."""
    is_stub = isinstance(p, ProductProfileStub)

    custom_size_allowed = p.custom_size_allowed
    if custom_size_allowed is None:
        size_type = "UNKNOWN"
    else:
        size_type = "CUSTOM" if custom_size_allowed else "FIXED"

    fixed_sizes = []
    if size_type == "FIXED":
        width = getattr(p, "trim_width_mm", None) if is_stub else p.width_mm
        height = getattr(p, "trim_height_mm", None) if is_stub else p.height_mm
        if width is not None and height is not None:
            fixed_sizes = [{"width_mm": width, "height_mm": height}]
    elif getattr(p, "size_presets", None):
        fixed_sizes = list(p.size_presets)  # CUSTOM 이어도 프리셋이 있으면 참고용으로 노출

    eyelet_enabled = (p.eyelet_enabled if is_stub else p.eyelet.enabled)
    cutcontour_enabled = "CUTLINE_PRINT" in (p.capabilities or [])
    white_enabled = bool(getattr(p, "white_choke_mm", None) or getattr(p, "white_spread_mm", None)) or \
        any(c in (p.capabilities or []) for c in ("WHITE_INK_PRINT", "WHITE_INK"))
    hole_enabled = getattr(p, "hole_diameter_mm", None) is not None
    slot_enabled = getattr(p, "stand_slot_width_mm", None) is not None

    source = p.source
    return {
        "product_id": p.product_id,
        "category": p.category,
        "product_name": p.product_name,

        "size_type": size_type,
        "fixed_sizes": fixed_sizes,
        "custom_size_allowed": custom_size_allowed,

        "min_width_mm": p.min_width_mm, "max_width_mm": p.max_width_mm,
        "min_height_mm": p.min_height_mm, "max_height_mm": p.max_height_mm,

        "bleed_mm": (getattr(p, "bleed_mm", None) if is_stub else p.safe_zone.bleed_mm),
        "safe_margin_mm": (getattr(p, "safe_margin_mm", None) if is_stub else p.safe_zone.safe_margin_mm),

        "recommended_dpi": p.recommended_dpi if not is_stub else p.recommended_dpi,
        "minimum_dpi": p.minimum_dpi if not is_stub else p.minimum_dpi,

        "color_mode": (p.color_mode_target if not is_stub else p.color_mode),

        "eyelet": eyelet_enabled,
        "cutcontour": cutcontour_enabled,
        "white_layer": white_enabled,
        "hole": hole_enabled,
        "slot": slot_enabled,

        "material": getattr(p, "material", None),
        "thickness_mm": getattr(p, "material_thickness_mm", None),
        "print_method": getattr(p, "print_method", None),
        "stand_option_available": getattr(p, "stand_option_available", None),
        "verified_fields": list(getattr(p, "verified_fields", []) or []),

        "guide_status": p.production_status.value,

        "source": {
            "provider": source.provider, "url": source.url,
            "verified": source.verified,
        } if source else None,
        "verified_at": source.verified_at if source else None,

        "is_dev_default": getattr(p, "is_dev_default", False),
        "needs_confirmation": (p.needs_confirmation if is_stub else not source.verified if source else True),
    }


def summarize_all_products() -> list[dict]:
    """20개 상품 전체(확정 2 + 미확정 18)를 표준 뷰로 조회한다."""
    repo = JsonProductProfileRepository(SEED_PATH)
    confirmed = {p.product_id: summarize_profile(p) for p in repo.list_all()}

    stubs = load_profile_stubs(STUB_DIR)
    stub_summaries = {s.product_id: summarize_profile(s) for s in stubs}

    # 확정(banner_indoor/hyeonsumak_outdoor -> seed 쪽 product_id)과 stub 파일 쪽 product_id
    # (indoor_banner/banner) 가 서로 다른 슬러그를 쓰고 있어, 두 세트를 합쳐 20개를 만든다.
    all_products = {}
    all_products.update(confirmed)
    all_products.update(stub_summaries)
    return list(all_products.values())


def verified_count() -> int:
    return sum(1 for p in summarize_all_products() if p["guide_status"] == "VERIFIED")


def production_beta_readiness(product_ids: list[str]) -> dict[str, dict]:
    """작업지시서 5번: 우선 출시 상품(P0/P1)의 준비 상태."""
    all_summaries = {p["product_id"]: p for p in summarize_all_products()}
    result = {}
    for pid in product_ids:
        summary = all_summaries.get(pid)
        if summary is None:
            result[pid] = {"found": False}
            continue
        missing_for_verified = []
        for field in ("min_width_mm", "max_width_mm", "min_height_mm", "max_height_mm",
                      "bleed_mm", "safe_margin_mm", "recommended_dpi", "minimum_dpi", "color_mode"):
            if summary.get(field) is None:
                missing_for_verified.append(field)
        result[pid] = {
            "found": True,
            "guide_status": summary["guide_status"],
            "is_dev_default": summary["is_dev_default"],
            "ready_for_verified_promotion": len(missing_for_verified) == 0 and not summary["is_dev_default"],
            "missing_fields": missing_for_verified,
        }
    return result
