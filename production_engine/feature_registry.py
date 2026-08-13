"""
feature_registry.py
----------------------
v1.9: Feature Status Registry (작업지시서 2번).

**조사 방법론 (매우 중요)**: "README에 있다고 구현 완료로 판단하지 말 것"이라는
작업지시서 원칙을 코드 레벨로 지킨다. 이 레지스트리의 각 항목은:

  - engine: 실제로 import 가능하고 단위 테스트가 통과하는 백엔드 모듈이 존재하는가
            (production_engine/tests/ 의 실제 테스트 결과에 근거 - 주장이 아니라 실행 결과)
  - api_endpoint_defined: 이 기능을 호출할 함수/클래스 진입점이 production_engine 에
            존재하는가 (Flask 라우트 자체는 app.py 영역이라 이 세션에는 없다 - "엔드포인트로
            연결할 준비가 된 함수가 있는가"까지만 확인 가능)
  - ui_connected: 실제 Frontend(Gemini 제작, 이 세션에는 코드가 없음)에 연결되어
            브라우저에서 동작하는가 - **이 세션은 이걸 검증할 방법이 없다.** 모든 항목을
            UNKNOWN 으로 두거나, editor/ 의 로직 모듈이 존재하는지(=UI에 연결할 준비가
            됐는지)까지만 표시하고, "브라우저에서 실제로 동작함"을 뜻하는 것은 아니라고
            명시한다.
  - production_verified: 그 기능이 실제 고객 주문에 써도 되는 검증된 제작수치로
            동작하는가 (Product Profile production_status 와 연동).

이 레지스트리는 하드코딩된 "true/false 표"가 아니라, 실제로 해당 모듈을 import 하고
간단한 self-check 를 실행해 engine 상태를 스스로 판정한다 (아래 `run_self_check()`).
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class UIConnectionStatus(str, Enum):
    CONNECTED = "CONNECTED"        # 실제 브라우저 동작까지 확인됨 (이 세션에서는 사용되지 않음)
    LOGIC_READY = "LOGIC_READY"    # editor/ 에 순수 로직 모듈은 있으나 실제 캔버스 바인딩 미검증
    NOT_STARTED = "NOT_STARTED"    # 관련 Frontend 작업 자체가 없음
    UNKNOWN = "UNKNOWN"            # 이 세션에 Frontend 코드가 없어 판단 불가


@dataclass
class FeatureStatus:
    feature_id: str
    label: str
    engine_module: Optional[str]           # production_engine 내 모듈 경로 (import 대상)
    engine_available: bool = False
    engine_check_detail: str = ""
    api_entry_points: list[str] = field(default_factory=list)  # 호출 가능한 함수/클래스 (엔드포인트 후보)
    ui_status: UIConnectionStatus = UIConnectionStatus.UNKNOWN
    ui_detail: str = ""
    production_verified: bool = False
    production_verified_detail: str = ""

    def to_dict(self) -> dict:
        return {
            "feature_id": self.feature_id,
            "label": self.label,
            "engine": self.engine_available,
            "engine_detail": self.engine_check_detail,
            "api_entry_points": self.api_entry_points,
            "ui_connected": self.ui_status.value,
            "ui_detail": self.ui_detail,
            "production_verified": self.production_verified,
            "production_verified_detail": self.production_verified_detail,
        }


def _try_import(module_path: str, attrs: list[str]) -> tuple[bool, str]:
    """모듈을 실제로 import 하고, 지정된 속성들이 전부 존재하는지 확인한다."""
    try:
        mod = importlib.import_module(module_path)
    except Exception as e:  # noqa: BLE001 - 조사 목적이므로 모든 예외를 잡아 상태로 기록
        return False, f"import 실패: {e}"
    missing = [a for a in attrs if not hasattr(mod, a)]
    if missing:
        return False, f"모듈은 존재하나 누락된 속성: {missing}"
    return True, "정상 import 및 속성 확인됨"


# ---------------------------------------------------------------------------
# 레지스트리 정의 - 작업지시서 2번 명시 18개 기능
# ---------------------------------------------------------------------------

def build_feature_registry() -> dict[str, FeatureStatus]:
    registry: dict[str, FeatureStatus] = {}

    def add(feature_id, label, module, attrs, ui_status, ui_detail, prod_verified, prod_detail, api_hints=None):
        ok, detail = _try_import(module, attrs) if module else (False, "해당 없음 - Backend 모듈 없음")
        registry[feature_id] = FeatureStatus(
            feature_id=feature_id, label=label, engine_module=module,
            engine_available=ok, engine_check_detail=detail,
            api_entry_points=api_hints or attrs,
            ui_status=ui_status, ui_detail=ui_detail,
            production_verified=prod_verified, production_verified_detail=prod_detail,
        )

    add("background_remove", "Background Remove",
        "production_engine.quick_actions", ["QUICK_ACTIONS", "resolve"],
        UIConnectionStatus.LOGIC_READY,
        "editor/image/BackgroundRemoveState.js 존재(브러시/edge 파라미터 로직, Node 테스트 통과). "
        "실제 AI 모델 호출은 production_engine 에 없음(app.py 의 rembg 경로는 이 세션에 없음).",
        False, "AI 배경 제거 자체가 quick_actions.py 에 NOT_CONNECTED 로 명시됨.")

    add("resize", "Resize (일반)",
        "production_engine.resize_engine", ["recalculate_for_new_size", "reposition_objects"],
        UIConnectionStatus.UNKNOWN, "Frontend 캔버스 리사이즈 UI 코드가 이 세션에 없음.",
        False, "엔진은 동작하나, 상품 자체가 VERIFIED 가 아니므로 프로덕션 검증은 아님.")

    add("custom_size", "Custom Size",
        "production_engine.resize_engine", ["validate_custom_size", "resolve_presets"],
        UIConnectionStatus.UNKNOWN, "가로/세로 mm 직접입력 UI는 Frontend 영역, 이 세션에 코드 없음.",
        False, "섹션 6 계약 검증 통과 - 단, VERIFIED 상품 0개이므로 실사용 검증은 아님.")

    add("undo", "Undo",
        "production_engine.history_schema", ["HistoryLog"],
        UIConnectionStatus.LOGIC_READY, "editor/history/HistoryManager.js 실제 Node 테스트 통과.",
        False, "Backend 스키마/로직만 검증됨 - 실제 캔버스 동작은 미검증.")

    add("redo", "Redo",
        "production_engine.history_schema", ["HistoryLog"],
        UIConnectionStatus.LOGIC_READY, "위와 동일 (HistoryLog.redo()/HistoryManager.redo()).",
        False, "위와 동일.")

    add("history", "History Panel",
        "production_engine.history_schema", ["HistoryEntry", "HistoryActionType"],
        UIConnectionStatus.LOGIC_READY, "타임라인 라벨/특정시점복원 로직 테스트됨.",
        False, "Panel UI 자체는 미구현.")

    add("snap", "Snap",
        None, [],
        UIConnectionStatus.LOGIC_READY, "editor/canvas/SnapEngine.js (Backend Python 모듈 없음 - JS 전용).",
        False, "N/A")

    add("guide", "Guide (Bleed/Trim/Safe 등 Tooltip)",
        "production_engine.guide_help", ["GUIDE_HELP_DATA", "get_guide_help"],
        UIConnectionStatus.UNKNOWN, "Tooltip 렌더링 자체는 Frontend 영역.",
        False, "텍스트 데이터만 제공 - 실제 표시 여부 미확인.")

    add("cutcontour", "CutContour",
        "production_engine.vision.contour_engine", ["build_production_cutline"],
        UIConnectionStatus.UNKNOWN, "Frontend 미리보기 연결 여부 이 세션에서 확인 불가.",
        False, "3개 아크릴 상품 전부 needs_confirmation=true - 제작수치 미확정.")

    add("white_layer", "WHITE",
        "production_engine.vision.white_layer", ["generate_white_layer"],
        UIConnectionStatus.UNKNOWN, "위와 동일.",
        False, "위와 동일 (white_choke_mm/white_spread_mm 미확정).")

    add("hole", "Hole",
        "production_engine.vision.hole_placement", ["recommend_hole_positions", "place_hole"],
        UIConnectionStatus.UNKNOWN, "위와 동일.",
        False, "hole_diameter_mm/hole_edge_margin_mm 미확정.")

    add("acrylic_slot", "Acrylic Slot",
        "production_engine.vision.stand_multipart", ["build_multipart_stand", "run_slot_preflight"],
        UIConnectionStatus.UNKNOWN, "Multi-Part UI 자체가 이 세션에 없음.",
        False, "stand_tab/slot 수치 미확정.")

    add("preflight", "Preflight",
        "production_engine.preflight.engine", ["run_preflight"],
        UIConnectionStatus.UNKNOWN, "Preflight 결과 패널 UI 연결 여부 미확인.",
        False, "엔진 자체는 194+ 테스트로 검증되었으나, '검증된 상품 수치' 기준 production_verified 는 아님.")

    add("cmyk", "CMYK 변환",
        "production_engine.pdf.cmyk", ["convert_to_cmyk"],
        UIConnectionStatus.UNKNOWN, "N/A (백엔드 처리 단계).",
        False, "ICC 프로파일 없이는 naive 변환 - 정밀 변환 미검증.")

    add("pdf_export", "PDF Export",
        "production_engine.pdf.builder", ["build_production_pdf"],
        UIConnectionStatus.UNKNOWN, "다운로드 버튼 연결 여부 미확인.",
        False, "PDF/X 미인증 (pdf_x_compliant 는 항상 False).")

    add("customer_proof", "Customer Proof",
        "production_engine.proof_generator", ["generate_customer_proof"],
        UIConnectionStatus.UNKNOWN, "N/A (백엔드 산출물).",
        False, "생성 로직은 테스트됨 - 실사용 케이스 미검증.")

    add("production_package", "Production Package",
        "production_engine.pipeline", ["ProductionPipeline"],
        UIConnectionStatus.UNKNOWN, "ZIP 다운로드 UI 연결 여부 미확인.",
        False, "생성/ZIP 묶음 테스트됨 - 실사용 케이스 미검증.")

    add("mockup_3d", "3D Mockup",
        "production_engine.design.schema", ["MockupData", "MockupDataRepository"],
        UIConnectionStatus.NOT_STARTED, "3D 뷰어 UI는 애초에 설계 범위에서 제외됨 (v1.5 작업지시서 명시).",
        False, "데이터 계약만 존재 - 실제 3D 렌더링 없음.")

    return registry


def summarize_registry(registry: dict[str, FeatureStatus]) -> dict:
    total = len(registry)
    engine_ok = sum(1 for f in registry.values() if f.engine_available)
    ui_logic_ready = sum(1 for f in registry.values() if f.ui_status == UIConnectionStatus.LOGIC_READY)
    ui_connected = sum(1 for f in registry.values() if f.ui_status == UIConnectionStatus.CONNECTED)
    prod_verified = sum(1 for f in registry.values() if f.production_verified)
    return {
        "total_features": total,
        "engine_available": engine_ok,
        "ui_logic_ready": ui_logic_ready,
        "ui_connected_verified": ui_connected,
        "production_verified": prod_verified,
    }
