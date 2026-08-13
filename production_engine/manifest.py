"""
manifest.py
-------------
Production Manifest 조립기.

최종 PDF와 함께 남기는 production_manifest.json 에는 다음이 기록되어야 한다
(작업지시서 7번 요구사항):
  - 상품규격 (사이즈, bleed, safe margin, 색상모드, ICC, PDF 표준, 후가공)
  - 원본파일 (파일명, 픽셀크기, 포맷, 용량, 알파채널 여부)
  - DPI (실효 DPI, 업스케일 배율)
  - 색상 (최종 색상모드, ICC 적용 여부)
  - 후가공 (아일렛 정책 + 실제 계산된 mm 좌표)
  - Preflight (PASS/WARNING/ERROR 전체 결과 + 개별 이슈 전부)
  - 출력파일 (실제 물리적 mm 크기, TrimBox/MediaBox 대응 값, PDF/X 인증 여부 - 항상 정직하게)
  - Job Ticket (있는 경우)

이 모듈은 PipelineContext 와 PreflightReport 를 받아 순수 dict 로 조립하고,
JSON 파일로 저장하는 것까지 담당한다. 웹 프레임워크에 종속되지 않는다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from .imaging.dpi import calculate_effective_dpi
from .models import JobTicket, PreflightReport

MANIFEST_VERSION = "1.0"


def build_production_manifest(ctx, report: PreflightReport, job_ticket: Optional[JobTicket] = None) -> dict:
    """PipelineContext(순환 import 방지를 위해 타입힌트는 생략) + PreflightReport -> dict."""
    profile = ctx.profile
    job = ctx.job
    vf = ctx.validated_file

    manifest: dict = {
        "manifest_version": MANIFEST_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "job_id": job.job_id,
        "product": {
            "product_id": profile.product_id,
            "product_name": profile.product_name,
            "category": profile.category,
            "width_mm": job.output_width_mm,
            "height_mm": job.output_height_mm,
            "custom_size_allowed": profile.custom_size_allowed,
            "bleed_mm": profile.safe_zone.bleed_mm,
            "safe_margin_mm": profile.safe_zone.safe_margin_mm,
            "extra_margin_by_edge_mm": profile.safe_zone.extra_margin_by_edge_mm,
            "color_mode": profile.color_mode_target,
            "icc_profile": profile.icc_profile_name,
            "pdf_standard": profile.pdf_standard,
            "finishing": profile.finishing,
        },
        "source_file": None,
        "dpi": None,
        "color": {
            "mode": "CMYK" if ctx.cmyk_path else "RGB",
            "icc_applied": ctx.icc_applied,
            "icc_profile_name": ctx.icc_profile_name,
        },
        "eyelet": {
            "enabled": profile.eyelet.enabled,
            "diameter_mm": profile.eyelet.diameter_mm,
            "margin_mm": profile.eyelet.margin_mm,
            "interval_mm": profile.eyelet.interval_mm,
            "placement_policy": profile.eyelet.placement_policy.value,
            "points": [
                {"x_mm": p.x_mm, "y_mm": p.y_mm, "edge": p.edge}
                for p in (getattr(ctx, "eyelet_points", None) or [])
            ],
        },
        "preflight": {
            "overall": report.overall.value,
            "issues": [i.to_dict() for i in report.issues],
        },
        "output_file": None,
        "job_ticket": job_ticket.to_dict() if job_ticket else None,
        # v1.5 작업지시서 3번: 관리자 강제 출력 여부/사유는 항상 manifest 에 기록한다.
        "export_control": {
            "forced": getattr(ctx, "export_forced", False),
            "authorized_by": getattr(ctx, "export_override", None).authorized_by if getattr(ctx, "export_override", None) else None,
            "reason": getattr(ctx, "export_override", None).reason if getattr(ctx, "export_override", None) else None,
            "overridden_issue_codes": list(getattr(ctx, "export_overridden_issue_codes", []) or []),
        },
    }

    if vf is not None:
        manifest["source_file"] = {
            "filename": vf.original_filename,
            "width_px": vf.width_px,
            "height_px": vf.height_px,
            "format": vf.detected_format.value,
            "size_bytes": vf.size_bytes,
            "has_alpha": vf.has_alpha,
        }
        dpi_result = calculate_effective_dpi(
            vf.width_px, vf.height_px, job.output_width_mm, job.output_height_mm
        )
        manifest["dpi"] = {
            "effective_dpi_x": round(dpi_result.dpi_x, 2),
            "effective_dpi_y": round(dpi_result.dpi_y, 2),
            "min_dpi": round(dpi_result.min_dpi, 2),
            "upscale_factor": round(ctx.upscale_factor, 4),
        }

    pdf_result = getattr(ctx, "pdf_build_result", None)
    if pdf_result is not None:
        manifest["output_file"] = {
            "path": pdf_result.output_path,
            "trim_size_mm": list(pdf_result.trim_size_mm),
            "media_size_mm": list(pdf_result.media_size_mm),
            "bleed_mm": pdf_result.bleed_mm,
            "pdf_standard": pdf_result.pdf_standard,
            # 정직성 원칙: 실제 전문 검증 도구를 통과하지 않았다면 항상 False.
            "pdf_x_compliant": pdf_result.pdf_x_compliant,
            "compliance_note": pdf_result.compliance_note,
            "output_intent_embedded": pdf_result.output_intent_embedded,
            "pikepdf_used": pdf_result.pikepdf_used,
        }

    return manifest


def write_production_manifest(path: str, manifest: dict) -> str:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return path
