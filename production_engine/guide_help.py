"""
guide_help.py
---------------
v1.8: Guide Help Data (작업지시서 10번).

Frontend가 Bleed/Trim/Safe/Eyelet/CutContour/WHITE 가이드선에 마우스를 올렸을 때
보여줄 Tooltip 텍스트를 백엔드가 단일 진실 소스로 관리한다 (여러 Frontend 화면/버전에서
같은 설명이 중복 작성되어 서로 달라지는 것을 방지).

작업지시서에 명시된 문구를 그대로 사용했다 - 임의로 표현을 바꾸지 않았다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GuideHelp:
    guide_id: str
    title: str
    description: str


GUIDE_HELP_DATA: dict[str, GuideHelp] = {
    "BLEED": GuideHelp(
        guide_id="BLEED", title="Bleed (도련)",
        description="재단 오차로 흰 여백이 생기지 않도록 디자인을 연장하는 영역",
    ),
    "TRIM": GuideHelp(
        guide_id="TRIM", title="Trim (재단선)",
        description="재단 후 실제 제품이 완성되는 위치",
    ),
    "SAFE": GuideHelp(
        guide_id="SAFE", title="Safe Zone (안전영역)",
        description="중요한 글자와 로고를 배치해야 하는 안전 영역",
    ),
    "EYELET": GuideHelp(
        guide_id="EYELET", title="Eyelet (아일렛)",
        description="현수막 아일렛이 설치되는 위치",
    ),
    "CUTCONTOUR": GuideHelp(
        guide_id="CUTCONTOUR", title="CutContour (칼선)",
        description="커팅 장비가 실제로 자르는 경로",
    ),
    "WHITE": GuideHelp(
        guide_id="WHITE", title="White (화이트 레이어)",
        description="투명/컬러 소재에서 백색 잉크를 인쇄하는 영역",
    ),
}


def get_guide_help(guide_id: str) -> GuideHelp:
    key = guide_id.upper()
    if key not in GUIDE_HELP_DATA:
        raise KeyError(f"알 수 없는 guide_id: {guide_id}")
    return GUIDE_HELP_DATA[key]


def all_guide_help() -> list[dict]:
    """Frontend가 한 번에 전부 받아 캐싱할 수 있도록 dict 리스트로 반환."""
    return [
        {"guide_id": g.guide_id, "title": g.title, "description": g.description}
        for g in GUIDE_HELP_DATA.values()
    ]
