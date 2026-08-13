"""
imaging/ratio.py
------------------
원본 이미지 비율 vs 제작(주문) 비율 비교, Cover/Contain/Crop 정책에 따른
실제 배치 좌표(원본 픽셀 좌표계) 계산.

정책 정의 (models.FitPolicy):
- CONTAIN: 원본 전체가 출력 영역 안에 들어가도록 축소. 남는 영역 발생 가능(레터박스).
           => 잘리는 내용은 없지만, 출력 캔버스에 여백이 생길 수 있음.
- COVER:   출력 영역을 여백 없이 꽉 채우도록 확대/축소. 넘치는 부분은 잘림.
           => 여백은 없지만 이미지 일부가 잘릴 수 있음. (일반적인 배너 기본값으로 흔히 사용)
- CROP_MANUAL: 사용자가 지정한 CropBox 를 그대로 사용. 시스템이 임의 계산하지 않음.

절대 하지 않는 것: 비율이 안 맞는다고 이미지를 강제로 늘리거나 눌러서(non-uniform scale)
                   왜곡시키는 것. 이는 인쇄 클레임의 가장 흔한 원인이므로 금지한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import CropBox, FitPolicy


@dataclass
class RatioComparison:
    source_ratio: float          # 원본 가로/세로 비율
    target_ratio: float          # 제작 가로/세로 비율
    ratio_diff_percent: float    # 두 비율의 차이 (%) - preflight 경고 판단에 사용
    matches: bool                # 실질적으로 동일하다고 볼 수 있는지 (임계값 이내)


def compare_ratio(
    source_width_px: int,
    source_height_px: int,
    target_width_mm: float,
    target_height_mm: float,
    tolerance_percent: float = 1.0,
) -> RatioComparison:
    source_ratio = source_width_px / source_height_px
    target_ratio = target_width_mm / target_height_mm
    diff_percent = abs(source_ratio - target_ratio) / target_ratio * 100
    return RatioComparison(
        source_ratio=source_ratio,
        target_ratio=target_ratio,
        ratio_diff_percent=diff_percent,
        matches=diff_percent <= tolerance_percent,
    )


def compute_contain_box(
    source_width_px: int, source_height_px: int, target_width_px: int, target_height_px: int
) -> CropBox:
    """
    CONTAIN: 크롭 없이 전체 원본을 사용한다.
    (실제 캔버스 배치에서 레터박스 여백 처리는 pdf 빌더 단계에서 수행)
    """
    return CropBox(x=0, y=0, width=source_width_px, height=source_height_px)


def compute_cover_crop_box(
    source_width_px: int, source_height_px: int, target_width_px: int, target_height_px: int
) -> CropBox:
    """
    COVER: 출력 비율에 맞춰 원본에서 중앙 기준으로 최대 크기를 잘라낸다.
    (좌우 또는 상하 중 넘치는 쪽만 대칭으로 크롭 - 왜곡 없음, 확대/축소는 균일 비율로만 수행)
    """
    source_ratio = source_width_px / source_height_px
    target_ratio = target_width_px / target_height_px

    if source_ratio > target_ratio:
        # 원본이 더 옆으로 넓다 -> 좌우를 잘라낸다
        crop_height = source_height_px
        crop_width = round(crop_height * target_ratio)
        x = round((source_width_px - crop_width) / 2)
        y = 0
    else:
        # 원본이 더 세로로 길다 -> 상하를 잘라낸다
        crop_width = source_width_px
        crop_height = round(crop_width / target_ratio)
        x = 0
        y = round((source_height_px - crop_height) / 2)

    return CropBox(x=x, y=y, width=crop_width, height=crop_height)


def resolve_crop_box(
    policy: FitPolicy,
    source_width_px: int,
    source_height_px: int,
    target_width_px: int,
    target_height_px: int,
    manual_box: CropBox | None = None,
) -> CropBox:
    if policy == FitPolicy.CROP_MANUAL:
        if manual_box is None:
            raise ValueError("CROP_MANUAL 정책에는 manual_box 가 필요합니다.")
        _validate_crop_box(manual_box, source_width_px, source_height_px)
        return manual_box
    if policy == FitPolicy.COVER:
        return compute_cover_crop_box(source_width_px, source_height_px, target_width_px, target_height_px)
    if policy == FitPolicy.CONTAIN:
        return compute_contain_box(source_width_px, source_height_px, target_width_px, target_height_px)
    raise ValueError(f"알 수 없는 FitPolicy: {policy}")


def _validate_crop_box(box: CropBox, source_width_px: int, source_height_px: int) -> None:
    if box.x < 0 or box.y < 0:
        raise ValueError("크롭 좌표는 음수일 수 없습니다.")
    if box.x + box.width > source_width_px or box.y + box.height > source_height_px:
        raise ValueError(
            f"크롭 영역이 원본 범위를 벗어납니다. "
            f"원본=({source_width_px}x{source_height_px}), 요청 crop={box}"
        )
    if box.width <= 0 or box.height <= 0:
        raise ValueError("크롭 영역의 폭/높이는 0보다 커야 합니다.")
