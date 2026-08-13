from __future__ import annotations

import io
import json
import os
import re
import secrets
import threading
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory
from PIL import Image, ImageOps
import numpy as np
from production_engine.vision.contour_engine import build_production_cutline

from production_engine.config import JsonProductProfileRepository, load_profile_stubs
from production_engine.coordinates import TrimCanvas, CoordinateContractError
from production_engine.models import FitPolicy, PreflightLevel, JobTicket
from production_engine.pipeline import ProductionPipeline, PipelineContext, RENDER_DPI_CAP, DEFAULT_RENDER_DPI_CAP
from production_engine.preflight.engine import ElementBox
from production_engine.security.storage import JobStorage
from production_engine.guide_help import all_guide_help
from production_engine.proof_generator import ProofMetadata
from production_engine.resize_engine import RepositionMode, ObjectTransformMM, SizeChangeError
from production_engine.taxonomy import (
    PRODUCT_TAXONOMY, PRODUCT_NAME_TO_ID, PRODUCT_ID_TO_NAME,
    CONFIRMED_PRODUCT_ID_ALIAS, CATEGORY_DIR, capabilities_for_product_id,
)

BASE = Path(__file__).resolve().parent
FRONTEND = BASE / "frontend"
WORKSPACE = BASE / "workspace"
SNAPSHOT_DIR = WORKSPACE / "_session_snapshots"
APPROVAL_DIR = WORKSPACE / "_approvals"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
APPROVAL_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_FILE = BASE / "production_engine" / "product_profiles.seed.json"
PROFILE_DIR = BASE / "product_profiles"

app = Flask(__name__, static_folder=None)
BUILD_VERSION = "2.7.3"
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("DONGLE_MAX_FILE_MB", "150")) * 1024 * 1024

repo = JsonProductProfileRepository(str(PROFILE_FILE))
storage = JobStorage(str(WORKSPACE))
pipeline = ProductionPipeline(storage)
CONTEXTS: dict[str, PipelineContext] = {}

# v1.4: 20개 상품은 모두 UI에 노출하지만, 실제 공식 가이드가 검증되지 않은 상품은
# production_enabled=False로 유지한다. 현재 기존 MVP 파이프라인이 실제 동작하는 두 상품만
# DEV profile로 제작/테스트를 허용한다.
DEV_PRODUCTION_PRODUCTS = {
    "indoor_banner": "banner_indoor",
    "outdoor_banner": "outdoor_banner",
    "banner": "hyeonsumak_outdoor",
    "button": "button_58",
    "fabric_button": "button_58",
    "acrylic_print": "acrylic_print",
    "acrylic_keyring": "acrylic_keyring",
    "acrylic_stand": "acrylic_stand",
}
LEGACY_PRODUCT_ALIASES = {
    "banner": "indoor_banner",      # old frontend legacy only; create_job resolves contextually below
    "placard": "banner",
    "indoor-banner": "indoor_banner",
    "outdoor-banner": "outdoor_banner",
}

CATEGORY_LABELS = {
    "SIGNAGE": "배너/사인",
    "ACRYLIC": "아크릴",
    "BUTTON": "버튼",
    "STICKER": "스티커",
    "LARGE_FORMAT": "실사출력",
    "CARD": "카드/명함",
}

RELATED = {
    "indoor_banner": ["outdoor_banner", "banner"],
    "outdoor_banner": ["indoor_banner", "banner"],
    "banner": ["indoor_banner", "outdoor_banner"],
    "acrylic_print": ["acrylic_keyring", "acrylic_stand"],
    "acrylic_keyring": ["acrylic_print", "acrylic_stand"],
    "acrylic_stand": ["acrylic_keyring", "acrylic_print"],
    "button": ["fabric_button"], "fabric_button": ["button"],
    "epoxy_sticker": ["removable_sticker", "dtf_sticker"],
    "removable_sticker": ["epoxy_sticker", "fabric_sticker"],
    "fabric_sticker": ["dtf_sticker", "removable_sticker"],
    "dtf_sticker": ["fabric_sticker", "epoxy_sticker"],
    "vehicle_sticker": ["epoxy_sticker", "magnetic_sheet"],
    "photo_paper": ["magnetic_sheet"], "magnetic_sheet": ["photo_paper", "vehicle_sticker"],
    "vinyl_cutting": ["vehicle_sticker"],
    "standard_business_card": ["premium_business_card", "transparent_hybrid_card"],
    "premium_business_card": ["standard_business_card", "transparent_hybrid_card"],
    "digital_invitation": ["premium_business_card"],
    "transparent_hybrid_card": ["premium_business_card", "standard_business_card"],
}


def _stub_catalog():
    return {s.product_id: s for s in load_profile_stubs(str(PROFILE_DIR))}


