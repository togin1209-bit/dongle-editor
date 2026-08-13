"""
preflight_v2.py
------------------
v1.8: Production Preflight v2 (작업지시서 9번).

기존 v1.5 preflight/engine.py 를 대체하지 않는다 - 그대로 유지한 채, 여기서는
그 결과 + v1.6 manufacturability(CutContour/Hole/White) + v1.8 Slot Preflight를
하나의 통합 리포트로 묶기만 한다 (ADDITIVE, 기존 API 무손상).

각 PreflightIssue 는 이미 (code=문제, message=이유, object_id=위치, recommendation=해결방법,
auto_fixable=자동수정 가능 여부) 구조를 갖고 있으므로, 이 모듈은 새 스키마를 만들지 않고
기존 스키마를 그대로 재사용해 "문제/이유/위치/해결방법 + [자동수정]" 요구사항을 만족한다.

**정직한 한계**: Thin Line(최소 선굵기) / Small Text(최소 글자크기) / Transparent
Object(의도치 않은 부분 투명 요소) 검사는 벡터/텍스트 레이어 메타데이터가 있어야
가능한데, 이 엔진은 래스터 이미지만 처리한다. v1.5의 VECTOR_CHECKS_NOT_IMPLEMENTED
와 동일한 원칙으로, 이 셋은 항상 명시적 WARNING(미구현 고지)으로 보고한다 - 통과한
것처럼 속이지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import PreflightIssue, PreflightLevel, PreflightReport
from .vision.manufacturability import ManufacturabilityReport
from .vision.stand_multipart import MultiPartStandResult


@dataclass
class UnifiedPreflightReport:
    overall: PreflightLevel
    issues: list[PreflightIssue] = field(default_factory=list)
    sources: dict = field(default_factory=dict)  # 어떤 하위 리포트들이 합쳐졌는지 (디버깅/추적용)

    def to_dict(self) -> dict:
        return {
            "overall": self.overall.value,
            "issues": [i.to_dict() for i in self.issues],
            "sources": self.sources,
        }


_LEVEL_ORDER = {PreflightLevel.PASS: 0, PreflightLevel.WARNING: 1, PreflightLevel.ERROR: 2}


def _worst(levels: list[PreflightLevel]) -> PreflightLevel:
    worst = PreflightLevel.PASS
    for lv in levels:
        if _LEVEL_ORDER[lv] > _LEVEL_ORDER[worst]:
            worst = lv
    return worst


def _unimplemented_vector_checks() -> list[PreflightIssue]:
    return [
        PreflightIssue(
            code="THIN_LINE_CHECK_NOT_IMPLEMENTED", level=PreflightLevel.WARNING,
            title="최소 선굵기 검사 미구현",
            message="벡터 레이어 정보가 없어 최소 선굵기(Thin Line)를 자동 검사하지 못했습니다.",
            recommendation="제작 전 디자이너가 수동으로 확인하세요.",
        ),
        PreflightIssue(
            code="SMALL_TEXT_CHECK_NOT_IMPLEMENTED", level=PreflightLevel.WARNING,
            title="최소 글자크기 검사 미구현",
            message="텍스트 레이어 정보가 없어 최소 글자크기(Small Text)를 자동 검사하지 못했습니다.",
            recommendation="제작 전 디자이너가 수동으로 확인하세요.",
        ),
        PreflightIssue(
            code="TRANSPARENT_OBJECT_CHECK_NOT_IMPLEMENTED", level=PreflightLevel.WARNING,
            title="개별 요소 투명도 검사 미구현",
            message="개별 디자인 요소(오브젝트) 단위의 의도치 않은 투명도는 캔버스 레이어 "
                    "정보가 없어 검사하지 못했습니다 (이미지 전체의 알파 채널 여부는 "
                    "기존 TRANSPARENCY_DETECTED 검사가 이미 확인합니다).",
            recommendation="제작 전 각 오브젝트의 Opacity 값을 확인하세요.",
        ),
    ]


def run_unified_preflight(
    base_report: PreflightReport,
    manufacturability_report: ManufacturabilityReport | None = None,
    stand_result: MultiPartStandResult | None = None,
    slot_issues: list[PreflightIssue] | None = None,
    include_vector_placeholders: bool = False,
) -> UnifiedPreflightReport:
    """
    v1.5 base_report(DPI/ColorMode/Bleed/SafeZone/Ratio/Upscale/Eyelet 등) +
    v1.6 manufacturability_report(CutContour/Hole/White) +
    v1.8 slot_issues(Slot 배치) 를 하나로 통합한다.

    include_vector_placeholders=True 이면 Thin Line/Small Text/Transparent Object
    의 "미구현" 고지 3건도 포함한다 (해당 상품이 벡터 검사가 의미 있는 CUTLINE_PRINT
    계열일 때만 True로 호출하는 것을 권장 - 호출부 판단에 맡긴다).
    """
    all_issues: list[PreflightIssue] = list(base_report.issues)
    sources = {"base_preflight": len(base_report.issues)}

    if manufacturability_report is not None:
        all_issues.extend(manufacturability_report.issues)
        sources["manufacturability"] = len(manufacturability_report.issues)

    if slot_issues is not None:
        all_issues.extend(slot_issues)
        sources["slot_preflight"] = len(slot_issues)

    if include_vector_placeholders:
        vector_issues = _unimplemented_vector_checks()
        all_issues.extend(vector_issues)
        sources["vector_placeholders"] = len(vector_issues)

    overall = _worst([i.level for i in all_issues]) if all_issues else PreflightLevel.PASS

    return UnifiedPreflightReport(overall=overall, issues=all_issues, sources=sources)
