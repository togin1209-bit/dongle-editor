"""
pdf/export_formats.py
------------------------
v1.4 - 향후 파일 생성 포맷 인터페이스 설계 (작업지시서 G).
v1.6 - SVG / CUTLINE_PDF 실제 구현 추가 (cutline_export.py, 작업지시서 7번).

**중요한 정정**: "AI-compatible PDF" 는 Adobe Illustrator의 고유(proprietary) .ai
바이너리 포맷을 생성하는 것이 아니다. Illustrator는 PDF 1.x 호환 구조로 저장된
PDF(및 PDF/X)를 "Illustrator 편집 가능 PDF"로 열 수 있는데, 이 모듈이 말하는
AI_COMPATIBLE_PDF 는 정확히 이것 — "Illustrator가 열어서 편집할 수 있는 형태의
표준 PDF" — 를 의미한다. 진짜 .ai 파일(AI 고유 리소스/레이어 구조 포함)을
생성하는 기능이 아니며, 이 모듈은 그렇게 주장하지 않는다.

v1.6부터 PRODUCTION_PDF / CUTLINE_PDF / SVG 3개가 실제로 동작한다.
AI_COMPATIBLE_PDF 는 CUTLINE_PDF와 동일 경로(표준 PDF)를 재사용할 수 있지만,
아직 별도 검증/테스트를 거치지 않아 미구현으로 남겨둔다.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class OutputFormat(str, Enum):
    PRODUCTION_PDF = "PRODUCTION_PDF"    # 구현됨 (pdf/builder.py)
    CUTLINE_PDF = "CUTLINE_PDF"          # v1.6부터 구현됨 (pdf/cutline_export.py)
    SVG = "SVG"                          # v1.6부터 구현됨 (pdf/cutline_export.py)
    AI_COMPATIBLE_PDF = "AI_COMPATIBLE_PDF"  # 미구현 - Illustrator에서 편집 가능한 표준 PDF (.ai 고유 포맷 아님)


IMPLEMENTED_FORMATS = {OutputFormat.PRODUCTION_PDF, OutputFormat.CUTLINE_PDF, OutputFormat.SVG}


class ExportFormatNotImplementedError(NotImplementedError):
    def __init__(self, fmt: OutputFormat):
        super().__init__(
            f"출력 포맷 '{fmt.value}' 는 아직 구현되지 않았습니다. "
            f"현재 구현된 포맷: {[f.value for f in IMPLEMENTED_FORMATS]}"
        )


def export(
    fmt: OutputFormat,
    *,
    image_path: Optional[str] = None,
    dest_path: str,
    **kwargs,
) -> str:
    """
    포맷별 내보내기 진입점 (라우팅).
    - PRODUCTION_PDF: pdf.builder.build_production_pdf() 로 위임 (image_path 필요)
    - CUTLINE_PDF: pdf.cutline_export.cutline_pdf_from_points() 로 위임
      (points_mm, width_mm, height_mm 필요, holes_mm/stroke_* 는 선택)
    - SVG: pdf.cutline_export.svg_from_points() 로 위임 (동일 kwargs)
    - AI_COMPATIBLE_PDF: 아직 미구현
    """
    if fmt == OutputFormat.PRODUCTION_PDF:
        from .builder import build_production_pdf

        if image_path is None:
            raise ValueError("PRODUCTION_PDF 내보내기에는 image_path 가 필요합니다.")
        result = build_production_pdf(image_path=image_path, dest_path=dest_path, **kwargs)
        return result.output_path

    if fmt == OutputFormat.CUTLINE_PDF:
        from .cutline_export import cutline_pdf_from_points

        _require_points_kwargs(kwargs)
        return cutline_pdf_from_points(dest_path=dest_path, **kwargs)

    if fmt == OutputFormat.SVG:
        from .cutline_export import svg_from_points

        _require_points_kwargs(kwargs)
        return svg_from_points(dest_path=dest_path, **kwargs)

    if fmt == OutputFormat.AI_COMPATIBLE_PDF:
        raise ExportFormatNotImplementedError(fmt)

    raise ValueError(f"알 수 없는 포맷: {fmt}")


def _require_points_kwargs(kwargs: dict) -> None:
    for key in ("points_mm", "width_mm", "height_mm"):
        if key not in kwargs:
            raise ValueError(f"CUTLINE_PDF/SVG 내보내기에는 '{key}' 가 필요합니다.")