def _seed_ui(product_id: str, alias_id: str):
    p = repo.get(alias_id)
    is_button = product_id in ("button", "fabric_button")
    return {
        "id": product_id,
        "profileId": alias_id,
        "name": PRODUCT_ID_TO_NAME.get(product_id, p.product_name),
        "category": next((c for c, names in PRODUCT_TAXONOMY.items() if PRODUCT_ID_TO_NAME.get(product_id) in names), p.category),
        "categoryLabel": "배너/사인",
        "widthMm": p.width_mm,
        "heightMm": p.height_mm,
        "fixed": True if is_button else not p.custom_size_allowed,
        "customSizeAllowed": False if is_button else p.custom_size_allowed,
        "bleedMm": p.safe_zone.bleed_mm,
        "safeMm": p.safe_zone.safe_margin_mm,
        "recommendedDpiMin": p.dpi_warning_below,
        "errorDpiBelow": p.dpi_error_below,
        "colorMode": p.color_mode_target,
        "pdfStandard": p.pdf_standard,
        "eyelet": {
            "enabled": p.eyelet.enabled,
            "diameterMm": p.eyelet.diameter_mm,
            "marginMm": p.eyelet.margin_mm,
            "intervalMm": p.eyelet.interval_mm,
            "placementPolicy": p.eyelet.placement_policy.value,
        },
        "finishing": p.finishing,
        "sizePresets": ([
            {"label":"32×32", "width_mm":32, "height_mm":32, "work_mm":44.5},
            {"label":"44×44", "width_mm":44, "height_mm":44, "work_mm":54},
            {"label":"58×58", "width_mm":58, "height_mm":58, "work_mm":70},
            {"label":"75×75", "width_mm":75, "height_mm":75, "work_mm":86},
        ] if is_button else p.size_presets),
        "capabilities": capabilities_for_product_id(product_id),
        "productionStatus": "PARTIAL",
        "needsConfirmation": True,
        "productionEnabled": True,
        "statusLabel": "MVP / 가이드 검증 필요",
        "relatedProducts": RELATED.get(product_id, []),
        "acrylicSpec": ({
            "cutlineOffsetMm": p.cutline_offset_mm,
            "holeDiameterMm": p.hole_diameter_mm,
            "holeEdgeMarginMm": p.hole_edge_margin_mm,
            "outerWallMm": 2.0 if product_id == "acrylic_keyring" else None,
            "transparentReverse": bool(product_id in ("acrylic_keyring", "acrylic_stand")),
            "partSlotSync": bool(product_id == "acrylic_stand"),
        } if product_id in ("acrylic_print", "acrylic_keyring", "acrylic_stand") else None),
    }


def _full_catalog():
    stubs = _stub_catalog()
    catalog = {}
    for category, names in PRODUCT_TAXONOMY.items():
        for name in names:
            pid = PRODUCT_NAME_TO_ID[name]
            if pid in DEV_PRODUCTION_PRODUCTS:
                item = _seed_ui(pid, DEV_PRODUCTION_PRODUCTS[pid])
                item["category"] = category
                item["categoryLabel"] = CATEGORY_LABELS[category]
                catalog[pid] = item
                continue
            stub = stubs.get(pid)
            catalog[pid] = {
                "id": pid,
                "name": name,
                "category": category,
                "categoryLabel": CATEGORY_LABELS[category],
                "widthMm": getattr(stub, "trim_width_mm", None),
                "heightMm": getattr(stub, "trim_height_mm", None),
                "fixed": bool(stub and stub.custom_size_allowed is False),
                "customSizeAllowed": getattr(stub, "custom_size_allowed", None),
                "bleedMm": getattr(stub, "bleed_mm", None),
                "safeMm": getattr(stub, "safe_margin_mm", None),
                "recommendedDpiMin": getattr(stub, "recommended_dpi", None),
                "errorDpiBelow": getattr(stub, "minimum_dpi", None),
                "colorMode": getattr(stub, "color_mode", None),
                "eyelet": {"enabled": bool(getattr(stub, "eyelet_enabled", False))},
                "capabilities": getattr(stub, "capabilities", capabilities_for_product_id(pid)),
                "productionStatus": getattr(getattr(stub, "production_status", None), "value", "GUIDE_REQUIRED"),
                "needsConfirmation": getattr(stub, "needs_confirmation", True),
                "productionEnabled": False,
                "statusLabel": "Guide Required",
                "relatedProducts": RELATED.get(pid, []),
                "source": {
                    "provider": getattr(getattr(stub, "source", None), "provider", None),
                    "url": getattr(getattr(stub, "source", None), "url", None),
                    "verified": getattr(getattr(stub, "source", None), "verified", False),
                },
            }
    return catalog


def _ui_issue(issue):
    severity = issue.level.value
    if issue.code == "COLOR_MODE_NOT_CONVERTED":
        severity = "WARNING"
    return severity


def _report_overall_for_ui(report):
    levels = [_ui_issue(i) for i in report.issues]
    if "BLOCKING_ERROR" in levels: return "BLOCKING_ERROR"
    if "WARNING" in levels: return "WARNING"
    return "PASS"


def _has_blocking_error(report):
    return any(i.level == PreflightLevel.ERROR and i.code != "COLOR_MODE_NOT_CONVERTED" for i in report.issues)


