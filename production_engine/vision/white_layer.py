"""
vision/white_layer.py
------------------------
v1.6: WHITE Layer Generator (작업지시서 4번).

투명 아크릴 등 소재 위에서 색상이 제대로 발색하려면 Artwork 아래(또는 위) 화이트
잉크 레이어를 인쇄해야 한다. 이 모듈은 Alpha mask 기반으로 화이트 레이어 마스크를
생성한다.

- choke(음수 방향, 마스크를 살짝 축소): 화이트가 Artwork보다 삐져나와 테두리에 흰 띠가
  보이는 것을 방지하고 싶을 때 사용.
- spread(양수 방향, 마스크를 살짝 확장): 반대로 흰색이 완전히 덮이지 않고 가장자리에
  틈이 보이는 것을 방지하고 싶을 때 사용.
- choke/spread 값은 반드시 ProductProfile(white_choke_mm/white_spread_mm)에서 읽는다.
  둘 다 지정되면 choke를 우선 적용한 뒤 spread를 적용한다(순서는 설계 선택 - 문서화).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from .contour_engine import MM_PER_INCH, alpha_to_mask, offset_mask


class WhiteLayerError(Exception):
    pass


@dataclass
class WhiteLayerResult:
    mask: np.ndarray            # 최종 화이트 레이어 마스크 (H,W, uint8 0/255)
    choke_mm: float
    spread_mm: float
    coverage_ratio: float       # 원본 alpha 대비 화이트 영역 비율 (참고용 - 1.0 근접이 이상적)


def generate_white_layer(
    rgba: np.ndarray,
    dpi: float,
    choke_mm: Optional[float] = None,
    spread_mm: Optional[float] = None,
    alpha_threshold: int = 128,
) -> WhiteLayerResult:
    if choke_mm is None and spread_mm is None:
        raise WhiteLayerError(
            "choke_mm/spread_mm 이 모두 None 입니다 - Product Profile 에 white_choke_mm/"
            "white_spread_mm 값이 확인되지 않았다는 뜻입니다. 임의 기본값으로 화이트 레이어를 "
            "생성하지 않습니다 (needs_confirmation 상태에서는 생성을 보류하세요)."
        )

    px_per_mm = dpi / MM_PER_INCH
    mask = alpha_to_mask(rgba, alpha_threshold=alpha_threshold)
    original_area = float(np.count_nonzero(mask))

    result_mask = mask
    if choke_mm:
        result_mask = offset_mask(result_mask, -abs(choke_mm) * px_per_mm)
    if spread_mm:
        result_mask = offset_mask(result_mask, abs(spread_mm) * px_per_mm)

    new_area = float(np.count_nonzero(result_mask))
    coverage_ratio = (new_area / original_area) if original_area > 0 else 0.0

    return WhiteLayerResult(
        mask=result_mask,
        choke_mm=choke_mm or 0.0,
        spread_mm=spread_mm or 0.0,
        coverage_ratio=round(coverage_ratio, 4),
    )
