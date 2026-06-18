"""Turn raw study text into a validated :class:`~diannot.models.Note` using Claude.

This is the "structure" step: it detects headings, term/definition pairs, lists
and comparison tables, and bolds testable terms — emitting JSON that conforms to
the Diannot block schema. The model output is parsed and validated with Pydantic,
and the call is retried (with the validation error fed back) on malformed output.

Authentication is handled entirely by the Claude Agent SDK / bundled CLI:
- a logged-in Claude Code subscription session, or
- an ``ANTHROPIC_API_KEY`` environment variable.
Diannot never reads, stores, or hardcodes credentials.
"""
from __future__ import annotations

import asyncio
import json
import re

from pydantic import ValidationError

from .config import Settings
from .models import Note

SYSTEM_PROMPT = """\
You are a study-notes structuring engine. You convert raw, often messy text \
(extracted from lecture handouts or PDFs) into a STRUCTURED JSON document of \
typed "blocks" for a beautifully styled study-notes app. You restructure and \
lightly clean the material — you do NOT summarize it away or invent facts.

OUTPUT CONTRACT (critical):
- Respond with a SINGLE JSON object and nothing else. No prose, no explanation,
  no markdown code fences.
- Shape: {"title": "<chapter title>", "blocks": [ <block>, ... ]}

BLOCK TYPES (each block is an object with a "type" field):
- {"type":"banner","text":"<chapter title>","subtitle":"<optional>"}
    The poster header. Emit exactly ONE, as the first block.
- {"type":"script_heading","text":"<major section title>"}
    For major sections (e.g. "The Circulatory System", "Blood Vessels").
- {"type":"subheading","text":"<sub-section>","caps":false}
    For smaller sub-sections or grouped key-term headers. Use caps:true for
    short all-caps labels.
- {"type":"body","text":"<paragraph>"}
    A paragraph. Bold testable/key phrases with **double asterisks**.
- {"type":"term_definition","term":"<Term>","definition":"<short definition>"}
    For "Term — definition" pairs (a bolded term followed by its meaning).
    Bold key words inside the definition with **double asterisks**.
- {"type":"list","ordered":false,"items":[{"text":"...","children":[...]}]}
    Bulleted/numbered lists; nest with "children". Bold key words with **...**.
- {"type":"table","headers":["..."],"rows":[["...","..."]],"caption":"<optional>"}
    Use for comparison-heavy content (e.g. comparing arteries/veins/capillaries).
    Bold key cell terms with **...**.
- {"type":"callout","variant":"key_points|tutor_tip|warning","title":"<optional>",
   "body":"<optional>","items":["<optional>", ...]}
    key_points = a boxed summary of testable points; tutor_tip = a tip/mnemonic;
    warning = a caution. Provide "body" and/or "items".
- {"type":"quote","text":"...","attribution":"<optional>"}
- {"type":"image","src":"...","caption":"...","source_credit":"..."}
    Only if the source clearly references a specific image file you were given.
    Do NOT fabricate image paths.

RULES:
1. Begin with one banner block for the chapter title. The raw text may repeat or
   garble the title (duplicated layout layers, OCR typos); DEDUPE it and fix only
   obvious typos in the TITLE (e.g. "Lymphathic"->"Lymphatic", "Systens"->"Systems").
2. Preserve the educational content faithfully. Do not drop facts, do not add
   facts, do not paraphrase into something shorter. Reorganize messy/interleaved
   two-column extraction back into logical reading order.
3. Convert obvious "Term — definition" lines into term_definition blocks.
4. Convert comparison-style content into a table block.
5. Convert bulleted/numbered runs into list blocks (preserve nesting).
6. Bold the testable terms and key phrases (anatomical names, key processes,
   numeric facts) with **double asterisks** in body, definitions, list items and
   table cells.
7. Do not set theme/pack/layout — the app controls those.
8. Output valid JSON only. Escape characters properly. No trailing commas.
"""


def _build_user_prompt(raw_text: str, title: str | None) -> str:
    title_hint = (
        f'The chapter title is "{title}". Use it for the banner.\n\n'
        if title
        else "Infer the chapter title from the text for the banner.\n\n"
    )
    return (
        title_hint
        + "Structure the following raw study text into the JSON document described "
        "in your instructions. Output JSON only.\n\n"
        "<<<RAW TEXT>>>\n"
        f"{raw_text}\n"
        "<<<END RAW TEXT>>>"
    )


def _extract_json(text: str) -> dict | None:
    """Pull a JSON object out of a model response (handles code fences/prose)."""
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL)
    if fence:
        t = fence.group(1).strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(t[start : end + 1])
    except json.JSONDecodeError:
        return None


async def _run_query(prompt: str, system: str, model: str) -> tuple[str, list[str]]:
    """Run a single-turn, tool-free query and return (text, stderr_lines)."""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        query,
    )

    stderr_lines: list[str] = []
    options = ClaudeAgentOptions(
        model=model,
        system_prompt=system,
        allowed_tools=[],
        max_turns=1,
        setting_sources=[],  # ignore project/user/local settings for a clean call
        permission_mode="bypassPermissions",
        # Clear the nested-session flag so the bundled CLI doesn't refuse to run
        # when Diannot is invoked from within a Claude Code session.
        env={"CLAUDECODE": ""},
        stderr=stderr_lines.append,
    )

    chunks: list[str] = []
    result_text: str | None = None
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in getattr(message, "content", None) or []:
                if isinstance(block, TextBlock):
                    chunks.append(block.text)
        elif isinstance(message, ResultMessage):
            result_text = getattr(message, "result", None)

    text = "".join(chunks).strip()
    if not text and result_text:
        text = result_text.strip()
    return text, stderr_lines


def structure_text(
    raw_text: str,
    title: str | None = None,
    theme: str = "circulatory",
    pack: str = "study_notes",
    model: str | None = None,
    settings: Settings | None = None,
    max_retries: int = 2,
) -> Note:
    """Structure ``raw_text`` into a validated :class:`Note`.

    Retries up to ``max_retries`` times, feeding the validation error back to the
    model. Raises :class:`RuntimeError` if no valid Note is produced.
    """
    if not raw_text.strip():
        raise ValueError("Cannot structure empty text.")

    settings = settings or Settings()
    model = model or settings.models.structure
    user_prompt = _build_user_prompt(raw_text, title)

    last_error = "unknown error"
    last_stderr: list[str] = []
    for attempt in range(max_retries + 1):
        prompt = user_prompt
        if attempt:
            prompt += (
                f"\n\nYour previous response was invalid ({last_error}). "
                "Return ONLY a corrected single JSON object."
            )
        text, last_stderr = asyncio.run(_run_query(prompt, SYSTEM_PROMPT, model))

        if not text:
            last_error = "empty response from model"
            continue
        data = _extract_json(text)
        if not isinstance(data, dict):
            last_error = "response was not a single JSON object"
            continue

        # The app controls these; never let the model override them.
        data.pop("theme", None)
        data.pop("pack", None)
        if title:
            data["title"] = title
        data["theme"] = theme
        data["pack"] = pack
        try:
            return Note.model_validate(data)
        except ValidationError as exc:
            last_error = str(exc)[:1500]

    hint = ""
    if last_stderr:
        tail = " | ".join(s.strip() for s in last_stderr[-4:] if s.strip())
        if tail:
            hint = f"\nLast CLI stderr: {tail}"
    raise RuntimeError(
        f"Structuring failed after {max_retries + 1} attempt(s). "
        f"Last error: {last_error}{hint}\n"
        "If this is an auth problem, ensure the Claude Code CLI is logged in or "
        "set ANTHROPIC_API_KEY."
    )
