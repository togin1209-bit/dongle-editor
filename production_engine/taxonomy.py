"""
taxonomy.py
-------------
v1.4/v1.4b: 20개 상품 Product Taxonomy, product_id 매핑, Capability 구성.

**중요 - 이 파일의 신뢰 수준**
- PRODUCT_TAXONOMY (상품 목록/그룹) 은 작업지시서에 명시된 20개 상품명을 그대로
  옮긴 것 - 확인된 사실이다.
- PRODUCT_ID_CAPABILITIES (상품별 capability 조합) 은 실제 상품 페이지를 조사하지
  못한 상태에서 일반적인 인쇄업계 관행에 기반해 구성한 "엔지니어링 추정치"다.
  예: "아크릴키링은 보통 칼선+화이트잉크+투명소재"라는 업계 통념이지, 이 특정
  업체의 실제 사양을 확인한 것이 아니다. 실제 조사 후 반드시 재검증해야 하며,
  이로부터 생성되는 모든 ProductProfileStub 은 needs_confirmation=True 로 표시된다.
- ROUTING_CAPABILITIES 는 실제 파이프라인 실행 여부를 좌우하는 부분집합이고,
  나머지는 "정보 표시용 속성 태그"라 라우팅/preflight 구현 여부 검사에 관여하지 않는다.
"""

from __future__ import annotations

from .models import Capability

# ---- B. Product Taxonomy (작업지시서 원문 그대로) ----
PRODUCT_TAXONOMY: dict[str, list[str]] = {
    "SIGNAGE": ["실내용배너", "실외용배너", "현수막"],
    "ACRYLIC": ["아크릴인쇄", "아크릴키링", "아크릴스탠드"],
    "BUTTON": ["버튼", "패브릭버튼"],
    "STICKER": ["에폭시스티커", "띠부스티커", "패브릭스티커", "DTF스티커", "차량스티커"],
    "LARGE_FORMAT": ["실사출력 인화지", "실사출력 통자석", "실사출력 시트지컷팅"],
    "CARD": ["일반지명함", "고급지명함", "디지털 청첩장", "투명하이브리드명함/투명포토카드"],
}

# 한글 상품명 -> product_id(영문 slug) -> product_profiles/<category_dir>/<file>.json 경로.
# 이 slug 체계는 임의로 부여한 것이므로, 실제 운영 상품 코드가 있으면 교체해야 한다.
PRODUCT_NAME_TO_ID: dict[str, str] = {
    "실내용배너": "indoor_banner",
    "실외용배너": "outdoor_banner",
    "현수막": "banner",
    "아크릴인쇄": "acrylic_print",
    "아크릴키링": "acrylic_keyring",
    "아크릴스탠드": "acrylic_stand",
    "버튼": "button",
    "패브릭버튼": "fabric_button",
    "에폭시스티커": "epoxy_sticker",
    "띠부스티커": "removable_sticker",
    "패브릭스티커": "fabric_sticker",
    "DTF스티커": "dtf_sticker",
    "차량스티커": "vehicle_sticker",
    "실사출력 인화지": "photo_paper",
    "실사출력 통자석": "magnetic_sheet",
    "실사출력 시트지컷팅": "vinyl_cutting",
    "일반지명함": "standard_business_card",
    "고급지명함": "premium_business_card",
    "디지털 청첩장": "digital_invitation",
    "투명하이브리드명함/투명포토카드": "transparent_hybrid_card",
}
PRODUCT_ID_TO_NAME: dict[str, str] = {v: k for k, v in PRODUCT_NAME_TO_ID.items()}

# v1.4b: 실내용배너(indoor_banner)/현수막(banner) 은 v1.2~v1.3 부터 이미 "banner_indoor"/
# "hyeonsumak_outdoor" 라는 product_id 로 seed.json/app.py/기존 60개 테스트에 깊이 연결되어
# 있다. 폴더 재구조화(카테고리별 slug 통일)를 이 두 상품에도 그대로 적용하면 기존에 정상
# 동작하던 파이프라인이 깨지므로, "새 taxonomy slug" <-> "기존에 실제로 쓰이는 확정
# product_id" 를 명시적으로 연결하는 별칭 테이블을 둔다. 신규 18개 상품은 이 별칭이 필요
# 없다 (아직 확정 프로필이 없으므로 taxonomy slug 를 그대로 product_id 로 채택).
CONFIRMED_PRODUCT_ID_ALIAS: dict[str, str] = {
    "indoor_banner": "banner_indoor",       # product_profiles/signage/indoor_banner.json -> seed.json "banner_indoor"
    "banner": "hyeonsumak_outdoor",         # product_profiles/signage/banner.json -> seed.json "hyeonsumak_outdoor"
}

