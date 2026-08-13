# DONGLE Studio v1.9.5 — 3 Product Production Contract Adapter

PRODUCT_PROFILES = {
    "indoor_banner": {"name":"실내용배너","bleed_mm":1.0,"recommended_dpi":300},
    "outdoor_banner": {"name":"실외용배너","bleed_mm":1.0,"recommended_dpi":300},
    "banner": {"name":"현수막","bleed_mm":1.0,"recommended_dpi":150,"min_side":30,"max_short_side":1800,"max_long_side":49100},
    "hyeonsumak": {"name":"현수막","bleed_mm":1.0,"recommended_dpi":150,"min_side":30,"max_short_side":1800,"max_long_side":49100},
}

BANNER_PRESETS=[(600,1800),(600,1600),(400,1200),(500,1500),(800,2400),(1000,2400)]

def get_product_profile(product_id):
    return PRODUCT_PROFILES.get(product_id)

def calculate_working_size(product_id, finished_w, finished_h):
    p=get_product_profile(product_id)
    if not p: raise ValueError("지원하지 않는 v1.9.5 상품입니다.")
    b=p["bleed_mm"]
    return {"working_width":finished_w+b*2,"working_height":finished_h+b*2}

def validate_product_size(product_id, finished_w, finished_h):
    p=get_product_profile(product_id)
    if not p: return {"status":"BLOCK","message":"지원하지 않는 v1.9.5 상품입니다."}
    if product_id in ("banner","hyeonsumak"):
        short_side=min(finished_w,finished_h); long_side=max(finished_w,finished_h)
        if finished_w<30 or finished_h<30: return {"status":"BLOCK","message":"각 변은 최소 30mm 이상이어야 합니다."}
        if short_side>1800 or long_side>49100: return {"status":"BLOCK","message":"현수막 최대 제작 가능 규격을 초과했습니다."}
        return {"status":"PASS","message":"제작 가능한 규격입니다."}
    # Indoor/outdoor custom size official min/max is not verified. Do not invent blockers.
    if finished_w<=0 or finished_h<=0: return {"status":"BLOCK","message":"가로/세로를 확인하세요."}
    return {"status":"PASS","message":"입력 규격입니다. 공식 자유규격 범위는 별도 확인이 필요합니다.","partial":True}

def calculate_effective_dpi(pixel_w,pixel_h,used_w_mm,used_h_mm):
    if not all(v and v>0 for v in (pixel_w,pixel_h,used_w_mm,used_h_mm)): return 0
    dpi_x=pixel_w/(used_w_mm/25.4); dpi_y=pixel_h/(used_h_mm/25.4)
    return round(min(dpi_x,dpi_y),1)
