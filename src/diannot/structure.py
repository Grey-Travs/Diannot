"""Turn raw study text *or* page images into a validated Note using Claude.

Two entry points share one block schema and validation path:
- :func:`structure_text`  — messy extracted text -> blocks.
- :func:`structure_image` — page image(s) -> blocks, vision-native (the model sees
  the page, so layout/tables/colour survive far better than OCR -> text -> structure).

Model output is parsed and validated with Pydantic, and the call is retried (with
the validation error fed back) on malformed output.

Authentication is handled entirely by the Claude Agent SDK / bundled CLI (a logged-in
Claude Code subscription session, or an ``ANTHROPIC_API_KEY``). Diannot never reads,
stores, or hardcodes credentials.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import sys

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)
from pydantic import ValidationError

from . import providers as _providers
from .config import Settings
from .models import Note

try:
    from claude_agent_sdk import CLINotFoundError as _CLINotFound
except Exception:  # SDK build without this exception class
    _CLINotFound = None

_CLAUDE_MISSING = (
    "This build doesn't include the Claude engine. In Settings, pick Gemini (free) "
    "or a local Ollama model."
)


def claude_engine_available() -> bool:
    """Whether the Claude engine can actually run here. The packaged build strips the bundled
    Claude CLI (see diannot_studio.spec), so it's only usable when running from source (not frozen).
    Used to hide the Claude option in the Settings engine picker for the installed app."""
    return not getattr(sys, "frozen", False)

SYSTEM_PROMPT = """\
You are a study-notes structuring engine. You convert source study material — messy \
extracted text OR images of textbook/lecture pages — into a STRUCTURED JSON document of \
typed "blocks" for a beautifully styled study-notes app. You restructure and lightly \
clean the material — you do NOT summarize it away or invent facts.

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
1. Begin with one banner block for the chapter title. The source may repeat or garble
   the title (duplicated layout layers, OCR typos); DEDUPE it and fix only obvious typos
   in the TITLE (e.g. "Lymphathic"->"Lymphatic", "Systens"->"Systems").
2. Be CONCISE — write compact, scannable study notes, not prose. Tighten wording, cut filler
   and redundancy, and prefer short phrases over full sentences. But keep EVERY key term, fact,
   number and formula — never invent or omit facts. Reorganize messy/interleaved two-column
   material back into logical reading order.
3. Convert obvious "Term — definition" lines into term_definition blocks.
4. Convert comparison-style content into a table block.
5. Convert bulleted/numbered runs into list blocks (preserve nesting).
6. Bold the testable terms and key phrases (anatomical names, key processes, numeric
   facts) with **double asterisks** in body, definitions, list items and table cells.
7. MATH, STATISTICS & CHEMISTRY: reproduce every mathematical or chemical expression you
   read as LaTeX, so it renders as real symbols (never as broken text or lookalike letters,
   and never dropped). Wrap inline math in single dollar signs and standalone equations in
   double dollar signs. Examples (statistics/math): $\\bar{x}$, $\\sigma^2$, $\\frac{a}{b}$,
   $\\sum_{i=1}^{n} x_i$, $p < 0.05$, $\\chi^2$, $\\mu \\pm \\sigma$, $\\leq$, $\\rightarrow$,
   $x^{2}$, $H_2O$ (subscripts with _ , superscripts with ^). Write CHEMICAL formulas and
   equations with the mhchem command \\ce{...}: $\\ce{H2SO4}$, $\\ce{CO2}$,
   $\\ce{2H2 + O2 -> 2H2O}$, $\\ce{CaCO3 ->[\\Delta] CaO + CO2}$. Use this inside body,
   definitions, list items, table cells and callouts — wherever a formula appears. For a literal
   PERCENT SIGN inside math write \\% (e.g. percent error $\\%e = \\sqrt{(\\%e_1)^2+(\\%e_2)^2}$);
   a bare % is a LaTeX comment and silently hides the rest of the line.
8. LAYOUT — FOLD THE PAGE INTO TWO COLUMNS OF WHOLE TOPICS. Organize the note as a SMALL number of
   topic-cards (usually 2–4), laid out like folding the page in half: each whole topic in ONE column,
   the LEFT column one topic and the RIGHT column another.
   a. Make ONE "list" block per topic — that topic's CARD. Put ALL of the topic's concepts as the
      list's ITEMS, e.g. an item "**Mean** ($\\bar{x}$) — the arithmetic average … Formula: $…$";
      use a concept's "children" for its own sub-points. Do NOT emit a separate term_definition or body
      block per concept in this layout — the concepts are ITEMS inside the topic's ONE card. (Within
      this two-column layout this overrides rule 3.)
   b. If the topic has a section name, emit it as a "script_heading" placed directly before that topic's
      card.
   c. KEEP EACH WHOLE TOPIC IN ONE COLUMN: set the topic's "script_heading" AND its card to the SAME
      "layout" — "col1" (left) for one topic, "col2" (right) for the next (balance more topics across the
      two columns). NEVER put a topic's heading in one column and its card in the other, and NEVER leave
      a topic's heading or card "full"/"auto" in this two-column layout.
   Use "full" only for the banner or a genuinely wide table; use "auto" only for a single-topic note.
   Default every multi-topic note to this folded two-column layout. Image blocks may also set "width"
   (10–100, percent of the column). Do NOT set theme or pack — the app controls those.
