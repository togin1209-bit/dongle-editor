"""
pipeline_router.py
---------------------
v1.4: Capability 기반 Production Pipeline 라우터.

작업지시서 C 요구사항: "모든 상품을 같은 PDF 처리방식으로 만들지 마세요."

이 모듈은 ProductProfile 의 capabilities 를 보고 어떤 파이프라인을 실행할지 결정한다.
**정직성 원칙**: 실제로 구현/검증된 것은 RECTANGULAR_PRINT (+ EYELET_FINISHING 부가기능)
뿐이다. CUTLINE_PRINT / WHITE_INK_PRINT / DOUBLE_SIDE_PRINT / LARGE_FORMAT_PRINT /
NO_PRINT_CUTTING 은 아직 실제 이미지 처리 알고리즘(외곽선 자동 검출, 화이트 채널 생성,
양면 정합, 대용량 타일링, 벡터화)이 구현되지 않았으므로, 완성된 것처럼 조용히 통과시키지
않고 NotImplementedError 를 명확히 발생시킨다 (부분적으로 동작하는 척 하는 것이 오히려
실제 인쇄 사고로 이어지므로).

IMPLEMENTED_CAPABILITIES 를 보면 현재 무엇이 실제로 동작하는지 한눈에 알 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Capability, Job, PreflightReport, ProductProfile
from .pipeline import PipelineContext, ProductionPipeline
from .taxonomy import IMPLEMENTED_CAPABILITIES, ROUTING_CAPABILITIES, routing_capabilities_of


class CapabilityNotImplementedError(NotImplementedError):
    def __init__(self, capability: str, product_id: str):
        self.capability = capability
        self.product_id = product_id
        super().__init__(
            f"'{product_id}' 상품에 필요한 Capability '{capability}' 는 아직 Production "
            f"Engine에 구현되지 않았습니다. RECTANGULAR_PRINT / EYELET_FINISHING 외 "
            f"기능은 v1.5+ 에서 실제 알고리즘 구현 후 지원 예정입니다. 지금 이 상품을 "
            f"제작 파이프라인에 투입하면 안 됩니다."
        )


@dataclass
class RoutingDecision:
    product_id: str
    capabilities: list[str]
    implemented: bool
    unimplemented_capabilities: list[str]
    pipeline: str  # 사용할 파이프라인 클래스 이름 (문서/로그용)


class PipelineRouter:
    """
    실제로 구현되어 검증된 capability 집합. 여기 없는 capability 가 하나라도
    상품에 필요하면, 그 상품은 아직 제작 파이프라인에 투입할 수 없다.
    """

    IMPLEMENTED_CAPABILITIES = IMPLEMENTED_CAPABILITIES

    def __init__(self, rectangular_pipeline: ProductionPipeline):
        # RECTANGULAR_PRINT(+EYELET_FINISHING) 는 v1.3 에서 이미 완성/테스트된
        # ProductionPipeline 을 그대로 재사용한다 (새로 만들지 않는다).
        self.rectangular_pipeline = rectangular_pipeline

    def route(self, profile: ProductProfile) -> RoutingDecision:
        """이 상품에 필요한 capability 를 분석해 실행 가능 여부와 사용할 파이프라인을 판단.
        (v1.4b: '속성 태그'는 라우팅 판단에서 제외하고, 라우팅 capability 만 확인한다.)"""
        capabilities = self._capabilities_of(profile)
        routing_caps = routing_capabilities_of(capabilities)
        unimplemented = [c for c in routing_caps if c not in self.IMPLEMENTED_CAPABILITIES]

        if unimplemented:
            return RoutingDecision(
                product_id=profile.product_id,
                capabilities=capabilities,
                implemented=False,
                unimplemented_capabilities=unimplemented,
                pipeline="(none - not implemented)",
            )

        return RoutingDecision(
            product_id=profile.product_id,
            capabilities=capabilities,
            implemented=True,
            unimplemented_capabilities=[],
            pipeline="ProductionPipeline(rectangular)",
        )

    def get_pipeline_for(self, profile: ProductProfile) -> ProductionPipeline:
        """
        실제로 사용할 파이프라인 인스턴스를 반환한다.
        구현되지 않은 capability 가 필요한 상품이면 CapabilityNotImplementedError 를 던진다.
        """
        decision = self.route(profile)
        if not decision.implemented:
            raise CapabilityNotImplementedError(
                capability=", ".join(decision.unimplemented_capabilities),
                product_id=profile.product_id,
            )
        return self.rectangular_pipeline

    @staticmethod
    def _capabilities_of(profile: ProductProfile) -> list[str]:
        """
        v1.4 승격 프로필은 profile.capabilities 를 명시적으로 갖고 있으므로 그것을 우선 사용한다.
        v1.3부터 있던 기존 확정 프로필(banner_indoor, hyeonsumak_outdoor 등)은 이 필드를
        비워둔 채 시드 JSON을 쓰고 있으므로, 하위 호환을 위해 finishing/eyelet 필드로부터
        추론하는 기존 로직을 폴백으로 유지한다.
        """
        if profile.capabilities:
            return list(profile.capabilities)

        caps = [Capability.RECTANGULAR_PRINT.value]
        if profile.eyelet.enabled:
            caps.append(Capability.EYELET_FINISHING.value)
        return caps
