"""
resize_engine.py
-------------------
v1.8: 자유 제작 사이즈 시스템 (작업지시서 1번).

**핵심 원칙**: 사이즈 변경은 "Canvas 크기만 바꾸는" 얕은 작업이 아니다. 이 모듈은
사이즈가 바뀔 때 실제로 다시 계산되어야 하는 것들을 명시적인 함수로 구현한다:

  - 사이즈 유효성 검증 (Product Profile min/max, custom_size_allowed)
  - 캔버스 종횡비 재계산
  - 기존 캔버스 객체의 "합리적인" 위치 재배치 (비례 스케일)
  - 아일렛 좌표 재계산 (finishing.eyelet_engine 재사용 - 이미 사이즈를 매번 새로
    받아 계산하도록 설계되어 있어 별도 캐시 무효화가 필요 없음)
  - Effective DPI 재계산 대상 여부 판단
  - 재계산 결과를 하나의 요약(ResizeRecalculationSummary)으로 묶어 반환

**이 모듈이 하지 않는 것**: 실제 Canvas 렌더링(Frontend), crop/resize 이미지 처리
(pipeline.prepare_working_image 가 담당), PDF 재생성(pipeline.build_pdf 가 담당).
이 모듈은 "사이즈 변경이라는 사건이 발생했을 때 무엇을, 어떤 순서로 다시 계산해야
하는지"를 정의하고, 객체 재배치처럼 다른 곳에 없는 새로운 계산만 직접 수행한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .finishing.eyelet_engine import calculate_eyelet_positions
from .imaging.dpi import calculate_effective_dpi
from .models import EyeletPoint, ProductProfile


class SizeChangeError(Exception):
    pass


class RepositionMode(str, Enum):
    PROPORTIONAL_STRETCH = "PROPORTIONAL_STRETCH"  # x/y 각각 독립적으로 비례 스케일 (구성 비율 유지, 형태는 늘어날 수 있음)
    PROPORTIONAL_UNIFORM = "PROPORTIONAL_UNIFORM"  # 가로/세로 중 더 작은 배율로 균일 스케일 후 중앙 정렬 (형태 유지, 여백 발생 가능)


@dataclass
class SizeValidationResult:
    valid: bool
    reason: Optional[str] = None
    allowed_range: Optional[str] = None


@dataclass
class SizePreset:
    label: str
    width_mm: float
    height_mm: float


@dataclass
class ObjectTransformMM:
    """Canvas 오브젝트 1개의 mm 좌표 (좌상단 기준). Frontend 가 현재 캔버스 상태를
    이 구조로 변환해 넘기면, 사이즈 변경 후 위치를 재계산해 동일 구조로 돌려준다."""

    object_id: str
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    rotation_deg: float = 0.0


@dataclass
class ResizeRecalculationSummary:
    old_size_mm: tuple[float, float]
    new_size_mm: tuple[float, float]
    old_aspect_ratio: float
    new_aspect_ratio: float
    bleed_mm: float
    safe_margin_mm: float
    eyelet_points: list[EyeletPoint]
    effective_dpi: Optional[dict]
    repositioned_object_count: int
    warnings: list[str] = field(default_factory=list)


def validate_custom_size(profile: ProductProfile, width_mm: float, height_mm: float) -> SizeValidationResult:
    """Product Profile 의 min/max 및 custom_size_allowed 규칙으로 사이즈를 검증한다."""
    if width_mm <= 0 or height_mm <= 0:
        return SizeValidationResult(valid=False, reason="가로/세로는 0보다 커야 합니다.")

    # 현수막 공식 범위: 방향 무관, 각 변 >=30mm, 짧은 변 <=1,800mm, 긴 변 <=49,100mm.
    if getattr(profile, "product_id", "") in {"hyeonsumak_outdoor", "banner"}:
        short_side=min(width_mm,height_mm); long_side=max(width_mm,height_mm)
        if width_mm>=30 and height_mm>=30 and short_side<=1800 and long_side<=49100:
            return SizeValidationResult(valid=True)
        return SizeValidationResult(valid=False, reason="현수막 제작 가능 범위를 벗어났습니다.", allowed_range="최소 30×30mm · 짧은 변 최대 1,800mm · 긴 변 최대 49,100mm")

    if profile.size_in_range(width_mm, height_mm):
        return SizeValidationResult(valid=True)

    if not profile.custom_size_allowed:
        allowed = f"{profile.width_mm}x{profile.height_mm}mm (고정 규격)"
        return SizeValidationResult(
            valid=False, reason="이 상품은 자유 사이즈를 지원하지 않습니다 (고정 규격).", allowed_range=allowed,
        )

    allowed = f"{profile.min_width_mm}~{profile.max_width_mm}mm(가로) x {profile.min_height_mm}~{profile.max_height_mm}mm(세로)"
    return SizeValidationResult(valid=False, reason="허용 범위를 벗어난 사이즈입니다.", allowed_range=allowed)


def resolve_presets(profile: ProductProfile) -> list[SizePreset]:
    """Product Profile 에 등록된 프리셋만 반환한다 (코드에 하드코딩하지 않음)."""
    return [SizePreset(**p) for p in profile.size_presets]


def reposition_objects(
    objects: list[ObjectTransformMM],
    old_width_mm: float,
    old_height_mm: float,
    new_width_mm: float,
    new_height_mm: float,
    mode: RepositionMode = RepositionMode.PROPORTIONAL_STRETCH,
) -> list[ObjectTransformMM]:
    """
    사이즈 변경 후 기존 객체의 위치/크기를 "합리적으로" 재배치한다.

    - PROPORTIONAL_STRETCH: 각 객체의 (x/old_width, y/old_height) 비율을 그대로
      새 캔버스에 적용한다. 캔버스가 늘어난 비율만큼 객체도 함께 늘어나(위치 간격
      비율은 보존) 구성 전체가 새 캔버스를 꽉 채운 상태를 유지한다.
    - PROPORTIONAL_UNIFORM: 가로/세로 스케일 중 작은 값으로 균일하게 축소/확대하고,
      중앙 정렬한다. 객체 간 형태(정비율)는 유지되지만 새 캔버스 전체를 채우지
      못하고 여백이 남을 수 있다.
    """
    if old_width_mm <= 0 or old_height_mm <= 0:
        raise SizeChangeError("이전 사이즈가 유효하지 않습니다 (0 이하).")

    scale_x = new_width_mm / old_width_mm
    scale_y = new_height_mm / old_height_mm

    if mode == RepositionMode.PROPORTIONAL_UNIFORM:
        uniform = min(scale_x, scale_y)
        offset_x = (new_width_mm - old_width_mm * uniform) / 2
        offset_y = (new_height_mm - old_height_mm * uniform) / 2
        result = []
        for obj in objects:
            result.append(ObjectTransformMM(
                object_id=obj.object_id,
                x_mm=obj.x_mm * uniform + offset_x,
                y_mm=obj.y_mm * uniform + offset_y,
                width_mm=obj.width_mm * uniform,
                height_mm=obj.height_mm * uniform,
                rotation_deg=obj.rotation_deg,
            ))
        return result

    # PROPORTIONAL_STRETCH (기본값)
    result = []
    for obj in objects:
        result.append(ObjectTransformMM(
            object_id=obj.object_id,
            x_mm=obj.x_mm * scale_x,
            y_mm=obj.y_mm * scale_y,
            width_mm=obj.width_mm * scale_x,
            height_mm=obj.height_mm * scale_y,
            rotation_deg=obj.rotation_deg,
        ))
    return result


def recalculate_for_new_size(
    profile: ProductProfile,
    old_width_mm: float,
    old_height_mm: float,
    new_width_mm: float,
    new_height_mm: float,
    objects: Optional[list[ObjectTransformMM]] = None,
    reposition_mode: RepositionMode = RepositionMode.PROPORTIONAL_STRETCH,
    source_width_px: Optional[int] = None,
    source_height_px: Optional[int] = None,
) -> tuple[SizeValidationResult, Optional[ResizeRecalculationSummary], list[ObjectTransformMM]]:
    """
    사이즈 변경 1건에 대해 검증 + 전체 재계산을 한 번에 수행하는 진입점.

    반환: (검증 결과, 재계산 요약 - 검증 실패 시 None, 재배치된 객체 목록 - 실패 시 빈 리스트)
    """
    validation = validate_custom_size(profile, new_width_mm, new_height_mm)
    if not validation.valid:
        return validation, None, []

    warnings: list[str] = []

    # 아일렛: finishing.eyelet_engine.calculate_eyelet_positions 는 사이즈를 인자로
    # 직접 받으므로, 새 사이즈로 다시 호출하는 것만으로 자동 재계산된다.
    eyelet_points: list[EyeletPoint] = []
    if profile.eyelet.enabled:
        eyelet_points = calculate_eyelet_positions(new_width_mm, new_height_mm, profile.eyelet)

    effective_dpi = None
    if source_width_px and source_height_px:
        dpi_result = calculate_effective_dpi(source_width_px, source_height_px, new_width_mm, new_height_mm)
        effective_dpi = {
            "dpi_x": round(dpi_result.dpi_x, 1), "dpi_y": round(dpi_result.dpi_y, 1),
            "min_dpi": round(dpi_result.min_dpi, 1),
        }
        if dpi_result.min_dpi < profile.dpi_error_below:
            warnings.append(f"새 사이즈 기준 실효 해상도({dpi_result.min_dpi:.1f} DPI)가 최소 기준 미만입니다.")

    repositioned = []
    if objects:
        repositioned = reposition_objects(objects, old_width_mm, old_height_mm, new_width_mm, new_height_mm, reposition_mode)

    summary = ResizeRecalculationSummary(
        old_size_mm=(old_width_mm, old_height_mm),
        new_size_mm=(new_width_mm, new_height_mm),
        old_aspect_ratio=round(old_width_mm / old_height_mm, 4),
        new_aspect_ratio=round(new_width_mm / new_height_mm, 4),
        bleed_mm=profile.safe_zone.bleed_mm,
        safe_margin_mm=profile.safe_zone.safe_margin_mm,
        eyelet_points=eyelet_points,
        effective_dpi=effective_dpi,
        repositioned_object_count=len(repositioned),
        warnings=warnings,
    )
    return validation, summary, repositioned
