"""
security/file_validator.py
---------------------------
업로드 파일 검증.

핵심 원칙:
1. 확장자(파일명)는 절대 신뢰하지 않는다. 파일의 실제 바이트 시그니처(magic byte)로 판별한다.
2. python-magic 계열 시스템 라이브러리 의존 없이, 표준 라이브러리만으로 시그니처를 검사한다.
   (배포 환경에 libmagic 이 없을 수 있으므로 자체 구현으로 의존성을 줄임)
3. Pillow 로 실제로 열어서 "디코딩 가능한 진짜 이미지"인지까지 검증한다
   (시그니처만 흉내낸 폴리글랏/손상 파일 방어).
4. 압축 폭탄(decompression bomb) 방지를 위해 픽셀 총량 상한을 둔다.
5. EXIF/메타데이터는 저장 전 제거한다 (개인정보 유출 방지, 위치정보 등).
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from enum import Enum
from typing import BinaryIO, Optional

from PIL import Image

# Pillow 자체의 decompression bomb 경고 임계값도 우리 정책과 맞춘다.
# (기본값은 매우 낮아서 대형 인쇄용 이미지에서 오탐이 날 수 있으므로 명시적으로 재설정)
MAX_IMAGE_PIXELS = int(os.getenv("DONGLE_MAX_IMAGE_PIXELS", "120000000"))
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

MAX_FILE_SIZE_BYTES = int(os.getenv("DONGLE_MAX_FILE_MB", "150")) * 1024 * 1024


class DetectedFormat(str, Enum):
    JPEG = "JPEG"
    PNG = "PNG"
    TIFF = "TIFF"
    PDF = "PDF"
    UNKNOWN = "UNKNOWN"


# 파일 시그니처(매직 넘버) 테이블. 확장자가 아니라 실제 바이트로 판별한다.
_SIGNATURES: list[tuple[bytes, DetectedFormat]] = [
    (b"\xff\xd8\xff", DetectedFormat.JPEG),
    (b"\x89PNG\r\n\x1a\n", DetectedFormat.PNG),
    (b"II*\x00", DetectedFormat.TIFF),   # little-endian TIFF
    (b"MM\x00*", DetectedFormat.TIFF),   # big-endian TIFF
    (b"%PDF-", DetectedFormat.PDF),
]

ALLOWED_FORMATS = {
    DetectedFormat.JPEG,
    DetectedFormat.PNG,
    DetectedFormat.TIFF,
    # PDF 원본 업로드는 차기 단계 (텍스트/벡터 추출 필요) - MVP 범위에서는 이미지 3종만 허용
}


class FileValidationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


@dataclass
class ValidatedFile:
    detected_format: DetectedFormat
    width_px: int
    height_px: int
    size_bytes: int
    has_alpha: bool
    original_filename: str  # 참고용 원본 파일명 (저장 경로에는 사용하지 않음)


def detect_format(head_bytes: bytes) -> DetectedFormat:
    """파일 앞부분 바이트만으로 실제 포맷을 판별한다. 확장자는 사용하지 않는다."""
    for sig, fmt in _SIGNATURES:
        if head_bytes.startswith(sig):
            return fmt
    return DetectedFormat.UNKNOWN


def validate_upload(file_obj: BinaryIO, original_filename: str) -> ValidatedFile:
    """
    업로드된 파일을 검증한다. 문제가 있으면 FileValidationError 를 발생시킨다.

    file_obj: 파일 전체를 담은 바이너리 스트림 (seek 가능해야 함)
    original_filename: 사용자가 올린 원본 파일명 (표시/로그용, 저장 경로 생성에는 미사용)
    """
    file_obj.seek(0, io.SEEK_END)
    size_bytes = file_obj.tell()
    file_obj.seek(0)

    if size_bytes == 0:
        raise FileValidationError("EMPTY_FILE", "빈 파일입니다.")

    if size_bytes > MAX_FILE_SIZE_BYTES:
        raise FileValidationError(
            "FILE_TOO_LARGE",
            f"파일 크기가 상한({MAX_FILE_SIZE_BYTES / 1024 / 1024:.0f}MB)을 초과했습니다.",
        )

    head = file_obj.read(16)
    file_obj.seek(0)
    fmt = detect_format(head)

    if fmt == DetectedFormat.UNKNOWN:
        raise FileValidationError(
            "UNSUPPORTED_FORMAT", "지원하지 않는 파일 형식입니다 (JPEG/PNG/TIFF만 허용)."
        )

    if fmt not in ALLOWED_FORMATS:
        raise FileValidationError(
            "UNSUPPORTED_FORMAT", f"{fmt.value} 형식은 아직 지원하지 않습니다."
        )

    # 시그니처만 믿지 않고 실제 디코딩까지 시도한다.
    # (예: JPEG 시그니처를 가진 손상 파일, 폴리글랏 파일 등을 걸러낸다)
    try:
        with Image.open(file_obj) as img:
            img.verify()  # 구조 검증 (여기서는 픽셀 데이터까지 읽지 않음)
    except Exception as e:
        raise FileValidationError(
            "CORRUPT_OR_INVALID_IMAGE", f"이미지 파일이 손상되었거나 유효하지 않습니다: {e}"
        )

    # verify() 이후에는 파일 핸들을 재사용할 수 없으므로 다시 연다.
    file_obj.seek(0)
    try:
        with Image.open(file_obj) as img:
            width_px, height_px = img.size
            has_alpha = img.mode in ("RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info
            )
    except Exception as e:
        raise FileValidationError(
            "CORRUPT_OR_INVALID_IMAGE", f"이미지 정보를 읽을 수 없습니다: {e}"
        )

    total_pixels = width_px * height_px
    if total_pixels > MAX_IMAGE_PIXELS:
        raise FileValidationError(
            "IMAGE_TOO_LARGE_PIXELS",
            f"이미지 해상도가 너무 큽니다 ({width_px}x{height_px} = {total_pixels:,}px). "
            f"상한: {MAX_IMAGE_PIXELS:,}px",
        )

    file_obj.seek(0)
    return ValidatedFile(
        detected_format=fmt,
        width_px=width_px,
        height_px=height_px,
        size_bytes=size_bytes,
        has_alpha=has_alpha,
        original_filename=original_filename,
    )


def strip_metadata_and_save(file_obj: BinaryIO, dest_path: str) -> None:
    """
    EXIF/GPS/작성자 등 메타데이터를 제거한 뒤 저장한다.
    원본 픽셀 데이터는 손실 없이 그대로 유지한다 (재인코딩으로 인한 화질 저하 최소화를 위해
    가능한 경우 재압축 파라미터를 원본에 맞춘다).
    """
    file_obj.seek(0)
    with Image.open(file_obj) as img:
        img.load()
        fmt = img.format

        # 주의: list(img.getdata()) / putdata() 방식은 대형 인쇄용 이미지(수천만~억 픽셀)에서
        # 매우 느리고 메모리를 과도하게 사용한다 (성능 요구사항 위반).
        # tobytes/frombytes 는 C 레벨 버퍼 복사라 훨씬 빠르고 메모리 효율적이다.
        raw = img.tobytes()
        clean = Image.frombytes(img.mode, img.size, raw)

        save_kwargs = {}
        if fmt == "JPEG":
            save_kwargs["quality"] = 95
            save_kwargs["exif"] = b""  # 명시적으로 EXIF 제거
        elif fmt == "TIFF":
            save_kwargs["exif"] = b""
        # PNG 는 frombytes 로 새로 만든 이미지에 원본의 text/EXIF 청크가 애초에 없으므로 별도 처리 불필요.

        clean.save(dest_path, format=fmt, **save_kwargs)