def _json_issue(issue):
    recommendation = {
        "DPI_TOO_LOW": "더 높은 해상도의 원본 이미지로 교체하세요.",
        "DPI_WARNING": "가급적 고해상도 원본으로 교체하세요.",
        "RATIO_MISMATCH": "Cover/Contain 배치 또는 크롭 영역을 확인하세요.",
        "SAFE_ZONE_VIOLATION": "중요 요소를 안전영역 안쪽으로 이동하세요.",
        "ICC_PROFILE_NOT_CONFIGURED": "실제 인쇄소 ICC 프로파일 확정 전 색상 차이가 있을 수 있습니다.",
        "ICC_PROFILE_MISSING": "지정 ICC 프로파일을 적용하세요.",
        "COLOR_MODE_NOT_CONVERTED": "편집은 RGB로 진행하고 인쇄파일 생성 시 CMYK로 자동 변환합니다.",
    }.get(issue.code, "제작 설정과 원본 파일을 확인하세요.")
    return {
        "code": issue.code, "severity": _ui_issue(issue),
        "blocking": bool(getattr(issue, "blocking", False)),
        "object_id": getattr(issue, "object_id", None),
        "current_value": getattr(issue, "current_value", None),
        "recommended_value": getattr(issue, "recommended_value", None),
        "title": issue.title or issue.code.replace("_", " ").title(),
        "description": issue.message,
        "recommendation": issue.recommendation or recommendation,
        "auto_fixable": bool(getattr(issue, "auto_fixable", False)),
        "detail": issue.detail or {},
    }


def _ctx(job_id: str) -> PipelineContext:
    ctx = CONTEXTS.get(job_id)
    if not ctx: raise KeyError("존재하지 않거나 서버 재시작으로 만료된 작업입니다. 새 작업을 생성해주세요.")
    return ctx


def _fit_policy(value: str | None) -> FitPolicy:
    try: return FitPolicy(value or "contain")
    except ValueError: return FitPolicy.CONTAIN


@app.after_request
def secure_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    return resp


@app.get("/")
def index(): return send_from_directory(FRONTEND, "index.html")
@app.get("/css/<path:name>")
def css(name): return send_from_directory(FRONTEND / "css", name)
@app.get("/js/<path:name>")
def js(name): return send_from_directory(FRONTEND / "js", name)
@app.get("/assets/<path:name>")
def assets(name): return send_from_directory(FRONTEND / "assets", name)


def _safe_session_id(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or ""))[:96]
    if not value:
        raise ValueError("invalid session id")
    return value

@app.post("/api/session-snapshots/<session_id>")
def save_session_snapshot(session_id):
    """Server-side editor autosave. No browser localStorage is required."""
    try:
        sid=_safe_session_id(session_id)
        data=request.get_json(silent=True) or {}
        canvas=data.get("canvas")
        if not isinstance(canvas,dict):
            return jsonify({"error":"canvas snapshot is required"}),400
        # Guard against accidental huge JSON snapshots.
        raw=json.dumps(data,ensure_ascii=False,separators=(",",":"))
        if len(raw.encode("utf-8")) > 8*1024*1024:
            return jsonify({"error":"snapshot is too large"}),413
        target=SNAPSHOT_DIR/f"{sid}.json"
        tmp=target.with_suffix(".tmp")
        tmp.write_text(raw,encoding="utf-8")
        tmp.replace(target)
        return jsonify({"ok":True,"session_id":sid})
    except Exception as e:
        return jsonify({"error":str(e)}),400

@app.get("/api/session-snapshots/latest")
def latest_session_snapshot():
    try:
        files=sorted(SNAPSHOT_DIR.glob("*.json"),key=lambda x:x.stat().st_mtime,reverse=True)
        if not files:return jsonify({"snapshot":None})
        path=files[0]
        data=json.loads(path.read_text(encoding="utf-8"))
        return jsonify({"session_id":path.stem,"snapshot":data})
    except Exception as e:
        return jsonify({"error":str(e)}),400

@app.get("/api/version")
def version(): return jsonify({"version": BUILD_VERSION, "build": "Service Release Candidate v2.7.3"})


@app.get("/api/v17/capabilities")
def v17_capabilities():
    return jsonify({
        "version": "1.7",
        "smart_inspector": True,
        "history": True,
        "keyboard_shortcuts": True,
        "quick_actions": True,
        "acrylic_product_intelligence": True,
        "production_pdf": True,
        "note": "Frontend active build is regression-safe v1.6.1 base with additive v1.7 workspace."
    })

@app.get("/api/v18/capabilities")
def v18_capabilities():
    return jsonify({
        "version": "1.8",
        "dynamic_resize": True,
        "multipart_acrylic_stand": True,
        "preflight_v2": True,
        "customer_proof": True,
        "production_package": True,
        "guide_help": True,
        "background_remove_v2_state": True,
        "note": "Active UI is v1.7 regression-safe workspace with v1.8 Production APIs integrated."
    })

@app.get("/api/v181/capabilities")
def v181_capabilities():
    return jsonify({
        "version": "1.8.1",
        "ux_refinement": True,
        "product_search": True,
        "category_filter": True,
        "always_visible_size_panel": True,
        "semantic_light_theme": True,
        "guide_help_ui": True,
        "note": "Frontend-only regression-safe UX refinement on top of v1.8 Production Intelligence."
    })


