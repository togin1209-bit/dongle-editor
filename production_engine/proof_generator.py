"""
proof_generator.py
---------------------
v1.8: Customer Proof Generator (작업지시서 11번).

Production PDF(인쇄소 전달용, CMYK/Bleed 포함)와는 별도로, 고객이 "이대로 맞는지"
확인하는 JPG 시안(Proof)을 만든다.

**중요한 원칙(작업지시서 명시)**: Production PDF에는 불필요한 정보(주문번호, 상품명
텍스트 오버레이 등)가 들어가면 안 된다 - 그건 인쇄소가 실제로 인쇄할 데이터이기
때문이다. Proof는 반대로 그런 정보가 있어야 고객이 확인하기 편하다. 이 모듈은 항상
Proof 전용 별도 파일(JPG)만 만들고, 기존 pdf/builder.py 의 Production PDF 생성
경로는 전혀 건드리지 않는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

_KOREAN_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = _KOREAN_FONT_CANDIDATES if not bold else list(reversed(_KOREAN_FONT_CANDIDATES))
    for path in candidates:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size, index=3 if "CJK" in path else 0)
            except OSError:
                continue
    return ImageFont.load_default()


@dataclass
class ProofMetadata:
    order_number: Optional[str] = None
    product_name: Optional[str] = None
    width_mm: Optional[float] = None
    height_mm: Optional[float] = None
    side_label: Optional[str] = None  # "앞면" | "뒷면" 등

    def lines(self) -> list[str]:
        parts = []
        if self.product_name:
            size = f" {self.width_mm:.0f}×{self.height_mm:.0f}mm" if self.width_mm and self.height_mm else ""
            parts.append(f"{self.product_name}{size}")
        if self.side_label:
            parts.append(self.side_label)
        if self.order_number:
            parts.append(f"주문번호 {self.order_number}")
        return parts


def generate_customer_proof(
    image_path: str,
    dest_path: str,
    metadata: Optional[ProofMetadata] = None,
    max_dimension_px: int = 1600,
    jpeg_quality: int = 88,
    show_metadata_overlay: bool = True,
) -> str:
    """
    제작용 이미지(CMYK 변환 전/후 무관 - 시안이므로 화면 표시용 RGB로 통일)를 받아
    고객 확인용 Proof JPG 를 생성한다.

    - 큰 원본을 그대로 쓰지 않고 max_dimension_px 이내로 축소한다 (Proof는 웹/모바일
      확인용이지 인쇄용이 아니므로 큰 용량이 불필요하다).
    - metadata 가 주어지면 하단에 반투명 정보 바를 그려 상품명/사이즈/앞뒤/주문번호를
      표시한다 (Production PDF에는 이 정보가 들어가지 않는다 - 완전히 다른 파일이다).
    """
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        w, h = img.size
        scale = min(1.0, max_dimension_px / max(w, h))
        if scale < 1.0:
            img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)

        if show_metadata_overlay and metadata and metadata.lines():
            img = _draw_metadata_overlay(img, metadata.lines())

        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        img.save(dest_path, format="JPEG", quality=jpeg_quality)

    return dest_path


def _draw_metadata_overlay(img: Image.Image, lines: list[str]) -> Image.Image:
    img = img.copy()
    draw = ImageDraw.Draw(img, "RGBA")
    font = _load_font(size=max(14, img.width // 40))

    line_height = font.size + 6
    bar_height = line_height * len(lines) + 16
    bar_top = img.height - bar_height

    draw.rectangle([0, bar_top, img.width, img.height], fill=(0, 0, 0, 160))
    y = bar_top + 8
    for line in lines:
        draw.text((12, y), line, fill=(255, 255, 255, 255), font=font)
        y += line_height

    return img


def default_proof_filename(order_number: Optional[str], job_id: str) -> str:
    """작업지시서 예시(ORD-2026-10001_proof.jpg)와 동일한 규칙."""
    base = order_number or job_id
    return f"{base}_proof.jpg"


def default_production_filename(order_number: Optional[str], job_id: str) -> str:
    base = order_number or job_id
    return f"{base}_production.pdf"
