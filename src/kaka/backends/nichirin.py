"""JSON CLI adapter. No HTTP listener, AI API, or Kakao credentials."""

from __future__ import annotations

import asyncio
import json
import os
import struct
import sys
from contextlib import suppress
from pathlib import Path

from kaka.backends import BackendError
from kaka.models import Message, Room, identifier

HINTS = {
    "KEY_UNAVAILABLE": "PC 카카오톡에서 이 방을 한 번 열고 최소화한 뒤 F5를 누르세요.",
    "KAKAO_NOT_RUNNING": "PC 카카오톡을 실행하고 로그인한 뒤 F5를 누르세요.",
    "NO_USER_DATA": "PC 카카오톡 로그인을 확인하세요.",
    "WINDOW_NOT_FOUND": "PC 카카오톡에서 대상 방을 한 번 열어 주세요.",
    "INPUT_NOT_FOUND": "카카오톡 채팅방 입력창을 찾지 못했습니다. 해당 창을 다시 열어 주세요.",
    "AMBIGUOUS_CHAT": "채팅방을 확정하지 못했습니다. 방 이름을 구분하고 다시 선택하세요.",
    "CHAT_NOT_FOUND": "채팅방이 사라졌습니다. F5로 방 목록을 새로 불러오세요.",
    "BUSY": "카카오톡 데이터를 갱신 중입니다. 다음 조회에서 다시 확인합니다.",
    "READ_FAILED": "대화 조회 실패. 카카오톡 로그인·64비트 버전·열린 방을 확인하세요.",
    "SEND_FAILED": "전송 여부를 확인하지 못했습니다. 원래 카카오톡에서 확인하세요.",
}


class EngineTransport:
    def __init__(self, root: Path, *, timeout: float = 20):
        self.root = root.resolve()
        self.timeout = timeout
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None

    async def call(self, args: list[str], *, writing: bool = False) -> dict:
        if not (self.root / "nichirin" / "__main__.py").is_file():
            raise BackendError(
                "ENGINE_MISSING",
                "연동 엔진이 없습니다. scripts/setup.ps1을 실행하세요.",
                delivery="not_delivered",
            )
        async with self._lock:
            process = None
            try:
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-X",
                    "utf8",
                    str(Path(__file__).with_name("_worker.py")),
                    str(self.root),
                    cwd=self.root,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    **({"creationflags": 0x08000000} if sys.platform == "win32" else {}),
                )
                self._process = process
                body = json.dumps({"args": args}, ensure_ascii=False).encode("utf-8")
                stdout, _stderr = await asyncio.wait_for(process.communicate(body), self.timeout)
            except TimeoutError as error:
                raise BackendError(
                    "TIMEOUT", "카카오톡 연결이 지연됩니다. 전송은 자동 재시도하지 않습니다."
                ) from error
            except OSError as error:
                raise BackendError(
                    "ENGINE_START",
                    "연동 엔진을 시작하지 못했습니다.",
                    delivery="not_delivered" if process is None else "unknown",
                ) from error
            finally:
                if process is not None and process.returncode is None:
                    with suppress(ProcessLookupError):
                        process.kill()
                    await process.communicate()
                self._process = None
            try:
                result = json.loads(stdout.decode("utf-8-sig"))
                if not isinstance(result, dict) or type(result.get("ok")) is not bool:
                    raise ValueError("invalid envelope")
            except (ValueError, UnicodeError) as error:
                # Do not include engine stdout/stderr: it may contain chat contents.
                raise BackendError("PROTOCOL", "연동 엔진의 응답 형식이 맞지 않습니다.") from error
            if not result["ok"]:
                failure = result.get("error") or {}
                code = str(failure.get("code", "UNKNOWN"))
                disposition = failure.get("disposition") or {}
                raise BackendError(
                    code,
                    HINTS.get(code, f"카카오톡 연동 오류: {code}"),
                    delivery=disposition.get("delivery", "unknown"),
                )
            if process.returncode != 0:
                raise BackendError("PROTOCOL", "연동 엔진이 정상 종료되지 않았습니다.")
            if writing and result.get("submitted") is not True:
                raise BackendError(
                    "UNCONFIRMED", "전송 결과가 불확실합니다. 카카오톡에서 확인하세요."
                )
            return result

    async def close(self) -> None:
        if self._process is not None and self._process.returncode is None:
            with suppress(ProcessLookupError):
                self._process.kill()
            await self._process.wait()


class NichirinBackend:
    def __init__(self, root: Path, *, timeout: float = 20):
        self.transport = EngineTransport(root, timeout=timeout)

    async def status(self) -> dict:
        if sys.platform != "win32" or struct.calcsize("P") != 8:
            raise BackendError(
                "PLATFORM",
                "실제 연결에는 Windows 10/11과 64비트 Python이 필요합니다. --demo로 화면을 볼 수 있습니다.",
            )
        return await self.transport.call(["status"])

    async def rooms(self) -> list[Room]:
        return [Room.parse(r) for r in (await self.transport.call(["rooms"]))["rooms"]]

    async def messages(
        self, room_id: str, *, before_id: int | None = None, limit: int = 100
    ) -> list[Message]:
        room_id = identifier(room_id)
        args = ["messages", "--room-id", room_id, "--limit", str(limit)]
        if before_id is not None:
            args += ["--before-id", str(before_id)]
        raw = await self.transport.call(args)
        if identifier(raw["room"]["id"]) != room_id:
            raise BackendError("WRONG_ROOM", "다른 채팅방의 응답을 받았습니다.")
        try:
            messages = [Message.parse(m) for m in raw["messages"]]
            if any(m.room_id != room_id for m in messages):
                raise ValueError("mixed rooms")
            return messages
        except (KeyError, TypeError, ValueError) as error:
            raise BackendError("PROTOCOL", "메시지 응답을 해석하지 못했습니다.") from error

    async def send(self, room_id: str, text: str) -> dict:
        # `--` makes strings such as --open and $() literal message text.
        return await self.transport.call(
            ["send", "--room-id", identifier(room_id), "--open", "--", text], writing=True
        )

    async def close(self) -> None:
        await self.transport.close()