# category -> product_profiles/ 하위 폴더명 (요청된 폴더 구조 그대로)
CATEGORY_DIR: dict[str, str] = {
    "SIGNAGE": "signage",
    "ACRYLIC": "acrylic",
    "BUTTON": "button",
    "STICKER": "sticker",
    "LARGE_FORMAT": "large_format",
    "CARD": "card",
}


def all_product_names() -> list[tuple[str, str]]:
    """(category, product_name) 튜플 리스트로 20개 상품 전체를 반환."""
    out = []
    for category, names in PRODUCT_TAXONOMY.items():
        for name in names:
            out.append((category, name))
    return out


def all_products() -> list[tuple[str, str, str]]:
    """(category, product_name, product_id) 튜플 리스트."""
    return [(cat, name, PRODUCT_NAME_TO_ID[name]) for cat, name in all_product_names()]


# ---- 라우팅 capability: pipeline_router.py / preflight 가 "구현됐는지" 를 검사하는 대상 ----
ROUTING_CAPABILITIES: set[str] = {
    Capability.RECTANGULAR_PRINT.value,
    Capability.CUTLINE_PRINT.value,
    Capability.WHITE_INK_PRINT.value,
    Capability.DOUBLE_SIDE_PRINT.value,
    Capability.LARGE_FORMAT_PRINT.value,
    Capability.NO_PRINT_CUTTING.value,
    Capability.EYELET_FINISHING.value,
}

# v1.4: 실제로 구현/검증된 라우팅 capability 집합.
IMPLEMENTED_CAPABILITIES: set[str] = {
    Capability.RECTANGULAR_PRINT.value,
    Capability.EYELET_FINISHING.value,
}

