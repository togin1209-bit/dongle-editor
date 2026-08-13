"""
imaging/dpi.py
----------------
Effective DPI(실효 해상도) 계산.

주의: 이미지 파일 자체에 박혀있는 "DPI 메타데이터"(예: Photoshop이 저장한 72dpi 표시)는
절대 신뢰하지 않는다. 그 값은 화면 표시용 관습값일 뿐, 실제 인쇄 품질과 무관하다.

실제로 의미 있는 값은:
    effective_dpi = 원본 픽셀 수 / (실제 출력되는 물리적 크기(inch))

이 값이 낮으면 확대 인쇄 시 이미지가 흐릿해진다.
"""

from __future__ import annotations

from dataclasses import dataclass

MM_PER_INCH = 25.4


@dataclass
class EffectiveDpiResult:
    dpi_x: float
    dpi_y: float

    @property
    def min_dpi(self) -> float:
        """가로/세로 중 더 낮은 쪽이 실제 품질을 결정한다 (보수적으로 판단)."""
        return min(self.dpi_x, self.dpi_y)


def mm_to_inch(mm: float) -> float:
    return mm / MM_PER_INCH


def calculate_effective_dpi(
    pixel_width: int,
    pixel_height: int,
    output_width_mm: float,
    output_height_mm: float,
) -> EffectiveDpiResult:
    """
    실제 출력 크기(mm) 기준 실효 DPI를 계산한다.

    예: 원본 3000px 가로 이미지를 가로 1000mm(약 39.4인치) 배너로 출력하면
        effective_dpi_x = 3000 / 39.4 ≈ 76 DPI
    """
    if pixel_width <= 0 or pixel_height <= 0:
        raise ValueError("픽셀 크기는 0보다 커야 합니다.")
    if output_width_mm <= 0 or output_height_mm <= 0:
        raise ValueError("출력 크기(mm)는 0보다 커야 합니다.")

    width_inch = mm_to_inch(output_width_mm)
    height_inch = mm_to_inch(output_height_mm)

    dpi_x = pixel_width / width_inch
    dpi_y = pixel_height / height_inch

    return EffectiveDpiResult(dpi_x=dpi_x, dpi_y=dpi_y)


def required_pixels_for_dpi(output_width_mm: float, output_height_mm: float, target_dpi: float) -> tuple[int, int]:
    """특정 목표 DPI를 만족하려면 원본이 최소 몇 픽셀이어야 하는지 계산 (안내 메시지용)."""
    width_px = round(mm_to_inch(output_width_mm) * target_dpi)
    height_px = round(mm_to_inch(output_height_mm) * target_dpi)
    return width_px, height_px
