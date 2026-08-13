"""
vision/auto_repair.py
------------------------
v1.6: Auto Repair (작업지시서 6번).

**절대 원칙: 원본 파일은 변경하지 않는다. Working Copy(numpy 배열의 복사본)에서만
수정한다.** 이 모듈의 모든 함수는 입력 배열을 절대 in-place 로 건드리지 않고, 항상
새 배열을 반환한다 (.copy() 명시적으로 사용).

가능한 자동 복구:
  - tiny alpha noise: 알파 채널의 미세한 얼룩(고립된 소수 픽셀) 제거
  - small isolated contour: 노이즈성 작은 컨투어(섬) 제거 (contour_engine.remove_tiny_islands 재사용)
  - jagged contour: 거친 톱니 모양 컨투어 스무딩 (contour_engine.smooth_contour 재사용)
  - tiny hole: 아주 작은 내부 구멍(핀홀)을 메움
  - disconnected island: 원거리에 떨어진 작은 섬 제거 (메인 바디와 분리된 파편)

이 모듈은 "안전한 범위"만 자동 수정한다 - 즉 명백한 노이즈로 판단되는 것만 건드리고,
의도된 디자인일 가능성이 있는 요소(큰 구멍, 큰 별도 오브젝트)는 절대 건드리지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .contour_engine import alpha_to_mask


@dataclass
class RepairAction:
    code: str
    description: str
    count: int = 1


@dataclass
class AutoRepairResult:
    repaired_rgba: np.ndarray          # 새 배열 (원본과 다른 객체)
    actions: list[RepairAction] = field(default_factory=list)

    def summary(self) -> str:
        if not self.actions:
            return "복구할 문제가 없었습니다."
        return "; ".join(f"{a.description}({a.count}건)" for a in self.actions)


def auto_repair(
    rgba: np.ndarray,
    alpha_threshold: int = 128,
    min_noise_area_px: int = 9,
    min_hole_area_px: int = 9,
    morphology_kernel_px: int = 2,
) -> AutoRepairResult:
    """
    안전한 범위 내에서 alpha 채널 노이즈를 자동 복구한다.
    입력 rgba 는 절대 수정하지 않고, 항상 새 배열을 반환한다.
    """
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError("RGBA(H,W,4) 이미지가 필요합니다.")

    working = rgba.copy()  # 원본 보호 - 이후 모든 수정은 이 복사본에만 적용
    alpha = working[:, :, 3].copy()
    mask = alpha_to_mask(working, alpha_threshold=alpha_threshold)

    actions: list[RepairAction] = []

    # 1) tiny alpha noise / jagged edge: 작은 커널로 open(erode->dilate) 하여
    #    미세한 돌기/얼룩을 제거한다. 큰 형태에는 거의 영향이 없다.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (morphology_kernel_px * 2 + 1,) * 2)
    opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    removed_noise_px = int(np.count_nonzero(mask) - np.count_nonzero(opened))
    if removed_noise_px > 0:
        actions.append(RepairAction(code="TINY_ALPHA_NOISE_REMOVED", description="미세 알파 노이즈 제거", count=1))
    mask = opened

    # 2) small isolated contour / disconnected island: 연결요소 분석으로 작은 섬 제거.
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if num_labels > 2:  # 배경(0) + 메인 바디 하나만 있으면 num_labels==2
        # 가장 큰 컴포넌트(메인 바디)를 제외한 나머지 중, 작은 것만 제거
        areas = stats[1:, cv2.CC_STAT_AREA]  # 라벨 0은 배경이므로 제외
        main_label = 1 + int(np.argmax(areas))
        removed_islands = 0
        for label in range(1, num_labels):
            if label == main_label:
                continue
            area = stats[label, cv2.CC_STAT_AREA]
            if area < min_noise_area_px * 20:  # 메인 바디가 아닌데 작으면 노이즈로 간주
                mask[labels == label] = 0
                removed_islands += 1
        if removed_islands:
            actions.append(RepairAction(code="DISCONNECTED_ISLAND_REMOVED", description="분리된 작은 섬 제거", count=removed_islands))

    # 3) tiny hole: 마스크 내부의 작은 구멍(핀홀)을 채운다 (닫힘 연산 + 구멍 채우기).
    filled = mask.copy()
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    filled_holes = 0
    if hierarchy is not None:
        for i, c in enumerate(contours):
            is_hole = hierarchy[0][i][3] != -1  # 부모가 있으면 hole
            if is_hole and cv2.contourArea(c) < min_hole_area_px:
                cv2.drawContours(filled, [c], -1, 255, thickness=cv2.FILLED)
                filled_holes += 1
    if filled_holes:
        actions.append(RepairAction(code="TINY_HOLE_FILLED", description="미세 핀홀 메움", count=filled_holes))
    mask = filled

    # 최종 알파 채널 재구성: 마스크가 0인 곳은 완전 투명(0), 마스크가 255인 곳은 원래 알파값 유지
    # (완전 불투명으로 강제하지 않고, 원래의 그라데이션/안티에일리어싱 값은 보존한다)
    new_alpha = np.where(mask > 0, alpha, 0).astype(np.uint8)
    working[:, :, 3] = new_alpha

    return AutoRepairResult(repaired_rgba=working, actions=actions)
