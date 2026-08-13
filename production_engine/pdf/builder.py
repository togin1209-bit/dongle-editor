"""
pdf/builder.py
-----------------
Production PDF 빌더.

**중요 - 정직한 한계 고지**
이 모듈은 "PDF/X-1a 지향(oriented)" 산출물을 만든다. 즉:
- TrimBox / BleedBox / MediaBox 를 정확히 설정한다.
- CMYK 이미지로 배치한다.
- OutputIntent(ICC 프로파일 임베드) 를 pikepdf 로 삽입한다.

하지만 진짜 PDF/X-1a "규격 준수 인증"은:
- 정확한 인쇄소 지정 ICC 프로파일이 있어야 하고
- Adobe Acrobat Preflight / callas pdfToolbox 같은 전문 검증 도구로
  최종 검증받는 것이 인쇄 업계 표준 관행이다.

따라서 이 빌더가 만든 PDF는 "제작 가능한 인쇄파일 초안"이지,
"검증된 PDF/X-1a 인증 파일"이라고 자동으로 단정해서는 안 된다.
GPT/상위 시스템은 이 산출물을 최종 인쇄소 전달 전 실제 검증 도구를 거치도록
UX에 명시하는 것을 권장한다. (README 및 한계 섹션 참고)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

try:
    import pikepdf
    _PIKEPDF_AVAILABLE = True
except ImportError:
    pikepdf = None
    _PIKEPDF_AVAILABLE = False
from PIL import Image
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

MM_PER_INCH = 25.4
PT_PER_MM = 72.0 / MM_PER_INCH


@dataclass
class PdfBuildResult:
    output_path: str
    trim_size_mm: tuple[float, float]
    media_size_mm: tuple[float, float]
    bleed_mm: float
    pdf_standard: str
    output_intent_embedded: bool
    pikepdf_used: bool
    # v1.3: "PDF/X 인증"은 이 엔진이 스스로 판단할 수 없다 (Adobe Preflight/callas 같은
    # 전문 검증 도구의 몫). 따라서 이 값은 항상 False로 고정하고, 실제로 외부 도구에서
    # 검증을 통과한 경우에만 상위 시스템(GPT/운영자)이 별도로 기록해야 한다.
    # "표시하지 마세요" 요구사항을 코드 레벨에서 강제하기 위한 필드다.
    pdf_x_compliant: bool = False
    compliance_note: str = (
        "이 PDF는 PDF/X-1a 규격을 '지향'하여 생성되었으나(TrimBox/BleedBox/OutputIntent 포함), "
        "전문 검증 도구로 인증받지 않았습니다. 'PDF/X 인증 완료'로 표시하지 마세요."
    )


def build_production_pdf(
    image_path: str,
    dest_path: str,
    trim_width_mm: float,
    trim_height_mm: float,
    bleed_mm: float,
    pdf_standard: str = "PDF/X-1a",
    output_icc_path: Optional[str] = None,
    output_icc_name: Optional[str] = None,
) -> PdfBuildResult:
    """
    이미지 1장을 받아 Bleed 를 포함한 최종 PDF 를 생성한다.
    이미지는 이미 (trim + bleed) 크기에 맞게 크롭/리사이즈되어 있다고 가정한다
    (imaging.processor 단계에서 처리 완료된 상태).
    """
    media_width_mm = trim_width_mm + bleed_mm * 2
    media_height_mm = trim_height_mm + bleed_mm * 2

    media_width_pt = media_width_mm * PT_PER_MM
    media_height_pt = media_height_mm * PT_PER_MM

    # v1.3: 실제로 배치될 이미지가 (trim+bleed) 캔버스 비율과 맞는지 미리 검증한다.
    # pipeline.py 의 prepare_working_image() 가 이미 bleed 포함 캔버스로 이미지를 준비하지만,
    # 이 함수는 외부(GPT 통합 코드 등)에서 image_path 를 직접 넘겨 호출할 수도 있으므로
    # 방어적으로 한 번 더 확인해 "조용한 왜곡"을 방지한다.
    with Image.open(image_path) as src_img:
        img_w_px, img_h_px = src_img.size
    px_ratio = img_w_px / img_h_px
    mm_ratio = media_width_mm / media_height_mm
    if abs(px_ratio - mm_ratio) / mm_ratio > 0.02:  # 2% 초과 오차
        raise ValueError(
            f"이미지 픽셀 비율({px_ratio:.4f})이 출력 캔버스(재단+도련) 비율({mm_ratio:.4f})과 "
            f"일치하지 않습니다. 이대로 배치하면 이미지가 눈에 띄게 왜곡되므로 PDF 생성을 "
            f"중단합니다. 이미지가 (trim_width_mm+2*bleed_mm) x (trim_height_mm+2*bleed_mm) "
            f"비율에 맞춰 준비되었는지 확인하세요."
        )

    # 1) reportlab 으로 이미지 배치 + 기본 PDF 생성
    tmp_path = dest_path + ".tmp.pdf"
    c = canvas.Canvas(tmp_path, pagesize=(media_width_pt, media_height_pt))
    c.drawImage(
        image_path,
        0,
        0,
        width=media_width_pt,
        height=media_height_pt,
        preserveAspectRatio=False,  # 이미지가 이미 정확한 크기로 준비되었으므로 강제 변형 없음
    )
    c.showPage()
    c.save()

    # 2) pikepdf가 있으면 TrimBox/BleedBox/MediaBox 및 OutputIntent를 설정한다.
    #    설치가 불가능한 환경에서는 기본 PDF로 폴백하여 프로그램 자체는 계속 동작한다.
    output_intent_embedded = False
    if _PIKEPDF_AVAILABLE:
        with pikepdf.open(tmp_path) as pdf:
            page = pdf.pages[0]
            media_box = [0, 0, media_width_pt, media_height_pt]
            trim_x0 = bleed_mm * PT_PER_MM
            trim_y0 = bleed_mm * PT_PER_MM
            trim_x1 = trim_x0 + trim_width_mm * PT_PER_MM
            trim_y1 = trim_y0 + trim_height_mm * PT_PER_MM
            page.MediaBox = media_box
            page.BleedBox = media_box
            page.TrimBox = [trim_x0, trim_y0, trim_x1, trim_y1]
            if output_icc_path and os.path.isfile(output_icc_path):
                _embed_output_intent(pdf, output_icc_path, output_icc_name or "Custom CMYK Profile")
                output_intent_embedded = True
            with pdf.open_metadata() as meta:
                meta["pdf:Producer"] = "DONGLE Studio Production Engine"
                meta["xmp:CreatorTool"] = "DONGLE Studio Production Engine"
            pdf.save(dest_path)
        os.remove(tmp_path)
    else:
        os.replace(tmp_path, dest_path)

    return PdfBuildResult(
        output_path=dest_path,
        trim_size_mm=(trim_width_mm, trim_height_mm),
        media_size_mm=(media_width_mm, media_height_mm),
        bleed_mm=bleed_mm,
        pdf_standard=pdf_standard,
        output_intent_embedded=output_intent_embedded,
        pikepdf_used=_PIKEPDF_AVAILABLE,
    )


def _embed_output_intent(pdf: pikepdf.Pdf, icc_path: str, profile_name: str) -> None:
    """PDF/X 규격이 요구하는 OutputIntent(색상 프로파일 임베드)를 삽입한다."""
    with open(icc_path, "rb") as f:
        icc_bytes = f.read()

    icc_stream = pikepdf.Stream(pdf, icc_bytes)
    icc_stream["/N"] = 4  # CMYK = 4 채널
    icc_stream["/Alternate"] = pikepdf.Name("/DeviceCMYK")

    output_intent = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/OutputIntent"),
                "/S": pikepdf.Name("/GTS_PDFX"),
                "/OutputConditionIdentifier": pikepdf.String(profile_name),
                "/Info": pikepdf.String(profile_name),
                "/DestOutputProfile": pdf.make_indirect(icc_stream),
            }
        )
    )
    pdf.Root.OutputIntents = pdf.make_indirect(pikepdf.Array([output_intent]))
