import asyncio
import json

import pytest

from src.data.store import Bookkeeper


def _log_line_sync(bookkeeper: Bookkeeper, payload: dict) -> None:
    line = json.dumps(payload).encode("utf-8")
    asyncio.run(bookkeeper.log_line(line))


def test_observe_is_dispatched_and_written(tmp_path):
    # Regression test: log_line silently dropped 'observe' messages, and
    # _log_observe called a method (_serialize_dict) that didn't exist on
    # Bookkeeper, so this would have raised AttributeError the first time
    # anything actually published to the 'observe' topic.
    directory = str(tmp_path) + "/"
    bookkeeper = Bookkeeper(directory)

    _log_line_sync(
        bookkeeper,
        {
            "topic": "observe",
            "datetime": "2026-08-21T00:00:00",
            "message": "call outcome",
            "target": {"prospect": "acme", "call_id": "42"},
            "result": "meeting_booked",
        },
    )

    log_path = tmp_path / "logs" / "observe.txt"
    assert log_path.exists(), "observe topic was not dispatched to _log_observe"

    line = log_path.read_text().strip()
    server_dt, message, target_line, result = line.split("\t")
    assert server_dt == "2026-08-21T00:00:00"
    assert message == "call outcome"
    assert target_line == "acme;42"
    assert result == "meeting_booked"


def test_serialize_dict_handles_non_string_values(tmp_path):
    # _serialize_list previously joined values with no str() cast, which
    # crashes on anything but a dict of strings (e.g. a float uncertainty,
    # or an int call id) — exactly the shape Query/Solve targets carry.
    bookkeeper = Bookkeeper(str(tmp_path) + "/")
    assert bookkeeper._serialize_dict({"a": 1, "b": 0.5, "c": "x"}) == "1;0.5;x"


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