@app.get("/api/v191/capabilities")
def api_v191_capabilities():
    return jsonify({
        "version": BUILD_VERSION,
        "release": "Production Ready Integration",
        "active_frontend": "v1.9.5 3-product Production UX",
        "production_profiles": "Claude v1.9",
        "gemini_v19": "archived_reference_to_prevent_regression",
        "launcher": "RUN_DONGLE.bat",
    })


@app.get("/api/guide-help")
def guide_help():
    return jsonify({"guides": all_guide_help()})

@app.get("/api/products")
def products(): return jsonify(_full_catalog())


@app.post("/api/acrylic/preview-contour")
def acrylic_preview_contour():
    """v1.9.7 Acrylic contour preview/verified keyring cutline.

    Keyring free-form guide is verified from the supplied production guide: cutline is
    at least 1mm outside the printed artwork. Stand uses the same 1mm preview offset,
    while its tab/slot dimensions remain user-confirmed because exact clearance values
    are not readable enough to safely hard-code.
    """
    try:
        f=request.files.get("image")
        product_id=str(request.form.get("product_id") or "acrylic_keyring")
        if not f: return jsonify({"error":"투명 PNG 이미지가 필요합니다."}),400
        if product_id not in ("acrylic_print","acrylic_keyring","acrylic_stand"):
            return jsonify({"error":"현재 자동 칼선은 아크릴키링/아크릴스탠드만 지원합니다."}),400
        raw=f.read()
        with Image.open(io.BytesIO(raw)) as img:
            if img.mode != "RGBA":
                return jsonify({"error":"투명 배경 RGBA PNG가 필요합니다. 배경제거 후 다시 시도하세요."}),400
            rgba=np.array(img)
            dpi_info=img.info.get("dpi", (300,300))
            dpi=float(dpi_info[0] if isinstance(dpi_info,(tuple,list)) else dpi_info or 300)
            if dpi < 10 or dpi > 2400: dpi=300.0
        offset_mm=max(1.0,min(10.0,float(request.form.get("offset_mm") or 1.0)))
        offset_mm=float(round(offset_mm))
        cut=build_production_cutline(rgba,dpi=dpi,offset_mm=offset_mm,min_island_area_mm2=0.2,min_radius_mm=None)
        px_per_mm=dpi/25.4
        points_px=[[round(x*px_per_mm,3),round(y*px_per_mm,3)] for x,y in cut.points_mm]
        payload={
            "ok":True,"preview_only": product_id=="acrylic_stand","production_ready": product_id in ("acrylic_keyring","acrylic_print"),
            "product_id":product_id,"cutline_offset_mm":offset_mm,
            "reason":(f"PNG 외곽 사방 {offset_mm:g}mm 칼선 적용" if product_id in ("acrylic_keyring","acrylic_print") else f"스탠드 칼선 {offset_mm:g}mm 적용 · Tab/Slot 공차는 확인값 입력 필요"),
            "source_width_px":cut.image_width_px,"source_height_px":cut.image_height_px,"dpi":dpi,
            "point_count":len(points_px),"points_px":points_px,
            "analysis":{"raw_contours":cut.analysis.total_raw_contours,"islands_removed":cut.analysis.islands_removed,"self_intersections":len(cut.analysis.self_intersections)},
        }
        if product_id=="acrylic_keyring":
            payload["hole"]={"diameter_mm":3.0,"minimum_outer_wall_mm":2.0,"minimum_center_edge_mm":3.5,"modes":["AUTO_RECOMMEND","TOP_CENTER","TOP_LEFT","TOP_RIGHT","MANUAL"]}
            payload["layers"]={"color":"CMYK","white":"K100","cutline":"K100","transparent_reverse_required":True}
        return jsonify(payload)
    except Exception as e:
        return jsonify({"error":f"외곽선 분석 실패: {e}"}),400


