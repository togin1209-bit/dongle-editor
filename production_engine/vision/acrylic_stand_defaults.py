"""
vision/acrylic_stand_defaults.py
--------------------------------
v1.9.8 (GEMINI track): PROVISIONAL 아크릴 스탠드 끼움 공차 기본값.

⚠️ 매우 중요 - 하드코딩 금지 원칙과의 관계
================================================
작업지시서(#7/#9/#23)는 "제작사 확정치가 없으면 Tab/Slot 공차를 임의로
하드코딩하지 말라"고 명시한다. 그래서 이 값들은 **ProductProfile(제작 truth)
에는 절대 들어가지 않는다.** product_profiles.seed.json / product_profiles/acrylic/
acrylic_stand.json 의 stand_* 필드는 계속 `null`(미확정) 로 남으며,
`is_ready_for_acrylic_production()` 는 계속 False 를 반환한다.

이 모듈이 제공하는 값은 오직:
  1) UI 입력칸의 placeholder/편집 시작값 (사용자가 즉시 덮어씀)
  2) 사용자가 값을 아직 입력하지 않았을 때 미리보기 기하를 그리기 위한 fallback
로만 쓰이며, 항상 `CONFIRMED = False` 로 표시된다. Fallback 이 사용되면
Preflight 는 `STAND_TOLERANCE_PROVISIONAL` WARNING 을 올리고, 해당 산출물은
Production Ready 로 승격되지 않는다.

확정값이 들어오면 (UI 입력 또는 profile 확정) 이 모듈은 우회되고,
`resolve_stand_params()` 가 `using_provisional=False` 를 반환한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .stand_builder import StandParams


# 확정 여부 플래그 - 절대 True 로 바꾸지 말 것 (제작사 확인 전까지).
CONFIRMED = False

# adpiamall 아크릴 스탠드 일반 규격을 참고한 "그럴듯하지만 미확정" 시작값.
# 실제 제작 투입 전 반드시 제작사 확정치로 교체되어야 한다.
PROVISIONAL_STAND_DEFAULTS = {
    "material_thickness_mm": 3.0,     # 3T 아크릴이 가장 흔함
    "stand_tab_width_mm": 20.0,       # 하단 탭 폭
    "stand_tab_height_mm": 8.0,       # 하단 탭 높이(받침대에 꽂히는 깊이 여유 포함)
    "stand_slot_fit_tolerance_mm": 0.2,  # 끼움 공차 (slot_width = thickness + fit_tolerance)
    "stand_slot_clearance_mm": 0.2,   # 슬롯 여유
    "_note": "PROVISIONAL — adpiamall 일반 규격 참고. 제작사 확정 전 임시값.",
    "_confirmed": CONFIRMED,
    "_source": "https://www.adpiamall.com/estimate/goods2019/840 (수치 미표기 항목)",
}


def provisional_slot_width_mm(
    thickness_mm: float = PROVISIONAL_STAND_DEFAULTS["material_thickness_mm"],
    fit_tolerance_mm: float = PROVISIONAL_STAND_DEFAULTS["stand_slot_fit_tolerance_mm"],
) -> float:
    """작업지시서 #9: slot_width_mm = acrylic_thickness_mm + fit_tolerance_mm."""
    return round(thickness_mm + fit_tolerance_mm, 3)


@dataclass
class ResolvedStandParams:
    """profile 값을 우선하고, 없으면 provisional 로 채운 결과 + 어떤 필드가
    provisional 로 채워졌는지 추적."""

    params: StandParams
    using_provisional: bool
    provisional_fields: list[str]


def _first_confirmed(*values):
    for v in values:
        if v is not None:
            return v, True  # confirmed
    return None, False


def resolve_stand_params(
    profile,
    ui_overrides: Optional[dict] = None,
) -> ResolvedStandParams:
    """
    우선순위: UI 입력값 > Profile 확정값 > PROVISIONAL 기본값.

    - UI 또는 Profile 에서 온 값은 confirmed 로 간주한다.
    - 어느 쪽에도 값이 없어 PROVISIONAL 로 채운 필드는 `provisional_fields` 에 기록되고,
      하나라도 있으면 `using_provisional=True`.

    이 함수는 절대로 profile 객체를 변경하지 않는다 (읽기 전용).
    """
    ui = ui_overrides or {}
    provisional_fields: list[str] = []

    def pick(field_name: str, profile_attr: str, default_value: float) -> float:
        # UI override (0/빈값은 "미입력"으로 취급 - 명시적으로 양수여야 확정)
        ui_val = ui.get(field_name)
        if ui_val is not None and float(ui_val) > 0:
            return float(ui_val)
        prof_val = getattr(profile, profile_attr, None)
        if prof_val is not None and float(prof_val) > 0:
            return float(prof_val)
        provisional_fields.append(field_name)
        return float(default_value)

    thickness = pick(
        "material_thickness_mm", "material_thickness_mm",
        PROVISIONAL_STAND_DEFAULTS["material_thickness_mm"],
    )
    tab_w = pick(
        "tab_width_mm", "stand_tab_width_mm",
        PROVISIONAL_STAND_DEFAULTS["stand_tab_width_mm"],
    )
    tab_h = pick(
        "tab_height_mm", "stand_tab_height_mm",
        PROVISIONAL_STAND_DEFAULTS["stand_tab_height_mm"],
    )
    clearance = pick(
        "slot_clearance_mm", "stand_slot_clearance_mm",
        PROVISIONAL_STAND_DEFAULTS["stand_slot_clearance_mm"],
    )

    # slot_width: profile/ui 에 명시값이 있으면 그것, 없으면 thickness + fit_tolerance
    slot_w_ui = ui.get("slot_width_mm")
    slot_w_prof = getattr(profile, "stand_slot_width_mm", None)
    if slot_w_ui is not None and float(slot_w_ui) > 0:
        slot_w = float(slot_w_ui)
    elif slot_w_prof is not None and float(slot_w_prof) > 0:
        slot_w = float(slot_w_prof)
    else:
        provisional_fields.append("slot_width_mm")
        slot_w = provisional_slot_width_mm(
            thickness, PROVISIONAL_STAND_DEFAULTS["stand_slot_fit_tolerance_mm"]
        )

    params = StandParams(
        material_thickness_mm=thickness,
        tab_width_mm=tab_w,
        tab_height_mm=tab_h,
        slot_width_mm=slot_w,
        slot_clearance_mm=clearance,
    )
    return ResolvedStandParams(
        params=params,
        using_provisional=bool(provisional_fields),
        provisional_fields=provisional_fields,
    )
