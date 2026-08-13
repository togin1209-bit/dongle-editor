"""
pdf/cmyk.py
-------------
RGB -> CMYK 변환.

정직하게 밝혀야 할 한계:
- Pillow의 기본 `img.convert("CMYK")` 는 ICC 프로파일을 전혀 고려하지 않는 "naive" 변환이다.
  (단순 수식 변환 - 실제 인쇄 색상과 상당히 다르게 나올 수 있음)
- 색상 정확도가 중요한 인쇄용 변환은 반드시 ICC 프로파일 기반 변환
  (PIL.ImageCms.profileToProfile) 을 사용해야 하며, 이를 위해서는
  1) 입력 프로파일 (보통 sRGB.icc)
  2) 목표 프로파일 (인쇄소가 지정한 CMYK 프로파일, 예: JapanColor2001Coated.icc)
  이 실제 .icc 파일로 시스템에 존재해야 한다.
- 이 프로파일 파일들은 이 저장소에 포함되어 있지 않다 (라이선스/용량 문제 + 인쇄소별로 다름).
  따라서 이 모듈은:
    a) ICC 프로파일 경로가 주어지면 정확한 변환을 수행하고
    b) 주어지지 않으면 naive 변환을 수행하되 "ICC_NOT_APPLIED" 를 결과에 명시하여
       preflight 단계에서 반드시 경고가 뜨도록 한다.
  즉, "임시 구현을 완성된 것처럼" 숨기지 않는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from PIL import Image

try:
    from PIL import ImageCms
    _IMAGECMS_AVAILABLE = True
except ImportError:  # Pillow가 littlecms 없이 빌드된 경우
    _IMAGECMS_AVAILABLE = False


@dataclass
class CmykConversionResult:
    output_path: str
    icc_applied: bool
    icc_profile_name: Optional[str]
    method: str  # "icc_profile_to_profile" | "naive_convert"


def convert_to_cmyk(
    source_path: str,
    dest_path: str,
    input_icc_path: Optional[str] = None,
    output_icc_path: Optional[str] = None,
    output_icc_name: Optional[str] = None,
) -> CmykConversionResult:
    """
    이미지를 CMYK로 변환한다.

    input_icc_path / output_icc_path 가 둘 다 주어지고 실제 파일이 존재하면
    ICC 기반 정밀 변환을 수행한다. 그렇지 않으면 naive 변환으로 폴백한다.
    """
    use_icc = (
        _IMAGECMS_AVAILABLE
        and input_icc_path
        and output_icc_path
        and os.path.isfile(input_icc_path)
        and os.path.isfile(output_icc_path)
    )

    with Image.open(source_path) as img:
        img.load()
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        elif img.mode == "RGBA":
            # CMYK는 알파 채널을 지원하지 않으므로 흰 배경에 합성한다.
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background

        if use_icc:
            src_profile = ImageCms.ImageCmsProfile(input_icc_path)
            dst_profile = ImageCms.ImageCmsProfile(output_icc_path)
            cmyk_img = ImageCms.profileToProfile(
                img,
                src_profile,
                dst_profile,
                renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
                outputMode="CMYK",
            )
            cmyk_img.save(dest_path)
            return CmykConversionResult(
                output_path=dest_path,
                icc_applied=True,
                icc_profile_name=output_icc_name,
                method="icc_profile_to_profile",
            )
        else:
            # Naive 변환: 색상 정확도를 보장하지 않는다. preflight 에서 반드시 경고되어야 한다.
            cmyk_img = img.convert("CMYK")
            cmyk_img.save(dest_path)
            return CmykConversionResult(
                output_path=dest_path,
                icc_applied=False,
                icc_profile_name=None,
                method="naive_convert",
            )
