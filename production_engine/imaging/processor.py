"""
imaging/processor.py
----------------------
실제 Resize/Crop 실행.

원칙:
- 원본 파일(original/)은 절대 열어서 저장(save)하지 않는다. 항상 새 파일(working/)에 결과를 쓴다.
- 크롭 좌표는 항상 "원본 픽셀 좌표계" 기준으로 받는다 (화면 미리보기 좌표계와 분리 - ratio.py 참고).
- 업스케일이 발생하면 그 사실과 배율을 결과에 기록한다 (숨기지 않는다 -> preflight 에서 사용).
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from ..models import CropBox


@dataclass
class ProcessResult:
    working_path: str
    output_width_px: int
    output_height_px: int
    upscale_factor: float  # 1.0 이하면 업스케일 없음. 예: 1.5 면 150% 확대.
    resample_method: str


def crop_and_resize(
    source_path: str,
    crop_box: CropBox,
    output_width_px: int,
    output_height_px: int,
    working_path: str,
) -> ProcessResult:
    """
    원본에서 crop_box 영역을 잘라낸 뒤 output_width_px x output_height_px 로 리샘플링하여
    working_path 에 저장한다.
    """
    if output_width_px <= 0 or output_height_px <= 0:
        raise ValueError("출력 픽셀 크기는 0보다 커야 합니다.")

    with Image.open(source_path) as img:
        img.load()

        # 원본 파일 객체 자체는 건드리지 않고, crop() 은 새 이미지 객체를 반환한다.
        box = (crop_box.x, crop_box.y, crop_box.x + crop_box.width, crop_box.y + crop_box.height)
        cropped = img.crop(box)

        scale_x = output_width_px / crop_box.width
        scale_y = output_height_px / crop_box.height
        # 두 축 스케일이 크게 다르면 비율이 왜곡된 리사이즈 요청이라는 뜻 -> 상위 레이어(ratio.py)에서
        # 이미 COVER/CONTAIN 계산 시 동일 비율을 보장하지만, 방어적으로 한 번 더 확인한다.
        if abs(scale_x - scale_y) / max(scale_x, scale_y) > 0.02:  # 2% 초과 오차
            raise ValueError(
                f"가로/세로 스케일 비율이 일치하지 않습니다 (scale_x={scale_x:.4f}, "
                f"scale_y={scale_y:.4f}). 이미지가 왜곡되므로 처리를 중단합니다."
            )

        upscale_factor = max(scale_x, scale_y)

        # 다운스케일: LANCZOS (고품질 축소)
        # 업스케일: BICUBIC (Pillow 에서 확대 시 일반적으로 무난한 선택)
        resample = Image.LANCZOS if upscale_factor <= 1.0 else Image.BICUBIC
        resample_name = "LANCZOS" if upscale_factor <= 1.0 else "BICUBIC"
        resized = cropped.resize((output_width_px, output_height_px), resample=resample)

        save_kwargs = {}
        if resized.mode == "RGBA" and working_path.lower().endswith((".jpg", ".jpeg")):
            # JPEG는 알파 채널을 지원하지 않음 -> 흰 배경으로 합성 (검정 배경으로 잘리는 사고 방지)
            background = Image.new("RGB", resized.size, (255, 255, 255))
            background.paste(resized, mask=resized.split()[3])
            resized = background

        resized.save(working_path, **save_kwargs)

    return ProcessResult(
        working_path=working_path,
        output_width_px=output_width_px,
        output_height_px=output_height_px,
        upscale_factor=upscale_factor,
        resample_method=resample_name,
    )


def pixels_for_target(width_mm: float, height_mm: float, render_dpi: float) -> tuple[int, int]:
    """제작 사이즈(mm)와 렌더링 DPI를 받아 실제 리사이즈 목표 픽셀 수를 계산한다."""
    from .dpi import mm_to_inch

    width_px = max(1, round(mm_to_inch(width_mm) * render_dpi))
    height_px = max(1, round(mm_to_inch(height_mm) * render_dpi))
    return width_px, height_px