@app.post("/api/acrylic/stand/structure")
def acrylic_stand_structure():
    """Generate a multi-part stand slot layout preview.

    The guide-confirmed rule is structural: part count == slot count. Exact tab/slot
    tolerances are supplied by the operator until a numeric factory spec is confirmed.
    This prevents hidden guessed manufacturing values from entering production.
    """
    try:
        data=request.get_json(silent=True) or {}
        count=max(1,min(12,int(data.get("part_count") or 1)))
        base_w=float(data.get("base_width_mm") or 100)
        base_d=float(data.get("base_depth_mm") or 40)
        thickness=float(data.get("material_thickness_mm") or 0)
        tab_w=float(data.get("tab_width_mm") or 0)
        tab_h=float(data.get("tab_height_mm") or 0)
        slot_w=float(data.get("slot_width_mm") or 0)
        clearance=float(data.get("slot_clearance_mm") or 0)
        # v1.9.8: 미입력 공차는 profile→PROVISIONAL 기본값으로 채워 실제 슬롯 기하를
        # 그린다(엔진의 canonical 배치식 재사용). 하드코딩이 아니라 명시적 PROVISIONAL 이며
        # using_provisional=True 로 표시되고 production_ready 로 승격되지 않는다.
        from types import SimpleNamespace
        from production_engine.vision.acrylic_stand_defaults import resolve_stand_params
        from production_engine.vision.stand_multipart import _spaced_centers
        stub=SimpleNamespace(material_thickness_mm=None,stand_tab_width_mm=None,
                             stand_tab_height_mm=None,stand_slot_width_mm=None,
                             stand_slot_clearance_mm=None)
        resolved=resolve_stand_params(stub,ui_overrides={
            "material_thickness_mm":thickness or None,"tab_width_mm":tab_w or None,
            "tab_height_mm":tab_h or None,"slot_width_mm":slot_w or None,
            "slot_clearance_mm":clearance or None})
        rp=resolved.params
        # 미확정(=Profile/UI 모두 값 없음) 필드는 여전히 "operator 확인 필요"로 노출한다.
        missing=[f for f in ("material_thickness_mm","tab_width_mm","tab_height_mm","slot_width_mm")
                 if f in resolved.provisional_fields]
        eff_slot_w=rp.slot_width_mm+rp.slot_clearance_mm
        centers=_spaced_centers(base_w,count,eff_slot_w,spacing_mm=15.0,margin_mm=10.0)
        slot_depth=rp.material_thickness_mm+rp.slot_clearance_mm
        slots=[]
        warnings=[]
        for i,cx in enumerate(centers):
            left=cx-eff_slot_w/2; right=cx+eff_slot_w/2
            if left<0 or right>base_w:
                warnings.append(f"슬롯 {i+1}이(가) 받침대(폭 {base_w:.0f}mm) 밖으로 나갑니다.")
            slots.append({"slot_id":f"slot_{i+1}","part_id":f"part_{i+1}",
                          "center_x_mm":round(cx,3),"center_y_mm":round(base_d/2,3),
                          "slot_width_mm":round(eff_slot_w,3),"slot_depth_mm":round(slot_depth,3)})
        for a,b in zip(slots,slots[1:]):
            gap=(b["center_x_mm"]-eff_slot_w/2)-(a["center_x_mm"]+eff_slot_w/2)
            if gap<8.0: warnings.append(f"슬롯 {a['slot_id']}~{b['slot_id']} 간격이 {gap:.1f}mm 로 좁습니다(최소 8mm 권장).")
        if resolved.using_provisional:
            warnings.append("끼움 공차가 임시(PROVISIONAL)값입니다. 제작 전 확정값 입력이 필요합니다.")
        return jsonify({
            "ok":True,"production_ready":not missing,"missing_fields":missing,
            "part_count":count,"slot_count":count,"synced":True,
            "base":{"width_mm":base_w,"depth_mm":base_d},"slots":slots,
            "using_provisional":resolved.using_provisional,
            "provisional_fields":resolved.provisional_fields,
            "resolved_tolerances":{"material_thickness_mm":rp.material_thickness_mm,
                "tab_width_mm":rp.tab_width_mm,"tab_height_mm":rp.tab_height_mm,
                "slot_width_mm":rp.slot_width_mm,"slot_clearance_mm":rp.slot_clearance_mm},
            "warnings":warnings,
            "rule":"파츠 수량과 받침대 홈 수량 1:1 자동 동기화",
            "note":"공차 미입력 시 PROVISIONAL 기본값으로 미리보기만 제공하며, 확인값 입력 전에는 제작 준비 완료로 처리하지 않습니다."
        })
    except Exception as e:
        return jsonify({"error":f"스탠드 구조 계산 실패: {e}"}),400


@app.get("/api/product-groups")
def product_groups():
    cat = _full_catalog()
    groups=[]
    for category,names in PRODUCT_TAXONOMY.items():
        groups.append({
            "id": category, "label": CATEGORY_LABELS[category],
            "products": [cat[PRODUCT_NAME_TO_ID[n]] for n in names]
        })
    return jsonify({"groups": groups})


@app.post("/api/jobs")
def create_job():
    data = request.get_json(silent=True) or {}
    product = str(data.get("product", "indoor_banner"))
    # old UI compatibility
    if product == "placard": product = "banner"
    if product == "banner_indoor": product = "indoor_banner"
    catalog = _full_catalog()
    if product not in catalog:
        return jsonify({"error": "지원하지 않는 상품입니다."}), 400
    meta = catalog[product]
    if not meta["productionEnabled"]:
        return jsonify({
            "error": f"{meta['name']}은(는) 아직 공식 제작가이드 검증이 필요합니다.",
            "production_status": meta["productionStatus"],
            "guide_required": True,
        }), 409
    profile_id = DEV_PRODUCTION_PRODUCTS[product]
    if product in ("button", "fabric_button"):
        requested = float(data.get("width_mm") or 58)
        button_profiles = {32:"button_32",44:"button_44",58:"button_58",75:"button_75"}
        if requested not in button_profiles:
            return jsonify({"error":"버튼은 32 / 44 / 58 / 75mm 고정 규격만 제작할 수 있습니다."}), 400
        profile_id = button_profiles[int(requested)]
    profile = repo.get(profile_id)
    width = float(data.get("width_mm") or profile.width_mm)
    height = float(data.get("height_mm") or profile.height_mm)
    if not profile.custom_size_allowed:
        width, height = profile.width_mm, profile.height_mm
    try:
        ctx = pipeline.create_job(profile, width, height, _fit_policy(data.get("fit_policy")))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    CONTEXTS[ctx.job.job_id] = ctx
    return jsonify({"job_id": ctx.job.job_id, "product": product, "width_mm": width, "height_mm": height, "status": ctx.job.status})


