"""
pdf/cutline_export.py
------------------------
v1.6: 실제 칼선(Cut Contour) SVG / PDF 출력 구현 (작업지시서 7번).

vision.contour_engine.ProductionCutline 이 만들어낸 mm 좌표 폴리곤을 받아
실제 SVG 벡터 파일과 칼선 전용 PDF를 생성한다. v1.4/v1.5 에서는 이 두 포맷이
미구현(NotImplementedError)이었지만, 아크릴 칼선 데이터가 실제로 생성되는 v1.6부터는
최소 구현을 제공한다.

**정직한 한계**:
- CUTLINE_PDF 는 칼선을 별도 색상(기본: 마젠타 100%, 인쇄업계 관행상 "CutContour"
  스팟컬러로 흔히 쓰이는 색)의 벡터 선으로 그린다. 다만 진짜 PDF Spot Color(별색
  분판, `/Separation` 컬러스페이스)까지는 구현하지 않았다 - 지금은 CMYK 근사색으로
  표시만 한다. 실제 인쇄소가 진짜 스팟컬러 분판을 요구하면 pikepdf로 `/Separation`
  컬러스페이스를 추가하는 작업이 추가로 필요하다 (README/보고서에 한계로 명시).
- AI_COMPATIBLE_PDF 는 CUTLINE_PDF/PRODUCTION_PDF 와 동일한 표준 PDF 생성 경로를
  쓴다 - Illustrator 고유 .ai 바이너리 포맷이 아니다.
"""

from __future__ import annotations

import os

from reportlab.lib.units import mm as MM_UNIT
from reportlab.pdfgen import canvas

PT_PER_MM = 72.0 / 25.4


def svg_from_points(
    points_mm: list[tuple[float, float]],
    dest_path: str,
    width_mm: float,
    height_mm: float,
    holes_mm: list[list[tuple[float, float]]] | None = None,
    stroke_color: str = "#FF00FF",
    stroke_width_mm: float = 0.1,
) -> str:
    """폴리곤(mm 좌표)을 SVG 파일로 저장한다. 좌표계는 mm 그대로(viewBox 를 mm 단위로 지정)."""
    if len(points_mm) < 3:
        raise ValueError("SVG로 내보내려면 점이 3개 이상 필요합니다.")

    def _path_d(pts: list[tuple[float, float]]) -> str:
        d = f"M {pts[0][0]:.3f},{pts[0][1]:.3f} "
        d += " ".join(f"L {x:.3f},{y:.3f}" for x, y in pts[1:])
        d += " Z"
        return d

    paths = [f'<path d="{_path_d(points_mm)}" fill="none" stroke="{stroke_color}" stroke-width="{stroke_width_mm}" />']
    for hole in holes_mm or []:
        if len(hole) >= 3:
            paths.append(f'<path d="{_path_d(hole)}" fill="none" stroke="{stroke_color}" stroke-width="{stroke_width_mm}" />')

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width_mm}mm" height="{height_mm}mm" '
        f'viewBox="0 0 {width_mm} {height_mm}">\n'
        + "\n".join(paths) + "\n</svg>\n"
    )

    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(svg)
    return dest_path


def cutline_pdf_from_points(
    points_mm: list[tuple[float, float]],
    dest_path: str,
    width_mm: float,
    height_mm: float,
    holes_mm: list[list[tuple[float, float]]] | None = None,
    stroke_color_cmyk: tuple[float, float, float, float] = (0, 1, 0, 0),  # 마젠타 100% - CutContour 관행색
    stroke_width_mm: float = 0.1,
) -> str:
    """폴리곤(mm 좌표)을 벡터 선(Path)으로 그린 PDF를 생성한다 (레이어/색상 근사 - 상단 docstring 한계 참고)."""
    if len(points_mm) < 3:
        raise ValueError("PDF로 내보내려면 점이 3개 이상 필요합니다.")

    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    c = canvas.Canvas(dest_path, pagesize=(width_mm * PT_PER_MM, height_mm * PT_PER_MM))
    c.setStrokeColorCMYK(*stroke_color_cmyk)
    c.setLineWidth(stroke_width_mm * PT_PER_MM)

    def _draw_polygon(pts: list[tuple[float, float]]):
        path = c.beginPath()
        # PDF는 y축이 위로 증가하므로 mm 좌표(위->아래)를 뒤집는다.
        x0, y0 = pts[0]
        path.moveTo(x0 * PT_PER_MM, (height_mm - y0) * PT_PER_MM)
        for x, y in pts[1:]:
            path.lineTo(x * PT_PER_MM, (height_mm - y) * PT_PER_MM)
        path.close()
        c.drawPath(path, stroke=1, fill=0)

    _draw_polygon(points_mm)
    for hole in holes_mm or []:
        if len(hole) >= 3:
            _draw_polygon(hole)

    c.showPage()
    c.save()
    return dest_path
