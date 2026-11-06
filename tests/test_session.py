import asyncio
import time
from datetime import UTC, datetime

import pytest

from kaka.backends import BackendError
from kaka.backends.demo import DemoBackend
from kaka.models import Message
from kaka.session import ChatSession


async def create_session():
    backend = DemoBackend(auto_reply=False)
    session = ChatSession(backend, send_interval=0)
    await session.refresh_rooms()
    await session.sync("101")
    return session, backend


async def test_catchup_does_not_lose_more_than_one_page():
    session, backend = await create_session()
    for i in range(350):
        backend.inject("101", f"새 메시지 {i}")
    count = await session.sync("101")
    assert count == 350
    assert len(session.state("101").messages) == 352
    assert await session.sync("101") == 0


async def test_failed_catchup_never_advances_high_water_mark():
    session, backend = await create_session()
    previous = session.state("101").latest_id
    for i in range(120):
        backend.inject("101", str(i))
    original = backend.messages

    async def fail_older(*args, **kwargs):
        if kwargs.get("before_id") is not None:
            raise BackendError("BUSY", "busy")
        return await original(*args, **kwargs)

    backend.messages = fail_older
    with pytest.raises(BackendError):
        await session.sync("101")
    assert session.state("101").latest_id == previous
    backend.messages = original
    assert await session.sync("101") == 120


async def test_unknown_send_is_never_retried():
    session, backend = await create_session()
    calls = []

    async def timeout(room_id, text):
        calls.append((room_id, text))
        raise BackendError("TIMEOUT", "unknown")

    backend.send = timeout
    out = await session.send("101", "확인")
    assert out.status == "unknown"
    for _ in range(3):
        await session.sync("101")
    assert calls == [("101", "확인")]
    assert session.restore_last("101") == "확인"


async def test_readback_recovers_send_that_timed_out_after_submit():
    session, backend = await create_session()

    async def delivered_but_timeout(room_id, text):
        backend.inject(room_id, text, from_me=True)
        raise BackendError("TIMEOUT", "unknown")

    backend.send = delivered_but_timeout
    assert (await session.send("101", "확인")).status == "confirmed"


async def test_preflight_failure_prevents_write():
    session, backend = await create_session()
    calls = []

    async def locked(*_args, **_kwargs):
        raise BackendError("KEY_UNAVAILABLE", "locked")

    async def write(*args):
        calls.append(args)

    backend.messages, backend.send = locked, write
    out = await session.send("101", "확인")
    assert out.status == "rejected"
    assert calls == []


async def test_double_enter_and_room_switch_cannot_retarget_send():
    session, backend = await create_session()
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def slow(room_id, text):
        calls.append((room_id, text))
        entered.set()
        await release.wait()
        backend.inject(room_id, text, from_me=True)
        return {"ok": True, "submitted": True}

    backend.send = slow
    session.active_id = "101"
    task = asyncio.create_task(session.send("101", "처음 방"))
    await entered.wait()
    session.active_id = "102"
    assert await session.send("102", "두 번째") is None
    release.set()
    assert (await task).status == "confirmed"
    assert calls == [("101", "처음 방")]


async def test_known_refusal_and_readback_timeout_are_distinct():
    session, backend = await create_session()

    async def refusal(*_args):
        raise BackendError("WINDOW_NOT_FOUND", "missing", delivery="not_delivered")

    backend.send = refusal
    assert (await session.send("101", "안녕")).status == "rejected"


async def test_empty_and_invalid_inputs_cannot_send():
    session, _ = await create_session()
    assert await session.send("101", "  \n") is None
    for value in ["\x00hello", "a" * 4001]:
        with pytest.raises(BackendError):
            await session.send("101", value)
    assert not session.send_busy
    assert session.state("101").outgoing == []


async def test_older_history_is_deduplicated():
    session, backend = await create_session()
    backend._messages["103"] = [
        Message(str(i), "103", "친구", str(i), datetime.now(UTC)) for i in range(1, 251)
    ]
    await session.sync("103")
    assert len(session.state("103").messages) == 100
    assert await session.older("103") == 100
    assert await session.older("103") == 50
    assert not session.state("103").older_available
    assert len(session.state("103").messages) == 250


async def test_expired_submission_becomes_unknown_without_resending():
    session, _ = await create_session()
    from kaka.models import Outgoing

    out = Outgoing(
        "확인되지 않은 글",
        session.state("101").latest_id,
        time.monotonic() - 60,
        status="submitted",
    )
    session.state("101").outgoing.append(out)
    await session.sync("101")
    assert out.status == "unknown"