@app.post("/api/jobs/<job_id>/resize")
def resize_job(job_id):
    try:
        ctx=_ctx(job_id)
        data=request.get_json(silent=True) or {}
        width=float(data.get("width_mm") or 0)
        height=float(data.get("height_mm") or 0)
        mode_value=str(data.get("reposition_mode") or "PROPORTIONAL_STRETCH")
        try: mode=RepositionMode(mode_value)
        except Exception: mode=RepositionMode.PROPORTIONAL_STRETCH
        objects=[]
        for o in data.get("objects",[]):
            objects.append(ObjectTransformMM(
                object_id=str(o.get("object_id","")), x_mm=float(o.get("x_mm",0)), y_mm=float(o.get("y_mm",0)),
                width_mm=float(o.get("width_mm",0)), height_mm=float(o.get("height_mm",0)), rotation_deg=float(o.get("rotation_deg",0))
            ))
        ctx,summary,repositioned=pipeline.resize_job(ctx,width,height,objects or None,mode)
        return jsonify({
            "ok":True,"width_mm":ctx.job.output_width_mm,"height_mm":ctx.job.output_height_mm,
            "bleed_mm":summary.bleed_mm,"safe_margin_mm":summary.safe_margin_mm,
            "effective_dpi":summary.effective_dpi,"warnings":summary.warnings,
            "eyelets":[{"x_mm":p.x_mm,"y_mm":p.y_mm,"edge":p.edge} for p in summary.eyelet_points],
            "objects":[{"object_id":o.object_id,"x_mm":o.x_mm,"y_mm":o.y_mm,"width_mm":o.width_mm,"height_mm":o.height_mm,"rotation_deg":o.rotation_deg} for o in repositioned]
        })
    except (SizeChangeError,ValueError) as e:
        return jsonify({"error":str(e)}),400
    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.post("/api/jobs/<job_id>/upload")
def upload(job_id):
    try:
        ctx=_ctx(job_id); f=request.files.get("image")
        if not f: return jsonify({"error":"이미지 파일이 없습니다."}),400
        pipeline.ingest_upload(ctx, f.stream, f.filename or "upload")
        vf=ctx.validated_file
        return jsonify({"ok":True,"filename":vf.original_filename,"width_px":vf.width_px,"height_px":vf.height_px,"format":vf.detected_format.value,"has_alpha":vf.has_alpha,"size_bytes":vf.size_bytes})
    except Exception as e: return jsonify({"error":str(e)}),400


@app.post("/api/jobs/<job_id>/preflight")
def preflight(job_id):
    try:
        ctx=_ctx(job_id); data=request.get_json(silent=True) or {}; ctx.job.fit_policy=_fit_policy(data.get("fit_policy"))
        elements=[]
        for e in data.get("protected_elements",[]):
            elements.append(ElementBox(name=str(e.get("name","element")),x_mm=float(e.get("x_mm",0)),y_mm=float(e.get("y_mm",0)),width_mm=float(e.get("width_mm",0)),height_mm=float(e.get("height_mm",0))))
        pipeline.prepare_working_image(ctx)
        report=pipeline.preflight(ctx, protected_elements=elements or None)
        return jsonify({
            "job_id":job_id,"overall":_report_overall_for_ui(report),"issues":[_json_issue(i) for i in report.issues],
            "effective":{"source_width_px":ctx.validated_file.width_px,"source_height_px":ctx.validated_file.height_px,"upscale_factor":round(ctx.upscale_factor,3)},
            "eyelets":[{"x_mm":p.x_mm,"y_mm":p.y_mm,"edge":p.edge} for p in pipeline.compute_eyelets(ctx)]
        })
    except Exception as e: return jsonify({"error":str(e)}),400


@app.post("/api/jobs/<job_id>/remove-background")
def remove_background(job_id):
    try:
        _ctx(job_id); f=request.files.get("image")
        if not f: return jsonify({"error":"배경 제거할 이미지가 없습니다."}),400
        from rembg import remove
        return send_file(io.BytesIO(remove(f.read())), mimetype="image/png", download_name="removed_bg.png")
    except ImportError: return jsonify({"error":"AI 배경 제거 패키지(rembg/onnxruntime)가 설치되지 않았습니다."}),500
    except Exception as e: return jsonify({"error":f"배경 제거 실패: {e}"}),500


