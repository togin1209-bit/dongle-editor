"""
guide_merge.py
------------------
v1.4b 작업지시서 #4: "실제 제작가이드 값은 추후 GPT가 제공할 product_guides_verified.json
을 주입하면 적용할 수 있도록, 데이터와 Production Engine을 완전히 분리해주세요."

이 모듈이 그 분리 지점이다.

흐름:
  1. product_profiles/<category>/<product_id>.json  (여기 있는 stub, 지금은 전부 null)
  2. + product_guides_verified.json                  (GPT가 실제 조사 후 제공할 검증 데이터)
  3. = merge_verified_guides() 가 병합한 완전한 ProductProfileStub (필드가 채워짐)
  4. .to_product_profile() 로 승격 -> 실제 파이프라인 투입 가능

**엔진 코드(models.py, pipeline.py, preflight/engine.py 등) 는 이 병합 과정에서
전혀 수정되지 않는다.** product_guides_verified.json 파일 하나만 새로 생기거나
바뀌어도 아래 함수들을 그대로 재호출하면 최신 데이터가 반영된다 - 이것이
"데이터와 엔진의 완전한 분리"의 의미다.

product_guides_verified.json 예상 스키마 (product_id 를 키로 하는 dict):
{
  "acrylic_keyring": {
    "trim_width_mm": 50, "trim_height_mm": 50, "bleed_mm": 2,
    "min_width_mm": 30, "max_width_mm": 100, "min_height_mm": 30, "max_height_mm": 100,
    "custom_size_allowed": true, "recommended_dpi": 300, "minimum_dpi": 150,
    "color_mode": "CMYK", "safe_margin_mm": 3,
    "source": {
      "provider": "adpiamall", "url": "https://www.adpiamall.com/estimate/goods2019/667",
      "verified": true, "verified_at": "2026-08-12T00:00:00+00:00",
      "notes": "GPT가 실제 페이지를 조사해 확인함"
    }
  },
  ...
}
"""

from __future__ import annotations

import json
import os

from .models import ProductionStatus, ProductProfileStub, SourceInfo

# ProductProfileStub 의 필드 중, 검증된 가이드로 덮어쓸 수 있는 필드 목록.
# (product_id/category/product_name/capabilities/related_products 처럼 taxonomy.py 에서
#  오는 구조적 필드는 가이드로 덮어쓰지 않는다 - 그건 taxonomy.py 의 책임이다.)
OVERRIDABLE_FIELDS = (
    "variant", "trim_width_mm", "trim_height_mm", "work_width_mm", "work_height_mm",
    "bleed_mm", "min_width_mm", "max_width_mm", "min_height_mm", "max_height_mm",
    "custom_size_allowed", "recommended_dpi", "minimum_dpi", "color_mode", "icc_profile",
    "safe_margin_mm", "cutline_required", "cutline_type", "white_ink_required",
    "white_ink_rule", "eyelet_enabled", "finishing", "front_back", "material",
    "supported_source_formats", "production_notes",
    # v1.6: 아크릴 제작 파라미터
    "cutline_offset_mm", "minimum_cut_radius_mm", "hole_diameter_mm", "hole_edge_margin_mm",
    "material_thickness_mm", "stand_tab_width_mm", "stand_tab_height_mm",
    "stand_slot_width_mm", "stand_slot_clearance_mm", "white_choke_mm", "white_spread_mm",
    "size_presets", "print_method", "stand_option_available",
)


def load_verified_guides(path: str) -> dict[str, dict]:
    """product_guides_verified.json 을 로드한다. 파일이 없으면 빈 dict (아직 검증된 게 없다는 뜻)."""
    if not path or not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def merge_guide_into_stub(stub: ProductProfileStub, guide_entry: dict) -> ProductProfileStub:
    """
    검증된 가이드 데이터 1건을 stub 에 덮어써서 새 ProductProfileStub 을 반환한다
    (원본 stub 은 변경하지 않는다 - 순수 함수).

    - OVERRIDABLE_FIELDS 에 있는 값만 덮어쓴다.
    - 덮어쓴 필드는 unconfirmed_fields 에서 제거된다.
    - guide_entry 에 "source" 가 있으면 SourceInfo 로 반영한다.
    - 남은 unconfirmed_fields 가 없고 source.verified=True 면 production_status 를
      VERIFIED 로, 일부만 채워졌으면 PARTIAL 로 자동 승격한다.
    """
    import copy

    merged = copy.deepcopy(stub)

    for field_name in OVERRIDABLE_FIELDS:
        if field_name in guide_entry and guide_entry[field_name] is not None:
            setattr(merged, field_name, guide_entry[field_name])
            if field_name in merged.unconfirmed_fields:
                merged.unconfirmed_fields.remove(field_name)

    if "source" in guide_entry:
        s = guide_entry["source"]
        merged.source = SourceInfo(
            provider=s.get("provider", merged.source.provider),
            url=s.get("url", merged.source.url),
            verified=s.get("verified", merged.source.verified),
            verified_at=s.get("verified_at", merged.source.verified_at),
            notes=s.get("notes", merged.source.notes),
        )

    if merged.is_ready_for_production() and merged.source.verified:
        merged.production_status = ProductionStatus.VERIFIED
        merged.needs_confirmation = False
    elif len(merged.unconfirmed_fields) < len(stub.unconfirmed_fields):
        merged.production_status = ProductionStatus.PARTIAL
        # PARTIAL 은 여전히 파이프라인에 투입 불가 (needs_confirmation 유지)

    return merged


def merge_all(stubs: list[ProductProfileStub], guides: dict[str, dict]) -> list[ProductProfileStub]:
    """stub 리스트 전체에 대해 해당 product_id 의 검증 가이드가 있으면 병합한다."""
    result = []
    for stub in stubs:
        guide_entry = guides.get(stub.product_id)
        if guide_entry:
            merged = merge_guide_into_stub(stub, guide_entry)
            merged.validate_production_status()  # VERIFIED 오표시 방어
            result.append(merged)
        else:
            result.append(stub)
    return result
