"""
vision/contour_engine.py
---------------------------
v1.6: Acrylic Keyring Auto Contour Pipeline (작업지시서 1번).

투명 PNG(Alpha Channel) -> Alpha mask -> 외곽 contour -> cleanup -> smoothing ->
offset -> production cutline 을 순서대로 처리하는 실제 동작 파이프라인.

라이브러리: OpenCV(cv2) 로 구현했다. shapely/pyclipper 같은 전용 폴리곤 오프셋
라이브러리는 이 환경에 설치되어 있지 않아(네트워크 차단), **오프셋은 형태학적
(morphological) 방식**으로 구현했다 - 마스크를 원형 커널로 dilate(외곽 확장)/erode
(내측 축소)한 뒤 다시 contour를 추출하는 방식이다. 이는 실무에서도 널리 쓰이는
레이저커팅 오프셋 근사법이며, 별도 라이브러리 없이 코너를 자연스럽게 라운딩 처리하는
장점이 있다 (단, 아주 날카로운 뾰족점은 커널 해상도에 따라 약간 뭉툭해질 수 있음 -
이 한계는 README/보고서에 명시한다).

모든 좌표는 최종적으로 mm 단위로 변환되어 반환된다 (dpi 파라미터로 px<->mm 환산).
칼선 오프셋 값(offset_mm), 최소 곡률 반경(min_radius_mm) 등은 전부 호출자가
ProductProfile 에서 읽어 전달해야 한다 - 이 모듈 내부에는 어떤 제작수치도
하드코딩되어 있지 않다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

MM_PER_INCH = 25.4


class ContourEngineError(Exception):
    pass


# ---------------------------------------------------------------------------
# 좌표/도형 표현
# ---------------------------------------------------------------------------

@dataclass
class CornerInfo:
    index: int
    x_mm: float
    y_mm: float
    convex: bool
    interior_angle_deg: float
    radius_mm: Optional[float] = None


@dataclass
class SelfIntersection:
    segment_a: tuple[int, int]   # (point_index, next_point_index)
    segment_b: tuple[int, int]
    x_mm: float
    y_mm: float


@dataclass
class ContourAnalysis:
    total_raw_contours: int
    islands_removed: int
    corners: list[CornerInfo] = field(default_factory=list)
    self_intersections: list[SelfIntersection] = field(default_factory=list)
    corners_below_min_radius: list[int] = field(default_factory=list)  # corner index 목록


@dataclass
class ProductionCutline:
    points_mm: list[tuple[float, float]]           # 닫힌 폴리곤 (외곽, 오프셋 적용됨)
    artwork_points_mm: list[tuple[float, float]]     # 오프셋 적용 전 원본 artwork 외곽선 (참고용)
    holes_mm: list[list[tuple[float, float]]]         # artwork 내부에 있던 구멍(내곽) - 오프셋 미적용, 원본 그대로
    analysis: ContourAnalysis
    offset_mm: float
    image_width_px: int
    image_height_px: int
    dpi: float


# ---------------------------------------------------------------------------
# 1단계: Alpha mask
# ---------------------------------------------------------------------------

def alpha_to_mask(rgba: np.ndarray, alpha_threshold: int = 128) -> np.ndarray:
    """RGBA numpy 배열(H,W,4) -> 이진 마스크(H,W, uint8, 0 또는 255)."""
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ContourEngineError(
            f"RGBA 이미지가 필요합니다 (H,W,4). 받은 shape: {rgba.shape}. "
            "알파 채널이 없는 이미지(RGB/JPEG 등)로는 외곽 컨투어를 자동 추출할 수 없습니다."
        )
    alpha = rgba[:, :, 3]
    mask = np.where(alpha >= alpha_threshold, 255, 0).astype(np.uint8)
    if not np.any(mask):
        raise ContourEngineError("알파 채널이 전부 투명합니다 - 추출할 형태가 없습니다.")
    return mask


# ---------------------------------------------------------------------------
# 2단계: Contour 추출 (multiple contour + hole 지원)
# ---------------------------------------------------------------------------

def extract_contours(mask: np.ndarray) -> tuple[list[np.ndarray], np.ndarray]:
    """
    RETR_CCOMP 로 외곽(레벨0)과 구멍(레벨1)을 모두 찾는다.
    반환: (contours, hierarchy). hierarchy[i] = [next, prev, first_child, parent]
    parent == -1 인 것이 외곽 컨투어(=독립된 island), parent != -1 인 것이 구멍이다.
    """
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise ContourEngineError("마스크에서 어떤 컨투어도 찾지 못했습니다.")
    return list(contours), hierarchy[0] if hierarchy is not None else np.empty((0, 4))


def remove_tiny_islands(
    contours: list[np.ndarray], hierarchy: np.ndarray, min_area_px: float
) -> tuple[list[np.ndarray], np.ndarray, int]:
    """
    외곽(부모==-1) 컨투어 중 면적이 min_area_px 미만인 것을 노이즈로 간주해 제거한다.
    (예: 안티에일리어싱 잔여 픽셀, 저장 시 생긴 미세 얼룩 등)
    구멍(부모!=-1)은 이 필터를 적용하지 않는다 - 작은 구멍이라도 디자인 의도일 수 있다.
    반환: (남은 contours, 남은 hierarchy, 제거된 개수)
    """
    keep_idx = []
    removed = 0
    for i, c in enumerate(contours):
        is_outer = hierarchy[i][3] == -1
        area = cv2.contourArea(c)
        if is_outer and area < min_area_px:
            removed += 1
            continue
        keep_idx.append(i)
    new_contours = [contours[i] for i in keep_idx]
    new_hierarchy = hierarchy[keep_idx] if len(keep_idx) else np.empty((0, 4))
    return new_contours, new_hierarchy, removed


# ---------------------------------------------------------------------------
# 3단계: 단순화(simplify) + 스무딩(smooth)
# ---------------------------------------------------------------------------

def simplify_contour(contour: np.ndarray, epsilon_ratio: float = 0.002) -> np.ndarray:
    """cv2.approxPolyDP 로 포인트 수를 줄인다. epsilon_ratio 는 둘레 길이에 대한 비율."""
    perimeter = cv2.arcLength(contour, True)
    epsilon = max(0.5, epsilon_ratio * perimeter)  # 최소 0.5px - 완전히 없애지 않도록
    simplified = cv2.approxPolyDP(contour, epsilon, True)
    return simplified.reshape(-1, 2).astype(np.float64)


def smooth_contour(points: np.ndarray, window: int = 5) -> np.ndarray:
    """닫힌 폴리곤에 대해 순환(circular) 이동평균 스무딩을 적용한다.
    window 는 홀수여야 코너가 대칭적으로 부드러워진다."""
    n = len(points)
    if n < window:
        return points
    if window % 2 == 0:
        window += 1
    half = window // 2
    padded = np.vstack([points[-half:], points, points[:half]])
    kernel = np.ones(window) / window
    smoothed_x = np.convolve(padded[:, 0], kernel, mode="valid")
    smoothed_y = np.convolve(padded[:, 1], kernel, mode="valid")
    return np.stack([smoothed_x, smoothed_y], axis=1)


# ---------------------------------------------------------------------------
# 4단계: Offset (형태학적 방식)
# ---------------------------------------------------------------------------

def offset_mask(mask: np.ndarray, offset_px: float) -> np.ndarray:
    """
    마스크를 offset_px 만큼 형태학적으로 확장(양수, dilate)하거나 축소(음수, erode)한다.
    원형(circular) 구조 요소를 써서 코너가 자연스럽게 라운딩된다 - 이것이 이 방식의
    핵심 특성이자, 동시에 한계이기도 하다 (아주 날카로운 뾰족점을 완벽히 보존하지 못함).
    """
    radius = max(1, round(abs(offset_px)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    if offset_px > 0:
        return cv2.dilate(mask, kernel)
    elif offset_px < 0:
        return cv2.erode(mask, kernel)
    return mask.copy()


# ---------------------------------------------------------------------------
# 5단계: 코너 분류(concave/convex), 자기교차 검출, 최소 반경 검증
# ---------------------------------------------------------------------------

def classify_corners(points_mm: np.ndarray) -> list[CornerInfo]:
    """각 정점에서 인접 두 변의 외적 부호로 convex/concave 를 판정한다.
    폴리곤이 시계방향인지 반시계방향인지에 무관하게, 다수결로 '기준 부호'를 정해
    상대적으로 일관되게 분류한다."""
    n = len(points_mm)
    if n < 3:
        return []

    cross_signs = []
    for i in range(n):
        p_prev = points_mm[(i - 1) % n]
        p_curr = points_mm[i]
        p_next = points_mm[(i + 1) % n]
        v1 = p_curr - p_prev
        v2 = p_next - p_curr
        cross = v1[0] * v2[1] - v1[1] * v2[0]
        cross_signs.append(cross)

    positive_count = sum(1 for c in cross_signs if c > 0)
    dominant_sign = 1 if positive_count >= n / 2 else -1

    corners = []
    for i in range(n):
        p_prev = points_mm[(i - 1) % n]
        p_curr = points_mm[i]
        p_next = points_mm[(i + 1) % n]
        v1 = p_curr - p_prev
        v2 = p_next - p_curr
        cross = cross_signs[i]
        convex = (cross * dominant_sign) >= 0

        # 내각 계산 (참고 정보)
        a = p_prev - p_curr
        b = p_next - p_curr
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na < 1e-9 or nb < 1e-9:
            angle_deg = 180.0
        else:
            cos_angle = np.clip(np.dot(a, b) / (na * nb), -1.0, 1.0)
            angle_deg = float(np.degrees(np.arccos(cos_angle)))

        radius_mm = _circumradius(p_prev, p_curr, p_next)

        corners.append(
            CornerInfo(
                index=i, x_mm=float(p_curr[0]), y_mm=float(p_curr[1]),
                convex=bool(convex), interior_angle_deg=angle_deg, radius_mm=radius_mm,
            )
        )
    return corners


def _circumradius(p1: np.ndarray, p2: np.ndarray, p3: np.ndarray) -> Optional[float]:
    """세 점(p1,p2,p3)으로 이루어진 삼각형의 외접원 반지름 - p2 지점의 국소 곡률 반경 근사치."""
    a = np.linalg.norm(p2 - p3)
    b = np.linalg.norm(p1 - p3)
    c = np.linalg.norm(p1 - p2)
    area2 = abs((p2[0] - p1[0]) * (p3[1] - p1[1]) - (p3[0] - p1[0]) * (p2[1] - p1[1]))
    if area2 < 1e-9:
        return None  # 세 점이 거의 일직선 -> 곡률 거의 0 (반경 무한대) -> 문제 없음으로 취급
    return float((a * b * c) / (2 * area2))


def validate_minimum_radius(corners: list[CornerInfo], min_radius_mm: float) -> list[int]:
    """min_radius_mm 보다 국소 곡률 반경이 작은 코너의 index 목록을 반환한다.
    radius_mm 가 None(직선에 가까움)인 코너는 문제 없음으로 간주한다."""
    violations = []
    for c in corners:
        if c.radius_mm is not None and c.radius_mm < min_radius_mm:
            violations.append(c.index)
    return violations


def detect_self_intersections(points_mm: np.ndarray) -> list[SelfIntersection]:
    """
    폴리곤 변들 사이의 자기교차를 O(n^2) 로 검사한다 (단순화 이후라 n이 크지 않음을 전제).
    인접 변(공유 정점이 있는 변)은 검사에서 제외한다.
    """
    n = len(points_mm)
    if n < 4:
        return []
    intersections = []
    for i in range(n):
        a1, a2 = points_mm[i], points_mm[(i + 1) % n]
        for j in range(i + 1, n):
            # 인접하거나 동일한 변은 제외
            if j == i or (j + 1) % n == i or (i + 1) % n == j:
                continue
            b1, b2 = points_mm[j], points_mm[(j + 1) % n]
            pt = _segment_intersection(a1, a2, b1, b2)
            if pt is not None:
                intersections.append(
                    SelfIntersection(
                        segment_a=(i, (i + 1) % n), segment_b=(j, (j + 1) % n),
                        x_mm=float(pt[0]), y_mm=float(pt[1]),
                    )
                )
    return intersections


def _segment_intersection(p1, p2, p3, p4) -> Optional[np.ndarray]:
    """두 선분 (p1,p2), (p3,p4) 의 교차점을 반환 (없으면 None). 끝점 공유는 교차로 치지 않는다."""
    d1 = p2 - p1
    d2 = p4 - p3
    denom = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(denom) < 1e-9:
        return None  # 평행
    t = ((p3[0] - p1[0]) * d2[1] - (p3[1] - p1[1]) * d2[0]) / denom
    u = ((p3[0] - p1[0]) * d1[1] - (p3[1] - p1[1]) * d1[0]) / denom
    eps = 1e-6
    if eps < t < 1 - eps and eps < u < 1 - eps:
        return p1 + t * d1
    return None


# ---------------------------------------------------------------------------
# 전체 파이프라인
# ---------------------------------------------------------------------------

def build_production_cutline(
    rgba: np.ndarray,
    dpi: float,
    offset_mm: float,
    min_island_area_mm2: float = 1.0,
    min_radius_mm: Optional[float] = None,
    alpha_threshold: int = 128,
    epsilon_ratio: float = 0.002,
    smooth_window: int = 5,
) -> ProductionCutline:
    """
    Artwork(RGBA) -> Alpha mask -> contour -> cleanup -> smoothing -> offset ->
    production cutline 전체 파이프라인.

    모든 제작 수치(offset_mm, min_radius_mm 등)는 호출자가 ProductProfile 에서 읽어
    전달해야 한다 - 여기서는 하드코딩된 기본 제작값을 쓰지 않는다.
    """
    height_px, width_px = rgba.shape[0], rgba.shape[1]
    px_per_mm = dpi / MM_PER_INCH

    mask = alpha_to_mask(rgba, alpha_threshold=alpha_threshold)
    raw_contours, hierarchy = extract_contours(mask)

    min_island_area_px = min_island_area_mm2 * (px_per_mm ** 2)
    contours, hierarchy, islands_removed = remove_tiny_islands(raw_contours, hierarchy, min_island_area_px)

    if not contours:
        raise ContourEngineError(
            "노이즈 제거 후 남은 컨투어가 없습니다. min_island_area_mm2 값이 너무 크거나 "
            "원본 이미지에 유효한 형태가 없습니다."
        )

    # 가장 면적이 큰 외곽(부모==-1) 컨투어를 메인 바디로 선택 (multiple contour 중 대표).
    outer_indices = [i for i in range(len(contours)) if hierarchy[i][3] == -1]
    main_idx = max(outer_indices, key=lambda i: cv2.contourArea(contours[i]))
    main_contour = contours[main_idx]

    # 구멍(hole, 부모==main_idx 원본 인덱스 매핑 필요 -> 재계산된 hierarchy 기준으로 자식 찾기)
    hole_contours = [contours[i] for i in range(len(contours)) if hierarchy[i][3] == main_idx]

    artwork_points_px = simplify_contour(main_contour, epsilon_ratio=epsilon_ratio)
    artwork_points_mm = artwork_points_px / px_per_mm

    # 오프셋은 마스크 레벨에서 수행 (자연스러운 코너 처리를 위해)
    offset_px = offset_mm * px_per_mm
    if abs(offset_px) > 1e-6:
        single_contour_mask = np.zeros_like(mask)
        cv2.drawContours(single_contour_mask, [main_contour], -1, 255, thickness=cv2.FILLED)
        offset_result_mask = offset_mask(single_contour_mask, offset_px)
        offset_contours, offset_hierarchy = extract_contours(offset_result_mask)
        offset_outer = [i for i in range(len(offset_contours)) if offset_hierarchy[i][3] == -1]
        if not offset_outer:
            raise ContourEngineError("오프셋 적용 후 유효한 외곽선을 찾지 못했습니다 (offset_mm 값을 확인하세요).")
        offset_main_idx = max(offset_outer, key=lambda i: cv2.contourArea(offset_contours[i]))
        dense_cutline_px = offset_contours[offset_main_idx].reshape(-1, 2).astype(np.float64)
    else:
        dense_cutline_px = main_contour.reshape(-1, 2).astype(np.float64)

    # 중요: 스무딩은 반드시 "단순화(simplify) 이전", 점 밀도가 높은 원본 컨투어에 적용해야
    # 한다. 단순화로 점 개수가 10~20개 수준으로 줄어든 뒤에 고정 window로 이동평균을
    # 적용하면, 오목(concave) 꼭짓점 같은 국소적 형태가 통째로 뭉개져 사라진다
    # (별 모양 검증 테스트에서 실제로 발견/수정한 버그 - tests/ 참고).
    dense_cutline_mm = dense_cutline_px / px_per_mm
    dense_cutline_mm = smooth_contour(dense_cutline_mm, window=smooth_window)

    cutline_points_mm = simplify_contour(
        (dense_cutline_mm * px_per_mm).astype(np.float32).reshape(-1, 1, 2), epsilon_ratio=epsilon_ratio
    ) / px_per_mm

    corners = classify_corners(cutline_points_mm)
    self_intersections = detect_self_intersections(cutline_points_mm)
    below_min_radius = (
        validate_minimum_radius(corners, min_radius_mm) if min_radius_mm is not None else []
    )

    holes_mm = []
    for hc in hole_contours:
        hole_simplified_px = simplify_contour(hc, epsilon_ratio=epsilon_ratio)
        holes_mm.append([(float(x), float(y)) for x, y in (hole_simplified_px / px_per_mm)])

    analysis = ContourAnalysis(
        total_raw_contours=len(raw_contours),
        islands_removed=islands_removed,
        corners=corners,
        self_intersections=self_intersections,
        corners_below_min_radius=below_min_radius,
    )

    return ProductionCutline(
        points_mm=[(float(x), float(y)) for x, y in cutline_points_mm],
        artwork_points_mm=[(float(x), float(y)) for x, y in artwork_points_mm],
        holes_mm=holes_mm,
        analysis=analysis,
        offset_mm=offset_mm,
        image_width_px=width_px,
        image_height_px=height_px,
        dpi=dpi,
    )
