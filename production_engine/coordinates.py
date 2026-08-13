"""
coordinates.py
------------------
v1.4 - WYSIWYG 좌표계 계약 (작업지시서 F).

**문제 재현**: 600x1800mm 디자인을 PDF로 만들면 디자인이 상단 일부에 몰리는 현상이
보고되었다. 이는 전형적으로 다음 두 가지 원인 중 하나(또는 둘 다) 때문에 발생한다.

  1) 좌표계 원점/방향 불일치: 에디터 캔버스는 보통 좌상단 원점, y축 아래로 증가(top-down).
     반면 PDF(및 reportlab)는 좌하단 원점, y축 위로 증가(bottom-up)다. 이 y축 반전을
     빠뜨리거나 잘못 적용하면 객체들이 실제 배치와 상하로 뒤집히거나, 변환식에 버그가
     있으면 "위쪽에 몰리는" 것처럼 보이는 왜곡이 생긴다.
  2) Bleed 오프셋 누락/이중 적용: MediaBox 는 (trim+bleed) 크기인데, 객체 좌표를
     trim 기준으로만 계산하고 bleed 오프셋을 더하지 않거나, 반대로 이미 bleed가 반영된
     좌표에 다시 bleed를 더하면 객체가 원래 위치에서 벗어난다.

이 모듈은 아래 4단계 변환 계약을 명시적인 함수로 구현하고, 각 단계가 독립적으로
테스트 가능하도록 분리한다.

    Editor Canvas px  --(1)-->  Normalized (0~1)  --(2)-->  Product mm (Trim 기준)  --(3)-->  PDF point

핵심 불변식(invariant, tests/test_coordinates.py 에서 검증):
  - (1)(2) 단계는 bleed 를 전혀 몰라도 된다 (bleed 파라미터를 받지 않는다).
    즉 bleed 값이 얼마든 "Trim 기준 mm 좌표"는 절대 변하지 않는다.
  - bleed 오프셋은 오직 (3) 단계, mm -> PDF point 변환에서만 한 번 적용된다.
  - y축 반전(top-down -> bottom-up)과 회전각 부호 반전(시계방향 화면 회전을
    PDF 좌표계에서 동일하게 보이도록)은 반드시 (3) 단계에서 함께 처리된다.

**에디터 쪽 계약 (프론트엔드가 지켜야 하는 것 - 이번 작업에서 프론트엔드 코드는
수정하지 않았으므로, 아래는 GPT/프론트엔드팀에 전달할 "인터페이스 계약"이다)**:
  - 모든 객체는 origin(기준점)을 '중심(center)'으로 사용해야 한다 (fabric.js 기준
    `originX: 'center', originY: 'center'`). 좌상단 origin을 쓰면 회전 시 중심이
    아니라 좌상단을 기준으로 회전하게 되어, 회전된 객체의 위치 계산이 어긋난다.
  - 캔버스 픽셀 종횡비는 반드시 Trim mm 종횡비와 정확히 같아야 한다
    (canvas_px_width/canvas_px_height == trim_width_mm/trim_height_mm).
    다르면 x/y 스케일이 달라져 회전이 더 이상 "순수 회전"이 아니게 되고,
    본 모듈은 이 불일치를 감지하면 명시적으로 예외를 발생시킨다.
"""

from __future__ import annotations

from dataclasses import dataclass

MM_PER_INCH = 25.4
PT_PER_MM = 72.0 / MM_PER_INCH

# 캔버스 px 종횡비와 trim mm 종횡비의 허용 오차 (초과 시 CoordinateContractError)
_ASPECT_TOLERANCE = 0.01  # 1%


class CoordinateContractError(Exception):
    pass


@dataclass
class ObjectTransformPx:
    """
    에디터 캔버스에서의 객체 상태. origin은 반드시 '중심'이어야 한다
    (center_x_px, center_y_px 는 객체의 중심점 좌표).
    width_px/height_px 는 스케일 적용 전 원본 크기, scale_x/scale_y 는 배율.
    rotation_deg 는 화면 기준 시계방향(clockwise) 각도.
    """

    center_x_px: float
    center_y_px: float
    width_px: float
    height_px: float
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation_deg: float = 0.0


@dataclass
class ObjectTransformMm:
    """Trim 좌상단을 원점(0,0)으로 하는 mm 좌표. bleed 와 무관하다 (bleed 파라미터 없음)."""

    center_x_mm: float
    center_y_mm: float
    width_mm: float
    height_mm: float
    rotation_deg: float  # 화면 기준 시계방향, 아직 PDF 좌표계로 반전되지 않은 상태