def _prepare_editor_render(ctx: PipelineContext, blob) -> str:
    """v1.4 WYSIWYG raster contract.

    Editor PNG is the TRIM canvas. We first validate its pixel aspect against trim mm
    with Claude's TrimCanvas contract. The exact editor render is resized only to the
    trim raster. Bleed is created outside it, so adding bleed never shifts/scales the
    design visible inside TrimBox.
    """
    paths=storage.get_paths(ctx.job.job_id)
    source=Path(paths.working_dir)/"editor_trim_source.png"; blob.save(source)
    render_dpi=RENDER_DPI_CAP.get(ctx.profile.category,DEFAULT_RENDER_DPI_CAP)
    bleed=float(ctx.profile.safe_zone.bleed_mm)
    trim_w=float(ctx.job.output_width_mm); trim_h=float(ctx.job.output_height_mm)
    trim_px=(max(1,round(trim_w/25.4*render_dpi)),max(1,round(trim_h/25.4*render_dpi)))
    bleed_px=max(0,round(bleed/25.4*render_dpi))
    media_px=(trim_px[0]+bleed_px*2, trim_px[1]+bleed_px*2)

    with Image.open(source) as src:
        src=src.convert("RGB")
        try:
            TrimCanvas(src.width,src.height,trim_w,trim_h)
        except CoordinateContractError as e:
            raise ValueError(f"Canvas/PDF WYSIWYG 좌표계 오류: {e}")
        trim_img=src.resize(trim_px,Image.Resampling.LANCZOS)
        if bleed_px:
            # Extend design under bleed as a background, then paste the exact trim image
            # back at the bleed offset. Thus the TrimBox is pixel-faithful to the editor.
            bg=src.resize(media_px,Image.Resampling.LANCZOS)
            bg.paste(trim_img,(bleed_px,bleed_px))
            final_img=bg
        else:
            final_img=trim_img
        final=Path(paths.working_dir)/"editor_render.png"
        final_img.save(final,"PNG",optimize=False)
    return str(final)


@app.post("/api/jobs/<job_id>/export")
def export(job_id):
    try:
        ctx=_ctx(job_id); artwork=request.files.get("artwork")
        if not artwork: return jsonify({"error":"에디터 렌더 이미지가 없습니다."}),400
        if request.form.get("fit_policy"): ctx.job.fit_policy=_fit_policy(request.form.get("fit_policy"))
        if ctx.validated_file:
            pipeline.prepare_working_image(ctx); pre=pipeline.preflight(ctx)
            if _has_blocking_error(pre) and request.form.get("force")!="true":
                return jsonify({"error":"BLOCKING_ERROR가 있어 제작파일 생성을 중단했습니다.","overall":_report_overall_for_ui(pre),"issues":[_json_issue(i) for i in pre.issues]}),409
        ctx.working_path=_prepare_editor_render(ctx,artwork)
        pipeline.convert_color(ctx); pipeline.build_pdf(ctx)
        try:
            ticket=JobTicket(
                order_number=request.form.get("order_number",""), channel=request.form.get("channel","기타"), customer_name=request.form.get("customer_name",""),
                product=ctx.profile.product_name, width_mm=ctx.job.output_width_mm, height_mm=ctx.job.output_height_mm,
                quantity=max(1,int(request.form.get("quantity","1") or 1)), finishing=[x for x in request.form.get("finishing","").split(",") if x],
                memo=request.form.get("memo",""), source_filename=(ctx.validated_file.original_filename if ctx.validated_file else "")
            ); pipeline.attach_job_ticket(ctx,ticket)
        except Exception: pass
        final_report=pipeline.preflight(ctx) if ctx.validated_file else None
        if final_report is not None: pipeline.export_manifest(ctx,final_report)
        def _name_token(v, fallback=""):
            v=re.sub(r'[\\/:*?"<>|\r\n]+', "_", str(v or fallback)).strip(" ._")
            return v[:48]
        order=_name_token(request.form.get("order_number"))
        channel=_name_token(request.form.get("channel"))
        customer=_name_token(request.form.get("customer_name"))
        product=_name_token(ctx.profile.product_name,"product")
        parts=[x for x in (order,channel,customer,product,job_id[:8]) if x]
        return send_file(ctx.output_pdf_path,as_attachment=True,download_name="_".join(parts)+".pdf")
    except Exception as e: return jsonify({"error":str(e)}),500


@app.post("/api/jobs/<job_id>/proof")
def generate_proof_download(job_id):
    try:
        ctx=_ctx(job_id)
        data=request.get_json(silent=True) or {}
        metadata=ProofMetadata(
            order_number=data.get("order_number") or (ctx.job_ticket.order_number if ctx.job_ticket else None),
            product_name=ctx.profile.product_name,width_mm=ctx.job.output_width_mm,height_mm=ctx.job.output_height_mm,
            side_label=data.get("side_label")
        )
        path=pipeline.generate_proof(ctx,metadata=metadata)
        return send_file(path,as_attachment=True,download_name=Path(path).name)
    except Exception as e:
        return jsonify({"error":str(e)}),400

@app.post("/api/jobs/<job_id>/package")
def generate_package_download(job_id):
    try:
        ctx=_ctx(job_id)
        if not ctx.output_pdf_path or not Path(ctx.output_pdf_path).exists():
            return jsonify({"error":"먼저 Production PDF를 생성해주세요."}),409
        report=pipeline.preflight(ctx) if ctx.validated_file else None
        if report is None:
            return jsonify({"error":"Preflight 결과가 없어 패키지를 생성할 수 없습니다."}),409
        result=pipeline.build_production_package(ctx,report)
        return send_file(result.zip_path,as_attachment=True,download_name=Path(result.zip_path).name)
    except Exception as e:
        return jsonify({"error":str(e)}),400

