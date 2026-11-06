"""Synthetic data only. Demo never opens the real KakaoTalk client."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from kaka.models import Message, Room


class DemoBackend:
    def __init__(self, *, auto_reply: bool = True):
        self._rooms = [
            Room("101", "나와의 채팅", member_count=1),
            Room("102", "프로젝트 팀 · 데모", unread=2, member_count=4),
            Room("103", "주말 약속 · 데모", member_count=3),
        ]
        now = datetime.now().astimezone()
        self._messages: dict[str, list[Message]] = {
            "101": [
                Message(
                    "1",
                    "101",
                    "나",
                    "KAKA에 오신 것을 환영합니다.",
                    now - timedelta(minutes=3),
                    True,
                ),
                Message(
                    "2",
                    "101",
                    "나",
                    "이 화면은 가짜 데이터입니다. 메시지를 써도 실제 카카오톡으로 보내지지 않습니다.",
                    now - timedelta(minutes=2),
                    True,
                ),
            ],
            "102": [
                Message(
                    "3", "102", "지민", "오늘 변경한 화면 같이 볼까요?", now - timedelta(minutes=3)
                ),
                Message(
                    "4",
                    "102",
                    "나",
                    "네, 터미널에서 확인하고 있어요.",
                    now - timedelta(minutes=2),
                    True,
                ),
                Message(
                    "5",
                    "102",
                    "유진",
                    "입력 중에 새 메시지가 와도 초안이 유지되면 좋겠어요.",
                    now - timedelta(minutes=1),
                ),
            ],
            "103": [
                Message("6", "103", "민수", "토요일에 점심 먹을까요?", now - timedelta(minutes=10)),
                Message(
                    "7",
                    "103",
                    "서연",
                    "좋아요! 저는 12시부터 가능합니다.",
                    now - timedelta(minutes=9),
                ),
            ],
        }
        self._next_id = 100
        self._tasks: set[asyncio.Task] = set()
        self.auto_reply = auto_reply

    async def status(self) -> dict:
        return {"ok": True, "running": True, "demo": True}

    async def rooms(self) -> list[Room]:
        return list(self._rooms)

    async def messages(
        self, room_id: str, *, before_id: int | None = None, limit: int = 100
    ) -> list[Message]:
        values = self._messages[room_id]
        if before_id is not None:
            values = [m for m in values if int(m.id) < before_id]
        return list(values[-limit:])

    def inject(self, room_id: str, text: str, *, from_me: bool = False) -> Message:
        self._next_id += 1
        msg = Message(
            str(self._next_id),
            room_id,
            "나" if from_me else "데모 상대",
            text,
            datetime.now().astimezone(),
            from_me,
        )
        self._messages[room_id].append(msg)
        return msg

    async def send(self, room_id: str, text: str) -> dict:
        self.inject(room_id, text, from_me=True)
        if self.auto_reply and room_id != "101":
            task = asyncio.create_task(self._reply(room_id))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return {"ok": True, "submitted": True}

    async def _reply(self, room_id: str) -> None:
        await asyncio.sleep(1)
        self.inject(room_id, "잘 받았어요. 이것은 수신 동작을 보여주는 데모 메시지입니다.")

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