9. If you are given page IMAGES: transcribe ALL visible text faithfully and in logical
   reading order (reconstruct across columns), INCLUDING any formulas, equations, statistical
   notation or chemical reactions — transcribe those as LaTeX per rule 7. For photographs,
   diagrams or micrographs you cannot transcribe, capture them briefly as a body note or an
   image caption that describes them — never invent labels, numbers, or text you cannot clearly read.
10. CONFIDENCE: any block may include "confidence": "low" or "medium" when its text is
    uncertain (illegible/blurry source, ambiguous wording, a number you are unsure of, or
    content you had to reconstruct). Omit "confidence" for clearly-read content. Never
    guess silently — flag it instead.
11. SOURCE PAGE: when page numbers are provided to you, set each block's "source_page"
    to the page number it came from.
12. Output valid JSON only. Escape characters properly: a backslash in LaTeX must be doubled
    in JSON, so e.g. the body text $\\sigma^2$ is written "$\\\\sigma^2$" in the JSON string.
    No trailing commas.
"""


def _build_user_prompt(raw_text: str, title: str | None) -> str:
    title_hint = (
        f'The chapter title is "{title}". Use it for the banner.\n\n'
        if title
        else "Infer the chapter title from the text for the banner.\n\n"
    )
    return (
        title_hint
        + "Structure the following raw study text into the JSON document described in "
        "your instructions. Output JSON only.\n\n"
        "<<<RAW TEXT>>>\n"
        f"{raw_text}\n"
        "<<<END RAW TEXT>>>"
    )


def _build_vision_prompt(title: str | None, n_images: int, pages_label: str | None = None) -> str:
    title_hint = (
        f'The chapter title is "{title}". Use it for the banner.\n'
        if title
        else "Infer the chapter title from the page(s) for the banner.\n"
    )
    page_line = f"These image(s) are page(s) {pages_label} (in order). " if pages_label else ""
    return (
        title_hint
        + f"You are given {n_images} page image(s) of study material. {page_line}"
        "Transcribe and structure ALL of their content into the JSON document described "
        "in your instructions, in logical reading order. Output JSON only."
    )


def _extract_json(text: str) -> object | None:
    """Pull a JSON value out of a model response (handles code fences/prose)."""
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


def _note_from_response(
    text: str, title: str | None, theme: str, pack: str
) -> tuple[Note | None, str]:
    """Parse + validate a model response into a Note, or return (None, error)."""
    if not text:
        return None, "empty response from model"
    data = _extract_json(text)
    if not isinstance(data, dict):
        return None, "response was not a single JSON object"
    # The app controls these; never let the model override them.
    data.pop("theme", None)
    data.pop("pack", None)
    if title:
        data["title"] = title
    data["theme"] = theme
    data["pack"] = pack
    try:
        return Note.model_validate(data), ""
    except ValidationError as exc:
        return None, str(exc)[:1500]


def _options(model: str, system: str, stderr_sink) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=model,
        system_prompt=system,
        allowed_tools=[],
        max_turns=1,
        setting_sources=[],  # ignore project/user/local settings for a clean call
        permission_mode="bypassPermissions",
        # Clear the nested-session flag so the bundled CLI runs from inside a
        # Claude Code session.
        env={"CLAUDECODE": ""},
        stderr=stderr_sink,
    )


async def _collect(messages) -> str:
    """Concatenate assistant text from a query() message stream."""
    chunks: list[str] = []
    result_text: str | None = None
    async for message in messages:
        if isinstance(message, AssistantMessage):
            for block in getattr(message, "content", None) or []:
                if isinstance(block, TextBlock):
                    chunks.append(block.text)
        elif isinstance(message, ResultMessage):
            result_text = getattr(message, "result", None)
    text = "".join(chunks).strip()
    if not text and result_text:
        text = result_text.strip()
    return text


async def _run_text(prompt: str, model: str, system: str = SYSTEM_PROMPT) -> tuple[str, list[str]]:
    stderr: list[str] = []
    text = await _collect(query(prompt=prompt, options=_options(model, system, stderr.append)))
    return text, stderr


async def _run_multimodal(
    content: list[dict], model: str, system: str = SYSTEM_PROMPT
) -> tuple[str, list[str]]:
    stderr: list[str] = []

    async def _stream():
        yield {"type": "user", "message": {"role": "user", "content": content}}

    text = await _collect(query(prompt=_stream(), options=_options(model, system, stderr.append)))
    return text, stderr


def _gen_text(prompt: str, model: str, settings: Settings, provider: str, system: str) -> tuple[str, list[str]]:
    """Run a text completion through the chosen backend. Returns (text, stderr lines)."""
    if provider == "ollama":
        cfg = settings.providers
        return _providers.ollama_complete(system, prompt, cfg.ollama_model, cfg.ollama_host), []
    if provider == "gemini":
        cfg = settings.providers
        return _providers.gemini_complete(system, prompt, cfg.gemini_model, os.environ.get("GEMINI_API_KEY", "")), []
    try:
        return asyncio.run(_run_text(prompt, model, system=system))
    except Exception as exc:
        if _CLINotFound is not None and isinstance(exc, _CLINotFound):
            raise RuntimeError(_CLAUDE_MISSING) from None
        raise


def _gen_vision(
    content: list[dict], prompt_text: str, images: list[bytes], model: str, settings: Settings, provider: str
) -> tuple[str, list[str]]:
    """Run a vision completion through the chosen backend. Returns (text, stderr lines)."""
    if provider in ("ollama", "gemini"):
        cfg = settings.providers
        b64 = [base64.b64encode(img).decode("ascii") for img in images]
        if provider == "ollama":
            text = _providers.ollama_complete(
                SYSTEM_PROMPT, prompt_text, cfg.ollama_vision_model, cfg.ollama_host, images=b64
            )
        else:
            text = _providers.gemini_complete(
                SYSTEM_PROMPT, prompt_text, cfg.gemini_model, os.environ.get("GEMINI_API_KEY", ""),
                images=b64, timeout=300,  # vision generations run longer than the text default
            )
        return text, []
    try:
        return asyncio.run(_run_multimodal(content, model))
    except Exception as exc:
        if _CLINotFound is not None and isinstance(exc, _CLINotFound):
            raise RuntimeError(_CLAUDE_MISSING) from None
        raise


def complete_json(
    system: str,
    prompt: str,
    model: str | None = None,
    settings: Settings | None = None,
    max_retries: int = 2,
) -> dict:
    """Generic structured call: return the parsed JSON object from the model.

    Used by flashcard/quiz generation. Retries on non-JSON output.
    """
    settings = settings or Settings()
    model = model or settings.models.structure
    last_error = "unknown error"
    for attempt in range(max_retries + 1):
        attempt_prompt = prompt
        if attempt:
            attempt_prompt += (
                f"\n\nYour previous response was invalid ({last_error}). "
                "Return ONLY a single valid JSON object."
            )
        text, _ = _gen_text(attempt_prompt, model, settings, settings.providers.study, system)
        if not text:
            last_error = "empty response"
            continue
        data = _extract_json(text)
        if not isinstance(data, dict):
            last_error = "response was not a JSON object"
            continue
        return data
    raise RuntimeError(f"JSON completion failed after {max_retries + 1} attempt(s): {last_error}")


def _failure(max_retries: int, last_error: str, last_stderr: list[str], provider: str = "claude") -> RuntimeError:
    hint = ""
    if last_stderr:
        tail = " | ".join(s.strip() for s in last_stderr[-4:] if s.strip())
        if tail:
            hint = f"\nLast CLI stderr: {tail}"
    advice = {
        "gemini": "Check your internet connection and the Gemini key in Settings.",
        "ollama": "Make sure Ollama is running and the model is pulled (Settings → AI engine).",
    }.get(provider, "If this is an auth problem, ensure the Claude Code CLI is logged in or set ANTHROPIC_API_KEY.")
    return RuntimeError(
        f"Structuring failed after {max_retries + 1} attempt(s). Last error: {last_error}{hint}\n{advice}"
    )


# Big documents are split into small chunks so each AI call stays well under the timeout and the
# output token cap — one giant call times out (esp. on slow wifi) and can truncate.
_CHUNK_TARGET = 6500   # aim for ~this many characters per chunk
_CHUNK_THRESHOLD = 10000  # only split inputs larger than this


def _split_for_structuring(text: str, target: int = _CHUNK_TARGET) -> list[str]:
    """Split a large document into chunks at blank-line (paragraph) boundaries, packing paragraphs up
    to ``target`` chars. Small inputs return a single chunk unchanged."""
    if len(text) <= _CHUNK_THRESHOLD:
        return [text]
    chunks: list[str] = []
    cur = ""
    for para in re.split(r"\n\s*\n", text):
        if cur and len(cur) + len(para) + 2 > target:
            chunks.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur.strip():
        chunks.append(cur)
    # Hard-split any single paragraph that's still much larger than the target.
    out: list[str] = []
    for chunk in chunks:
        if len(chunk) > target * 1.8:
            out.extend(chunk[i:i + target] for i in range(0, len(chunk), target))
        else:
            out.append(chunk)
    return [c for c in out if c.strip()] or [text]


def _structure_one(
    raw_text: str, title: str | None, theme: str, pack: str, model: str,
    settings: Settings, max_retries: int,
) -> Note:
    """Structure ONE chunk of text into a Note. Retries on invalid output AND on transient
    provider errors (e.g. a timeout on slow wifi), within the retry budget."""
    base_prompt = _build_user_prompt(raw_text, title)
    last_error, last_stderr = "unknown error", []
    for attempt in range(max_retries + 1):
        prompt = base_prompt
        if attempt:
            prompt += (
                f"\n\nYour previous response was invalid ({last_error}). "
                "Return ONLY a corrected single JSON object."
            )
        try:
            text, last_stderr = _gen_text(prompt, model, settings, settings.providers.notes, SYSTEM_PROMPT)
        except RuntimeError as exc:
            if str(exc) == _CLAUDE_MISSING:
                raise  # not transient — fail fast with the clear message
            last_error, text = str(exc), ""  # transient (timeout/network) — retry
        if text:
            note, last_error = _note_from_response(text, title, theme, pack)
            if note is not None:
                return note
    raise _failure(max_retries, last_error, last_stderr, settings.providers.notes)


def structure_text(
    raw_text: str,
    title: str | None = None,
    theme: str = "circulatory",
    pack: str = "study_notes",
    model: str | None = None,
    settings: Settings | None = None,
    max_retries: int = 2,
    on_progress=None,
) -> Note:
    """Structure ``raw_text`` into a validated :class:`Note`. A large document is split into several
    small AI calls (so it can't time out / truncate) and the resulting blocks are merged into one
    note. ``on_progress(done, total)`` is called per chunk for UI progress."""
    if not raw_text.strip():
        raise ValueError("Cannot structure empty text.")
    settings = settings or Settings()
    model = model or settings.models.structure
    chunks = _split_for_structuring(raw_text)

    merged: Note | None = None
    for i, chunk in enumerate(chunks):
        if on_progress:
            on_progress(i + 1, len(chunks))
        note = _structure_one(chunk, title if i == 0 else None, theme, pack, model, settings, max_retries)
        if merged is None:
            merged = note
        else:
            extra = note.blocks
            if extra and extra[0].type == "banner":  # only the first chunk keeps the chapter banner
                extra = extra[1:]
            merged.blocks.extend(extra)
    return merged  # chunks is never empty, so merged is set


def structure_image(
    images: list[bytes],
    title: str | None = None,
    theme: str = "circulatory",
    pack: str = "study_notes",
    model: str | None = None,
    settings: Settings | None = None,
    max_retries: int = 2,
    source_pages: list[int] | None = None,
) -> Note:
    """Structure page image(s) (PNG bytes) into a validated :class:`Note` via vision.

    ``source_pages`` are the 1-based page numbers of ``images`` (in order). When a single
    page is given, every block is attributed to it; for multiple pages the model attributes
    each block via its ``source_page`` field.
    """
    if not images:
        raise ValueError("No images to structure.")
    settings = settings or Settings()
    model = model or settings.models.structure
    pages_label = ", ".join(str(p) for p in source_pages) if source_pages else None

    base_prompt_text = _build_vision_prompt(title, len(images), pages_label)
    base_content: list[dict] = [{"type": "text", "text": base_prompt_text}]
    for img in images:
        base_content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.b64encode(img).decode("ascii"),
                },
            }
        )

    provider = settings.providers.notes
    last_error, last_stderr = "unknown error", []
    for attempt in range(max_retries + 1):
        content, prompt_text = base_content, base_prompt_text
        if attempt:
            retry = (
                f"Your previous response was invalid ({last_error}). "
                "Return ONLY a corrected single JSON object."
            )
            content = base_content + [{"type": "text", "text": retry}]
            prompt_text = f"{base_prompt_text}\n\n{retry}"
        text, last_stderr = _gen_vision(content, prompt_text, images, model, settings, provider)
        note, last_error = _note_from_response(text, title, theme, pack)
        if note is not None:
            if source_pages and len(source_pages) == 1:
                for block in note.blocks:
                    block.source_page = source_pages[0]
            return note
    raise _failure(max_retries, last_error, last_stderr, provider)
