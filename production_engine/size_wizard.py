"""
size_wizard.py
------------------
v1.9 PRODUCTION GUIDE 반영: "사용자는 완성사이즈만 입력한다" UX 계약 (작업지시서
"UX 추가 요구" / "REAL-TIME SIZE VALIDATION" / "IMAGE QUALITY" 섹션).

이 모듈은 Frontend가 그대로 화면에 표시할 수 있는 **완성된 한국어 메시지**를 만든다
(디자인/문구는 예시로 주어진 것을 그대로 재사용했다 - 임의로 새로 만들지 않음):

  "✓ 제작 가능한 사이즈입니다."
  "⚠ 해당 상품의 최대 제작 가능 크기를 초과했습니다."
  "이미지 품질 187ppi / 권장: 150ppi 이상 / ✓ 출력에 적합합니다."
  "ⓘ 실제 작업파일은 도련을 포함하여 602 × 1802mm로 자동 생성됩니다."

내부적으로는 기존 resize_engine.validate_custom_size() / imaging.dpi.calculate_effective_dpi()
를 그대로 재사용한다 (계산 로직 중복 없음 - 이 모듈은 메시지 포맷팅 계층이다).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .imaging.dpi import calculate_effective_dpi
from .models import ProductProfile
from .resize_engine import validate_custom_size


class SizeJudgement(str, Enum):
    OK = "OK"                 # 제작 가능
    CAUTION = "CAUTION"       # 주의 (제작은 가능하나 확인 필요 - 예: 프리셋 범위 밖 추정치 영역)
    BLOCKED = "BLOCKED"       # 제작 불가


@dataclass
class SizeInputResult:
    judgement: SizeJudgement
    message: str
    finished_width_mm: float
    finished_height_mm: float
    working_width_mm: Optional[float] = None
    working_height_mm: Optional[float] = None
    working_size_note: Optional[str] = None


def evaluate_finished_size(profile: ProductProfile, width_mm: float, height_mm: float) -> SizeInputResult:
    """
    사용자가 [가로]x[세로] 완성사이즈만 입력했을 때, 실시간으로 판정 메시지 + 자동
    계산된 Working Size(도련 포함)를 함께 반환한다.
    """
    validation = validate_custom_size(profile, width_mm, height_mm)

    if not validation.valid:
        message = f"⚠ 해당 상품의 최대 제작 가능 크기를 초과했습니다."
        if validation.allowed_range:
            message += f" (허용 범위: {validation.allowed_range})"
        return SizeInputResult(
            judgement=SizeJudgement.BLOCKED, message=message,
            finished_width_mm=width_mm, finished_height_mm=height_mm,
        )

    bleed_mm = profile.safe_zone.bleed_mm
    working_w = width_mm + bleed_mm * 2
    working_h = height_mm + bleed_mm * 2

    note = (
        f"ⓘ 실제 작업파일은 도련을 포함하여 {working_w:g} × {working_h:g}mm로 자동 생성됩니다."
    )

    # bleed_mm 등 일부 제작수치가 아직 미검증(v1.2 dev-default)인 상품은 '제작 가능'이
    # 아니라 '주의'로 낮춰 표시한다 - 조용히 확정된 것처럼 보이면 안 된다.
    if profile.is_dev_default or "safe_zone.bleed_mm" not in (profile.verified_fields or []):
        return SizeInputResult(
            judgement=SizeJudgement.CAUTION,
            message="⚠ 제작 가능하나, 이 상품의 도련(Bleed) 수치는 아직 제작사 공식 자료로 "
                    "검증되지 않았습니다 (참고용 추정치 적용).",
            finished_width_mm=width_mm, finished_height_mm=height_mm,
            working_width_mm=working_w, working_height_mm=working_h, working_size_note=note,
        )

    return SizeInputResult(
        judgement=SizeJudgement.OK, message="✓ 제작 가능한 사이즈입니다.",
        finished_width_mm=width_mm, finished_height_mm=height_mm,
        working_width_mm=working_w, working_height_mm=working_h, working_size_note=note,
    )


@dataclass
class ImageQualityResult:
    effective_dpi: float
    recommended_dpi: float
    is_adequate: bool
    message: str


def evaluate_image_quality(
    profile: ProductProfile, pixel_width: int, pixel_height: int, usage_width_mm: float, usage_height_mm: float,
) -> ImageQualityResult:
    """
    작업지시서 IMAGE QUALITY 섹션 예시 그대로:
      "이미지 품질 187ppi / 권장: 150ppi 이상 / ✓ 출력에 적합합니다."
    """
    dpi_result = calculate_effective_dpi(pixel_width, pixel_height, usage_width_mm, usage_height_mm)
    effective = dpi_result.min_dpi
    recommended = profile.dpi_warning_below
    adequate = effective >= recommended

    status_line = "✓ 출력에 적합합니다." if adequate else "⚠ 해상도가 낮아 흐릿하게 출력될 수 있습니다."
    message = f"이미지 품질 {effective:.0f}ppi\n권장: {recommended:g}ppi 이상\n{status_line}"

    return ImageQualityResult(
        effective_dpi=round(effective, 1), recommended_dpi=recommended,
        is_adequate=adequate, message=message,
    )
