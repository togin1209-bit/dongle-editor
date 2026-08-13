"""
quick_actions.py
-------------------
v1.7: Production Quick Action Layer (작업지시서 8번), Background Remove 연계 Quick
Action(작업지시서 7번 "배경제거 완료 후" 버튼들) 포함.

이 모듈은 "어떤 Quick Action이 존재하고, 각각이 실제로 어느 백엔드 기능에 연결되는지"를
레지스트리로 정의한다. Frontend는 이 레지스트리를 그대로 버튼 목록으로 렌더링하고,
클릭 시 `resolve()` 가 반환하는 정보로 실제 API를 호출하면 된다.

**정직성 원칙**: 아직 Production Engine에 실제로 구현되지 않은 Quick Action(예: AI
화질 개선, AI 배경 제거는 rembg 등 외부 모델이 필요하며 이 프로젝트에서는 지금까지
app.py 레벨에서만 연결되어 있었고 production_engine 자체에는 없다)은
`backend_status="NOT_CONNECTED"` 로 명확히 표시한다 - 존재하지 않는 기능을 연결된
것처럼 속이지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class QuickActionCategory(str, Enum):
    IMAGE_AI = "IMAGE_AI"              # AI 배경 제거, 화질 개선, 상품에 맞게 채우기, 사진 교체, 색상 보정
    CUTLINE = "CUTLINE"                 # 스티커 칼선 생성, 아크릴 칼선 생성
    ACRYLIC_GOODS = "ACRYLIC_GOODS"      # 아크릴 키링/스탠드 만들기 (배경 제거 후 버튼)


class BackendStatus(str, Enum):
    CONNECTED = "CONNECTED"                # production_engine 에 실제로 구현되어 바로 호출 가능
    NOT_CONNECTED = "NOT_CONNECTED"        # UI/레지스트리만 존재, 백엔드 구현 없음 (v1.7 기준)
    PARTIALLY_CONNECTED = "PARTIALLY_CONNECTED"  # 관련 엔진은 있지만 이 Quick Action 전용 엔드포인트는 없음


@dataclass
class QuickAction:
    action_id: str
    label: str                    # 작업지시서 원문 한글 라벨 그대로
    category: QuickActionCategory
    backend_status: BackendStatus
    backend_hint: str              # 실제 연결 시 어떤 모듈/메서드를 호출해야 하는지
    requires_alpha_channel: bool = False
    applicable_object_types: tuple = ("IMAGE",)


# 작업지시서 8번 + 7번에 나열된 Quick Action 전체를 그대로 등록한다.
QUICK_ACTIONS: dict[str, QuickAction] = {
    "ai_background_remove": QuickAction(
        action_id="ai_background_remove", label="AI 배경 제거", category=QuickActionCategory.IMAGE_AI,
        backend_status=BackendStatus.NOT_CONNECTED,
        backend_hint=(
            "app.py 의 /api/jobs/<job_id>/remove-background 가 rembg 로 이미 구현되어 있으나, "
            "production_engine 패키지 자체에는 배경제거 로직이 없다 (app.py 전용). "
            "production_engine 에 정식 편입하려면 vision/background_removal.py 신설 필요."
        ),
    ),
    "quality_enhance": QuickAction(
        action_id="quality_enhance", label="화질 개선", category=QuickActionCategory.IMAGE_AI,
        backend_status=BackendStatus.NOT_CONNECTED,
        backend_hint="업스케일링(super-resolution) 모델이 필요 - 현재 production_engine 에 미구현.",
    ),
    "fit_to_product": QuickAction(
        action_id="fit_to_product", label="상품에 맞게 채우기", category=QuickActionCategory.IMAGE_AI,
        backend_status=BackendStatus.PARTIALLY_CONNECTED,
        backend_hint=(
            "imaging.ratio.resolve_crop_box() + imaging.processor.crop_and_resize() 로 이미 구현된 "
            "Cover/Contain 로직을 재사용 가능 (pipeline.prepare_working_image() 참고). "
            "Quick Action 전용 엔드포인트만 새로 추가하면 됨."
        ),
    ),
    "sticker_cutline": QuickAction(
        action_id="sticker_cutline", label="스티커 칼선 생성", category=QuickActionCategory.CUTLINE,
        backend_status=BackendStatus.PARTIALLY_CONNECTED, requires_alpha_channel=True,
        backend_hint=(
            "vision.contour_engine.build_production_cutline() 으로 생성 가능 (v1.6에서 아크릴키링용으로 "
            "이미 구현됨 - 스티커 상품(sticker_epoxy 등)의 cutline_offset_mm 이 Product Profile에 "
            "확정되면 동일 엔진을 그대로 재사용할 수 있음). 현재 스티커 상품들은 해당 필드가 "
            "미확인(null) 상태라 실제 호출은 아직 차단됨."
        ),
    ),
    "acrylic_cutline": QuickAction(
        action_id="acrylic_cutline", label="아크릴 칼선 생성", category=QuickActionCategory.CUTLINE,
        backend_status=BackendStatus.CONNECTED, requires_alpha_channel=True,
        backend_hint="acrylic_pipeline.AcrylicProductionPipeline.generate_cutline() (v1.6, 실제 구현/테스트됨).",
    ),
    "photo_replace": QuickAction(
        action_id="photo_replace", label="사진 교체", category=QuickActionCategory.IMAGE_AI,
        backend_status=BackendStatus.PARTIALLY_CONNECTED,
        backend_hint="pipeline.ingest_upload() 로 새 원본을 다시 업로드하는 흐름 재사용 가능.",
    ),
    "color_correction": QuickAction(
        action_id="color_correction", label="색상 보정", category=QuickActionCategory.IMAGE_AI,
        backend_status=BackendStatus.NOT_CONNECTED,
        backend_hint="밝기/대비/채도/색온도 보정 알고리즘이 production_engine 에 아직 없음.",
    ),
    "make_acrylic_keyring": QuickAction(
        action_id="make_acrylic_keyring", label="아크릴 키링 만들기", category=QuickActionCategory.ACRYLIC_GOODS,
        backend_status=BackendStatus.CONNECTED, requires_alpha_channel=True,
        backend_hint=(
            "acrylic_pipeline.AcrylicProductionPipeline: generate_cutline() -> recommend_hole()/"
            "place_hole_on_job() -> generate_white_layer() -> analyze_manufacturability() (v1.6 전체 파이프라인)."
        ),
    ),
    "make_acrylic_stand": QuickAction(
        action_id="make_acrylic_stand", label="아크릴 스탠드 만들기", category=QuickActionCategory.ACRYLIC_GOODS,
        backend_status=BackendStatus.CONNECTED, requires_alpha_channel=True,
        backend_hint="acrylic_pipeline.AcrylicProductionPipeline.generate_stand() (v1.6, 실제 구현/테스트됨).",
    ),
    "download_transparent_png": QuickAction(
        action_id="download_transparent_png", label="배경없는 PNG", category=QuickActionCategory.IMAGE_AI,
        backend_status=BackendStatus.PARTIALLY_CONNECTED, requires_alpha_channel=True,
        backend_hint=(
            "v1.8 작업지시서 3번: 배경제거 결과(알파 마스크 적용된 RGBA)를 그대로 PNG로 "
            "저장해 내려주기만 하면 된다 - 별도 이미지 처리 없이 working image 를 PNG로 "
            "export 하는 엔드포인트만 추가하면 CONNECTED 로 승격 가능."
        ),
    ),
}


@dataclass
class QuickActionResolution:
    action: QuickAction
    callable_now: bool
    reason: str


def resolve(action_id: str, has_alpha_channel: bool = False) -> QuickActionResolution:
    """Frontend가 버튼 클릭 시 호출 가능 여부를 판단할 때 쓰는 진입점."""
    action = QUICK_ACTIONS.get(action_id)
    if action is None:
        raise KeyError(f"알 수 없는 Quick Action: {action_id}")

    if action.backend_status == BackendStatus.NOT_CONNECTED:
        return QuickActionResolution(action=action, callable_now=False, reason="백엔드 미구현")

    if action.requires_alpha_channel and not has_alpha_channel:
        return QuickActionResolution(
            action=action, callable_now=False,
            reason="이 작업에는 투명 배경(알파 채널) 이미지가 필요합니다. 먼저 배경 제거를 진행하세요.",
        )

    if action.backend_status == BackendStatus.PARTIALLY_CONNECTED:
        return QuickActionResolution(
            action=action, callable_now=False,
            reason=f"관련 엔진은 있으나 전용 엔드포인트 연결이 아직 없습니다: {action.backend_hint}",
        )

    return QuickActionResolution(action=action, callable_now=True, reason="사용 가능")


def list_actions_for_category(category: QuickActionCategory) -> list[QuickAction]:
    return [a for a in QUICK_ACTIONS.values() if a.category == category]


def actions_after_background_remove() -> list[QuickAction]:
    """v1.8 작업지시서 3번: 배경제거 완료 후 노출되는 Quick Action 4종
    (v1.7의 3종 + '배경없는 PNG' 다운로드 추가 - ADDITIVE)."""
    return [
        QUICK_ACTIONS["download_transparent_png"],
        QUICK_ACTIONS["make_acrylic_keyring"],
        QUICK_ACTIONS["make_acrylic_stand"],
        QUICK_ACTIONS["sticker_cutline"],
    ]
