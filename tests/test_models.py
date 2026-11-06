from datetime import UTC, datetime

import pytest

from kaka.models import Conversation, Message, Outgoing, display_text, identifier


def msg(mid="9007199254740993", text="확인", room="101", mine=False):
    return Message(mid, room, "지민", text, datetime.now(UTC), mine)


@pytest.mark.parametrize("value", [True, 1.2, None, "１２３", "1e10", "", "../1"])
def test_reject_lossy_ids(value):
    with pytest.raises(ValueError):
        identifier(value)


def test_large_identifier_and_deduplication():
    state = Conversation()
    assert identifier("9007199254740993") == "9007199254740993"
    assert state.merge("101", [msg()]) == 1
    assert state.merge("101", [msg()]) == 0
    assert state.latest_id == 9007199254740993
    assert len(state.messages) == 1


def test_message_edits_replace_existing_id():
    state = Conversation()
    state.merge("101", [msg(text="이전")])
    state.merge("101", [msg(text="수정")])
    assert state.ordered()[0].text == "수정"


def test_duplicate_rows_in_a_single_batch_count_once():
    state = Conversation()
    assert state.merge("101", [msg(), msg()]) == 1


def test_room_mismatch_is_atomic():
    state = Conversation()
    with pytest.raises(ValueError):
        state.merge("101", [msg("1"), msg("2", room="102")])
    assert state.messages == {}


def test_control_sequences_are_not_rendered():
    assert display_text("안녕\x1b[31m빨강\x1b[0m\x00\x07\n한글😀") == "안녕빨강\n한글😀"
    assert display_text("\x1b]52;c;payload\x07본문") == "본문"
    assert display_text("[red]hello[/red]") == "[red]hello[/red]"


def test_confirmation_does_not_match_old_identical_or_other_sender():
    state = Conversation(outgoing=[Outgoing("확인", 10, 0, status="submitted")])
    state.merge("101", [msg("9", mine=True), msg("11", mine=False)])
    assert state.outgoing[0].status == "submitted"
    state.merge("101", [msg("12", mine=True)])
    assert state.outgoing[0].status == "confirmed"


def test_one_record_cannot_confirm_two_pending_sends_across_polls():
    state = Conversation(
        outgoing=[
            Outgoing("확인", 10, 0, status="unknown"),
            Outgoing("확인", 10, 0, status="submitted"),
        ]
    )
    state.merge("101", [msg("11", mine=True)])
    state.merge("101", [msg("11", mine=True)])
    assert [o.status for o in state.outgoing] == ["confirmed", "submitted"]
