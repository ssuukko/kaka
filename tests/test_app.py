import asyncio

from textual import events
from textual.widgets import Input, OptionList, RichLog

from kaka.app import Composer, KakaApp
from kaka.backends import BackendError
from kaka.backends.demo import DemoBackend


async def test_ui_select_send_and_search():
    backend = DemoBackend(auto_reply=False)
    app = KakaApp(backend, demo=True, poll_interval=60)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        rooms = app.query_one("#rooms", OptionList)
        assert rooms.option_count == 3
        rooms.highlighted = 0
        rooms.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert app.session.active_id == "101"
        composer = app.query_one("#composer", Composer)
        composer.load_text("직접 입력한 한글😀")
        composer.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert composer.text == ""
        assert backend._messages["101"][-1].text == "직접 입력한 한글😀"
        assert app.session.state("101").outgoing[-1].status == "confirmed"
        await pilot.press("ctrl+f")
        app.query_one("#search", Input).value = "프로젝트"
        await pilot.pause()
        assert rooms.option_count == 1


async def test_room_drafts_survive_switch_and_incoming_message():
    backend = DemoBackend(auto_reply=False)
    app = KakaApp(backend, demo=True, poll_interval=60)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await app.select_room("101")
        composer = app.query_one("#composer", Composer)
        composer.load_text("아직 작성 중\n두 번째 줄")
        await pilot.pause()
        await app.select_room("102")
        composer.load_text("다른 방 초안")
        await pilot.pause()
        await app.select_room("101")
        assert composer.text == "아직 작성 중\n두 번째 줄"
        backend.inject("101", "새 메시지")
        await app.poll()
        await pilot.pause()
        assert composer.text == "아직 작성 중\n두 번째 줄"
        assert app.session.state("102").draft == "다른 방 초안"


async def test_paste_and_newline_do_not_send():
    backend = DemoBackend(auto_reply=False)
    app = KakaApp(backend, demo=True, poll_interval=60)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.select_room("101")
        composer = app.query_one("#composer", Composer)
        composer.focus()
        composer.post_message(events.Paste("붙여넣기\n여러 줄\n"))
        await pilot.pause()
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert len(backend._messages["101"]) == 2
        assert "붙여넣기" in composer.text
        assert composer.text.count("\n") >= 3


async def test_slow_send_room_switch_does_not_clear_other_draft():
    backend = DemoBackend(auto_reply=False)
    entered, release = asyncio.Event(), asyncio.Event()
    original = backend.send

    async def slow(room_id, text):
        entered.set()
        await release.wait()
        return await original(room_id, text)

    backend.send = slow
    app = KakaApp(backend, demo=True, poll_interval=60)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.select_room("101")
        composer = app.query_one("#composer", Composer)
        composer.load_text("보낼 글")
        composer.focus()
        await pilot.press("enter")
        await entered.wait()
        await app.select_room("102")
        composer.load_text("현재 방의 새 초안")
        await pilot.pause()
        release.set()
        await pilot.pause()
        assert composer.text == "현재 방의 새 초안"
        assert backend._messages["101"][-1].text == "보낼 글"
        assert all(m.text != "보낼 글" for m in backend._messages["102"])


async def test_refused_send_restores_draft():
    backend = DemoBackend(auto_reply=False)

    async def refuse(*_args):
        raise BackendError("WINDOW_NOT_FOUND", "missing", delivery="not_delivered")

    backend.send = refuse
    app = KakaApp(backend, demo=True, poll_interval=60)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.select_room("101")
        composer = app.query_one("#composer", Composer)
        composer.load_text("복구할 글")
        composer.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert composer.text == "복구할 글"
        assert app.session.state("101").outgoing[-1].status == "rejected"


async def test_scrollback_does_not_jump_on_receive():
    backend = DemoBackend(auto_reply=False)
    for i in range(100):
        backend.inject("101", f"합성 메시지 {i}")
    app = KakaApp(backend, demo=True, poll_interval=60)
    async with app.run_test(size=(90, 28)) as pilot:
        await pilot.pause()
        await app.select_room("101")
        await pilot.pause()
        log = app.query_one("#history", RichLog)
        log.scroll_to(y=10, animate=False)
        await pilot.pause()
        old_y = log.scroll_y
        backend.inject("101", "새로운 글")
        await app.poll()
        await pilot.pause()
        assert log.scroll_y == old_y
        assert app._new_count == 1
        app.action_latest()
        await pilot.pause()
        assert log.is_vertical_scroll_end


async def test_narrow_layout_and_control_text():
    backend = DemoBackend(auto_reply=False)
    backend.inject("101", "[link=https://bad.example]원문[/link]\x1b[31m 빨강")
    app = KakaApp(backend, demo=True, poll_interval=60)
    async with app.run_test(size=(60, 22)) as pilot:
        await pilot.pause()
        await app.select_room("101")
        app.action_sidebar()
        await pilot.pause()
        assert not app.query_one("#sidebar").display
        composer = app.query_one("#composer", Composer)
        assert composer.size.width > 40
        composer.load_text("한글 테스트")
        await pilot.pause()
        assert composer.text == "한글 테스트"


async def test_recovery_cannot_overwrite_input_before_changed_event():
    app = KakaApp(DemoBackend(auto_reply=False), demo=True, poll_interval=60)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.select_room("101")
        composer = app.query_one("#composer", Composer)
        composer.load_text("방금 쓴 다음 글")
        # Deliberately no pause: TextArea.Changed hasn't reached the app yet.
        app.restore_if_empty("101", "실패한 이전 글")
        assert composer.text == "방금 쓴 다음 글"
        assert app.session.state("101").draft == "방금 쓴 다음 글"
