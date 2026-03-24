"""Tests for json_repair module."""

import json

import pytest

from tidyup.json_repair import repair_json


def test_valid_json_passes_through():
    data = {"files": [{"file": "a.pdf", "folder": "Work", "reason": "report"}]}
    result = repair_json(json.dumps(data))
    assert result == data


def test_valid_json_array():
    data = [1, 2, 3]
    result = repair_json(json.dumps(data))
    assert result == data


def test_trailing_comma_in_array():
    text = '{"files": [1, 2, 3,]}'
    result = repair_json(text)
    assert result == {"files": [1, 2, 3]}


def test_trailing_comma_in_object():
    text = '{"a": 1, "b": 2,}'
    result = repair_json(text)
    assert result == {"a": 1, "b": 2}


def test_missing_comma_between_objects():
    text = '[{"a": 1}{"b": 2}]'
    result = repair_json(text)
    assert result == [{"a": 1}, {"b": 2}]


def test_missing_comma_between_arrays():
    text = "[[1, 2][3, 4]]"
    result = repair_json(text)
    assert result == [[1, 2], [3, 4]]


def test_unclosed_bracket():
    text = '{"files": [{"file": "a.pdf", "folder": "Work", "reason": "ok"}'
    result = repair_json(text)
    assert result["files"][0]["file"] == "a.pdf"


def test_unclosed_brace():
    text = '{"files": [{"file": "a.pdf", "folder": "Work", "reason": "ok"}]'
    result = repair_json(text)
    assert result["files"][0]["folder"] == "Work"


def test_leading_trailing_non_json_text():
    text = 'Here is the JSON:\n{"a": 1}\nDone!'
    result = repair_json(text)
    assert result == {"a": 1}


def test_leading_text_with_array():
    text = "Sure, here you go: [1, 2, 3] hope that helps"
    result = repair_json(text)
    assert result == [1, 2, 3]


def test_strings_containing_braces_not_confused():
    text = '{"msg": "use {braces} and [brackets]", "x": 1}'
    result = repair_json(text)
    assert result == {"msg": "use {braces} and [brackets]", "x": 1}


def test_escaped_quotes_in_strings():
    text = r'{"path": "C:\\Users\\test", "val": "say \"hello\""}'
    result = repair_json(text)
    assert result["path"] == "C:\\Users\\test"


def test_irreparable_input_raises_json_error():
    with pytest.raises(json.JSONDecodeError):
        repair_json("this is not json at all")


def test_empty_string_raises_json_error():
    with pytest.raises(json.JSONDecodeError):
        repair_json("")


def test_realistic_missing_comma_in_large_response():
    """Simulate the reported bug: missing comma between two file entries in a large response."""
    entries = []
    for i in range(100):
        entries.append(
            f'{{"file": "file{i:03d}.pdf", "folder": "Work/Reports", "reason": "report {i}"}}'
        )
    # Drop the comma between entry 50 and 51 (simulating LLM output error)
    text = '{"files": [' + ", ".join(entries[:50])
    text += "  " + entries[50]  # missing comma here
    text += ", ".join(["", *entries[51:]]) + "]}"
    result = repair_json(text)
    assert "files" in result
    assert len(result["files"]) == 100


def test_multiple_issues_combined():
    """Trailing comma + surrounding text."""
    text = 'Response:\n{"items": [1, 2, 3,]}\n'
    result = repair_json(text)
    assert result == {"items": [1, 2, 3]}
