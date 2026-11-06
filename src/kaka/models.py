"""In-memory domain values. Real conversations are never written by KAKA."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Do not let a chat participant inject terminal controls/OSC links into the TUI.
_ANSI = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]")


def display_text(value: str) -> str:
    value = _ANSI.sub("", value)
    return "".join(c for c in value if c in "\n\t" or (ord(c) >= 32 and not 127 <= ord(c) < 160))


def identifier(value: Any) -> str:
    # Never round an identifier via float; Kakao IDs can exceed JavaScript's 2^53.
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("잘못된 메시지/채팅방 ID입니다.")
    value = str(value)
    if not value.isascii() or not value.isdigit():
        raise ValueError("잘못된 메시지/채팅방 ID입니다.")
    return value


@dataclass(frozen=True)
class Room:
    id: str
    title: str
    readable: bool = True
    unread: int = 0
    member_count: int = 0

    @classmethod
    def parse(cls, raw: dict) -> Room:
        return cls(
            identifier(raw["id"]),
            str(raw["title"]),
            bool(raw.get("readable", False)),
            int(raw.get("unread", 0)),
            int(raw.get("memberCount", 0)),
        )


@dataclass(frozen=True)
class Message:
    id: str
    room_id: str
    sender: str
    text: str
    sent_at: datetime
    from_me: bool = False
    kind: str = "text"

    @classmethod
    def parse(cls, raw: dict) -> Message:
        when = datetime.fromisoformat(raw["sentAt"])
        if when.tzinfo is None:
            raise ValueError("시간대가 없는 메시지는 표시하지 않습니다.")
        return cls(
            identifier(raw["id"]),
            identifier(raw["roomId"]),
            str(raw.get("sender") or "알 수 없음"),
            str(raw.get("text") or ""),
            when,
            bool(raw.get("fromMe", False)),
            str(raw.get("kind", "text")),
        )


@dataclass
class Outgoing:
    text: str
    after_id: int
    started: float
    status: str = "sending"  # sending, submitted, confirmed, rejected, unknown
    detail: str = "전송 중"
    confirmed_id: str | None = None


@dataclass
class Conversation:
    messages: dict[str, Message] = field(default_factory=dict)
    draft: str = ""
    initialized: bool = False
    outgoing: list[Outgoing] = field(default_factory=list)
    older_available: bool = True

    @property
    def latest_id(self) -> int:
        return max((int(i) for i in self.messages), default=0)

    @property
    def earliest_id(self) -> int:
        return min((int(i) for i in self.messages), default=0)

    def ordered(self) -> list[Message]:
        return sorted(self.messages.values(), key=lambda m: int(m.id))

    def merge(self, room_id: str, incoming: list[Message]) -> int:
        # Validate the entire batch before advancing any state.
        if any(m.room_id != room_id for m in incoming):
            raise ValueError("다른 채팅방의 응답입니다. 현재 대화를 갱신하지 않았습니다.")
        added = len({m.id for m in incoming} - self.messages.keys())
        self.messages.update((m.id, m) for m in incoming)
        # One log row can reconcile at most one outgoing entry.
        used = {out.confirmed_id for out in self.outgoing if out.confirmed_id is not None}
        for out in self.outgoing:
            if out.status not in {"submitted", "unknown"}:
                continue
            for m in self.ordered():
                if (
                    m.id not in used
                    and int(m.id) > out.after_id
                    and m.from_me
                    and m.text.replace("\r\n", "\n") == out.text.replace("\r\n", "\n")
                ):
                    out.status, out.detail = "confirmed", "대화 기록에서 확인"
                    out.confirmed_id = m.id
                    used.add(m.id)
                    break
        return added