# ---- C+작업지시서 v1.4b #9: 상품별 명시적 Capability 구성 ----
# 라우팅 capability + 속성 태그를 함께 담는다. product_id 기준.
# 예시(작업지시서 원문)와 일치하도록 구성했고, 나머지 상품은 같은 원칙을 유지하며
# 일관되게 채운 "엔지니어링 추정치"다 (전부 재검증 필요).
PRODUCT_ID_CAPABILITIES: dict[str, list[str]] = {
    # SIGNAGE
    "indoor_banner": [Capability.RECTANGULAR_PRINT.value, Capability.CMYK_OUTPUT.value, Capability.FIXED_SIZE.value],
    "outdoor_banner": [Capability.RECTANGULAR_PRINT.value, Capability.CMYK_OUTPUT.value, Capability.CUSTOM_SIZE.value, Capability.EYELET_FINISHING.value, Capability.EYELET.value],
    "banner": [Capability.RECTANGULAR_PRINT.value, Capability.CMYK_OUTPUT.value, Capability.CUSTOM_SIZE.value, Capability.EYELET_FINISHING.value, Capability.EYELET.value],
    # ACRYLIC
    "acrylic_print": [Capability.CUTLINE_PRINT.value, Capability.WHITE_INK_PRINT.value, Capability.WHITE_INK.value, Capability.TRANSPARENT_MATERIAL.value, Capability.CMYK_OUTPUT.value, Capability.CUSTOM_SIZE.value],
    "acrylic_keyring": [Capability.CUTLINE_PRINT.value, Capability.WHITE_INK_PRINT.value, Capability.WHITE_INK.value, Capability.TRANSPARENT_MATERIAL.value, Capability.CMYK_OUTPUT.value, Capability.CUSTOM_SIZE.value],
    "acrylic_stand": [Capability.CUTLINE_PRINT.value, Capability.WHITE_INK_PRINT.value, Capability.WHITE_INK.value, Capability.TRANSPARENT_MATERIAL.value, Capability.CMYK_OUTPUT.value, Capability.CUSTOM_SIZE.value],
    # BUTTON
    "button": [Capability.CUTLINE_PRINT.value, Capability.ROUND_PRODUCT.value, Capability.CMYK_OUTPUT.value, Capability.FIXED_SIZE.value],
    "fabric_button": [Capability.CUTLINE_PRINT.value, Capability.ROUND_PRODUCT.value, Capability.CMYK_OUTPUT.value, Capability.FIXED_SIZE.value],
    # STICKER
    "epoxy_sticker": [Capability.CUTLINE_PRINT.value, Capability.CMYK_OUTPUT.value, Capability.CUSTOM_SIZE.value],
    "removable_sticker": [Capability.CUTLINE_PRINT.value, Capability.CMYK_OUTPUT.value, Capability.CUSTOM_SIZE.value],
    "fabric_sticker": [Capability.CUTLINE_PRINT.value, Capability.CMYK_OUTPUT.value, Capability.CUSTOM_SIZE.value],
    "dtf_sticker": [Capability.CUTLINE_PRINT.value, Capability.CMYK_OUTPUT.value, Capability.CUSTOM_SIZE.value],
    "vehicle_sticker": [Capability.CUTLINE_PRINT.value, Capability.LARGE_FORMAT_PRINT.value, Capability.CMYK_OUTPUT.value, Capability.CUSTOM_SIZE.value],
    # LARGE_FORMAT
    "photo_paper": [Capability.RECTANGULAR_PRINT.value, Capability.LARGE_FORMAT_PRINT.value, Capability.CMYK_OUTPUT.value, Capability.CUSTOM_SIZE.value],
    "magnetic_sheet": [Capability.RECTANGULAR_PRINT.value, Capability.LARGE_FORMAT_PRINT.value, Capability.CMYK_OUTPUT.value, Capability.CUSTOM_SIZE.value],
    "vinyl_cutting": [Capability.NO_PRINT_CUTTING.value, Capability.NO_PRINT.value, Capability.VECTOR_CUT_PATH.value, Capability.CUSTOM_SIZE.value],
    # CARD
    "standard_business_card": [Capability.RECTANGULAR_PRINT.value, Capability.DOUBLE_SIDE_PRINT.value, Capability.CMYK_OUTPUT.value, Capability.FIXED_SIZE.value],
    "premium_business_card": [Capability.RECTANGULAR_PRINT.value, Capability.DOUBLE_SIDE_PRINT.value, Capability.CMYK_OUTPUT.value, Capability.FIXED_SIZE.value],
    "digital_invitation": [Capability.RECTANGULAR_PRINT.value, Capability.CMYK_OUTPUT.value, Capability.CUSTOM_SIZE.value],
    "transparent_hybrid_card": [Capability.RECTANGULAR_PRINT.value, Capability.DOUBLE_SIDE_PRINT.value, Capability.TRANSPARENT_MATERIAL.value, Capability.CMYK_OUTPUT.value, Capability.FIXED_SIZE.value],
}


def capabilities_for_product_id(product_id: str) -> list[str]:
    return list(PRODUCT_ID_CAPABILITIES.get(product_id, []))


def default_capabilities_for(category: str, product_name: str) -> list[str]:
    """(하위호환) 상품명 기준 조회 - product_id로 변환 후 PRODUCT_ID_CAPABILITIES 조회."""
    product_id = PRODUCT_NAME_TO_ID.get(product_name)
    if product_id is None:
        return []
    return capabilities_for_product_id(product_id)


def routing_capabilities_of(capabilities: list[str]) -> list[str]:
    """전체 capability 목록에서 '라우팅에 관여하는' 것만 추린다 (속성 태그 제외)."""
    return [c for c in capabilities if c in ROUTING_CAPABILITIES]


