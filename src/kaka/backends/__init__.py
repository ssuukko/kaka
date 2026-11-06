"""Backend boundary: the UI never knows how KakaoTalk stores messages."""

from typing import Protocol

from kaka.models import Message, Room


class BackendError(Exception):
    def __init__(self, code: str, message: str, *, delivery: str = "unknown"):
        super().__init__(message)
        self.code = code
        self.delivery = delivery


class Backend(Protocol):
    async def status(self) -> dict: ...
    async def rooms(self) -> list[Room]: ...
    async def messages(
        self, room_id: str, *, before_id: int | None = None, limit: int = 100
    ) -> list[Message]: ...
    async def send(self, room_id: str, text: str) -> dict: ...
    async def close(self) -> None: ...