@dataclass
class ObjectTransformPdfPt:
    """PDF point 좌표 (좌하단 원점, y축 위로 증가). reportlab/pikepdf 에 바로 사용 가능."""

    center_x_pt: float
    center_y_pt: float
    width_pt: float
    height_pt: float
    rotation_deg: float  # PDF 좌표계 기준 각도 (부호 반전 적용됨)


@dataclass
class TrimCanvas:
    """
    (1)(2) 단계 전용 - bleed 를 모른다. 에디터 캔버스 px 크기와 Trim mm 크기만 안다.
    """

    canvas_px_width: float
    canvas_px_height: float
    trim_width_mm: float
    trim_height_mm: float

    def __post_init__(self):
        if self.canvas_px_width <= 0 or self.canvas_px_height <= 0:
            raise CoordinateContractError("캔버스 픽셀 크기는 0보다 커야 합니다.")
        if self.trim_width_mm <= 0 or self.trim_height_mm <= 0:
            raise CoordinateContractError("Trim mm 크기는 0보다 커야 합니다.")

        canvas_ratio = self.canvas_px_width / self.canvas_px_height
        trim_ratio = self.trim_width_mm / self.trim_height_mm
        diff = abs(canvas_ratio - trim_ratio) / trim_ratio
        if diff > _ASPECT_TOLERANCE:
            raise CoordinateContractError(
                f"캔버스 픽셀 종횡비({canvas_ratio:.4f})와 Trim mm 종횡비({trim_ratio:.4f})가 "
                f"{diff*100:.1f}% 어긋납니다. 이 상태에서 좌표 변환을 하면 도형이 비대칭으로 "
                f"늘어나고 회전각이 깨집니다. 캔버스를 Trim 비율에 맞춰 다시 생성하세요."
            )

    @property
    def mm_per_px_x(self) -> float:
        return self.trim_width_mm / self.canvas_px_width

    @property
    def mm_per_px_y(self) -> float:
        return self.trim_height_mm / self.canvas_px_height


def px_to_mm(obj: ObjectTransformPx, canvas: TrimCanvas) -> ObjectTransformMm:
    """(1)+(2) 통합: 에디터 px -> Trim mm. bleed 를 전혀 사용하지 않는다 (핵심 불변식)."""
    sx = canvas.mm_per_px_x
    sy = canvas.mm_per_px_y
    return ObjectTransformMm(
        center_x_mm=obj.center_x_px * sx,
        center_y_mm=obj.center_y_px * sy,
        width_mm=obj.width_px * obj.scale_x * sx,
        height_mm=obj.height_px * obj.scale_y * sy,
        rotation_deg=obj.rotation_deg,
    )


def mm_to_pdf_point(
    obj: ObjectTransformMm, trim_width_mm: float, trim_height_mm: float, bleed_mm: float
) -> ObjectTransformPdfPt:
    """
    (3) 단계: Trim mm -> PDF point. 여기서만 bleed 오프셋과 y축 반전을 적용한다.

    - x: 왼쪽에서 오른쪽으로 증가하는 방향은 에디터/PDF 동일 -> 그대로 bleed_mm 만 더한다.
    - y: 에디터는 위에서 아래로 증가(top-down), PDF는 아래에서 위로 증가(bottom-up)이므로
         반드시 반전해야 한다. Trim 영역은 PDF 좌표계에서 y = bleed_mm ~ (bleed_mm+trim_height_mm)
         구간을 차지한다. 에디터 y좌표(top 기준, 아래로 증가) center_y_mm 을
         "Trim 상단으로부터의 거리"로 보고, PDF의 "Trim 상단" 위치(= bleed_mm + trim_height_mm)에서
         빼주면 된다.
    - rotation: 화면(y축 아래로 증가)에서의 시계방향 회전은, y축을 반전한 PDF 좌표계에서는
      반시계방향으로 보이므로 부호를 반전해야 시각적으로 동일한 회전이 유지된다.
    """
    if bleed_mm < 0:
        raise CoordinateContractError("bleed_mm 은 0 이상이어야 합니다.")

    x_pt = (bleed_mm + obj.center_x_mm) * PT_PER_MM
    y_pt = (bleed_mm + trim_height_mm - obj.center_y_mm) * PT_PER_MM

    return ObjectTransformPdfPt(
        center_x_pt=x_pt,
        center_y_pt=y_pt,
        width_pt=obj.width_mm * PT_PER_MM,
        height_pt=obj.height_mm * PT_PER_MM,
        rotation_deg=-obj.rotation_deg,
    )


def px_to_pdf_point(
    obj: ObjectTransformPx, canvas: TrimCanvas, bleed_mm: float
) -> ObjectTransformPdfPt:
    """편의 함수: (1)->(2)->(3) 전체를 한 번에 수행."""
    mm = px_to_mm(obj, canvas)
    return mm_to_pdf_point(mm, canvas.trim_width_mm, canvas.trim_height_mm, bleed_mm)