# ---- 작업지시서 v1.4b #7: 관련 상품(related_products) - UI 추천용 ----
# product_id 기준. "이 상품을 보는 사람이 함께 볼 만한 상품"을 큐레이션한 것으로,
# 실제 판매 데이터/추천 알고리즘이 아니라 카테고리 인접성에 기반한 초기값이다.
RELATED_PRODUCTS: dict[str, list[str]] = {
    # SIGNAGE - 예시(작업지시서 원문)와 일치
    "indoor_banner": ["outdoor_banner", "banner"],
    "outdoor_banner": ["indoor_banner", "banner"],
    "banner": ["indoor_banner", "outdoor_banner"],
    # ACRYLIC - 예시(작업지시서 원문)와 일치: 아크릴키링 -> 아크릴인쇄, 아크릴스탠드
    "acrylic_print": ["acrylic_keyring", "acrylic_stand"],
    "acrylic_keyring": ["acrylic_print", "acrylic_stand"],
    "acrylic_stand": ["acrylic_print", "acrylic_keyring"],
    # BUTTON
    "button": ["fabric_button"],
    "fabric_button": ["button"],
    # STICKER
    "epoxy_sticker": ["removable_sticker", "fabric_sticker"],
    "removable_sticker": ["epoxy_sticker", "dtf_sticker"],
    "fabric_sticker": ["epoxy_sticker", "dtf_sticker"],
    "dtf_sticker": ["fabric_sticker", "removable_sticker"],
    "vehicle_sticker": ["dtf_sticker"],
    # LARGE_FORMAT
    "photo_paper": ["magnetic_sheet"],
    "magnetic_sheet": ["photo_paper"],
    "vinyl_cutting": ["vehicle_sticker"],
    # CARD - 예시(작업지시서 원문)와 일치: 일반지명함 -> 고급지명함, 투명하이브리드명함
    "standard_business_card": ["premium_business_card", "transparent_hybrid_card"],
    "premium_business_card": ["standard_business_card", "transparent_hybrid_card"],
    "digital_invitation": ["standard_business_card"],
    "transparent_hybrid_card": ["premium_business_card", "standard_business_card"],
}


def related_products_for(product_id: str) -> list[str]:
    return list(RELATED_PRODUCTS.get(product_id, []))


# 실제 실행 코드가 아니라, pipeline_router.py 가 각 라우팅 capability 를 만났을 때
# "무엇을 해야 하는지"를 문서화한 참조 테이블이다. 실제 구현 여부는
# IMPLEMENTED_CAPABILITIES 를 참고할 것.
CAPABILITY_PIPELINE_STEPS: dict[str, list[str]] = {
    Capability.RECTANGULAR_PRINT.value: [
        "upload_validate", "crop_resize", "cmyk_convert", "pdf_build", "preflight",
    ],
    Capability.CUTLINE_PRINT.value: [
        "upload_validate", "crop_resize", "background_removal(선택)", "cutline_path_generate",
        "cmyk_convert", "pdf_build_with_cutline_layer", "preflight(+cutline 검사)",
    ],
    Capability.WHITE_INK_PRINT.value: [
        "upload_validate", "crop_resize", "white_layer_generate", "cmyk_convert",
        "pdf_build_with_spot_white_channel", "preflight(+white_ink 검사)",
    ],
    Capability.DOUBLE_SIDE_PRINT.value: [
        "upload_validate(front)", "upload_validate(back)", "crop_resize(front/back)",
        "cmyk_convert(front/back)", "pdf_build_double_side(2p)", "preflight(+front_back 검사)",
    ],
    Capability.LARGE_FORMAT_PRINT.value: [
        "upload_validate", "tile_or_stream_processing(대용량 메모리 관리)", "crop_resize",
        "cmyk_convert", "pdf_build", "preflight",
    ],
    Capability.NO_PRINT_CUTTING.value: [
        "upload_validate(벡터 또는 외곽 이미지)", "vector_cut_path_generate", "svg_build",
        "preflight(+cutline 검사, 인쇄 관련 검사 생략)",
    ],
    Capability.EYELET_FINISHING.value: [
        "eyelet_position_calculate(v1.3 엔진 재사용)", "preflight(+eyelet_collision 검사)",
    ],
}


def build_ui_taxonomy_tree() -> dict:
    """작업지시서 v1.4b #8: UI용 트리 구조 JSON을 코드로부터 생성한다 (하드코딩 이중관리 방지)."""
    category_labels = {
        "SIGNAGE": "배너/사인",
        "ACRYLIC": "아크릴",
        "BUTTON": "버튼",
        "STICKER": "스티커",
        "LARGE_FORMAT": "실사출력",
        "CARD": "카드/명함",
    }
    tree = {"categories": []}
    for category, names in PRODUCT_TAXONOMY.items():
        tree["categories"].append({
            "category_id": category,
            "label": category_labels[category],
            "children": [
                {
                    "product_id": PRODUCT_NAME_TO_ID[name],
                    "label": name,
                    "related_products": related_products_for(PRODUCT_NAME_TO_ID[name]),
                }
                for name in names
            ],
        })
    return tree
