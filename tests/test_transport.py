import json
from pathlib import Path

import pytest

from kaka.backends import BackendError
from kaka.backends.nichirin import EngineTransport, NichirinBackend


def fake_engine(tmp_path: Path, source: str) -> Path:
    module = tmp_path / "nichirin"
    module.mkdir()
    (module / "__init__.py").write_text("", encoding="utf-8")
    (module / "__main__.py").write_text(source, encoding="utf-8")
    return tmp_path


async def test_worker_round_trip_unicode_and_literal_shell_characters(tmp_path):
    root = fake_engine(
        tmp_path,
        "import sys,json\nprint(json.dumps({'ok':True,'args':sys.argv[1:]},ensure_ascii=False))",
    )
    transport = EngineTransport(root)
    text = "한글😀\n--open $(do-not-run) `literal` &|<> [red]"
    args = ["send", "--room-id", "9007199254740993", "--", text]
    actual = await transport.call(args)
    assert actual["args"] == args
    assert transport._process is None


async def test_send_body_does_not_appear_in_process_command_line(tmp_path, monkeypatch):
    import asyncio

    calls = []
    original = asyncio.create_subprocess_exec

    async def spy(*args, **kwargs):
        calls.append(args)
        assert not kwargs.get("shell")
        return await original(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    root = fake_engine(tmp_path, "import json\nprint(json.dumps({'ok': True, 'submitted':True}))")
    await EngineTransport(root).call(["send", "--", "private synthetic message"], writing=True)
    assert all("private synthetic message" not in str(arg) for arg in calls[0])


async def test_timeout_kills_and_reaps_child(tmp_path):
    root = fake_engine(tmp_path, "import time\ntime.sleep(30)")
    transport = EngineTransport(root, timeout=0.1)
    with pytest.raises(BackendError) as failure:
        await transport.call(["send", "--", "test"], writing=True)
    assert failure.value.delivery == "unknown"
    assert transport._process is None


async def test_malformed_response_does_not_leak_content(tmp_path):
    root = fake_engine(tmp_path, "print('sensitive-chat-text')")
    with pytest.raises(BackendError) as failure:
        await EngineTransport(root).call(["messages"])
    assert "sensitive" not in str(failure.value)
    assert failure.value.code == "PROTOCOL"


async def test_error_disposition_is_preserved(tmp_path):
    payload = {
        "ok": False,
        "error": {
            "code": "SEND_FAILED",
            "message": "secret original text",
            "disposition": {"delivery": "not_delivered", "retry": "safe"},
        },
    }
    root = fake_engine(
        tmp_path, f"import json\nprint(json.dumps({payload!r}))\nraise SystemExit(1)"
    )
    with pytest.raises(BackendError) as failure:
        await EngineTransport(root).call(["send"], writing=True)
    assert failure.value.delivery == "not_delivered"
    assert "secret" not in str(failure.value)


@pytest.mark.parametrize(
    "payload,exit_code", [({"ok": True}, 0), ({"ok": True, "submitted": True}, 1)]
)
async def test_inconsistent_send_ack_is_not_success(tmp_path, payload, exit_code):
    root = fake_engine(
        tmp_path, f"import json\nprint(json.dumps({payload!r}))\nraise SystemExit({exit_code})"
    )
    with pytest.raises(BackendError):
        await EngineTransport(root).call(["send"], writing=True)


async def test_missing_engine_is_known_unsent(tmp_path):
    with pytest.raises(BackendError) as failure:
        await EngineTransport(tmp_path).call(["send"], writing=True)
    assert failure.value.delivery == "not_delivered"


async def test_pinned_upstream_fixtures_are_parsed():
    backend = NichirinBackend(Path("."))

    async def fixture(args, **kwargs):
        name = "rooms" if args[0] == "rooms" else "messages"
        return json.loads((Path(__file__).parent / "fixtures" / f"{name}.json").read_text())

    backend.transport.call = fixture
    rooms = await backend.rooms()
    assert rooms[2].id == "9007199254740993"
    messages = await backend.messages("1001")
    assert [m.from_me for m in messages] == [False, True, False]
    assert messages[0].sent_at.tzinfo is not None
    with pytest.raises(BackendError):
        await backend.messages("1002")
