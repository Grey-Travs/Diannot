"""Structure helpers (pure; no model calls)."""
from diannot.structure import _extract_json, _note_from_response


def test_extract_json_variants():
    assert _extract_json('{"a": 1}') == {"a": 1}
    assert _extract_json('```json\n{"a": 2}\n```') == {"a": 2}
    assert _extract_json('prefix {"a": 3} suffix') == {"a": 3}
    assert _extract_json("[1, 2, 3]") is None  # bare array -> no object found


def test_note_from_response_valid_overrides_meta():
    text = '{"title": "T", "theme": "x", "blocks": [{"type": "body", "text": "hi"}]}'
    note, err = _note_from_response(text, "Override", "circulatory", "study_notes")
    assert err == "" and note is not None
    assert note.title == "Override"  # caller title wins
    assert note.theme == "circulatory"  # app controls theme, not the model


def test_note_from_response_invalid():
    note, err = _note_from_response("not json", None, "circulatory", "study_notes")
    assert note is None and err

    note2, err2 = _note_from_response("[1, 2]", None, "circulatory", "study_notes")
    assert note2 is None and err2
