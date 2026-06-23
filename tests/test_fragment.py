"""Fix-this-block-with-AI: restructure_fragment + helpers (no live AI; _gen_text is mocked)."""
import pytest

import diannot.structure as S
from diannot.models import (
    BodyBlock,
    CalloutBlock,
    DiagramBlock,
    ImageBlock,
    ListBlock,
    ListItem,
    QuoteBlock,
    ScriptHeadingBlock,
    SubheadingBlock,
    TableBlock,
    TermDefinitionBlock,
)

TABLE_JSON = '{"blocks":[{"type":"table","headers":["Op","Formula"],"rows":[["Add","$e^2$"]]}]}'


def _mock_gen(monkeypatch, *responses):
    """Make _gen_text yield the given responses in order (str -> model text, Exception -> raised),
    recording each call's prompt. No backoff sleeps."""
    calls: list[str] = []
    it = iter(responses)

    def fake(prompt, model, settings, provider, system):
        calls.append(prompt)
        r = next(it, responses[-1])
        if isinstance(r, Exception):
            raise r
        return r, []

    monkeypatch.setattr(S, "_gen_text", fake)
    monkeypatch.setattr(S.time, "sleep", lambda *_a, **_k: None)
    return calls


def test_fragment_returns_blocks_no_banner(monkeypatch):
    _mock_gen(monkeypatch, TABLE_JSON)
    blocks, diagnosis = S.restructure_fragment("several ops each with a formula", hint="make a table")
    assert len(blocks) == 1 and blocks[0].type == "table"
    assert all(b.type != "banner" for b in blocks)
    assert isinstance(diagnosis, str)


def test_fragment_drops_banner_and_coerces_layout(monkeypatch):
    _mock_gen(monkeypatch,
              '{"blocks":[{"type":"banner","text":"X"},{"type":"body","text":"hi","layout":"col1"}]}')
    blocks, _ = S.restructure_fragment("text")
    assert [b.type for b in blocks] == ["body"]   # banner stripped
    assert blocks[0].layout == "auto"             # col1 coerced


def test_fragment_bare_table_coerces_to_auto(monkeypatch):
    """A table with NO explicit layout must not keep TableBlock's default 'full' (which would break
    out of its column / span both columns). The headline 'Make a table' path."""
    _mock_gen(monkeypatch, '{"blocks":[{"type":"table","headers":["A"],"rows":[["1"]]}]}')
    blocks, _ = S.restructure_fragment("x", hint="make a table")
    assert blocks[0].type == "table" and blocks[0].layout == "auto"


def test_fragment_parses_diagnosis_and_reason_hint(monkeypatch):
    """The fix now CHECKS then fixes: it parses a 'diagnosis' and threads the local reason into the prompt."""
    calls = _mock_gen(monkeypatch,
                      '{"diagnosis":"raw-text wall that should be a list","blocks":[{"type":"body","text":"hi"}]}')
    blocks, diagnosis = S.restructure_fragment("x", reason="Long unstructured paragraph")
    assert blocks[0].type == "body" and diagnosis == "raw-text wall that should be a list"
    assert "Long unstructured paragraph" in calls[0]   # the heuristic reason is sent to the model


def test_fixable_block_types_excludes_banner_and_media():
    assert {"body", "table", "list", "term_definition", "callout", "quote"} <= S.FIXABLE_BLOCK_TYPES
    for t in ("banner", "script_heading", "image", "diagram"):
        assert t not in S.FIXABLE_BLOCK_TYPES   # never restructure a header / poster / media block


def test_fragment_recovers_on_second_attempt(monkeypatch):
    calls = _mock_gen(monkeypatch, "not json", TABLE_JSON)
    blocks, _ = S.restructure_fragment("text", max_retries=2)
    assert blocks[0].type == "table" and len(calls) == 2


def test_fragment_retries_then_fails(monkeypatch):
    calls = _mock_gen(monkeypatch, "bad", "bad", "bad")   # max_retries=2 -> 3 attempts
    with pytest.raises(RuntimeError):
        S.restructure_fragment("text", max_retries=2)
    assert len(calls) == 3


def test_fragment_claude_missing_propagates_without_retry(monkeypatch):
    calls = _mock_gen(monkeypatch, RuntimeError(S._CLAUDE_MISSING))
    with pytest.raises(RuntimeError, match="Claude Code CLI"):
        S.restructure_fragment("text")
    assert len(calls) == 1   # not transient -> no retry


def test_fragment_empty_text_raises():
    with pytest.raises(ValueError):
        S.restructure_fragment("   ")


def test_blocks_parser_rejects_bad_shapes():
    assert S._blocks_from_fragment_response("")[0] is None
    assert S._blocks_from_fragment_response("not json")[0] is None
    assert S._blocks_from_fragment_response('{"blocks":[]}')[0] is None        # empty after cleaning
    assert S._blocks_from_fragment_response('{"nope":1}')[0] is None           # no blocks array


def test_block_to_text_per_type():
    assert S._block_to_text(BodyBlock(text="hello **world**")) == "hello **world**"
    assert S._block_to_text(ScriptHeadingBlock(text="Heading")) == "Heading"
    assert S._block_to_text(SubheadingBlock(text="Sub")) == "Sub"
    assert S._block_to_text(QuoteBlock(text="q")) == "q"
    assert "Term" in S._block_to_text(TermDefinitionBlock(term="Term", definition="def"))
    lt = S._block_to_text(ListBlock(items=[ListItem(text="a", children=[ListItem(text="a1")]),
                                           ListItem(text="b")]))
    assert "- a" in lt and "  - a1" in lt and "- b" in lt   # nesting preserved
    tt = S._block_to_text(TableBlock(headers=["A", "B"], rows=[["1", "2"]], caption="Cap"))
    assert "Cap" in tt and "A | B" in tt and "1 | 2" in tt
    assert "tip" in S._block_to_text(CalloutBlock(variant="tutor_tip", title="tip", body="b", items=["i"]))
    assert "pic.png" in S._block_to_text(ImageBlock(src="pic.png", caption="a fig"))
    assert "A-->B" in S._block_to_text(DiagramBlock(mermaid="graph TD; A-->B", caption="d"))
