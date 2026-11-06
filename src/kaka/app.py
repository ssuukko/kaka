"""KAKA's own terminal UI. Chat contents are always plain text, never markup."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message as UIMessage
from textual.widgets import Footer, Input, Label, OptionList, RichLog, Static, TextArea
from textual.widgets.option_list import Option

from kaka.backends import Backend, BackendError
from kaka.models import display_text
from kaka.session import ChatSession


class Composer(TextArea):
    class Submit(UIMessage):
        pass

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.post_message(self.Submit())
        elif event.key in {"shift+enter", "ctrl+j"}:
            event.stop()
            event.prevent_default()
            self.insert("\n")
        else:
            await super()._on_key(event)


class KakaApp(App):
    TITLE = "KAKA"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("ctrl+q", "quit", "종료", priority=True),
        Binding("ctrl+f", "search", "방 검색", priority=True),
        Binding("f5", "refresh", "새로고침", priority=True),
        Binding("ctrl+l", "latest", "최신 메시지", priority=True),
        Binding("ctrl+p", "older", "이전 기록", priority=True),
        Binding("ctrl+r", "restore", "미전송 복구", priority=True),
        Binding("ctrl+b", "sidebar", "목록 접기", priority=True),
    ]
    CSS = """
    Screen { background: #101418; color: #d8dee6; }
    #brand { height: 3; padding: 1 2; background: #171d24; color: #f5d76e; text-style: bold; }
    #body { height: 1fr; }
    #sidebar { width: 29; min-width: 18; background: #141a21; padding: 1; border-right: solid #2b3543; }
    #search { height: 3; border: round #344152; background: #101418; }
    #rooms { height: 1fr; background: #141a21; border: none; }
    #room-note { height: 2; color: #8491a3; padding: 0 1; }
    #main { width: 1fr; padding: 0 1; }
    #room-title { height: 3; padding: 1; color: #eff2f6; text-style: bold; }
    #history { height: 1fr; border-top: solid #2b3543; background: #101418; padding: 0 1; }
    #new { height: 1; color: #f5d76e; padding: 0 1; }
    #composer { height: 5; border: round #435167; background: #171d24; }
    #hint { height: 1; color: #8491a3; }
    #connection { height: 2; padding: 0 2; color: #9ba8b8; background: #171d24; }
    Footer { background: #171d24; }
    """

    def __init__(
        self,
        backend: Backend,
        *,
        demo: bool = False,
        poll_interval: float = 2,
        room_name: str | None = None,
    ):
        super().__init__()
        self.session = ChatSession(backend, send_interval=0 if demo else 2)
        self.demo = demo
        self.poll_interval = poll_interval
        self.initial_room = room_name
        self._poll_busy = False
        self._last_room_refresh = datetime.min
        self._loading_draft = False
        self._rendered: tuple = ()
        self._new_count = 0
        self._closing = False

    def compose(self) -> ComposeResult:
        mode = "DEMO · 실제 전송 없음" if self.demo else "KakaoTalk · 내 터미널의 대화"
        yield Static(f"K A K A     {mode}", id="brand")
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Input(placeholder="채팅방 검색  Ctrl+F", id="search")
                yield OptionList(id="rooms")
                yield Static("숫자: PC 카톡의 안 읽은 수", id="room-note")
            with Vertical(id="main"):
                yield Label("채팅방을 선택하세요", id="room-title", markup=False)
                yield RichLog(
                    id="history",
                    min_width=10,
                    wrap=True,
                    markup=False,
                    highlight=False,
                    auto_scroll=False,
                )
                yield Static("", id="new")
                yield Composer(id="composer", soft_wrap=True, tab_behavior="focus")
                yield Static("Enter 전송  ·  Ctrl+J 줄바꿈  ·  Tab 이동", id="hint")
        yield Static("연결 확인 중…", id="connection", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#composer", Composer).disabled = True
        self.set_interval(self.poll_interval, self.schedule_poll)
        self.run_worker(self.initialize(), group="init", exclusive=True)

    async def initialize(self) -> None:
        try:
            status = await self.session.backend.status()
            if status.get("running") is False:
                raise BackendError(
                    "KAKAO_NOT_RUNNING", "PC 카카오톡을 실행하고 로그인한 뒤 F5를 누르세요."
                )
            await self.session.refresh_rooms()
            self.render_rooms()
            self.set_connection(
                "데모 연결됨 · 합성 데이터" if self.demo else "연결됨 · 대화는 이 PC에서 처리됩니다"
            )
            if not self.session.active_id and self.initial_room:
                matches = [r for r in self.session.rooms if r.title == self.initial_room]
                if len(matches) == 1:
                    await self.select_room(matches[0].id)
                else:
                    self.set_connection("방 이름이 없거나 중복됩니다. 목록에서 직접 선택하세요.")
            elif self.session.active_id:
                await self.select_room(self.session.active_id)
            else:
                self.query_one("#rooms", OptionList).focus()
        except (BackendError, ValueError, KeyError) as error:
            self.set_connection(str(error))

    def set_connection(self, value: str) -> None:
        if not self._closing:
            self.query_one("#connection", Static).update(display_text(value))

    def render_rooms(self) -> None:
        widget = self.query_one("#rooms", OptionList)
        selected = widget.highlighted
        selected_id = None
        if selected is not None and selected < widget.option_count:
            selected_id = widget.get_option_at_index(selected).id
        query = self.query_one("#search", Input).value.casefold().strip()
        widget.clear_options()
        for room in self.session.rooms:
            if query not in room.title.casefold():
                continue
            name = Text(display_text(room.title))
            if not room.readable:
                name.append("  잠김", style="dim")
            elif room.unread:
                name.append(f"  {room.unread}", style="bold #f5d76e")
            widget.add_option(Option(name, id=room.id))
        if selected_id:
            try:
                widget.highlighted = widget.get_option_index(selected_id)
            except Exception:
                pass

    @on(Input.Changed, "#search")
    def filter_rooms(self) -> None:
        self.render_rooms()

    @on(Input.Submitted, "#search")
    def focus_rooms(self) -> None:
        self.query_one("#rooms", OptionList).focus()

    @on(OptionList.OptionSelected, "#rooms")
    def choose_room(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.run_worker(self.select_room(event.option.id), group="select", exclusive=True)

    async def select_room(self, room_id: str) -> None:
        old_id = self.session.active_id
        composer = self.query_one("#composer", Composer)
        if old_id:
            self.session.state(old_id).draft = composer.text
        room = next((r for r in self.session.rooms if r.id == room_id), None)
        if room is None:
            self.set_connection("현재 목록에 없는 방입니다. F5로 갱신하세요.")
            return
        self.session.active_id = room_id
        self._loading_draft = True
        composer.load_text(self.session.state(room_id).draft)
        self._loading_draft = False
        composer.disabled = False
        self.query_one("#room-title", Label).update(display_text(room.title))
        self._rendered = ()
        self._new_count = 0
        self.render_history(force=True, bottom=True)
        composer.focus()
        try:
            await self.session.sync(room_id)
            if self.session.active_id == room_id:
                self.render_history(force=True, bottom=True)
                self.set_connection(
                    "데모 · 실제 카카오톡으로 전송되지 않습니다"
                    if self.demo
                    else "연결됨 · Enter로 현재 방에 전송"
                )
        except (BackendError, ValueError) as error:
            if self.session.active_id == room_id:
                self.set_connection(str(error))

    @on(TextArea.Changed, "#composer")
    def remember_draft(self) -> None:
        if self.session.active_id and not self._loading_draft:
            self.session.state(self.session.active_id).draft = self.query_one(
                "#composer", Composer
            ).text

    def schedule_poll(self) -> None:
        if not self._poll_busy and self.session.active_id and not self._closing:
            self.run_worker(self.poll(), group="poll")

    async def poll(self) -> None:
        self._poll_busy = True
        room_id = self.session.active_id
        try:
            if room_id:
                log = self.query_one("#history", RichLog)
                at_bottom = log.is_vertical_scroll_end
                added = await self.session.sync(room_id)
                if self.session.active_id == room_id:
                    if not at_bottom:
                        self._new_count += added
                    self.render_history()
                    self.set_connection(
                        "데모 연결됨" if self.demo else "연결됨 · 새 메시지 확인 중"
                    )
            if (datetime.now() - self._last_room_refresh).total_seconds() > 15:
                await self.session.refresh_rooms()
                self._last_room_refresh = datetime.now()
                self.render_rooms()
        except (BackendError, ValueError) as error:
            if self.session.active_id == room_id:
                self.set_connection(str(error))
        finally:
            self._poll_busy = False

    def render_history(self, *, force: bool = False, bottom: bool = False) -> None:
        room_id = self.session.active_id
        if not room_id:
            return
        state = self.session.state(room_id)
        messages = state.ordered()
        pending = [p for p in state.outgoing if p.status != "confirmed"]
        fingerprint = (
            room_id,
            tuple(messages),
            tuple((p.text, p.status, p.detail) for p in pending),
        )
        if not force and fingerprint == self._rendered:
            return
        self._rendered = fingerprint
        log = self.query_one("#history", RichLog)
        was_bottom = bottom or log.is_vertical_scroll_end
        offset = log.scroll_y
        log.clear()
        previous_day = None
        for message in messages:
            when = message.sent_at.astimezone()
            if when.date() != previous_day:
                log.write(Text(f"\n  {when:%Y년 %m월 %d일}\n", style="dim"))
                previous_day = when.date()
            header = Text(f"{when:%H:%M}  ", style="dim")
            header.append(
                "나" if message.from_me else display_text(message.sender),
                style="bold #f5d76e" if message.from_me else "bold #a9b9ce",
            )
            log.write(header)
            body = message.text or f"[{message.kind}]"
            log.write(Text("  " + display_text(body).replace("\n", "\n  ")))
            log.write(Text(""))
        for outgoing in pending[-20:]:
            label = {
                "sending": "전송 중",
                "submitted": "기록 확인 중",
                "unknown": "전송 미확인",
                "rejected": "미전송",
            }[outgoing.status]
            log.write(Text(f"[{label}] {display_text(outgoing.text)}", style="dim"))
        if not messages and not pending:
            log.write(
                Text(
                    "대화를 불러오는 중입니다. 잠긴 방은 PC 카카오톡에서 한 번 열어 주세요.",
                    style="dim",
                )
            )
        if was_bottom:
            self._new_count = 0
            self.call_after_refresh(log.scroll_end, animate=False)
        else:
            self.call_after_refresh(log.scroll_to, y=offset, animate=False)
        self.query_one("#new", Static).update(
            f"↓ 새 메시지 {self._new_count}개 · Ctrl+L로 최신 이동" if self._new_count else ""
        )

    @on(Composer.Submit)
    def submit_message(self) -> None:
        room_id = self.session.active_id
        composer = self.query_one("#composer", Composer)
        if not room_id or self.session.send_busy or not composer.text.strip():
            return
        text = composer.text
        # Capture both room and body before any await; a room switch cannot retarget it.
        self.run_worker(self.send_message(room_id, text), group="send")

    async def send_message(self, room_id: str, text: str) -> None:
        if self.session.send_busy:
            return
        state = self.session.state(room_id)
        state.draft = ""
        if self.session.active_id == room_id:
            self.query_one("#composer", Composer).load_text("")
        self.set_connection("전송 중…")
        try:
            outgoing = await self.session.send(room_id, text)
            if outgoing is not None:
                if outgoing.status == "rejected":
                    self.restore_if_empty(room_id, text)
                prefix = "이전 방 전송 결과: " if self.session.active_id != room_id else ""
                self.set_connection(prefix + outgoing.detail)
        except BackendError as error:
            self.restore_if_empty(room_id, text)
            self.set_connection(str(error))
        finally:
            if self.session.active_id == room_id:
                self.render_history()

    def restore_if_empty(self, room_id: str, text: str) -> None:
        state = self.session.state(room_id)
        # A Changed event may still be queued. Read the widget itself before restoring.
        if self.session.active_id == room_id:
            composer = self.query_one("#composer", Composer)
            if composer.text:
                state.draft = composer.text
                return
            composer.load_text(text)
            state.draft = text
        elif not state.draft:
            state.draft = text

    def action_search(self) -> None:
        self.query_one("#sidebar").display = True
        self.query_one("#search", Input).focus()

    def action_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar")
        sidebar.display = not sidebar.display
        if not sidebar.display:
            self.query_one("#composer", Composer).focus()

    def action_refresh(self) -> None:
        self.run_worker(self.initialize(), group="init", exclusive=True)

    def action_latest(self) -> None:
        self._new_count = 0
        self.query_one("#new", Static).update("")
        self.query_one("#history", RichLog).scroll_end(animate=False)

    def action_older(self) -> None:
        if self.session.active_id:
            self.run_worker(self.load_older(self.session.active_id), group="older", exclusive=True)

    async def load_older(self, room_id: str) -> None:
        try:
            count = await self.session.older(room_id)
            if self.session.active_id == room_id:
                self.render_history(force=True)
                self.set_connection(f"이전 기록 {count}개 불러옴 · 위로 스크롤하세요")
        except BackendError as error:
            self.set_connection(str(error))

    def action_restore(self) -> None:
        room_id = self.session.active_id
        if not room_id:
            return
        composer = self.query_one("#composer", Composer)
        if composer.text:
            self.set_connection("현재 초안을 비운 뒤 Ctrl+R을 누르세요. 초안을 덮어쓰지 않습니다.")
            return
        text = self.session.restore_last(room_id)
        if text is not None:
            composer.load_text(text)
            self.set_connection(
                "이전 글을 복구했습니다. 이미 전송됐는지 확인한 뒤 Enter를 누르세요."
            )
        else:
            self.set_connection("복구할 미전송 글이 없습니다.")

    def action_quit(self) -> None:
        if self.session.send_busy:
            self.set_connection("전송 처리 중입니다. 결과를 확인한 뒤 Ctrl+Q로 종료하세요.")
            return
        self.exit()

    async def on_unmount(self) -> None:
        self._closing = True
        await self.session.backend.close()
