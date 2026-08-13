"""
preflight/engine.py
----------------------
Print Preflight 엔진 (v1.3).

검사 항목 (작업지시서 3번 요구사항 반영):
1. Effective DPI
2. Aspect Ratio
3. Upscaling
4. Safe Area
5. Bleed (프로필에 정의되어 있는지 + 실제 출력 파이프라인에 반영되는지)
6. Image Bounds (크롭 영역이 원본 픽셀 범위 내에 있는지)
7. Color Mode (RGB->CMYK 정책은 PipelineStage 에 따라 심각도가 달라짐 - 4번 요구사항)
8. Transparency (알파 채널 - CMYK/인쇄에서는 제거되어야 함)
9. Canvas Size (상품 허용 사이즈 범위)
10. Eyelet Collision (아일렛과 보호 요소 겹침, 배치 불가 상황)

모든 PreflightIssue 는 code/severity/title/description/recommendation/auto_fixable 을
전부 채워서 반환한다 (severity, description 은 models.PreflightIssue 의 별칭 프로퍼티).

각 검사는 PreflightIssue 로 기록되고, 전체 결과는 그 중 가장 나쁜 등급을 따른다.
ERROR 가 하나라도 있으면 제작 접수 불가로 처리해야 한다 (호출부에서 판단).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..finishing.eyelet_engine import is_layout_degenerate
from ..imaging.dpi import calculate_effective_dpi
from ..imaging.ratio import compare_ratio
from ..models import (
    Capability,
    CropBox,
    EyeletPoint,
    Job,
    PipelineStage,
    PreflightIssue,
    PreflightLevel,
    PreflightReport,
    ProductProfile,
)
from ..taxonomy import IMPLEMENTED_CAPABILITIES, routing_capabilities_of


@dataclass
class ElementBox:
    """
    안전영역 침범 / 아일렛 충돌 검사를 위한 '보호 대상 요소'(텍스트, 로고 등)의 위치.
    출력 캔버스 좌표계 기준, 단위 mm, 좌상단 원점.
    """

    name: str
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float


@dataclass
class PreflightInput:
    job: Job
    profile: ProductProfile
    source_width_px: int
    source_height_px: int
    upscale_factor: float
    color_mode: str  # 실제 처리된 이미지의 색상 모드 ("RGB", "CMYK" 등)
    icc_profile_applied: Optional[str]
    protected_elements: list[ElementBox] | None = None

    # v1.3 추가 필드 (모두 하위 호환을 위해 기본값 지정 - 기존 호출부는 그대로 동작)
    stage: PipelineStage = PipelineStage.FINAL
    has_alpha: bool = False
    crop_box: Optional[CropBox] = None
    eyelet_points: list[EyeletPoint] = field(default_factory=list)


    # v1.4 추가 필드 (상품별 capability 기반 검사용). 모두 기본값이 있어 하위 호환 유지.
    cutline_provided: Optional[bool] = None
    white_layer_provided: Optional[bool] = None
    back_image_provided: Optional[bool] = None

    # v1.5 추가 필드 (작업지시서 1번: Canvas/Product 비율 불일치, 파일 손상,
    # 좌표 변환 실패는 진짜 BLOCKING_ERROR 대상). 모두 선택값 - 없으면 검사를 건너뛴다.
    file_corrupt: bool = False
    file_corrupt_reason: Optional[str] = None
    canvas_px_width: Optional[float] = None
    canvas_px_height: Optional[float] = None


def run_preflight(data: PreflightInput) -> PreflightReport:
    report = PreflightReport(job_id=data.job.job_id, overall=PreflightLevel.PASS)

    _check_file_integrity(data, report)
    _check_capability_support(data, report)
    _check_dpi(data, report)
    _check_ratio(data, report)
    _check_canvas_coordinate_contract(data, report)
    _check_upscale(data, report)
    _check_canvas_size(data, report)
    _check_safe_zone(data, report)
    _check_image_bounds(data, report)
    _check_transparency(data, report)
    _check_color_mode(data, report)
    _check_eyelet(data, report)
    _check_cutline(data, report)
    _check_white_ink(data, report)
    _check_front_back(data, report)
    _check_unimplemented_vector_checks(data, report)

    return report


def _check_file_integrity(data: PreflightInput, report: PreflightReport) -> None:
    """v1.5: 파일 손상은 '실제 제작파일 생성 자체가 불가능한' 대표 사례 -> BLOCKING_ERROR.
    (정상 흐름에서는 security.file_validator.validate_upload() 가 업로드 시점에 이미
    막지만, preflight 스키마에도 이 판정을 명시적으로 노출하기 위한 방어적 검사.)"""
    if data.file_corrupt:
        report.add(
            PreflightIssue(
                code="FILE_CORRUPT",
                level=PreflightLevel.ERROR,
                message=f"원본 파일이 손상되어 있어 제작 파일을 생성할 수 없습니다: {data.file_corrupt_reason or '알 수 없는 오류'}",
                recommendation="원본 파일을 다시 업로드하세요.",
                auto_fixable=False,
            )
        )


def _check_canvas_coordinate_contract(data: PreflightInput, report: PreflightReport) -> None:
    """v1.5: 에디터 캔버스 픽셀 비율과 실제 제품(Trim) mm 비율이 근본적으로 다르면
    coordinates.py 의 좌표 변환 계약(px -> mm -> pt) 자체가 성립하지 않는다
    (CoordinateContractError). 이 경우는 "디자인을 조정하면 되는" 수준이 아니라
    "이 상태로는 애초에 좌표를 계산할 수 없는" 경우이므로 BLOCKING_ERROR다."""
    if data.canvas_px_width is None or data.canvas_px_height is None:
        return
    from ..coordinates import CoordinateContractError, TrimCanvas

    try:
        TrimCanvas(
            canvas_px_width=data.canvas_px_width,
            canvas_px_height=data.canvas_px_height,
            trim_width_mm=data.job.output_width_mm,
            trim_height_mm=data.job.output_height_mm,
        )
    except CoordinateContractError as e:
        report.add(
            PreflightIssue(
                code="CANVAS_ASPECT_RATIO_MISMATCH",
                level=PreflightLevel.ERROR,
                message=str(e),
                current_value=f"{data.canvas_px_width}x{data.canvas_px_height}px",
                recommended_value=f"{data.job.output_width_mm}x{data.job.output_height_mm}mm 비율과 동일해야 함",
                recommendation="에디터 캔버스를 Trim mm 비율에 맞춰 다시 생성하세요.",
                auto_fixable=False,
            )
        )


def _capabilities_of(profile: ProductProfile) -> list[str]:
    """pipeline_router._capabilities_of() 와 동일한 로직 (순환 import 방지를 위해 중복 구현).
    profile.capabilities 가 명시되어 있으면 그것을, 없으면 finishing/eyelet 필드로 추론."""
    if profile.capabilities:
        return list(profile.capabilities)
    caps = [Capability.RECTANGULAR_PRINT.value]
    if profile.eyelet.enabled:
        caps.append(Capability.EYELET_FINISHING.value)
    return caps


def _check_capability_support(data: PreflightInput, report: PreflightReport) -> None:
    """이 상품에 필요한 capability 중 아직 엔진에 구현되지 않은 것이 있으면 ERROR로 명시한다.
    (v1.4b: 속성 태그(CMYK_OUTPUT 등)는 라우팅 대상이 아니므로 이 검사에서 제외한다.)"""
    caps = _capabilities_of(data.profile)
    routing_caps = routing_capabilities_of(caps)
    unimplemented = [c for c in routing_caps if c not in IMPLEMENTED_CAPABILITIES]
    if unimplemented:
        report.add(
            PreflightIssue(
                code="CAPABILITY_NOT_IMPLEMENTED",
                level=PreflightLevel.ERROR,
                message=(
                    f"'{data.profile.product_name}' 상품에 필요한 기능"
                    f"({', '.join(unimplemented)})이 아직 Production Engine에 구현되지 않았습니다."
                ),
                detail={"unimplemented_capabilities": unimplemented},
                recommendation="해당 capability가 구현될 때까지 이 상품은 제작 접수를 보류하세요.",
                auto_fixable=False,
            )
        )


def _check_dpi(data: PreflightInput, report: PreflightReport) -> None:
    result = calculate_effective_dpi(
        pixel_width=data.source_width_px,
        pixel_height=data.source_height_px,
        output_width_mm=data.job.output_width_mm,
        output_height_mm=data.job.output_height_mm,
    )
    min_dpi = result.min_dpi
    profile = data.profile

    if min_dpi < profile.dpi_error_below:
        report.add(
            PreflightIssue(
                code="DPI_TOO_LOW_ERROR",
                # v1.5: 해상도 부족은 "만들 수는 있지만 흐릿하게 나올 수 있는" 품질 문제이지,
                # 파일 생성 자체가 불가능한 경우가 아니다. WARNING으로 재분류 (작업지시서 1번:
                # "권장 DPI 미달 -> 기본 WARNING"). 다만 심각도가 더 크다는 것을 메시지/추천으로
                # 명확히 알린다.
                level=PreflightLevel.WARNING,
                message=(
                    f"실효 해상도가 {min_dpi:.1f} DPI로, 최소 기준({profile.dpi_error_below} DPI) "
                    f"미만입니다. 이 상태로는 인쇄 품질을 보장할 수 없습니다."
                ),
                detail={"dpi_x": result.dpi_x, "dpi_y": result.dpi_y},
                current_value=f"{min_dpi:.1f} DPI",
                recommended_value=f">= {profile.dpi_error_below} DPI",
                recommendation=(
                    f"가로/세로 중 짧은 쪽 기준 최소 {profile.dpi_error_below} DPI 이상 확보되도록 "
                    "더 높은 해상도의 원본으로 교체하거나 출력 사이즈를 줄이세요."
                ),
                auto_fixable=False,
            )
        )
    elif min_dpi < profile.dpi_warning_below:
        report.add(
            PreflightIssue(
                code="DPI_LOW_WARNING",
                level=PreflightLevel.WARNING,
                message=(
                    f"실효 해상도가 {min_dpi:.1f} DPI로 권장 기준({profile.dpi_warning_below} DPI) "
                    f"미만입니다. 근거리에서 흐릿하게 보일 수 있습니다."
                ),
                detail={"dpi_x": result.dpi_x, "dpi_y": result.dpi_y},
                current_value=f"{min_dpi:.1f} DPI",
                recommended_value=f">= {profile.dpi_warning_below} DPI",
                recommendation=f"가능하면 {profile.dpi_warning_below} DPI 이상의 원본을 사용하세요.",
                auto_fixable=False,
            )
        )
    else:
        report.add(
            PreflightIssue(
                code="DPI_OK",
                level=PreflightLevel.PASS,
                message=f"실효 해상도 {min_dpi:.1f} DPI - 기준 충족.",
            )
        )


def _check_ratio(data: PreflightInput, report: PreflightReport) -> None:
    comparison = compare_ratio(
        source_width_px=data.source_width_px,
        source_height_px=data.source_height_px,
        target_width_mm=data.job.output_width_mm,
        target_height_mm=data.job.output_height_mm,
    )
    if not comparison.matches:
        # 비율 차이가 있어도 시스템이 COVER/CONTAIN 으로 정상 처리하므로 ERROR 는 아니지만,
        # 사용자가 "왜 잘렸는지/왜 여백이 생겼는지" 알아야 하므로 WARNING 으로 알린다.
        report.add(
            PreflightIssue(
                code="RATIO_MISMATCH_WARNING",
                level=PreflightLevel.WARNING,
                message=(
                    f"원본 비율({comparison.source_ratio:.3f})과 제작 비율"
                    f"({comparison.target_ratio:.3f})이 {comparison.ratio_diff_percent:.1f}% "
                    f"차이납니다. fit 정책({data.job.fit_policy.value})에 따라 "
                    f"{'크롭' if data.job.fit_policy.value == 'cover' else '여백'}이 발생합니다."
                ),
                detail={
                    "source_ratio": comparison.source_ratio,
                    "target_ratio": comparison.target_ratio,
                    "diff_percent": comparison.ratio_diff_percent,
                },
                current_value=f"{comparison.source_ratio:.3f}",
                recommended_value=f"{comparison.target_ratio:.3f}",
                recommendation="Cover/Contain 정책을 변경하거나 원하는 영역을 직접 크롭하세요.",
                auto_fixable=True,
            )
        )
    else:
        report.add(
            PreflightIssue(
                code="RATIO_OK",
                level=PreflightLevel.PASS,
                message="원본 비율과 제작 비율이 일치합니다.",
            )
        )


def _check_upscale(data: PreflightInput, report: PreflightReport) -> None:
    if data.upscale_factor > 1.0:
        # v1.5: 업스케일은 품질 저하 "경고"이지 생성 자체를 막을 이유가 아니다.
        # 배율과 무관하게 항상 WARNING (심각도는 메시지로 구분).
        report.add(
            PreflightIssue(
                code="UPSCALE_DETECTED",
                level=PreflightLevel.WARNING,
                message=f"이미지가 {data.upscale_factor * 100:.0f}%로 확대되었습니다. 화질 저하 가능성이 있습니다.",
                detail={"upscale_factor": data.upscale_factor},
                current_value=f"{data.upscale_factor * 100:.0f}%",
                recommended_value="<= 100%",
                recommendation="더 높은 해상도의 원본으로 교체하거나 출력 사이즈를 줄이세요.",
                auto_fixable=False,
            )
        )


def _check_canvas_size(data: PreflightInput, report: PreflightReport) -> None:
    profile = data.profile
    if not profile.size_in_range(data.job.output_width_mm, data.job.output_height_mm):
        if profile.custom_size_allowed:
            allowed = (
                f"{profile.min_width_mm}~{profile.max_width_mm}mm(가로) x "
                f"{profile.min_height_mm}~{profile.max_height_mm}mm(세로)"
            )
        else:
            allowed = f"{profile.width_mm}x{profile.height_mm}mm (고정 규격)"
        report.add(
            PreflightIssue(
                code="SIZE_OUT_OF_RANGE",
                level=PreflightLevel.ERROR,
                message=(
                    f"요청 사이즈({data.job.output_width_mm}x{data.job.output_height_mm}mm)가 "
                    f"'{profile.product_name}' 상품의 허용 범위({allowed})를 벗어났습니다."
                ),
                recommendation=f"허용 범위({allowed}) 내 사이즈로 다시 주문하세요.",
                auto_fixable=False,
            )
        )
    else:
        report.add(
            PreflightIssue(
                code="CANVAS_SIZE_OK",
                level=PreflightLevel.PASS,
                message="주문 사이즈가 상품 허용 범위 내에 있습니다.",
            )
        )


def _check_safe_zone(data: PreflightInput, report: PreflightReport) -> None:
    profile = data.profile
    safe = profile.safe_zone

    if safe.bleed_mm <= 0:
        report.add(
            PreflightIssue(
                code="BLEED_NOT_CONFIGURED",
                level=PreflightLevel.WARNING,
                message=f"'{profile.product_name}' 상품에 도련(Bleed)이 설정되어 있지 않습니다 (0mm).",
                recommendation="상품 프로필에 적절한 bleed_mm 값을 설정하세요 (배너 3mm, 현수막 10mm 권장).",
                auto_fixable=False,
            )
        )

    if data.protected_elements:
        for el in data.protected_elements:
            violation = _element_violates_safe_margin(el, data.job, safe)
            if violation:
                report.add(
                    PreflightIssue(
                        code="SAFE_ZONE_VIOLATION",
                        # v1.5: 안전영역 침범은 디자인 품질 이슈이지 PDF 생성 자체를 막지
                        # 않는다 (재단 시 잘릴 위험을 알리는 경고). WARNING으로 재분류.
                        level=PreflightLevel.WARNING,
                        message=f"요소 '{el.name}'이(가) 안전영역을 침범했습니다: {violation}",
                        detail={"element": el.name},
                        object_id=el.name,
                        recommendation="중요 요소를 안전영역 안쪽으로 이동하세요.",
                        auto_fixable=False,
                    )
                )
        if not any(i.code == "SAFE_ZONE_VIOLATION" for i in report.issues):
            report.add(
                PreflightIssue(
                    code="SAFE_ZONE_OK",
                    level=PreflightLevel.PASS,
                    message="보호 요소가 모두 안전영역 안에 있습니다.",
                )
            )
    else:
        report.add(
            PreflightIssue(
                code="SAFE_ZONE_NOT_CHECKED",
                level=PreflightLevel.WARNING,
                message=(
                    "텍스트/로고 등 보호 요소 좌표가 제공되지 않아 안전영역 침범 여부를 "
                    "자동 검사하지 못했습니다. (배경 이미지만 배치하는 경우 무시 가능)"
                ),
                recommendation="에디터에서 텍스트/로고 요소의 mm 좌표를 함께 전달하면 자동 검사가 가능합니다.",
                auto_fixable=False,
            )
        )


def _element_violates_safe_margin(el: ElementBox, job: Job, safe) -> Optional[str]:
    left_limit = safe.safe_margin_mm + safe.extra_margin_by_edge_mm.get("left", 0)
    right_limit = safe.safe_margin_mm + safe.extra_margin_by_edge_mm.get("right", 0)
    top_limit = safe.safe_margin_mm + safe.extra_margin_by_edge_mm.get("top", 0)
    bottom_limit = safe.safe_margin_mm + safe.extra_margin_by_edge_mm.get("bottom", 0)

    if el.x_mm < left_limit:
        return f"왼쪽 안전선({left_limit}mm) 침범"
    if el.y_mm < top_limit:
        return f"상단 안전선({top_limit}mm) 침범"
    if el.x_mm + el.width_mm > job.output_width_mm - right_limit:
        return f"오른쪽 안전선({right_limit}mm) 침범"
    if el.y_mm + el.height_mm > job.output_height_mm - bottom_limit:
        return f"하단 안전선({bottom_limit}mm) 침범"
    return None


def _check_image_bounds(data: PreflightInput, report: PreflightReport) -> None:
    """크롭 영역이 원본 픽셀 범위를 벗어나지 않는지 방어적으로 재확인한다.
    (정상 흐름에서는 imaging.ratio.resolve_crop_box 가 이미 막지만,
     외부에서 crop_box 를 직접 주입하는 경로를 대비한 이중 방어.)"""
    box = data.crop_box
    if box is None:
        return
    out_of_bounds = (
        box.x < 0
        or box.y < 0
        or box.x + box.width > data.source_width_px
        or box.y + box.height > data.source_height_px
        or box.width <= 0
        or box.height <= 0
    )
    if out_of_bounds:
        report.add(
            PreflightIssue(
                code="IMAGE_BOUNDS_INVALID",
                level=PreflightLevel.ERROR,
                message=(
                    f"크롭 영역({box.x},{box.y},{box.width}x{box.height})이 원본 이미지 범위"
                    f"({data.source_width_px}x{data.source_height_px})를 벗어났습니다."
                ),
                recommendation="크롭 영역을 원본 이미지 범위 내로 다시 지정하세요.",
                auto_fixable=False,
            )
        )
    else:
        report.add(
            PreflightIssue(
                code="IMAGE_BOUNDS_OK",
                level=PreflightLevel.PASS,
                message="크롭 영역이 원본 이미지 범위 내에 있습니다.",
            )
        )


def _check_transparency(data: PreflightInput, report: PreflightReport) -> None:
    if data.has_alpha:
        report.add(
            PreflightIssue(
                code="TRANSPARENCY_DETECTED",
                level=PreflightLevel.WARNING,
                message="원본 이미지에 투명(알파) 채널이 있습니다. 인쇄용 CMYK 변환 시 흰 배경으로 합성됩니다.",
                recommendation="투명 배경이 의도한 디자인이 아니라면 원하는 배경색으로 미리 합성해서 업로드하세요.",
                auto_fixable=True,
            )
        )


def _check_color_mode(data: PreflightInput, report: PreflightReport) -> None:
    profile = data.profile
    if data.color_mode.upper() != profile.color_mode_target.upper():
        if data.stage == PipelineStage.EDIT:
            # 편집 단계에서는 RGB 원본이 정상이다. 제작 ERROR로 취급하지 않는다.
            report.add(
                PreflightIssue(
                    code="COLOR_MODE_RGB_SOURCE",
                    level=PreflightLevel.WARNING,
                    message=(
                        f"현재 색상 모드는 {data.color_mode} 입니다. 편집 단계에서는 정상이며, "
                        f"최종 출력(Export) 시 {profile.color_mode_target}로 자동 변환됩니다."
                    ),
                    recommendation="출력 시 자동으로 CMYK 변환 및 (설정된 경우) ICC 프로파일이 적용됩니다.",
                    auto_fixable=True,
                )
            )
        else:
            # v1.5 작업지시서 4번: "RGB라는 이유만으로 Production Export를 막지 않는다."
            # 최종 단계에서도 CMYK 미변환은 WARNING이다 - 실제 변환은 build_pdf() 이전에
            # convert_color() 가 자동으로 수행하므로, 이 상태는 "아직 변환 전"이라는
            # 정보 표시일 뿐 생성 자체를 막을 이유가 아니다.
            report.add(
                PreflightIssue(
                    code="COLOR_MODE_NOT_CONVERTED",
                    level=PreflightLevel.WARNING,
                    message=(
                        f"최종 제작 단계인데 색상 모드가 아직 {data.color_mode} 입니다. "
                        f"Export 시 {profile.color_mode_target} 로 자동 변환됩니다."
                    ),
                    current_value=data.color_mode,
                    recommended_value=profile.color_mode_target,
                    recommendation="pipeline.convert_color() 를 호출해 CMYK 변환을 완료하세요 (Export 파이프라인이 자동 수행).",
                    auto_fixable=True,
                )
            )
        return

    if profile.icc_profile_name and not data.icc_profile_applied:
        report.add(
            PreflightIssue(
                code="ICC_PROFILE_MISSING",
                level=PreflightLevel.WARNING,
                message=(
                    f"권장 ICC 프로파일({profile.icc_profile_name})이 적용되지 않았습니다. "
                    "색상이 인쇄소 장비와 다르게 나올 수 있습니다."
                ),
                recommendation="ICC 프로파일 경로를 지정해 정밀 색상 변환을 적용하세요.",
                auto_fixable=False,
            )
        )
    elif not profile.icc_profile_name:
        report.add(
            PreflightIssue(
                code="ICC_PROFILE_NOT_CONFIGURED",
                level=PreflightLevel.WARNING,
                message="이 상품에는 아직 ICC 프로파일이 지정되어 있지 않습니다 (인쇄소 협의 필요).",
                recommendation="인쇄소와 협의해 실제 사용할 CMYK ICC 프로파일을 상품 프로필에 등록하세요.",
                auto_fixable=False,
            )
        )
    else:
        report.add(
            PreflightIssue(
                code="COLOR_MODE_OK",
                level=PreflightLevel.PASS,
                message=(
                    f"{profile.color_mode_target} 변환이 완료되었고 ICC 프로파일"
                    f"({profile.icc_profile_name})이 적용되었습니다."
                ),
            )
        )


def _check_eyelet(data: PreflightInput, report: PreflightReport) -> None:
    profile = data.profile
    spec = profile.eyelet
    if not spec.enabled:
        return

    if is_layout_degenerate(data.job.output_width_mm, data.job.output_height_mm, spec):
        report.add(
            PreflightIssue(
                code="EYELET_LAYOUT_DEGENERATE",
                level=PreflightLevel.WARNING,
                message=(
                    f"캔버스 크기({data.job.output_width_mm}x{data.job.output_height_mm}mm)가 "
                    f"작아 아일렛 margin({spec.margin_mm}mm) 기준 정상 배치가 어렵습니다."
                ),
                recommendation="아일렛 margin을 줄이거나 상품 최소 사이즈를 재검토하세요.",
                auto_fixable=False,
            )
        )

    if not data.eyelet_points:
        return

    width = data.job.output_width_mm
    height = data.job.output_height_mm
    out_of_bounds = [
        p for p in data.eyelet_points if not (0 <= p.x_mm <= width and 0 <= p.y_mm <= height)
    ]
    if out_of_bounds:
        report.add(
            PreflightIssue(
                code="EYELET_OUT_OF_BOUNDS",
                # v1.5: 아일렛이 계산상 캔버스를 벗어나는 것은 배치 설정 문제이지, PDF 생성
                # 자체를 막는 기술적 실패가 아니다 (현재 파이프라인은 아일렛을 PDF에 직접
                # 렌더링하지 않고 manifest 좌표로만 기록한다). WARNING으로 재분류.
                level=PreflightLevel.WARNING,
                message=f"아일렛 {len(out_of_bounds)}개가 캔버스 범위를 벗어났습니다.",
                recommendation="아일렛 배치 정책 또는 margin 값을 재확인하세요.",
                auto_fixable=False,
            )
        )

    if data.protected_elements:
        clearance_mm = spec.diameter_mm / 2 + 5.0  # 아일렛 반지름 + 5mm 여유
        collisions = []
        for point in data.eyelet_points:
            for el in data.protected_elements:
                if _circle_rect_overlap(
                    point.x_mm, point.y_mm, clearance_mm, el.x_mm, el.y_mm, el.width_mm, el.height_mm
                ):
                    collisions.append((point, el.name))
        if collisions:
            for point, name in collisions:
                report.add(
                    PreflightIssue(
                        code="EYELET_COLLISION",
                        level=PreflightLevel.WARNING,  # v1.5: 물리적 충돌 경고 - 생성은 가능, 확인 필요
                        message=(
                            f"아일렛(x={point.x_mm:.0f}mm, y={point.y_mm:.0f}mm)이 요소 "
                            f"'{name}'과(와) 겹칩니다."
                        ),
                        detail={"eyelet": {"x_mm": point.x_mm, "y_mm": point.y_mm}, "element": name},
                        object_id=name,
                        recommendation="요소를 아일렛 위치에서 충분히 떨어뜨리거나 아일렛 배치를 조정하세요.",
                        auto_fixable=False,
                    )
                )

    if not out_of_bounds and not any(i.code == "EYELET_COLLISION" for i in report.issues):
        report.add(
            PreflightIssue(
                code="EYELET_LAYOUT_OK",
                level=PreflightLevel.PASS,
                message=f"아일렛 {len(data.eyelet_points)}개 배치 정상 (충돌 없음).",
            )
        )


def _circle_rect_overlap(cx: float, cy: float, r: float, rx: float, ry: float, rw: float, rh: float) -> bool:
    closest_x = max(rx, min(cx, rx + rw))
    closest_y = max(ry, min(cy, ry + rh))
    dx = cx - closest_x
    dy = cy - closest_y
    return (dx * dx + dy * dy) <= (r * r)


def _check_cutline(data: PreflightInput, report: PreflightReport) -> None:
    caps = _capabilities_of(data.profile)
    if Capability.CUTLINE_PRINT.value not in caps:
        return
    if not data.cutline_provided:
        report.add(
            PreflightIssue(
                code="CUTLINE_DATA_MISSING",
                level=PreflightLevel.ERROR,
                message=f"'{data.profile.product_name}' 상품은 칼선(외곽선 컷) 데이터가 필요하지만 제공되지 않았습니다.",
                recommendation="칼선 벡터 경로를 생성/업로드하세요.",
                auto_fixable=False,
            )
        )
    else:
        report.add(
            PreflightIssue(
                code="CUTLINE_OK",
                level=PreflightLevel.PASS,
                message="칼선 데이터가 제공되었습니다.",
            )
        )


def _check_white_ink(data: PreflightInput, report: PreflightReport) -> None:
    caps = _capabilities_of(data.profile)
    if Capability.WHITE_INK_PRINT.value not in caps:
        return
    if not data.white_layer_provided:
        report.add(
            PreflightIssue(
                code="WHITE_INK_LAYER_MISSING",
                level=PreflightLevel.ERROR,
                message=f"'{data.profile.product_name}' 상품은 화이트 잉크 레이어가 필요하지만 생성되지 않았습니다.",
                recommendation="화이트 레이어 생성 규칙(white_ink_rule)에 따라 레이어를 생성하세요.",
                auto_fixable=False,
            )
        )
    else:
        report.add(
            PreflightIssue(
                code="WHITE_INK_OK",
                level=PreflightLevel.PASS,
                message="화이트 잉크 레이어가 제공되었습니다.",
            )
        )


def _check_front_back(data: PreflightInput, report: PreflightReport) -> None:
    caps = _capabilities_of(data.profile)
    if Capability.DOUBLE_SIDE_PRINT.value not in caps:
        return
    if not data.back_image_provided:
        report.add(
            PreflightIssue(
                code="BACK_SIDE_MISSING",
                level=PreflightLevel.ERROR,
                message=f"'{data.profile.product_name}' 상품은 양면 인쇄가 필요하지만 뒷면 이미지가 제공되지 않았습니다.",
                recommendation="뒷면 디자인 이미지를 업로드하세요.",
                auto_fixable=False,
            )
        )
    else:
        report.add(
            PreflightIssue(
                code="FRONT_BACK_OK",
                level=PreflightLevel.PASS,
                message="앞/뒷면 이미지가 모두 제공되었습니다.",
            )
        )


def _check_unimplemented_vector_checks(data: PreflightInput, report: PreflightReport) -> None:
    """
    Spot Color / Minimum Stroke / Minimum Text Size 검사는 벡터(텍스트/패스) 메타데이터가
    필요하지만, 현재 엔진은 래스터 이미지만 처리한다. 검사를 통과한 것처럼 속이지 않고,
    "아직 구현되지 않음"을 명시적으로 알린다 (해당 capability가 있는 상품에 한해).
    """
    caps = _capabilities_of(data.profile)
    needs_vector_checks = Capability.CUTLINE_PRINT.value in caps or Capability.NO_PRINT_CUTTING.value in caps
    if not needs_vector_checks:
        return
    report.add(
        PreflightIssue(
            code="VECTOR_CHECKS_NOT_IMPLEMENTED",
            level=PreflightLevel.WARNING,
            message=(
                "Spot Color / 최소 선굵기(Minimum Stroke) / 최소 글자크기(Minimum Text Size) "
                "검사는 벡터 데이터 처리 엔진이 아직 구현되지 않아 자동 검사되지 않았습니다."
            ),
            recommendation="제작 전 디자이너가 수동으로 확인하세요. (v1.5+ 벡터 엔진 구현 후 자동화 예정)",
            auto_fixable=False,
        )
    )
