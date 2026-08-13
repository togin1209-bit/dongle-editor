"""
pipeline.py
-------------
전체 Production 파이프라인 오케스트레이션.

이 모듈은 특정 웹 프레임워크(FastAPI/Flask 등)에 종속되지 않는다.
GPT 쪽 아키텍처에서 어떤 프레임워크를 쓰든, 이 클래스의 메서드를
엔드포인트 핸들러에서 호출하기만 하면 된다.

흐름:
  1. create_job()            - 상품 프로필 + 주문 사이즈로 Job 생성 (job 폴더 격리)
  2. ingest_upload()         - 업로드 파일 보안 검증 -> 원본 보존 저장 (EXIF 제거)
  3. prepare_working_image() - 비율 비교 -> Crop/Resize 정책 적용 -> working/ 에 저장
  4. convert_to_cmyk()       - CMYK 변환 (ICC 있으면 정밀 변환, 없으면 naive + 경고)
  5. build_pdf()             - Bleed/Trim 적용 Production PDF 생성 -> output/
  6. run_preflight()         - 최종 PASS/WARNING/ERROR 판정

각 단계는 독립적으로도 호출 가능 (단위 테스트 및 GPT 쪽 커스텀 조합을 위해).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import BinaryIO, Optional

from .finishing.eyelet_engine import calculate_eyelet_positions
from .imaging import processor
from .imaging.dpi import calculate_effective_dpi
from .imaging.ratio import resolve_crop_box
from .manifest import build_production_manifest, write_production_manifest
from .models import (
    AdministratorOverride,
    CropBox,
    EyeletPoint,
    FitPolicy,
    Job,
    JobTicket,
    PipelineStage,
    PreflightReport,
    ProductionJob,
    ProductProfile,
)
from .pdf.builder import PdfBuildResult, build_production_pdf
from .pdf.cmyk import convert_to_cmyk
from .preflight.engine import ElementBox, PreflightInput, run_preflight
from .proof_generator import ProofMetadata, default_proof_filename, generate_customer_proof
from .security.file_validator import ValidatedFile, strip_metadata_and_save, validate_upload
from .security.storage import JobStorage
from .resize_engine import (
    ObjectTransformMM,
    RepositionMode,
    ResizeRecalculationSummary,
    SizeChangeError,
    recalculate_for_new_size,
)


# 렌더링 DPI 정책: 상품군별로 "인쇄에 실제로 필요한" 최대 DPI를 정해 그 이상은
# 무의미하게 큰 파일을 만들지 않도록 캡을 둔다. (성능/메모리 보호)
RENDER_DPI_CAP = {
    "banner": 150,
    "hyeonsumak": 100,
}
DEFAULT_RENDER_DPI_CAP = 150


@dataclass
class PipelineContext:
    job: Job
    profile: ProductProfile
    validated_file: Optional[ValidatedFile] = None
    original_path: Optional[str] = None
    working_path: Optional[str] = None
    cmyk_path: Optional[str] = None
    output_pdf_path: Optional[str] = None
    upscale_factor: float = 1.0
    icc_applied: bool = False
    icc_profile_name: Optional[str] = None
    # v1.3 추가
    eyelet_points: list[EyeletPoint] = field(default_factory=list)
    pdf_build_result: Optional[PdfBuildResult] = None
    job_ticket: Optional[JobTicket] = None
    manifest_path: Optional[str] = None
    # v1.5 추가: 관리자 강제 출력 여부/사유를 Job 단위로 보관 (manifest 에 그대로 기록됨)
    export_forced: bool = False
    export_override: Optional[AdministratorOverride] = None
    export_overridden_issue_codes: list[str] = field(default_factory=list)
    # v1.8 추가: Customer Proof / Production Package 경로
    proof_path: Optional[str] = None
    job_json_path: Optional[str] = None
    preflight_json_path: Optional[str] = None


@dataclass
class ProductionPackageResult:
    """v1.8 작업지시서 12번: JOB/output/ 산출물 4종 + ZIP 경로."""

    production_pdf_path: str
    proof_path: str
    job_json_path: str
    preflight_json_path: str
    zip_path: str


class ExportBlockedError(RuntimeError):
    """v1.5: BLOCKING_ERROR 가 있는 상태에서 관리자 강제 출력 없이 Export 를 시도할 때 발생.
    호출부(app.py 등)는 이 예외를 잡아 blocking_issues 를 사용자에게 보여주고,
    필요하면 AdministratorOverride 를 채워 export_with_gate() 를 다시 호출해야 한다."""

    def __init__(self, blocking_issues):
        self.blocking_issues = blocking_issues
        codes = ", ".join(i.code for i in blocking_issues)
        super().__init__(
            f"BLOCKING_ERROR가 있어 Production PDF 생성을 중단했습니다: [{codes}]. "
            f"Administrator Override 를 사용하려면 authorized_by/reason 을 채운 "
            f"AdministratorOverride(enabled=True, ...) 를 전달하세요."
        )


class ProductionPipeline:
    def __init__(self, storage: JobStorage):
        self.storage = storage

    # ---- 1. Job 생성 ----
    def create_job(
        self, profile: ProductProfile, output_width_mm: float, output_height_mm: float,
        fit_policy: FitPolicy = FitPolicy.CONTAIN,
    ) -> PipelineContext:
        if not profile.size_in_range(output_width_mm, output_height_mm):
            raise ValueError(
                f"요청 사이즈({output_width_mm}x{output_height_mm}mm)가 "
                f"'{profile.product_name}' 허용 범위를 벗어났습니다."
            )
        job = Job.new(profile.product_id, output_width_mm, output_height_mm)
        job.fit_policy = fit_policy
        paths = self.storage.create_job()
        # create_job() 이 새 UUID를 만들므로, Job 의 job_id 를 실제 폴더명과 일치시킨다.
        job.job_id = os.path.basename(paths.root)
        job.status = "created"
        return PipelineContext(job=job, profile=profile)

    # ---- 2. 업로드 수신 ----
    def ingest_upload(self, ctx: PipelineContext, file_obj: BinaryIO, filename: str) -> PipelineContext:
        with self.storage.job_lock(ctx.job.job_id):
            validated = validate_upload(file_obj, filename)
            paths = self.storage.get_paths(ctx.job.job_id)
            ext = _ext_for_format(validated.detected_format)
            original_dest = os.path.join(paths.original_dir, f"source{ext}")

            file_obj.seek(0)
            strip_metadata_and_save(file_obj, original_dest)
            os.chmod(original_dest, 0o444)  # 원본은 이후 읽기 전용

            ctx.validated_file = validated
            ctx.original_path = original_dest
            ctx.job.status = "uploaded"
        return ctx

    # ---- 3. Crop/Resize ----
    def prepare_working_image(
        self, ctx: PipelineContext, manual_crop: Optional[CropBox] = None
    ) -> PipelineContext:
        if ctx.original_path is None or ctx.validated_file is None:
            raise RuntimeError("먼저 ingest_upload() 를 호출해야 합니다.")

        render_dpi = RENDER_DPI_CAP.get(ctx.profile.category, DEFAULT_RENDER_DPI_CAP)

        # v1.3 버그 수정: 캔버스 픽셀 목표치를 "재단 크기(trim)" 기준으로만 계산하면
        # build_pdf() 단계에서 이 이미지를 (trim+bleed) 크기의 MediaBox 에 채우기 위해
        # 다시 한 번 균일하게 확대(stretch)하게 되어, 실제 재단선 안쪽 결과물이 의도한
        # 디자인보다 미세하게 확대/크롭된 상태로 출력되는 문제가 있었다.
        # (배너 bleed 3mm 대비 trim 1000mm 수준에서는 ~0.6% 로 육안 차이가 작지만,
        #  현수막처럼 bleed 10mm 비중이 큰 경우 왜곡이 누적될 수 있어 원천 수정한다.)
        # 해결: 작업 캔버스 자체를 처음부터 "재단+도련(bleed)" 크기로 준비한다.
        bleed_mm = ctx.profile.safe_zone.bleed_mm
        media_width_mm = ctx.job.output_width_mm + bleed_mm * 2
        media_height_mm = ctx.job.output_height_mm + bleed_mm * 2

        target_w_px, target_h_px = processor.pixels_for_target(
            media_width_mm, media_height_mm, render_dpi
        )

        crop_box = resolve_crop_box(
            policy=ctx.job.fit_policy,
            source_width_px=ctx.validated_file.width_px,
            source_height_px=ctx.validated_file.height_px,
            target_width_px=target_w_px,
            target_height_px=target_h_px,
            manual_box=manual_crop,
        )
        ctx.job.crop_box = crop_box

        paths = self.storage.get_paths(ctx.job.job_id)
        canvas_w_px, canvas_h_px = target_w_px, target_h_px  # 재단+도련을 포함한 최종 캔버스 픽셀 크기

        if ctx.job.fit_policy == FitPolicy.CONTAIN:
            # CONTAIN: 원본 비율을 유지한 채 캔버스 안에 들어가는 최대 크기로 축소하고,
            # 남는 영역은 흰색 배경으로 채운다(letterbox). 캔버스 자체 크기는 변하지 않는다
            # (재단선/안전영역 계산 기준을 그대로 유지하기 위함).
            fit_w_px, fit_h_px = _fit_within(crop_box.width, crop_box.height, canvas_w_px, canvas_h_px)
            fitted_path = os.path.join(paths.working_dir, "working_fit.png")
            result = processor.crop_and_resize(
                source_path=ctx.original_path,
                crop_box=crop_box,
                output_width_px=fit_w_px,
                output_height_px=fit_h_px,
                working_path=fitted_path,
            )
            working_path = os.path.join(paths.working_dir, "working.png")
            _paste_on_canvas(fitted_path, working_path, canvas_w_px, canvas_h_px)
            ctx.upscale_factor = result.upscale_factor
        else:
            working_path = os.path.join(paths.working_dir, "working.png")
            result = processor.crop_and_resize(
                source_path=ctx.original_path,
                crop_box=crop_box,
                output_width_px=canvas_w_px,
                output_height_px=canvas_h_px,
                working_path=working_path,
            )
            ctx.upscale_factor = result.upscale_factor

        ctx.working_path = working_path
        ctx.job.status = "processing"
        return ctx

    # ---- 4. CMYK 변환 ----
    def convert_color(
        self, ctx: PipelineContext, input_icc_path: Optional[str] = None,
        output_icc_path: Optional[str] = None,
    ) -> PipelineContext:
        if ctx.working_path is None:
            raise RuntimeError("먼저 prepare_working_image() 를 호출해야 합니다.")

        paths = self.storage.get_paths(ctx.job.job_id)
        cmyk_path = os.path.join(paths.working_dir, "working_cmyk.jpg")

        result = convert_to_cmyk(
            source_path=ctx.working_path,
            dest_path=cmyk_path,
            input_icc_path=input_icc_path,
            output_icc_path=output_icc_path,
            output_icc_name=ctx.profile.icc_profile_name,
        )
        ctx.cmyk_path = result.output_path
        ctx.icc_applied = result.icc_applied
        ctx.icc_profile_name = result.icc_profile_name
        return ctx

    # ---- 2b. 자유 제작 사이즈 변경 (v1.8 작업지시서 1번) ----
    def resize_job(
        self,
        ctx: PipelineContext,
        new_width_mm: float,
        new_height_mm: float,
        objects: Optional[list[ObjectTransformMM]] = None,
        reposition_mode: RepositionMode = RepositionMode.PROPORTIONAL_STRETCH,
    ) -> tuple[PipelineContext, ResizeRecalculationSummary, list[ObjectTransformMM]]:
        """
        Job의 제작 사이즈를 변경하고, 영향받는 모든 것을 다시 계산한다:
          - 사이즈 유효성 (Product Profile min/max, custom_size_allowed)
          - 캔버스 종횡비
          - 아일렛 좌표 (활성화된 경우)
          - Effective DPI (원본이 이미 업로드되어 있으면)
          - 기존 캔버스 객체 재배치 (objects 를 넘긴 경우)
          - 이후 prepare_working_image()/convert_color()/build_pdf() 를 다시 호출하면
            Bleed 포함 작업 캔버스와 Production PDF의 MediaBox/TrimBox/BleedBox 도
            새 사이즈 기준으로 자동 재생성된다 (이 메서드가 직접 하지는 않음 - 원본
            이미지 재처리는 비용이 크므로, "크기만 확정"하는 이 단계와 "실제로
            이미지를 다시 처리"하는 단계를 분리했다. 최종 재생성은 호출부가
            이어서 prepare_working_image() 를 호출하면 된다).

        검증에 실패하면 SizeChangeError 를 던진다 (ctx는 변경되지 않은 채로 유지).
        """
        old_width_mm = ctx.job.output_width_mm
        old_height_mm = ctx.job.output_height_mm

        source_width_px = ctx.validated_file.width_px if ctx.validated_file else None
        source_height_px = ctx.validated_file.height_px if ctx.validated_file else None

        validation, summary, repositioned = recalculate_for_new_size(
            ctx.profile, old_width_mm, old_height_mm, new_width_mm, new_height_mm,
            objects=objects, reposition_mode=reposition_mode,
            source_width_px=source_width_px, source_height_px=source_height_px,
        )
        if not validation.valid:
            raise SizeChangeError(
                f"사이즈 변경이 거부되었습니다: {validation.reason}"
                + (f" (허용 범위: {validation.allowed_range})" if validation.allowed_range else "")
            )

        # 사이즈를 실제로 반영. 기존 작업 산출물(working/cmyk/pdf)은 이제 낡은 사이즈
        # 기준이므로 무효화한다 - 호출부가 prepare_working_image() 부터 다시 호출해야
        # 한다는 신호로 명시적으로 None 처리한다 (조용히 낡은 파일을 내버려두지 않음).
        ctx.job.output_width_mm = new_width_mm
        ctx.job.output_height_mm = new_height_mm
        ctx.job.crop_box = None
        ctx.working_path = None
        ctx.cmyk_path = None
        ctx.output_pdf_path = None
        ctx.pdf_build_result = None
        ctx.eyelet_points = summary.eyelet_points

        return ctx, summary, repositioned

    # ---- 5. PDF 생성 ----
    def build_pdf(self, ctx: PipelineContext, output_icc_path: Optional[str] = None) -> PipelineContext:
        if ctx.cmyk_path is None:
            raise RuntimeError("먼저 convert_color() 를 호출해야 합니다.")

        paths = self.storage.get_paths(ctx.job.job_id)
        pdf_path = os.path.join(paths.output_dir, "production.pdf")

        result = build_production_pdf(
            image_path=ctx.cmyk_path,
            dest_path=pdf_path,
            trim_width_mm=ctx.job.output_width_mm,
            trim_height_mm=ctx.job.output_height_mm,
            bleed_mm=ctx.profile.safe_zone.bleed_mm,
            pdf_standard=ctx.profile.pdf_standard,
            output_icc_path=output_icc_path,
            output_icc_name=ctx.profile.icc_profile_name,
        )
        ctx.output_pdf_path = pdf_path
        ctx.pdf_build_result = result
        ctx.job.status = "done"
        return ctx

    # ---- 5b. Export 게이트 (v1.5 작업지시서 3번: 관리자 강제 출력) ----
    def export_with_gate(
        self,
        ctx: PipelineContext,
        report: PreflightReport,
        output_icc_path: Optional[str] = None,
        admin_override: Optional[AdministratorOverride] = None,
    ) -> PipelineContext:
        """
        Preflight 결과를 보고 build_pdf() 를 실행할지 판단하는 게이트.

        - BLOCKING_ERROR 가 없으면: WARNING 이 있어도 정상 출력한다 (WARNING은 절대
          출력을 막지 않는다 - 작업지시서 3번 "WARNING이 존재해도 출력 가능").
        - BLOCKING_ERROR 가 있으면: 기본적으로 출력을 차단한다 (ExportBlockedError).
          단, admin_override.is_valid() 가 True 인 경우에만 강제로 진행한다.
        - 강제 출력 여부/사유/무시된 이슈 코드는 ctx 에 기록되어 Production Manifest 에
          그대로 남는다 (build_manifest/export_manifest 가 이 필드를 읽는다).
        """
        blocking_issues = [i for i in report.issues if i.blocking]

        if blocking_issues:
            if admin_override is not None and admin_override.is_valid():
                ctx.export_forced = True
                ctx.export_override = admin_override
                ctx.export_overridden_issue_codes = [i.code for i in blocking_issues]
            else:
                raise ExportBlockedError(blocking_issues)
        else:
            ctx.export_forced = False
            ctx.export_override = admin_override if admin_override is not None else None
            ctx.export_overridden_issue_codes = []

        ctx = self.build_pdf(ctx, output_icc_path=output_icc_path)
        return ctx

    # ---- 6. Preflight ----
    def preflight(
        self, ctx: PipelineContext, protected_elements: Optional[list[ElementBox]] = None
    ) -> PreflightReport:
        if ctx.validated_file is None:
            raise RuntimeError("먼저 ingest_upload() 를 호출해야 합니다.")

        # 색상 변환(convert_color)이 아직 실행되지 않았다면 편집(EDIT) 단계, CMYK 변환이
        # 완료된 뒤라면 최종(FINAL) 단계로 자동 판단한다. RGB 원본은 EDIT 단계에서는 정상이고
        # FINAL 단계에서만 ERROR 여야 한다 (작업지시서 4번 요구사항).
        stage = PipelineStage.FINAL if ctx.cmyk_path else PipelineStage.EDIT

        # 아일렛이 활성화된 상품이면 현재 주문 사이즈 기준으로 항상 재계산한다.
        # (사이즈가 바뀌어도 항상 최신 좌표를 preflight/manifest 에 반영하기 위해
        #  매번 새로 계산하고 별도로 캐시하지 않는다.)
        eyelet_points = self.compute_eyelets(ctx)

        data = PreflightInput(
            job=ctx.job,
            profile=ctx.profile,
            source_width_px=ctx.validated_file.width_px,
            source_height_px=ctx.validated_file.height_px,
            upscale_factor=ctx.upscale_factor,
            color_mode="CMYK" if ctx.cmyk_path else "RGB",
            icc_profile_applied=ctx.icc_profile_name if ctx.icc_applied else None,
            protected_elements=protected_elements,
            stage=stage,
            has_alpha=ctx.validated_file.has_alpha,
            crop_box=ctx.job.crop_box,
            eyelet_points=eyelet_points,
        )
        return run_preflight(data)

    # ---- 7. 아일렛 좌표 계산 ----
    def compute_eyelets(self, ctx: PipelineContext) -> list[EyeletPoint]:
        """상품 프로필의 EyeletSpec + 현재 주문 사이즈로 아일렛 mm 좌표를 계산한다.
        사이즈가 바뀌면 다시 호출하는 것만으로 자동 재계산된다."""
        points = calculate_eyelet_positions(
            ctx.job.output_width_mm, ctx.job.output_height_mm, ctx.profile.eyelet
        )
        ctx.eyelet_points = points
        return points

    # ---- 8. Job Ticket ----
    def attach_job_ticket(self, ctx: PipelineContext, ticket: JobTicket) -> PipelineContext:
        """주문 관리용 Job Ticket 을 이 작업(Job)에 연결한다. Production Manifest 생성 시 포함된다."""
        ctx.job_ticket = ticket
        return ctx

    # ---- 9. Production Manifest ----
    def build_manifest(self, ctx: PipelineContext, report: PreflightReport) -> dict:
        """PDF와 함께 남길 production_manifest.json 내용을 dict 로 조립한다."""
        self.compute_eyelets(ctx)  # manifest 에는 항상 최신 아일렛 좌표를 반영
        return build_production_manifest(ctx, report, job_ticket=ctx.job_ticket)

    def export_manifest(self, ctx: PipelineContext, report: PreflightReport) -> str:
        """production_manifest.json 을 output/ 디렉토리에 저장하고 경로를 반환한다."""
        manifest = self.build_manifest(ctx, report)
        paths = self.storage.get_paths(ctx.job.job_id)
        manifest_path = os.path.join(paths.output_dir, "production_manifest.json")
        write_production_manifest(manifest_path, manifest)
        ctx.manifest_path = manifest_path
        return manifest_path

    # ---- 10. Customer Proof (v1.8 작업지시서 11번) ----
    def generate_proof(
        self, ctx: PipelineContext, metadata: Optional[ProofMetadata] = None,
        source_image_path: Optional[str] = None,
    ) -> str:
        """
        Production PDF와 완전히 분리된 고객 확인용 JPG 시안을 생성한다.
        기본적으로 CMYK 변환 전 작업 이미지(ctx.working_path)를 원본으로 쓴다 - 고객이
        보는 화면은 RGB 화면 기준이 자연스럽고, Production PDF(CMYK)와는 별개 파일이라는
        원칙을 지키기 위함이다.
        """
        image_path = source_image_path or ctx.working_path or ctx.cmyk_path
        if image_path is None:
            raise RuntimeError("먼저 prepare_working_image() 를 호출해야 합니다 (Proof 생성용 이미지 없음).")

        paths = self.storage.get_paths(ctx.job.job_id)
        proof_filename = default_proof_filename(
            ctx.job_ticket.order_number if ctx.job_ticket else None, ctx.job.job_id,
        )
        proof_path = os.path.join(paths.output_dir, proof_filename)

        if metadata is None and ctx.job_ticket:
            metadata = ProofMetadata(
                order_number=ctx.job_ticket.order_number, product_name=ctx.profile.product_name,
                width_mm=ctx.job.output_width_mm, height_mm=ctx.job.output_height_mm,
            )
        generate_customer_proof(image_path, proof_path, metadata=metadata)
        ctx.proof_path = proof_path
        return proof_path

    # ---- 11. Production Package (v1.8 작업지시서 12번) ----
    def export_preflight_json(self, ctx: PipelineContext, report: PreflightReport) -> str:
        """output/preflight.json 을 별도 파일로 저장한다 (production_manifest.json 에도
        preflight 섹션이 포함되지만, 작업지시서 12번이 명시한 JOB/output/preflight.json
        구조를 그대로 제공하기 위해 독립 파일로도 남긴다)."""
        import json as _json

        paths = self.storage.get_paths(ctx.job.job_id)
        preflight_path = os.path.join(paths.output_dir, "preflight.json")
        payload = {"job_id": ctx.job.job_id, "overall": report.overall.value, "issues": [i.to_dict() for i in report.issues]}
        with open(preflight_path, "w", encoding="utf-8") as f:
            _json.dump(payload, f, ensure_ascii=False, indent=2)
        ctx.preflight_json_path = preflight_path
        return preflight_path

    def export_job_json(self, ctx: PipelineContext, preflight_report: Optional[PreflightReport] = None) -> str:
        """output/job.json — v1.9: JobTicket(주문 정보) + ProductionJob(제작 사양,
        Working Size 자동계산 포함)을 함께 저장한다."""
        import json as _json

        paths = self.storage.get_paths(ctx.job.job_id)
        job_json_path = os.path.join(paths.output_dir, "job.json")

        effective_dpi = None
        if ctx.validated_file:
            dpi_result = calculate_effective_dpi(
                ctx.validated_file.width_px, ctx.validated_file.height_px,
                ctx.job.output_width_mm, ctx.job.output_height_mm,
            )
            effective_dpi = round(dpi_result.min_dpi, 1)

        production_job = ProductionJob.from_profile_and_job(
            ctx.profile, ctx.job, effective_dpi=effective_dpi,
            preflight_overall=preflight_report.overall.value if preflight_report else None,
        )

        payload = {
            "job_ticket": ctx.job_ticket.to_dict() if ctx.job_ticket else {
                "job_id": ctx.job.job_id, "product_id": ctx.profile.product_id,
                "width_mm": ctx.job.output_width_mm, "height_mm": ctx.job.output_height_mm,
            },
            "production_job": production_job.to_dict(),
        }
        with open(job_json_path, "w", encoding="utf-8") as f:
            _json.dump(payload, f, ensure_ascii=False, indent=2)
        ctx.job_json_path = job_json_path
        return job_json_path

    def build_production_package(
        self, ctx: PipelineContext, report: PreflightReport, metadata: Optional[ProofMetadata] = None,
    ) -> "ProductionPackageResult":
        """
        JOB/output/ 아래에 production.pdf(이미 존재해야 함) + proof.jpg + job.json +
        preflight.json 을 전부 갖춘 뒤, 이 4개 파일을 하나의 ZIP으로 묶어 반환한다
        (작업지시서 12번: "향후 ZIP 다운로드도 가능하도록 구조화").

        build_pdf() 가 먼저 호출되어 output/production.pdf 가 존재해야 한다.
        """
        if ctx.output_pdf_path is None:
            raise RuntimeError("먼저 build_pdf() 를 호출해야 합니다 (production.pdf 없음).")

        proof_path = self.generate_proof(ctx, metadata=metadata)
        job_json_path = self.export_job_json(ctx, preflight_report=report)
        preflight_json_path = self.export_preflight_json(ctx, report)

        paths = self.storage.get_paths(ctx.job.job_id)
        zip_path = os.path.join(paths.output_dir, f"{ctx.job.job_id}_package.zip")
        import zipfile

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(ctx.output_pdf_path, arcname=os.path.basename(ctx.output_pdf_path))
            zf.write(proof_path, arcname=os.path.basename(proof_path))
            zf.write(job_json_path, arcname="job.json")
            zf.write(preflight_json_path, arcname="preflight.json")

        return ProductionPackageResult(
            production_pdf_path=ctx.output_pdf_path, proof_path=proof_path,
            job_json_path=job_json_path, preflight_json_path=preflight_json_path, zip_path=zip_path,
        )


def _ext_for_format(fmt) -> str:
    mapping = {"JPEG": ".jpg", "PNG": ".png", "TIFF": ".tiff"}
    return mapping.get(fmt.value, ".bin")


def _fit_within(source_w: int, source_h: int, max_w: int, max_h: int) -> tuple[int, int]:
    """원본 비율을 유지한 채 (max_w, max_h) 안에 들어가는 최대 크기 계산 (CONTAIN)."""
    scale = min(max_w / source_w, max_h / source_h)
    return max(1, round(source_w * scale)), max(1, round(source_h * scale))


def _paste_on_canvas(fitted_path: str, dest_path: str, canvas_w_px: int, canvas_h_px: int) -> None:
    """CONTAIN 결과물을 흰색 배경의 고정 캔버스 중앙에 배치한다 (letterbox)."""
    from PIL import Image

    with Image.open(fitted_path) as fitted:
        canvas_img = Image.new("RGB", (canvas_w_px, canvas_h_px), (255, 255, 255))
        offset_x = (canvas_w_px - fitted.width) // 2
        offset_y = (canvas_h_px - fitted.height) // 2
        if fitted.mode == "RGBA":
            canvas_img.paste(fitted, (offset_x, offset_y), mask=fitted.split()[3])
        else:
            canvas_img.paste(fitted.convert("RGB"), (offset_x, offset_y))
        canvas_img.save(dest_path)
