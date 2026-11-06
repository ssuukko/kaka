"""Conversation state and ordering, independent of Textual and Windows."""

from __future__ import annotations

import asyncio
import time

from kaka.backends import Backend, BackendError
from kaka.models import Conversation, Outgoing, Room


class ChatSession:
    PAGE_SIZE = 100
    MAX_CATCHUP_PAGES = 50

    def __init__(self, backend: Backend, *, send_interval: float = 2):
        self.backend = backend
        self.rooms: list[Room] = []
        self.conversations: dict[str, Conversation] = {}
        self.active_id: str | None = None
        self.send_busy = False
        self.send_interval = send_interval
        self._last_send = -float("inf")
        self._read_locks: dict[str, asyncio.Lock] = {}

    def state(self, room_id: str) -> Conversation:
        return self.conversations.setdefault(room_id, Conversation())

    async def refresh_rooms(self) -> None:
        rooms = await self.backend.rooms()
        if len({r.id for r in rooms}) != len(rooms):
            raise BackendError("PROTOCOL", "채팅방 ID가 중복되었습니다.")
        self.rooms = rooms

    async def sync(self, room_id: str) -> int:
        async with self._read_locks.setdefault(room_id, asyncio.Lock()):
            state = self.state(room_id)
            cursor = state.latest_id
            page = await self.backend.messages(room_id, limit=self.PAGE_SIZE)
            batch = list(page)
            # On reconnect, page backwards until the old high-water mark is covered.
            # Never silently skip a burst that exceeds a single page.
            pages = 1
            while cursor and len(page) == self.PAGE_SIZE and min(int(m.id) for m in page) > cursor:
                if pages >= self.MAX_CATCHUP_PAGES:
                    raise BackendError(
                        "CATCHUP_LIMIT",
                        "누적 메시지가 많아 갱신을 중단했습니다. 앱을 다시 열어 최근 기록부터 확인하세요.",
                    )
                before = min(int(m.id) for m in page)
                page = await self.backend.messages(room_id, before_id=before, limit=self.PAGE_SIZE)
                if any(int(m.id) >= before for m in page):
                    raise BackendError("PROTOCOL", "이전 기록 조회가 앞으로 진행하지 않습니다.")
                batch.extend(page)
                pages += 1
            added = state.merge(room_id, batch)
            if not state.initialized:
                state.older_available = len(batch) == self.PAGE_SIZE
            state.initialized = True
            for out in state.outgoing:
                if out.status == "submitted" and time.monotonic() - out.started > 30:
                    out.status, out.detail = "unknown", "기록 확인 지연 · 원래 카카오톡에서 확인"
            return added

    async def older(self, room_id: str) -> int:
        async with self._read_locks.setdefault(room_id, asyncio.Lock()):
            state = self.state(room_id)
            if not state.messages:
                return 0
            page = await self.backend.messages(
                room_id, before_id=state.earliest_id, limit=self.PAGE_SIZE
            )
            if any(int(m.id) >= state.earliest_id for m in page):
                raise BackendError("PROTOCOL", "이전 기록 조회의 순서가 잘못되었습니다.")
            count = state.merge(room_id, page)
            state.older_available = len(page) == self.PAGE_SIZE
            return count

    async def send(self, room_id: str, text: str) -> Outgoing | None:
        if self.send_busy or not text.strip():
            return None
        if "\x00" in text or len(text) > 4000:
            raise BackendError(
                "INVALID_TEXT",
                "메시지는 NUL 문자 없이 4,000자 이내로 작성하세요.",
                delivery="not_delivered",
            )
        if room_id not in {r.id for r in self.rooms}:
            raise BackendError(
                "UNKNOWN_ROOM",
                "선택한 채팅방이 없습니다. F5로 새로고침하세요.",
                delivery="not_delivered",
            )
        self.send_busy = True
        state = self.state(room_id)
        out = Outgoing(text, state.latest_id, time.monotonic())
        state.outgoing.append(out)
        try:
            # Reads are safe to retry; writes never are. Establish a fresh baseline
            # so an old identical message cannot be mistaken for this send.
            try:
                await self.sync(room_id)
                await asyncio.sleep(
                    max(0, self.send_interval - (time.monotonic() - self._last_send))
                )
            except BackendError as error:
                out.status, out.detail = "rejected", str(error)
                return out
            out.after_id = state.latest_id
            out.started = time.monotonic()
            self._last_send = out.started
            try:
                await self.backend.send(room_id, text)
                out.status, out.detail = "submitted", "클라이언트 제출됨 · 기록 확인 중"
            except BackendError as error:
                out.status = "rejected" if error.delivery == "not_delivered" else "unknown"
                out.detail = str(error)
            except Exception:
                out.status, out.detail = (
                    "unknown",
                    "전송 결과를 확인하지 못했습니다. 자동 재전송하지 않습니다.",
                )
            if out.status in {"submitted", "unknown"}:
                try:
                    await self.sync(room_id)
                except BackendError:
                    pass
            return out
        except asyncio.CancelledError:
            out.status, out.detail = "unknown", "앱 종료 중 전송이 중단됨 · 카카오톡에서 확인"
            raise
        finally:
            self.send_busy = False

    def restore_last(self, room_id: str) -> str | None:
        state = self.state(room_id)
        for out in reversed(state.outgoing):
            if out.status in {"rejected", "unknown"}:
                return out.text
        return None