@app.get("/api/jobs/<job_id>/manifest")
def download_manifest(job_id):
    try:
        ctx=_ctx(job_id)
        if not ctx.manifest_path or not Path(ctx.manifest_path).exists(): return jsonify({"error":"아직 Production Manifest가 생성되지 않았습니다."}),404
        return send_file(ctx.manifest_path,as_attachment=True,download_name=f"DONGLE_manifest_{job_id[:8]}.json")
    except Exception as e: return jsonify({"error":str(e)}),404


@app.post("/api/jobs/<job_id>/approval")
def create_customer_approval(job_id):
    """Create a lightweight approval link backed by the generated customer proof."""
    try:
        ctx=_ctx(job_id)
        data=request.get_json(silent=True) or {}
        proof_path=pipeline.generate_proof(ctx,metadata=ProofMetadata(
            order_number=data.get("order_number") or (ctx.job_ticket.order_number if ctx.job_ticket else None),
            product_name=ctx.profile.product_name,width_mm=ctx.job.output_width_mm,height_mm=ctx.job.output_height_mm,
            side_label=data.get("side_label")
        ))
        token=secrets.token_urlsafe(18)
        record={"token":token,"job_id":job_id,"status":"PENDING","proof_path":str(proof_path),
                "customer_name":str(data.get("customer_name") or ""),"memo":str(data.get("memo") or "")}
        (APPROVAL_DIR/f"{token}.json").write_text(json.dumps(record,ensure_ascii=False),encoding="utf-8")
        return jsonify({"ok":True,"token":token,"url":f"/approval/{token}","status":"PENDING"})
    except Exception as e:
        return jsonify({"error":str(e)}),400

def _approval_record(token:str):
    token=re.sub(r"[^A-Za-z0-9_-]","",token)
    path=APPROVAL_DIR/f"{token}.json"
    if not path.exists():raise FileNotFoundError("승인 링크가 존재하지 않습니다.")
    return path,json.loads(path.read_text(encoding="utf-8"))

@app.get("/approval/<token>")
def customer_approval_page(token):
    try:
        _,rec=_approval_record(token)
        status=rec.get("status","PENDING")
        html=f"""<!doctype html><html lang='ko'><meta charset='utf-8'><title>동그라미 스튜디오 시안 확인</title>
        <style>body{{font-family:Arial,'Noto Sans KR',sans-serif;background:#f5f7f8;margin:0;padding:30px;color:#17202a}}main{{max-width:760px;margin:auto;background:#fff;border:1px solid #e3e7eb;border-radius:16px;padding:22px}}img{{max-width:100%;display:block;margin:16px auto;border:1px solid #e3e7eb}}button{{border:0;border-radius:10px;padding:12px 18px;font-weight:700;cursor:pointer}}.ok{{background:#1f9d68;color:#fff}}.fix{{background:#fff3f3;color:#b42318;border:1px solid #fecaca}}textarea{{width:100%;min-height:90px;border:1px solid #d8dee4;border-radius:10px;padding:10px;box-sizing:border-box}}.row{{display:flex;gap:8px;margin-top:12px}}</style>
        <main><h2>시안 확인</h2><p>상태: <b>{status}</b></p><img src='/approval/{token}/image' alt='고객 시안'>
        <textarea id='memo' placeholder='수정 요청사항을 입력하세요.'></textarea><div class='row'>
        <button class='ok' onclick="send('APPROVED')">승인</button><button class='fix' onclick="send('REVISION_REQUESTED')">수정 요청</button></div>
        <script>async function send(status){{const memo=document.getElementById('memo').value;const r=await fetch('/approval/{token}',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{status,memo}})}});const j=await r.json();alert(j.ok?'처리되었습니다.':j.error);if(j.ok)location.reload();}}</script></main></html>"""
        return html
    except Exception as e:return str(e),404

@app.get("/approval/<token>/image")
def customer_approval_image(token):
    try:
        _,rec=_approval_record(token)
        return send_file(rec["proof_path"],mimetype="image/jpeg")
    except Exception as e:return str(e),404

@app.post("/approval/<token>")
def update_customer_approval(token):
    try:
        path,rec=_approval_record(token);data=request.get_json(silent=True) or {}
        status=str(data.get("status") or "").upper()
        if status not in {"APPROVED","REVISION_REQUESTED"}:return jsonify({"error":"invalid status"}),400
        rec["status"]=status;rec["customer_memo"]=str(data.get("memo") or "")
        path.write_text(json.dumps(rec,ensure_ascii=False),encoding="utf-8")
        return jsonify({"ok":True,"status":status})
    except Exception as e:return jsonify({"error":str(e)}),400

@app.get("/api/jobs/<job_id>/status")
def job_status(job_id):
    try:
        ctx=_ctx(job_id); return jsonify({"job_id":job_id,"status":ctx.job.status,"product_id":ctx.job.product_id})
    except Exception as e: return jsonify({"error":str(e)}),404


def open_browser(): webbrowser.open_new("http://127.0.0.1:5500")
if __name__=="__main__":
    print("="*62); print(" 동그라미 Editor v2.7.3 — Service Release Candidate"); print(" http://127.0.0.1:5500"); print("="*62)
    threading.Timer(1.2,open_browser).start(); app.run(host="127.0.0.1",port=5500,debug=False,threaded=True)
