"""
models.py
---------
DONGLE Studio Production Engine - 핵심 도메인 모델

v1.3 변경사항 (Claude):
- ProductProfile 확장: width_mm/height_mm/custom_size_allowed/finishing/eyelet 추가
  (기존 min/max_width_mm, dpi_warning_below/error_below, icc_profile_name,
   color_mode_target 필드는 app.py 등 기존 호출부가 이미 참조하고 있으므로
   이름을 그대로 유지하고, GPT 작업지시서에 명시된 필드명(recommended_dpi,
   minimum_dpi, color_mode, icc_profile)은 읽기 전용 별칭 프로퍼티로 추가했다.
   -> 기존 코드/테스트를 깨뜨리지 않으면서 요청된 스펙 필드명도 모두 만족한다.)
- EyeletPlacementPolicy / EyeletSpec / EyeletPoint 추가 (아일렛 엔진 도메인 모델)
- PreflightIssue 확장: title / recommendation / auto_fixable 필드 추가
  (기존 code/level/message/detail 은 app.py가 이미 사용 중이므로 그대로 유지)
- PipelineStage 추가: RGB->CMYK 정책을 "편집 단계(EDIT)"와 "최종 제작 단계(FINAL)"로
  분리 판단하기 위한 구분자
- JobTicket 추가: 주문 관리용 구조
- ProductionManifest 관련 모델은 preflight 결과/파일 경로 등 실행 시점 데이터가 많아
  manifest.py 에서 dict 형태로 조립한다 (여기서는 JobTicket까지만 도메인 모델로 정의).

설계 원칙 (변경 없음):
- 상품별 규격은 코드에 if-else로 하드코딩하지 않는다. ProductProfile 은 DB row / JSON
  하나를 그대로 매핑할 수 있는 구조로 유지한다.
- Job 은 "고객 1건의 작업"을 나타내며, 저장공간 격리의 기준 단위가 된다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import ClassVar, Optional


class FitPolicy(str, Enum):
    """원본 이미지 비율과 제작 비율이 다를 때 처리 정책."""

    CONTAIN = "contain"   # 전체 이미지가 보이도록 축소, 남는 영역은 배경색/여백 처리
    COVER = "cover"       # 제작 영역을 꽉 채우도록 확대, 넘치는 부분은 잘림
    CROP_MANUAL = "crop_manual"  # 사용자가 직접 크롭 좌표를 지정


class EyeletPlacementPolicy(str, Enum):
    """아일렛(그로밋) 배치 정책."""

    NONE = "NONE"
    FOUR_CORNERS = "FOUR_CORNERS"
    TOP_BOTTOM = "TOP_BOTTOM"
    LEFT_RIGHT = "LEFT_RIGHT"
    ALL_EDGES = "ALL_EDGES"
    CUSTOM_INTERVAL = "CUSTOM_INTERVAL"


class Capability(str, Enum):
    """
    v1.4: 20개 상품으로 확장하면서 도입한 '제작 능력' 구분자.

    두 가지 용도로 쓰인다 (taxonomy.ROUTING_CAPABILITIES 로 구분):
    1) **라우팅 capability** (아래 7개) — pipeline_router.py 가 이걸 보고 어떤 파이프라인을
       실행할지 결정한다. IMPLEMENTED_CAPABILITIES 에 없으면 CapabilityNotImplementedError.
         RECTANGULAR_PRINT, CUTLINE_PRINT, WHITE_INK_PRINT, DOUBLE_SIDE_PRINT,
         LARGE_FORMAT_PRINT, NO_PRINT_CUTTING, EYELET_FINISHING
    2) **속성 태그(descriptive tag)** (아래 9개, v1.4b 추가) — 라우팅에 관여하지 않고
       상품의 특성을 기술하는 용도. Preflight/Router 는 이 값들을 "구현 여부 확인 대상"으로
       취급하지 않는다 (항상 무시하고 통과시킴 - 정보 표시 목적).
         CMYK_OUTPUT, FIXED_SIZE, CUSTOM_SIZE, TRANSPARENT_MATERIAL, VECTOR_CUT_PATH,
         NO_PRINT, EYELET, WHITE_INK, ROUND_PRODUCT
    """

    # ---- 라우팅 capability (파이프라인 실행 여부를 좌우함) ----
    RECTANGULAR_PRINT = "RECTANGULAR_PRINT"
    CUTLINE_PRINT = "CUTLINE_PRINT"
    WHITE_INK_PRINT = "WHITE_INK_PRINT"
    DOUBLE_SIDE_PRINT = "DOUBLE_SIDE_PRINT"
    LARGE_FORMAT_PRINT = "LARGE_FORMAT_PRINT"
    NO_PRINT_CUTTING = "NO_PRINT_CUTTING"
    EYELET_FINISHING = "EYELET_FINISHING"

    # ---- 속성 태그 (정보 표시용, 라우팅에 관여하지 않음) ----
    CMYK_OUTPUT = "CMYK_OUTPUT"
    FIXED_SIZE = "FIXED_SIZE"
    CUSTOM_SIZE = "CUSTOM_SIZE"
    TRANSPARENT_MATERIAL = "TRANSPARENT_MATERIAL"
    VECTOR_CUT_PATH = "VECTOR_CUT_PATH"
    NO_PRINT = "NO_PRINT"
    EYELET = "EYELET"
    WHITE_INK = "WHITE_INK"
    ROUND_PRODUCT = "ROUND_PRODUCT"


class PreflightLevel(str, Enum):
    """
    v1.5: 검사 결과 3단계.

    - PASS           : 문제 없음.
    - WARNING         : 품질/완성도 문제이지만 Production PDF 생성 자체는 가능하다.
                        (예: RGB 원본, 권장 DPI 미달, 비율 불일치, 안전영역 침범,
                        아일렛 충돌 등 - 전부 "만들 수는 있지만 확인이 필요한" 문제)
    - ERROR(=BLOCKING_ERROR) : 실제 제작파일 생성 자체가 불가능한 경우에만 사용한다.
                        (예: 파일 손상, 크롭 좌표가 원본 범위를 벗어남, 캔버스/제품
                        비율이 근본적으로 맞지 않아 좌표 변환이 실패함, 미구현 capability)

    **중요**: Python 심볼 이름은 하위 호환을 위해 그대로 `ERROR` 를 쓰지만, 실제
    직렬화되는 문자열 값은 v1.5부터 "BLOCKING_ERROR" 이다 (PreflightIssue.severity,
    PreflightReport.overall.value 등에서 이 값이 그대로 노출된다). 기존 코드가
    `PreflightLevel.ERROR` 로 비교하는 부분은 전부 그대로 동작한다 - 심볼은 안 바뀌고
    값(직렬화 문자열)만 바뀌었다.
    """

    PASS = "PASS"
    WARNING = "WARNING"
    ERROR = "BLOCKING_ERROR"


class ProductionStatus(str, Enum):
    """
    v1.4b: 상품 1건이 '실제 주문 제작'에 얼마나 준비되었는지 나타내는 상태.

    - VERIFIED       : 실제 제작가이드(URL)를 조사해 모든 필수 수치가 확인되고 검증됨.
                        **엔진/코드가 이 상태를 자동으로 부여하지 않는다.** source.verified=True
                        이고 모든 필수 필드가 채워진 경우에만 validate_production_status() 를
                        통과하며, 그렇지 않으면 로드 시점에 명확히 예외가 발생한다.
    - PARTIAL        : 일부 필수 수치는 확인됐지만 전부는 아님.
    - GUIDE_REQUIRED : 제작가이드 조사가 아직 이뤄지지 않음 (기본값 - 현재 20개 상품 대부분 이 상태).
    - EXPERIMENTAL   : 수치는 있지만 아직 실제 주문에 써본 적 없는 잠정 값 (내부 테스트용).
    """

    VERIFIED = "VERIFIED"
    PARTIAL = "PARTIAL"
    GUIDE_REQUIRED = "GUIDE_REQUIRED"
    EXPERIMENTAL = "EXPERIMENTAL"


@dataclass
class SourceInfo:
    """
    제작규칙 데이터의 출처. "이 수치를 어디서, 언제, 누가 확인했는지"를 항상 추적할 수 있게 한다.
    """

    provider: Optional[str] = None      # 예: "adpiamall", "swadpia"
    url: Optional[str] = None
    verified: bool = False
    verified_at: Optional[str] = None   # ISO 8601 문자열
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "url": self.url,
            "verified": self.verified,
            "verified_at": self.verified_at,
            "notes": self.notes,
        }


class PipelineStage(str, Enum):
    """
    같은 이슈(예: RGB 색상 모드)라도 파이프라인 단계에 따라 심각도가 달라야 한다.
    - EDIT: 고객/운영자가 이미지를 편집 중인 단계. RGB 원본은 정상이며, 최종 출력 시
            CMYK로 자동 변환됨을 안내(INFO/WARNING)하는 수준이어야 한다.
    - FINAL: 실제 Production PDF를 만드는 단계. 이 시점에는 반드시 CMYK 변환이
             완료되어 있어야 하며, 안 되어 있으면 ERROR다.
    """

    EDIT = "edit"
    FINAL = "final"


class EyeletPlacementPolicy(str, Enum):
    """아일렛(그로밋) 배치 정책."""

    NONE = "NONE"
    FOUR_CORNERS = "FOUR_CORNERS"
    TOP_BOTTOM = "TOP_BOTTOM"
    LEFT_RIGHT = "LEFT_RIGHT"
    ALL_EDGES = "ALL_EDGES"
    CUSTOM_INTERVAL = "CUSTOM_INTERVAL"


@dataclass
class EyeletSpec:
    """
    상품 프로필에 종속되는 아일렛 후가공 규격.
    실제 좌표 계산은 finishing/eyelet_engine.py 가 담당하고, 여기서는 규격만 정의한다.
    """

    enabled: bool = False
    diameter_mm: float = 8.0      # 아일렛 지름
    margin_mm: float = 20.0       # 재단선에서 아일렛 "중심"까지의 거리
    interval_mm: float = 500.0    # 아일렛 간 간격 (TOP_BOTTOM/LEFT_RIGHT/ALL_EDGES/CUSTOM_INTERVAL 에서 사용)
    placement_policy: EyeletPlacementPolicy = EyeletPlacementPolicy.NONE


@dataclass
class EyeletPoint:
    """계산된 아일렛 1개의 실제 mm 좌표 (출력 캔버스 좌상단 원점 기준)."""

    x_mm: float
    y_mm: float
    edge: str  # "corner" | "top" | "bottom" | "left" | "right"


@dataclass
class SafeZoneSpec:
    """
    작업영역 / 재단영역 / 안전영역 정의.
    단위는 전부 mm. 상품마다 다르므로 ProductProfile 에 종속시킨다.

    - bleed_mm: 재단선 바깥으로 여유를 두는 도련 폭 (사방 동일 가정, 필요시 확장)
    - safe_margin_mm: 재단선 안쪽으로 텍스트/로고 등 중요 요소를 배치하면 안 되는 폭
    """

    bleed_mm: float
    safe_margin_mm: float
    # 현수막 그로밋(아일렛) 등, 특정 변에 추가 안전영역이 필요한 경우를 위한 확장 지점.
    # 예: {"top": 40, "bottom": 40, "left": 20, "right": 20}
    extra_margin_by_edge_mm: dict = field(default_factory=dict)


@dataclass
class ProductProfile:
    """
    상품 1종의 제작 규격을 담는 프로필.
    DB 테이블 product_profiles 의 1 row 에 대응하도록 설계.

    필드 설계 메모 (v1.3):
    - width_mm / height_mm : 상품의 "기본/주문" 사이즈. custom_size_allowed=False 인
      상품(예: 고정 규격 실내 배너)은 이 값이 곧 유일하게 허용되는 사이즈다.
    - custom_size_allowed=True 인 상품(예: 현수막)은 min/max_width_mm, min/max_height_mm
      범위 내에서 자유 사이즈를 허용한다. width_mm/height_mm 은 이 경우 "기본값"(에디터
      초기 캔버스 크기)으로 쓰인다.
    - 기존 필드명(dpi_warning_below, dpi_error_below, icc_profile_name, color_mode_target)은
      app.py 등 기존 코드가 이미 참조하고 있어 이름을 바꾸지 않았다. 대신 작업지시서에
      명시된 이름(recommended_dpi, minimum_dpi, icc_profile, color_mode)은 아래 프로퍼티로
      제공한다.
    """

    product_id: str                 # 예: "banner_indoor", "hyeonsumak_outdoor"
    product_name: str               # 화면 표시용 이름
    category: str                   # "banner" | "hyeonsumak" | ... (차기 상품 대비)

    width_mm: float                 # 기본/고정 주문 사이즈 (가로)
    height_mm: float                # 기본/고정 주문 사이즈 (세로)

    # 사이즈 제약 (mm). custom_size_allowed=True 일 때만 의미를 가진다.
    min_width_mm: float
    max_width_mm: float
    min_height_mm: float
    max_height_mm: float

    safe_zone: SafeZoneSpec

    # Effective DPI 판정 임계값. 상품 성격(근접용/원거리용)에 따라 다름.
    dpi_warning_below: float        # 이 값 미만이면 WARNING (= "권장 DPI")
    dpi_error_below: float          # 이 값 미만이면 ERROR (= "최소 DPI", 인쇄 품질 심각)

    custom_size_allowed: bool = True
    default_fit_policy: FitPolicy = FitPolicy.CONTAIN

    color_mode_target: str = "CMYK"
    icc_profile_name: Optional[str] = None   # 예: "JapanColor2001Coated" 등, 인쇄소 협의 후 지정
    pdf_standard: str = "PDF/X-1a"            # 추후 PDF/X-4 등으로 확장 가능하도록 문자열로 관리

    finishing: list[str] = field(default_factory=list)   # 예: ["eyelet"], ["hemming"]
    eyelet: EyeletSpec = field(default_factory=EyeletSpec)
    # v1.4: capability 목록을 명시적으로 저장 (ProductProfileStub.to_product_profile() 이
    # 채워준다). 비어있으면 pipeline_router.py 가 기존 방식대로(finishing/eyelet 필드로부터)
    # 추론한다 - v1.3부터 있던 banner_indoor/hyeonsumak_outdoor 와의 하위 호환을 위함.
    capabilities: list[str] = field(default_factory=list)

    # v1.4b 추가 (전부 기본값 있음 - 기존 seed.json/호출부와 하위 호환):
    related_products: list[str] = field(default_factory=list)
    production_status: ProductionStatus = ProductionStatus.GUIDE_REQUIRED
    source: SourceInfo = field(default_factory=SourceInfo)
    # is_dev_default=True 인 프로필은 "실제 검증된 제작규격이 아니라, 개발/테스트 파이프라인이
    # 동작하도록 하기 위한 잠정 기본값"임을 명시한다 (작업지시서 v1.4b #12).
    # banner_indoor/hyeonsumak_outdoor 가 여기 해당 - v1.2 단계 추정치일 뿐 실제 상품
    # 페이지에서 검증된 값이 아니다. GPT/운영팀이 실제 값으로 교체하기 전까지는
    # "실제 고객 주문에 이 수치를 그대로 쓰면 안 된다"는 경고로 취급해야 한다.
    is_dev_default: bool = False

    # v1.6: 아크릴 상품 제작 파라미터 (Product Profile 로부터 공급 - 코드 하드코딩 금지).
    # 전부 None 이면 "이 상품은 아직 아크릴 제작 알고리즘에 투입할 수 없음"을 뜻한다.
    cutline_offset_mm: Optional[float] = None
    minimum_cut_radius_mm: Optional[float] = None
    hole_diameter_mm: Optional[float] = None
    hole_edge_margin_mm: Optional[float] = None
    material_thickness_mm: Optional[float] = None
    stand_tab_width_mm: Optional[float] = None
    stand_tab_height_mm: Optional[float] = None
    stand_slot_width_mm: Optional[float] = None
    stand_slot_clearance_mm: Optional[float] = None
    white_choke_mm: Optional[float] = None
    white_spread_mm: Optional[float] = None

    # v1.8: 자유 제작 사이즈 프리셋 (섹션 1). 코드에 하드코딩하지 않고 Product Profile
    # 데이터로 관리한다. 각 항목은 {"label": str, "width_mm": float, "height_mm": float}.
    size_presets: list = field(default_factory=list)

    # v1.9: 실제 제작사 가이드 반영 (PM GPT 확보 자료). 소재/인쇄방식/거치대 옵션 여부.
    material: Optional[str] = None                    # 예: "PET 210μ", "현수막 150denier"
    print_method: Optional[str] = None                  # 예: "수성잉크 4색"
    stand_option_available: Optional[bool] = None         # 거치대(Stand) 옵션 존재 여부
    # 어떤 필드가 실제 제작사 자료로 "검증(VERIFIED)"되었는지 필드명 목록으로 추적한다.
    # (필드 단위 provenance - 과하게 복잡한 구조 대신 이름 목록만 유지)
    verified_fields: list = field(default_factory=list)

    # v1.9.2: size validation policy.
    # RECTANGULAR_AXES: width/height each use min/max fields as-is.
    # ROLL_ORIENTATION_FREE: either landscape or portrait is allowed;
    # the shorter side is the roll-width axis and the longer side is the length axis.
    size_constraint_mode: str = "RECTANGULAR_AXES"

    # ---- 작업지시서 명시 필드명과의 호환을 위한 읽기 전용 별칭 ----
    @property
    def recommended_dpi(self) -> float:
        return self.dpi_warning_below

    @property
    def minimum_dpi(self) -> float:
        return self.dpi_error_below

    @property
    def color_mode(self) -> str:
        return self.color_mode_target

    @property
    def icc_profile(self) -> Optional[str]:
        return self.icc_profile_name

    def size_in_range(self, width_mm: float, height_mm: float) -> bool:
        if not self.custom_size_allowed:
            # 고정 규격 상품: 정확히 일치해야 한다 (부동소수점 오차 허용 0.01mm)
            return abs(width_mm - self.width_mm) < 0.01 and abs(height_mm - self.height_mm) < 0.01

        if self.size_constraint_mode == "ROLL_ORIENTATION_FREE":
            # 현수막 공식 범위: 최소 30×30mm, 최대 1,800×49,100mm.
            # 5000×900 / 900×5000 모두 허용되어야 하므로 화면의 width/height 방향이 아니라
            # 짧은 변(롤 폭)과 긴 변(길이)을 기준으로 검증한다.
            short_side = min(width_mm, height_mm)
            long_side = max(width_mm, height_mm)
            return (
                short_side >= min(self.min_width_mm, self.min_height_mm)
                and long_side >= min(self.min_width_mm, self.min_height_mm)
                and short_side <= 1800
                and long_side <= 49100
            )

        return (
            self.min_width_mm <= width_mm <= self.max_width_mm
            and self.min_height_mm <= height_mm <= self.max_height_mm
        )


@dataclass
class CropBox:
    """원본 이미지 '픽셀 좌표계' 기준 크롭 영역. 화면 표시 좌표와 절대 혼동하지 않는다."""

    x: int
    y: int
    width: int
    height: int


@dataclass
class Job:
    """
    고객 작업 1건. 저장공간 격리 / 동시 작업 제어의 기본 단위.
    """

    job_id: str
    product_id: str
    output_width_mm: float
    output_height_mm: float
    fit_policy: FitPolicy = FitPolicy.CONTAIN
    crop_box: Optional[CropBox] = None
    status: str = "created"  # created -> uploaded -> processing -> preflight -> done / failed

    @staticmethod
    def new(product_id: str, output_width_mm: float, output_height_mm: float) -> "Job":
        return Job(
            job_id=str(uuid.uuid4()),
            product_id=product_id,
            output_width_mm=output_width_mm,
            output_height_mm=output_height_mm,
        )


@dataclass
class PreflightIssue:
    code: str
    level: PreflightLevel
    message: str
    detail: Optional[dict] = None
    # v1.3 추가 필드 (작업지시서: code/severity/title/description/recommendation/auto_fixable)
    title: str = ""
    recommendation: str = ""
    auto_fixable: bool = False
    # v1.5 추가 필드 (작업지시서: object_id/current_value/recommended_value/
    # autofix_available/blocking) - Frontend가 "무엇이, 왜, 어떻게 고치면 되는지"를
    # 구조화된 데이터로 표시할 수 있도록 한다.
    object_id: Optional[str] = None          # 이 이슈가 특정 디자인 요소/객체에 연결된 경우 (예: 텍스트 레이어 id, 아일렛 위치 id)
    current_value: Optional[str] = None       # 현재 값 (문자열로 통일 - 숫자/사이즈/색상모드 등 무엇이든 표시 가능하게)
    recommended_value: Optional[str] = None   # 권장 값

    def __post_init__(self):
        if not self.title:
            self.title = self.code.replace("_", " ").title()

    @property
    def severity(self) -> str:
        """작업지시서 명시 이름과의 호환용 별칭 (level 과 동일한 값).
        v1.5부터 level.value 는 PASS/WARNING/BLOCKING_ERROR 3단계 문자열이다."""
        return self.level.value

    @property
    def description(self) -> str:
        """작업지시서 명시 이름과의 호환용 별칭 (message 와 동일한 값)."""
        return self.message

    @property
    def autofix_available(self) -> bool:
        """v1.5 작업지시서 명시 필드명과의 호환용 별칭 (auto_fixable 과 동일한 값)."""
        return self.auto_fixable

    @property
    def blocking(self) -> bool:
        """이 이슈 하나만으로 Production PDF 생성을 막아야 하는지 여부.
        v1.5부터 ERROR(=BLOCKING_ERROR) 레벨만 blocking=True 다."""
        return self.level == PreflightLevel.ERROR

    def to_dict(self) -> dict:
        """v1.5 Preflight Result Schema (작업지시서 2번) 그대로의 dict 표현."""
        return {
            "code": self.code,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "object_id": self.object_id,
            "current_value": self.current_value,
            "recommended_value": self.recommended_value,
            "autofix_available": self.autofix_available,
            "blocking": self.blocking,
            "recommendation": self.recommendation,
            "detail": self.detail or {},
        }


@dataclass
class PreflightReport:
    job_id: str
    overall: PreflightLevel
    issues: list[PreflightIssue] = field(default_factory=list)

    def add(self, issue: PreflightIssue) -> None:
        self.issues.append(issue)
        # 전체 등급은 항상 "가장 나쁜" 레벨을 따라간다.
        order = {PreflightLevel.PASS: 0, PreflightLevel.WARNING: 1, PreflightLevel.ERROR: 2}
        if order[issue.level] > order[self.overall]:
            self.overall = issue.level

    def has_blocking_error(self) -> bool:
        return any(i.level == PreflightLevel.ERROR for i in self.issues)


@dataclass
class ProductProfileStub:
    """
    v1.4: 아직 실제 제작수치가 확인되지 않은 상품의 자리표시자(placeholder).

    작업지시서 원칙(A): "웹페이지에서 확인되지 않는 제작수치는 절대로 임의로 만들어내지
    않는다. 확인되지 않는 값은 null + needs_confirmation: true 로 저장한다."
    이를 코드 레벨에서 강제하기 위해, ProductProfile(운영에 실제 투입 가능한 확정 프로필)과
    이 ProductProfileStub(미확정 자리표시자)을 타입으로 분리했다.

    ProductProfileStub 은:
    - 카탈로그/택소노미 표시, GPT/운영자가 조사 후 채워 넣을 스키마 확인용으로만 쓰인다.
    - to_product_profile() 을 호출하기 전에는 실제 파이프라인(ProductionPipeline)에
      투입할 수 없다. 필수 필드가 비어있으면 to_product_profile() 이 어떤 필드가
      부족한지 정확히 알려주는 예외를 던진다 (조용히 기본값으로 때우지 않는다).
    """

    product_id: str
    category: str            # Taxonomy 그룹 id (예: "SIGNAGE", "ACRYLIC", ...)
    product_name: str
    variant: Optional[str] = None
    capabilities: list[str] = field(default_factory=list)  # Capability.value 문자열 목록

    trim_width_mm: Optional[float] = None
    trim_height_mm: Optional[float] = None
    work_width_mm: Optional[float] = None   # 재단+도련을 포함한 작업 캔버스 크기 (없으면 trim+bleed*2로 유도)
    work_height_mm: Optional[float] = None
    bleed_mm: Optional[float] = None

    min_width_mm: Optional[float] = None
    max_width_mm: Optional[float] = None
    min_height_mm: Optional[float] = None
    max_height_mm: Optional[float] = None
    custom_size_allowed: Optional[bool] = None

    recommended_dpi: Optional[float] = None
    minimum_dpi: Optional[float] = None

    color_mode: Optional[str] = None
    icc_profile: Optional[str] = None

    safe_margin_mm: Optional[float] = None

    cutline_required: Optional[bool] = None
    cutline_type: Optional[str] = None

    white_ink_required: Optional[bool] = None
    white_ink_rule: Optional[str] = None

    # v1.6 추가: 아크릴 상품 제작 파라미터 (전부 미확인 시 None 유지 - 하드코딩 금지)
    cutline_offset_mm: Optional[float] = None        # artwork 외곽 -> 칼선까지 오프셋
    minimum_cut_radius_mm: Optional[float] = None     # 칼선 최소 곡률 반경 (레이저/CNC 가공 한계)
    hole_diameter_mm: Optional[float] = None          # 키링 구멍 지름
    hole_edge_margin_mm: Optional[float] = None       # 구멍 중심 ~ 칼선까지 최소 거리
    material_thickness_mm: Optional[float] = None      # 아크릴 두께
    stand_tab_width_mm: Optional[float] = None          # 스탠드 하단 tab 폭
    stand_tab_height_mm: Optional[float] = None
    stand_slot_width_mm: Optional[float] = None          # 스탠드 base slot 폭
    stand_slot_clearance_mm: Optional[float] = None       # slot 끼움 여유
    white_choke_mm: Optional[float] = None                 # 화이트 레이어 choke(수축) - 양수면 artwork보다 작게
    white_spread_mm: Optional[float] = None                # 화이트 레이어 spread(확장) - 양수면 artwork보다 크게
    size_presets: list = field(default_factory=list)         # v1.8: [{"label":...,"width_mm":...,"height_mm":...}]
    print_method: Optional[str] = None                          # v1.9
    stand_option_available: Optional[bool] = None                 # v1.9
    verified_fields: list = field(default_factory=list)             # v1.9: 필드 단위 검증 추적

    eyelet_enabled: Optional[bool] = None
    finishing: list[str] = field(default_factory=list)

    front_back: Optional[str] = None   # "single" | "double"
    material: Optional[str] = None

    supported_source_formats: list[str] = field(default_factory=list)
    production_notes: Optional[str] = None

    needs_confirmation: bool = True
    unconfirmed_fields: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)  # 실제 조사 시 근거 URL을 기록하는 용도 (현재는 비어있음)
    related_products: list[str] = field(default_factory=list)  # v1.4b: UI 추천용 관련 상품 product_id 목록

    # v1.4b 추가: 출처 추적 + 제작 준비 상태
    source: SourceInfo = field(default_factory=SourceInfo)
    production_status: ProductionStatus = ProductionStatus.GUIDE_REQUIRED

    def validate_production_status(self) -> None:
        """
        'VERIFIED' 는 실제로 검증된 경우에만 붙을 수 있다는 것을 코드 레벨에서 강제한다.
        - VERIFIED 인데 source.verified 가 False 이거나 필수 필드가 비어있으면 예외.
        - 이 메서드는 생성자가 아니라 별도 호출 지점(config.load_profile_stubs 등)에서
          명시적으로 실행한다 - 그래야 "일단 만들고 나중에 채워넣는" 자연스러운 흐름을
          막지 않으면서도, 잘못된 VERIFIED 라벨이 조용히 시스템에 들어오는 것은 방지한다.
        """
        if self.production_status == ProductionStatus.VERIFIED:
            problems = []
            if not self.source.verified:
                problems.append("source.verified 가 True 가 아닙니다.")
            if not self.source.url:
                problems.append("source.url 이 비어있습니다.")
            missing = self.missing_required_fields()
            if missing:
                problems.append(f"필수 필드 누락: {missing}")
            if problems:
                raise ValueError(
                    f"'{self.product_id}' 는 production_status=VERIFIED 로 표시되어 있지만 "
                    f"실제로는 검증 조건을 만족하지 않습니다: {'; '.join(problems)}"
                )

    # 실제 제작(파이프라인 투입)에 반드시 필요한 필드 목록 (클래스 상수 - 인스턴스 필드 아님).
    REQUIRED_FOR_PRODUCTION: ClassVar[tuple] = (
        "trim_width_mm", "trim_height_mm", "bleed_mm",
        "min_width_mm", "max_width_mm", "min_height_mm", "max_height_mm",
        "custom_size_allowed", "recommended_dpi", "minimum_dpi",
        "color_mode", "safe_margin_mm",
    )

    def missing_required_fields(self) -> list[str]:
        return [f for f in self.REQUIRED_FOR_PRODUCTION if getattr(self, f) in (None, "")]

    def is_ready_for_production(self) -> bool:
        return len(self.missing_required_fields()) == 0

    # v1.6: 아크릴 상품(칼선/구멍/화이트/스탠드)에 한해 필요한 추가 필드.
    # 이 필드들은 REQUIRED_FOR_PRODUCTION(모든 상품 공통)에는 포함하지 않는다 - 상품마다
    # 필요한 하위 집합이 다르기 때문에, capability 기반으로 별도 검사한다.
    ACRYLIC_CUTLINE_FIELDS: ClassVar[tuple] = ("cutline_offset_mm", "minimum_cut_radius_mm", "material_thickness_mm")
    ACRYLIC_KEYRING_FIELDS: ClassVar[tuple] = ("hole_diameter_mm", "hole_edge_margin_mm")
    ACRYLIC_STAND_FIELDS: ClassVar[tuple] = (
        "stand_tab_width_mm", "stand_tab_height_mm", "stand_slot_width_mm", "stand_slot_clearance_mm",
    )
    ACRYLIC_WHITE_FIELDS: ClassVar[tuple] = ("white_choke_mm", "white_spread_mm")

    def missing_acrylic_fields(self) -> list[str]:
        """이 상품의 capability 에 따라 필요한 아크릴 전용 필드 중 비어있는 것을 반환한다."""
        needed: list[str] = []
        caps = set(self.capabilities)
        if "CUTLINE_PRINT" in caps:
            needed.extend(self.ACRYLIC_CUTLINE_FIELDS)
        if "keyring" in (self.product_id or ""):
            needed.extend(self.ACRYLIC_KEYRING_FIELDS)
        if "stand" in (self.product_id or ""):
            needed.extend(self.ACRYLIC_STAND_FIELDS)
        if "WHITE_INK_PRINT" in caps or "WHITE_INK" in caps:
            needed.extend(self.ACRYLIC_WHITE_FIELDS)
        return sorted({f for f in needed if getattr(self, f) in (None, "")})

    def is_ready_for_acrylic_production(self) -> bool:
        return self.is_ready_for_production() and len(self.missing_acrylic_fields()) == 0

    def to_product_profile(self) -> "ProductProfile":
        """
        확정 프로필로 승격한다. 필수 필드가 비어있으면 어떤 필드가 부족한지 정확히
        알려주는 ValueError 를 던진다 - 미확인 수치로 조용히 제작을 진행하는 사고를 방지한다.
        """
        missing = self.missing_required_fields()
        if missing:
            raise ValueError(
                f"'{self.product_id}' 상품은 아직 제작수치가 확인되지 않아 파이프라인에 "
                f"투입할 수 없습니다. 누락된 필드: {missing}. 실제 상품 페이지/인쇄소 협의로 "
                f"수치를 확인한 뒤 다시 시도하세요."
            )
        bleed = self.bleed_mm
        return ProductProfile(
            product_id=self.product_id,
            product_name=self.product_name,
            category=self.category,
            width_mm=self.trim_width_mm,
            height_mm=self.trim_height_mm,
            custom_size_allowed=self.custom_size_allowed,
            min_width_mm=self.min_width_mm,
            max_width_mm=self.max_width_mm,
            min_height_mm=self.min_height_mm,
            max_height_mm=self.max_height_mm,
            safe_zone=SafeZoneSpec(bleed_mm=bleed, safe_margin_mm=self.safe_margin_mm or 0),
            dpi_warning_below=self.recommended_dpi,
            dpi_error_below=self.minimum_dpi,
            color_mode_target=self.color_mode,
            icc_profile_name=self.icc_profile,
            finishing=list(self.finishing),
            eyelet=EyeletSpec(enabled=bool(self.eyelet_enabled)),
            capabilities=list(self.capabilities),
            related_products=list(self.related_products),
            production_status=self.production_status,
            source=self.source,
            is_dev_default=False,
            cutline_offset_mm=self.cutline_offset_mm,
            minimum_cut_radius_mm=self.minimum_cut_radius_mm,
            hole_diameter_mm=self.hole_diameter_mm,
            hole_edge_margin_mm=self.hole_edge_margin_mm,
            material_thickness_mm=self.material_thickness_mm,
            stand_tab_width_mm=self.stand_tab_width_mm,
            stand_tab_height_mm=self.stand_tab_height_mm,
            stand_slot_width_mm=self.stand_slot_width_mm,
            stand_slot_clearance_mm=self.stand_slot_clearance_mm,
            white_choke_mm=self.white_choke_mm,
            white_spread_mm=self.white_spread_mm,
            size_presets=list(self.size_presets),
            material=self.material,
            print_method=self.print_method,
            stand_option_available=self.stand_option_available,
            verified_fields=list(self.verified_fields),
        )

    def to_dict(self) -> dict:
        from dataclasses import asdict

        return asdict(self)


@dataclass
class AdministratorOverride:
    """
    v1.5 작업지시서 3번: 관리자 강제 출력.

    BLOCKING_ERROR 가 있으면 기본적으로 출력이 차단되지만, 관리자가 이 옵션을 명시적으로
    켠 경우에만 강제로 출력할 수 있다. 강제 출력 여부와 사유는 항상 Production Manifest에
    기록되어 추적 가능해야 한다 - "누가, 왜, 어떤 문제를 감수하고 출력했는지"가 남는다.
    """

    enabled: bool = False
    authorized_by: str = ""       # 강제 출력을 승인한 관리자 식별자 (이메일/아이디 등)
    reason: str = ""              # 강제 출력 사유 (감사 로그용, 비어있으면 안 됨)

    def is_valid(self) -> bool:
        """강제 출력을 실제로 발동하려면 승인자와 사유가 모두 기록되어야 한다."""
        return self.enabled and bool(self.authorized_by) and bool(self.reason)


@dataclass
class JobTicket:
    """
    주문 관리용 티켓. Production Engine 은 이 구조를 생성/보관만 하고,
    실제 주문/결제/CS 로직(스마트스토어 연동 등)은 GPT 쪽 상위 시스템의 몫이다.

    예시:
        JobTicket(
            order_number="20260811-001", channel="스마트스토어",
            customer_name="홍길동", product="현수막",
            width_mm=5000, height_mm=900, quantity=1,
            finishing=["eyelet_all_edges"], memo="고객 요청사항 ...",
            source_filename="my_banner.jpg",
        )
    """

    order_number: str
    channel: str
    customer_name: str
    product: str
    width_mm: float
    height_mm: float
    quantity: int = 1
    finishing: list[str] = field(default_factory=list)
    memo: str = ""
    source_filename: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "order_number": self.order_number,
            "channel": self.channel,
            "customer_name": self.customer_name,
            "product": self.product,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "quantity": self.quantity,
            "finishing": self.finishing,
            "memo": self.memo,
            "source_filename": self.source_filename,
            "created_at": self.created_at,
        }


@dataclass
class ProductionJob:
    """
    v1.9 PRODUCTION GUIDE 반영: "PRODUCTION JOB" 섹션. 상품 옵션까지 포함한 최종
    제작 단위 - Production Package(job.json)에 그대로 저장된다.

    JobTicket 과의 차이: JobTicket 은 "주문 관리"(누가/어디서/얼마나) 관점이고,
    ProductionJob 은 "제작 사양"(무엇을 어떤 규격/소재/공정으로 만드는지) 관점이다.
    한 주문(JobTicket)에 하나의 ProductionJob 이 대응한다.
    """

    product: str                      # 상품명 (예: "실내용 배너")
    finished_size_mm: tuple           # (width_mm, height_mm) - 사용자가 입력한 완성사이즈
    working_size_mm: tuple            # (width_mm, height_mm) - 도련 포함 자동 계산된 작업사이즈
    bleed_mm: float
    material: Optional[str] = None
    print_method: Optional[str] = None
    resolution_dpi: Optional[float] = None   # 실효 DPI (업로드 이미지 기준 계산된 값)
    finishing: list[str] = field(default_factory=list)
    stand: bool = False
    quantity: int = 1
    preflight_overall: Optional[str] = None   # PASS/WARNING/BLOCKING_ERROR (문자열로 저장)

    def to_dict(self) -> dict:
        return {
            "product": self.product,
            "finished_size_mm": {"width_mm": self.finished_size_mm[0], "height_mm": self.finished_size_mm[1]},
            "working_size_mm": {"width_mm": self.working_size_mm[0], "height_mm": self.working_size_mm[1]},
            "bleed_mm": self.bleed_mm,
            "material": self.material,
            "print_method": self.print_method,
            "resolution_dpi": self.resolution_dpi,
            "finishing": self.finishing,
            "stand": self.stand,
            "quantity": self.quantity,
            "preflight": self.preflight_overall,
        }

    @staticmethod
    def from_profile_and_job(profile: "ProductProfile", job: "Job", effective_dpi: Optional[float] = None,
                              preflight_overall: Optional[str] = None) -> "ProductionJob":
        """ProductProfile + Job 으로부터 ProductionJob 을 자동 조립한다 (Working Size 는
        항상 도련 포함 자동 계산 - 사용자가 직접 입력하지 않는다는 UX 원칙을 그대로 반영)."""
        bleed = profile.safe_zone.bleed_mm
        return ProductionJob(
            product=profile.product_name,
            finished_size_mm=(job.output_width_mm, job.output_height_mm),
            working_size_mm=(job.output_width_mm + bleed * 2, job.output_height_mm + bleed * 2),
            bleed_mm=bleed,
            material=profile.material,
            print_method=profile.print_method,
            resolution_dpi=effective_dpi,
            finishing=list(profile.finishing),
            stand=bool(profile.stand_option_available),
            quantity=1,
            preflight_overall=preflight_overall,
        )
