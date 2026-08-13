"""
history_schema.py
--------------------
v1.7: History System 데이터 구조 (작업지시서 3번).

Frontend의 실제 Undo/Redo 스택은 브라우저 메모리(JS)에서 동작해야 하므로(매 입력마다
서버 왕복은 비현실적), **이 모듈은 History의 "정식 스키마"를 Python 쪽에 정의**해
아래 두 가지 용도로 쓴다:
  1) Production Manifest 에 "이 작업물이 어떤 편집 과정을 거쳤는지" 감사(audit) 로그로
     남기고 싶을 때 (전체 History가 아니라 중요 action만 선택적으로 서버에 동기화).
  2) Frontend HistoryManager(JS, editor/history/HistoryManager.js)가 만드는 엔트리와
     동일한 필드 이름/구조를 쓰도록 계약을 고정해, 나중에 JS<->Python 데이터를 그대로
     주고받을 수 있게 한다 (JSON 직렬화 시 필드명이 일치해야 함).

action_type 목록은 작업지시서 3번에 명시된 최소 History 대상과 정확히 일치한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class HistoryActionType(str, Enum):
    OBJECT_ADD = "OBJECT_ADD"
    OBJECT_DELETE = "OBJECT_DELETE"
    OBJECT_MOVE = "OBJECT_MOVE"
    OBJECT_RESIZE = "OBJECT_RESIZE"
    OBJECT_ROTATE = "OBJECT_ROTATE"
    IMAGE_REPLACE = "IMAGE_REPLACE"
    BACKGROUND_REMOVE = "BACKGROUND_REMOVE"
    IMAGE_CROP = "IMAGE_CROP"
    COLOR_CHANGE = "COLOR_CHANGE"
    TEXT_CHANGE = "TEXT_CHANGE"
    LAYER_CHANGE = "LAYER_CHANGE"
    GROUP = "GROUP"
    UNGROUP = "UNGROUP"
    CUTLINE_GENERATE = "CUTLINE_GENERATE"
    HOLE_GENERATE = "HOLE_GENERATE"


# 사람이 읽는 기본 설명 (Frontend가 커스텀 설명을 안 넘기면 이걸 기본값으로 쓴다).
DEFAULT_DESCRIPTIONS: dict[HistoryActionType, str] = {
    HistoryActionType.OBJECT_ADD: "객체 추가",
    HistoryActionType.OBJECT_DELETE: "객체 삭제",
    HistoryActionType.OBJECT_MOVE: "객체 이동",
    HistoryActionType.OBJECT_RESIZE: "크기 조절",
    HistoryActionType.OBJECT_ROTATE: "회전",
    HistoryActionType.IMAGE_REPLACE: "이미지 교체",
    HistoryActionType.BACKGROUND_REMOVE: "배경 제거",
    HistoryActionType.IMAGE_CROP: "이미지 크롭",
    HistoryActionType.COLOR_CHANGE: "색상 변경",
    HistoryActionType.TEXT_CHANGE: "텍스트 수정",
    HistoryActionType.LAYER_CHANGE: "레이어 순서 변경",
    HistoryActionType.GROUP: "그룹 지정",
    HistoryActionType.UNGROUP: "그룹 해제",
    HistoryActionType.CUTLINE_GENERATE: "칼선 생성",
    HistoryActionType.HOLE_GENERATE: "타공 생성",
}


@dataclass
class HistoryEntry:
    action_type: HistoryActionType
    object_id: Optional[str] = None
    description: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    before_state: Optional[dict[str, Any]] = None
    after_state: Optional[dict[str, Any]] = None
    restorable: bool = True

    def __post_init__(self):
        if not self.description:
            self.description = DEFAULT_DESCRIPTIONS.get(self.action_type, self.action_type.value)

    def display_label(self) -> str:
        """History Panel에 표시할 'HH:MM 설명' 형태 (작업지시서 예시와 동일한 포맷)."""
        try:
            dt = datetime.fromisoformat(self.timestamp)
            time_str = dt.strftime("%H:%M")
        except ValueError:
            time_str = "--:--"
        return f"{time_str} {self.description}"

    def to_dict(self) -> dict:
        return {
            "action_type": self.action_type.value,
            "object_id": self.object_id,
            "description": self.description,
            "timestamp": self.timestamp,
            "before_state": self.before_state,
            "after_state": self.after_state,
            "restorable": self.restorable,
        }

    @staticmethod
    def from_dict(raw: dict) -> "HistoryEntry":
        return HistoryEntry(
            action_type=HistoryActionType(raw["action_type"]),
            object_id=raw.get("object_id"),
            description=raw.get("description", ""),
            timestamp=raw.get("timestamp", datetime.now(timezone.utc).isoformat()),
            before_state=raw.get("before_state"),
            after_state=raw.get("after_state"),
            restorable=raw.get("restorable", True),
        )


@dataclass
class HistoryLog:
    """Job 하나에 대한 History 전체. 특정 시점(index)으로 복원 가능한 구조."""

    job_id: str
    entries: list[HistoryEntry] = field(default_factory=list)
    current_index: int = -1  # 현재 위치 (마지막으로 적용된 entry의 index, -1이면 초기 상태)

    def push(self, entry: HistoryEntry) -> None:
        """새 액션을 기록한다. Redo 스택(current_index 이후의 항목)은 버려진다
        (표준 undo/redo 스택 동작 - 새 액션이 생기면 redo 히스토리는 무효)."""
        self.entries = self.entries[: self.current_index + 1]
        self.entries.append(entry)
        self.current_index = len(self.entries) - 1

    def can_undo(self) -> bool:
        return self.current_index >= 0

    def can_redo(self) -> bool:
        return self.current_index < len(self.entries) - 1

    def undo(self) -> Optional[HistoryEntry]:
        if not self.can_undo():
            return None
        entry = self.entries[self.current_index]
        self.current_index -= 1
        return entry

    def redo(self) -> Optional[HistoryEntry]:
        if not self.can_redo():
            return None
        self.current_index += 1
        return self.entries[self.current_index]

    def restore_to(self, index: int) -> list[HistoryEntry]:
        """특정 History Point로 복원할 때, 그 지점까지 순서대로 재생(replay)해야 할
        entry 리스트를 반환한다 (index가 현재보다 앞이면 undo 방향, 뒤면 redo 방향)."""
        if index < -1 or index >= len(self.entries):
            raise ValueError(f"유효하지 않은 history index: {index}")
        if index == self.current_index:
            return []
        if index < self.current_index:
            # undo 방향: current_index 부터 index+1 까지 역순으로 되돌린다
            to_undo = self.entries[index + 1: self.current_index + 1]
            self.current_index = index
            return list(reversed(to_undo))
        else:
            to_redo = self.entries[self.current_index + 1: index + 1]
            self.current_index = index
            return to_redo

    def timeline_labels(self) -> list[str]:
        """History Panel에 그대로 표시할 'HH:MM 설명' 문자열 리스트."""
        return [e.display_label() for e in self.entries]

    def to_dict(self) -> dict:
        return {"job_id": self.job_id, "entries": [e.to_dict() for e in self.entries], "current_index": self.current_index}
