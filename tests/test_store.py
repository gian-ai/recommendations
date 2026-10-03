import asyncio
import json

import pytest

from src.communicate.stub import Query
from src.data.store import Bookkeeper


def _log_line_sync(bookkeeper: Bookkeeper, payload: dict) -> None:
    line = json.dumps(payload).encode("utf-8")
    asyncio.run(bookkeeper.log_line(line))


def test_observe_is_dispatched_and_written(tmp_path):
    # Regression test: log_line silently dropped 'observe' messages, and
    # _log_observe called a method (_serialize_dict) that didn't exist on
    # Bookkeeper, so this would have raised AttributeError the first time
    # anything actually published to the 'observe' topic.
    #
    # The payload below is the Send envelope the queue actually broadcasts:
    # the Observe arrives as JSON inside 'message', and only 'datetime'
    # belongs to the envelope. An earlier version of this test passed a flat
    # payload that never occurs on the wire, which is how _log_observe
    # reading target/result straight off the envelope went unnoticed — it
    # logged the whole JSON blob as the message and two empty columns.
    directory = str(tmp_path) + "/"
    bookkeeper = Bookkeeper(directory)

    observe = {
        "topic": "observe",
        "id": "turn_002",
        "source": "rep",
        "message": "call outcome",
        "target": {"prospect": "acme", "call_id": "42"},
        "result": "meeting_booked",
    }

    _log_line_sync(
        bookkeeper,
        {
            "topic": "observe",
            "datetime": "2026-08-21T00:00:00",
            "command": "send",
            "message": json.dumps(observe),
            "delivery": "one",
            "index": 0,
        },
    )

    log_path = tmp_path / "logs" / "observe.txt"
    assert log_path.exists(), "observe topic was not dispatched to _log_observe"

    line = log_path.read_text().strip()
    server_dt, observe_id, source, message, target_line, result = line.split("\t")
    assert server_dt == "2026-08-21T00:00:00"
    assert message == "call outcome"
    assert result == "meeting_booked"

    # The join key, in the same column position solve.txt puts it, so the two
    # logs line up without a lookup table.
    assert observe_id == "turn_002"
    # And who said so. Without it, the system agreeing with its own choice and
    # a human correcting it are the same four fields — opposite signals that
    # read identically, and anything learning from the log trains on its own
    # guesses.
    assert source == "rep"

    # Keyed, not positional. #9's ranking joins these logs on the target
    # fields; when they were dumped as "acme;42" nothing on the line said
    # which value was the prospect and which was the call.
    assert json.loads(target_line) == {"prospect": "acme", "call_id": "42"}


def test_serialize_dict_keeps_types_rather_than_stringifying_them(tmp_path):
    # The old encoding joined values into text, so a float uncertainty and
    # the string "0.5" were indistinguishable once logged. JSON keeps them
    # apart, which matters because these logs are read back and compared.
    bookkeeper = Bookkeeper(str(tmp_path) + "/")
    encoded = bookkeeper._serialize_dict({"a": 1, "b": 0.5, "c": "x"})

    assert json.loads(encoded) == {"a": 1, "b": 0.5, "c": "x"}


def test_a_separator_inside_the_text_cannot_break_the_line(tmp_path):
    """The failure the old format had and nobody had hit yet.

    Targets carry the prospect's actual words. A tab in a transcript would
    have desynced every column after it, and a semicolon would have split one
    value into two — silently, into a log that #9 is supposed to rank from.
    """
    bookkeeper = Bookkeeper(str(tmp_path) + "/")
    hostile = {"utterance": "it is expensive;\tand slow", "call_id": "42"}

    encoded = bookkeeper._serialize_dict(hostile)

    assert "\t" not in encoded, "a tab would desync the columns"
    assert "\n" not in encoded, "a newline would split the record"
    assert json.loads(encoded) == hostile


def test_query_and_solve_still_dispatch(tmp_path):
    # Not new behaviour, just guarding against a regression while touching
    # log_line's dispatch table.
    directory = str(tmp_path) + "/"
    bookkeeper = Bookkeeper(directory)

    _log_line_sync(
        bookkeeper,
        {
            "topic": "query",
            "datetime": "2026-08-21T00:00:00",
            "message": "id1\ttarget\tprice\tchoice_a;choice_b",
        },
    )
    assert (tmp_path / "logs" / "query.txt").exists()

    _log_line_sync(
        bookkeeper,
        {
            "topic": "solve",
            "message": json.dumps(
                {
                    "choice": "choice_a",
                    "uncertainty": 0.2,
                    "origin_string": "id1\ttarget\tprice\tchoice_a;choice_b",
                }
            ),
        },
    )
    assert (tmp_path / "logs" / "solve.txt").exists()


# ── the wire format for target ───────────────────────────────────────────────


def test_a_target_field_survives_the_round_trip_with_its_keys():
    """The change #49 was blocked on.

    `{"utterance": "that seems expensive", "company": "Acme Corp"}` used to
    encode as `that seems expensive;Acme Corp`, and the reader joined it back
    into one string — so the company name became objection vocabulary and BM25
    scored it. Nothing raised.
    """
    target = {"utterance": "that seems expensive", "company": "Acme Corp"}

    assert Query.deserialize_dict(Query.serialize_dict(target)) == target


def test_an_old_positional_line_still_decodes():
    """query.txt and solve.txt already hold thousands of these. A format
    change that made an existing log unreadable would cost the only real
    traffic anyone has."""
    decoded = Query.deserialize_dict("call_7;price;that seems expensive")

    assert decoded == {
        "call_id": "call_7",
        "objection": "price",
        "utterance": "that seems expensive",
    }


def test_an_empty_target_is_an_empty_dict_not_a_crash():
    assert Query.deserialize_dict("") == {}
    assert Query.deserialize_dict(None) == {}


def test_the_encoding_is_stable_for_the_same_target():
    """These strings are joined across query.txt, solve.txt and observe.txt,
    and replayed by #13's harness. Key order changing between runs would
    break the join silently."""
    target = {"z": "last", "a": "first", "m": "middle"}

    assert Query.serialize_dict(target) == Query.serialize_dict(dict(reversed(target.items())))


def test_an_observation_without_an_id_still_writes(tmp_path):
    """Both new fields default, so an emitter with no decision in hand — or
    one written before they existed — logs rather than raising. The columns
    come out empty, which is the honest answer: nothing to join on."""
    directory = str(tmp_path) + "/"
    bookkeeper = Bookkeeper(directory)

    _log_line_sync(
        bookkeeper,
        {
            "topic": "observe",
            "datetime": "2026-08-21T00:00:00",
            "command": "send",
            "message": json.dumps({
                "topic": "observe",
                "message": "clip_004",
                "target": {"utterance": "that is expensive"},
                "result": "clip_004",
            }),
            "delivery": "one",
            "index": 0,
        },
    )

    line = (tmp_path / "logs" / "observe.txt").read_text().strip()
    server_dt, observe_id, source, message, target_line, result = line.split("\t")

    assert observe_id == ""
    assert source == ""
    assert result == "clip_004"