def pdf_point_bbox_corners(obj: ObjectTransformPdfPt) -> tuple[float, float, float, float]:
    """
    회전을 무시한(axis-aligned) 근사 바운딩박스 (x0,y0,x1,y1) - 디버깅/검증용.
    실제 렌더링에서는 rotation_deg 만큼 center 기준 회전이 필요하다 (reportlab
    canvas.translate + canvas.rotate 조합으로 구현 - GPT 통합 시 이 값들을 그대로 사용).
    """
    x0 = obj.center_x_pt - obj.width_pt / 2
    y0 = obj.center_y_pt - obj.height_pt / 2
    x1 = obj.center_x_pt + obj.width_pt / 2
    y1 = obj.center_y_pt + obj.height_pt / 2
    return (x0, y0, x1, y1)


# ---- v1.4b: fabric.js 원본 객체(origin이 center가 아닐 수 있음) 정규화 ----
# 관성적으로 originX/originY 는 'left'/'top' 이 fabric.js 기본값이다. left/top 은
# "그 origin 점의 좌표"를 의미하므로, center 좌표로 정확히 변환하려면 origin 위치를
# 알아야 한다. 이 함수는 그 변환을 명시적으로 처리한다.
_ORIGIN_X_OFFSET_FACTOR = {"left": 0.5, "center": 0.0, "right": -0.5}
_ORIGIN_Y_OFFSET_FACTOR = {"top": 0.5, "center": 0.0, "bottom": -0.5}


def fabric_object_to_transform(fabric_obj: dict) -> ObjectTransformPx:
    """
    fabric.js 캔버스 객체(JSON, 예: canvas.toJSON() 의 objects[i])를 이 모듈의
    center-origin 계약(ObjectTransformPx)으로 정규화한다.

    fabric.js 객체 필드:
      left, top    : origin 기준점의 캔버스 좌표 (origin이 'left'/'top' 이면 좌상단 좌표)
      width, height: 스케일 적용 전 크기
      scaleX, scaleY, angle (시계방향 도) : 그대로 사용
      originX, originY : 'left'|'center'|'right' / 'top'|'center'|'bottom' (기본 'left'/'top')

    **중요한 제약**: origin이 'center'가 아니면서 rotation(angle)이 0이 아닌 객체는
    "origin 기준으로 회전"이라는 fabric.js의 실제 동작과, 이 모듈이 가정하는
    "center 기준 회전"이 서로 다른 시각적 결과를 만든다. 이 경우 근사 변환으로 조용히
    넘어가지 않고 CoordinateContractError 를 던진다 - 에디터가 originX/originY:'center'
    를 쓰도록 강제하기 위함이다 (본 모듈 상단 계약 참고).
    """
    origin_x = fabric_obj.get("originX", "left")
    origin_y = fabric_obj.get("originY", "top")
    scale_x = fabric_obj.get("scaleX", 1.0)
    scale_y = fabric_obj.get("scaleY", 1.0)
    width = fabric_obj["width"]
    height = fabric_obj["height"]
    rotation = fabric_obj.get("angle", 0.0)

    if origin_x not in _ORIGIN_X_OFFSET_FACTOR:
        raise CoordinateContractError(f"알 수 없는 originX 값: {origin_x!r}")
    if origin_y not in _ORIGIN_Y_OFFSET_FACTOR:
        raise CoordinateContractError(f"알 수 없는 originY 값: {origin_y!r}")

    is_center_origin = origin_x == "center" and origin_y == "center"
    if not is_center_origin and abs(rotation) > 1e-6:
        raise CoordinateContractError(
            f"객체의 origin이 center가 아닌 상태({origin_x}/{origin_y})에서 회전"
            f"({rotation}deg)이 적용되어 있습니다. fabric.js는 origin 기준으로 회전하므로 "
            f"이 상태에서는 center 기준 좌표로 정확히 변환할 수 없습니다. 에디터에서 "
            f"객체 생성 시 originX/originY 를 'center' 로 설정하세요 (본 모듈 상단 "
            f"'에디터 쪽 계약' 참고)."
        )

    # 회전이 없으면 origin 위치와 무관하게 center 좌표를 안전하게 계산할 수 있다.
    dx = _ORIGIN_X_OFFSET_FACTOR[origin_x] * width * scale_x
    dy = _ORIGIN_Y_OFFSET_FACTOR[origin_y] * height * scale_y
    center_x = fabric_obj["left"] + dx
    center_y = fabric_obj["top"] + dy

    return ObjectTransformPx(
        center_x_px=center_x,
        center_y_px=center_y,
        width_px=width,
        height_px=height,
        scale_x=scale_x,
        scale_y=scale_y,
        rotation_deg=rotation,
    )
