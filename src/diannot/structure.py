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
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)
from pydantic import TypeAdapter, ValidationError

from . import providers as _providers
from .config import Settings
from .models import BannerBlock, Block, BodyBlock, Note

try:
    from claude_agent_sdk import CLINotFoundError as _CLINotFound
except Exception:  # SDK build without this exception class
    _CLINotFound = None

_CLAUDE_MISSING = (
    "Claude needs the Claude Code CLI. Install it once: npm i -g @anthropic-ai/claude-code "
    "(needs Node.js, then restart Diannot) — it uses your own Claude login, no API cost. "
    "Or pick Gemini (free) in Settings."
)


@lru_cache(maxsize=1)
def _find_claude_cli() -> str | None:
    """Locate a system-installed Claude Code CLI so the Agent SDK can use it via ``cli_path`` (the
    packaged build ships without the bundled CLI). A logged-in CLI uses the user's Claude subscription
    (e.g. Max) — no per-token API cost. Cached."""
    for name in ("claude", "claude.cmd", "claude.exe"):
        found = shutil.which(name)
        if found:
            return found
    for base in (os.environ.get("APPDATA", ""), os.environ.get("LOCALAPPDATA", "")):
        for name in ("claude.cmd", "claude.exe"):
            cand = os.path.join(base, "npm", name) if base else ""
            if cand and os.path.isfile(cand):
                return cand
    return None


def claude_engine_available() -> bool:
    """Claude works here if NOT a packaged build (the SDK's bundled CLI is present), OR a
    system-installed Claude Code CLI is found (we point the SDK at it via ``cli_path``). So a user
    with Claude Code installed can use Claude even in the installed app."""
    return (not getattr(sys, "frozen", False)) or _find_claude_cli() is not None

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
2. Be CONCISE and STRUCTURED — compact, scannable study notes, NEVER prose. CRITICAL: do NOT dump the
   source as a long paragraph or a WALL of raw text. A "body" block is at most 1–2 short sentences; if
   there is more to say, break it into a list, a table, term_definition blocks, or a script_heading +
   list card — never one big body block. Copying a run of source text verbatim into a body block is
   WRONG: structure it. Tighten wording, cut filler and redundancy, and prefer short phrases over full
   sentences. But keep EVERY key term, fact, number and formula — never invent or omit facts. Reorganize
   messy/interleaved two-column material back into logical reading order.
3. Convert obvious "Term — definition" lines into term_definition blocks.
4. TABLES — use a "table" block whenever the source is tabular: a real grid/table, OR a SET OF ITEMS
   that each share the SAME fields (e.g. several error-propagation operations each with a Formula and a
   "when to use"; several concentration units each with a Formula and a description; arteries vs veins
   vs capillaries). Make the shared fields the column "headers" and one item per row — do NOT flatten
   such repeated-attribute content into nested lists or term_definition blocks. Keep formulas in cells
   as LaTeX (rule 7). Example: headers ["Operation","Formula","When to use"], one row per operation.
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
      EXCEPTION (rule 4 wins): if a topic's content is genuinely TABULAR — rows of items that share the
      same fields — emit a "table" block for that topic instead of a list card. Place a narrow table in
      a column ("col1"/"col2") like any other card; set a wide multi-column table (and its heading) to
      "full". Tables are preferred over lists for such content — never flatten a table into list items.
   b. If the topic has a section name, emit it as a "script_heading" placed directly before that topic's
      card.
   c. KEEP EACH WHOLE TOPIC IN ONE COLUMN: set the topic's "script_heading" AND its card to the SAME
      "layout" — "col1" (left) for one topic, "col2" (right) for the next (balance more topics across the
      two columns). NEVER put a topic's heading in one column and its card in the other, and NEVER leave
      a topic's heading or card "full"/"auto" in this two-column layout — EXCEPT a genuinely wide table
      topic (rule 4 exception), whose heading AND table may both be "full".
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

# Used by "Fix this block with AI": re-structure ONE block of an EXISTING note. Unlike SYSTEM_PROMPT
# it must NOT emit a banner or force the col1/col2 layout — it returns only corrected content blocks.
FRAGMENT_SYSTEM_PROMPT = """\
You are a study-notes structuring engine FIXING ONE block of an existing note. You are given the raw
text of a single block that came out wrong (a plain-text wall, or content that should be a table/list
but isn't) plus an instruction for how to fix it. Re-express ONLY that text as one or more correctly
typed "blocks". Do NOT add a title, banner, whole-note heading or summary, and do NOT invent facts —
only restructure what is given.

OUTPUT CONTRACT (critical):
- Respond with a SINGLE JSON object and nothing else. No prose, no code fences.
- First CHECK the given text and state a one-sentence "diagnosis" of what is structurally wrong (e.g.
  "raw-text wall that should be 3 list items"); if it is already well-formed, say "Looks fine — minor tidy".
- Shape: {"diagnosis":"<one sentence>", "blocks": [ <block>, ... ]}   (NO "title" field, and NO "banner" block.)

BLOCK TYPES (object with a "type" field):
- {"type":"script_heading","text":"<section title>"}
- {"type":"subheading","text":"<sub-section>","caps":false}
- {"type":"body","text":"<paragraph>"}   Bold testable phrases with **double asterisks**.
- {"type":"term_definition","term":"<Term>","definition":"<short definition>"}
- {"type":"list","ordered":false,"items":[{"text":"...","children":[...]}]}   Nestable; bold key words.
- {"type":"table","headers":["..."],"rows":[["...","..."]],"caption":"<optional>"}
- {"type":"callout","variant":"key_points|tutor_tip|warning","title":"...","body":"...","items":[...]}
- {"type":"quote","text":"...","attribution":"<optional>"}

RULES:
1. Follow the user's instruction. "Make this a table" -> emit a table; "make this a list" -> one list.
2. TABLES — when content is tabular (a grid, OR a set of items that each share the SAME fields, e.g.
   several operations each with a Formula + a "when to use"), use a "table": shared fields as
   "headers", one item per row. Do NOT flatten such repeated-attribute content into nested lists.
3. Convert "Term — definition" pairs into term_definition blocks and bulleted/numbered runs into list
   blocks (preserve nesting). Be concise; keep EVERY term, fact, number and formula — never invent.
4. MATH, STATISTICS & CHEMISTRY: reproduce every expression as LaTeX so it renders as real symbols.
   Inline math in single dollar signs, standalone equations in double dollars: $\\bar{x}$, $\\sigma^2$,
   $\\frac{a}{b}$, $x^{2}$, $H_2O$. Chemistry with mhchem \\ce{...}: $\\ce{H2SO4}$, $\\ce{2H2 + O2 ->
   2H2O}$. For a literal percent inside math write \\% (a bare % is a comment that hides the line).
5. LAYOUT: set every block's "layout" to "auto". Do NOT use "col1"/"col2"/"full", and NEVER emit a
   "banner" — this is one block inside an existing note. Do NOT set "theme" or "pack".
6. Output valid JSON only. A backslash in LaTeX must be DOUBLED in JSON: $\\sigma^2$ -> "$\\\\sigma^2$".
   No trailing commas.
"""

# Quick-action buttons in the "Fix with AI" dialog -> the instruction sent to the model (a custom
# free-text hint, if given, is appended). Shared by both editors so the mapping lives in one place.
FRAGMENT_QUICK_ACTIONS = {
    "table": "Reformat this content as a TABLE: make the repeated/shared fields the columns (headers) "
             "and one item per row. Keep any formulas as LaTeX.",
    "list": "Reformat this content as a single clean LIST block, preserving any nesting.",
    "termdef": "Split this into term_definition blocks — one bold term and a short definition each.",
    "auto": "Fix the structure: choose the best block type(s) (table, list, term/definition, body) "
            "for this content.",
}

# Only text-bearing CONTENT blocks may be "fixed". Excludes the banner (the poster header — the
# fragment path strips banners, so fixing one would destroy it), section headings, and media
# (image/diagram), where re-structuring the text would lose the title or the media.
FIXABLE_BLOCK_TYPES = frozenset(
    {"body", "subheading", "term_definition", "list", "table", "callout", "quote"}
)


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


# --- "Fix this block with AI": re-structure ONE block's text -> corrected blocks ------------------
_BLOCKS_ADAPTER = TypeAdapter(list[Block])


def _block_to_text(block) -> str:
    """The plain source text of a block (keeping **bold** / $math$) — the AI input when re-fixing it."""
    t = getattr(block, "type", "")
    if t in ("script_heading", "subheading", "body", "quote", "banner"):
        return (getattr(block, "text", "") or "").strip()
    if t == "term_definition":
        return f"**{block.term}** — {block.definition}".strip()
    if t == "list":
        def _items(items, depth=0):
            out = []
            for it in items:
                out.append("  " * depth + f"- {it.text}")
                out.extend(_items(it.children, depth + 1))
            return out
        return "\n".join(_items(block.items))
    if t == "table":
        lines = [block.caption] if getattr(block, "caption", None) else []
        lines.append(" | ".join(block.headers))
        lines.extend(" | ".join(r) for r in block.rows)
        return "\n".join(s for s in lines if s)
    if t == "callout":
        return "\n".join(s for s in [block.title or "", block.body or "", *(block.items or [])] if s).strip()
    if t == "image":
        return " ".join(s for s in (block.caption, block.alt, block.src) if s).strip()
    if t == "diagram":
        return " ".join(s for s in (getattr(block, "caption", None), block.mermaid) if s).strip()
    return ""


# --- "Looks broken?" — an INSTANT, local, no-AI heuristic for flagging genuinely-malformed blocks. --
# Calibrated for PRECISION (must NOT flag well-formed notes): every signal is an unambiguous structural
# defect. It deliberately ignores block.confidence — the liberal ingestion "low" is what caused the
# false-positive amber flags the user complained about, so the UI no longer keys off it.
# MATH/greek/chemistry commands only — NOT generic LaTeX like \section / \emph / \textbf, so prose that
# merely mentions a typesetting/regex command won't be mistaken for leaked math (precision over recall).
_MATH_CMD_RE = re.compile(
    r"\\(?:frac|dfrac|tfrac|sqrt|sum|prod|int|iint|oint|lim|infty|partial|nabla|cdot|times|div|"
    r"pm|mp|leq|geq|neq|approx|equiv|propto|binom|overline|underline|vec|hat|bar|dot|ddot|"
    r"alpha|beta|gamma|delta|epsilon|varepsilon|zeta|eta|theta|vartheta|iota|kappa|lambda|mu|nu|xi|"
    r"rho|sigma|tau|upsilon|phi|varphi|chi|psi|omega|"
    r"Gamma|Delta|Theta|Lambda|Xi|Pi|Sigma|Phi|Psi|Omega|ce|pu)\b"
)
_UNESCAPED_DOLLAR_RE = re.compile(r"(?<!\\)\$")


def _broken_math(text: str) -> bool:
    """Math left as plain text: 2+ MATH commands OUTSIDE any $…$ span, or a string with real math syntax
    and an odd number of UNESCAPED '$' (unbalanced). Currency ("$5", "\\$50") and prose mentioning
    non-math LaTeX commands never trip — precision over recall."""
    t = text or ""
    outside = re.sub(r"\$[^$\n]*\$", "", t)  # drop balanced inline-math spans first
    if len(_MATH_CMD_RE.findall(outside)) >= 2:
        return True
    has_math = bool(_MATH_CMD_RE.search(t) or re.search(r"[_^]\{", t))
    return has_math and len(_UNESCAPED_DOLLAR_RE.findall(t)) % 2 == 1


def looks_broken(block) -> str | None:
    """A short human reason if ``block`` looks GENUINELY malformed, else None (local, instant, no AI)."""
    t = getattr(block, "type", "")
    if t == "body":
        text = (getattr(block, "text", "") or "").strip()
        # Only a VERY long, structure-free body is a likely failed-import dump. 1000+ chars with no bold
        # is far beyond a normal note paragraph; lower thresholds wrongly flagged legitimate prose.
        if len(text) >= 1000 and text.count("**") < 2:
            return "Long unstructured paragraph — may be a failed-import text dump."
        if _broken_math(text):
            return "Math looks unrendered — LaTeX left as plain text."
    elif t == "list":
        items = getattr(block, "items", []) or []
        if len(items) >= 3 and sum(1 for it in items[:8] if " | " in (it.text or "")) >= 3:
            return "List rows contain “|” columns — likely a table that got flattened."
    elif t == "table":
        headers = getattr(block, "headers", []) or []
        rows = getattr(block, "rows", []) or []
        if not headers or any(len(r) != len(headers) for r in rows):
            return "Malformed table — ragged rows or missing headers."
    elif t in ("term_definition", "callout"):
        if _broken_math(_block_to_text(block)):
            return "Math looks unrendered — LaTeX left as plain text."
    return None


def heuristic_flags(note) -> dict[int, str]:
    """Map block-index -> reason for every block the instant local check finds malformed."""
    return {i: r for i, b in enumerate(note.blocks) if (r := looks_broken(b))}


def _build_fragment_prompt(text: str, hint: str | None, reason: str | None = None) -> str:
    instruction = (hint or "").strip() or FRAGMENT_QUICK_ACTIONS["auto"]
    reason_line = f"A quick check flagged this block: {reason.strip()}\n" if (reason or "").strip() else ""
    return (
        f"Instruction: {instruction}\n"
        f"{reason_line}"
        'First CHECK the text and give a one-sentence "diagnosis", then re-structure it into JSON '
        '({"diagnosis":"...","blocks":[...]} — no title, no banner). Output JSON only.\n\n'
        "<<<BLOCK TEXT>>>\n"
        f"{text}\n"
        "<<<END BLOCK TEXT>>>"
    )


def _blocks_from_fragment_response(text: str) -> tuple[list[Block] | None, str, str]:
    """Parse a fragment response ``{"diagnosis":..., "blocks":[...]}`` into ``(blocks, diagnosis, error)``
    — dropping any banner and coercing col1/col2 layouts to auto so the result blends into the note.
    ``diagnosis`` is the model's one-line "what was wrong" (``""`` if the model omitted it: back-compat)."""
    if not text:
        return None, "", "empty response from model"
    data = _extract_json(text)
    if not isinstance(data, dict) or not isinstance(data.get("blocks"), list):
        return None, "", "response was not a JSON object with a 'blocks' array"
    diagnosis = str(data.get("diagnosis") or "").strip()[:200]
    cleaned: list[dict] = []
    for b in data["blocks"]:
        if not isinstance(b, dict) or b.get("type") == "banner":  # a fragment never introduces a banner
            continue
        b.pop("theme", None)
        b.pop("pack", None)
        b["layout"] = "auto"  # a fragment never pins a column or spans width — and this also
        cleaned.append(b)     # neutralizes TableBlock's default layout="full" when the AI omits it
    if not cleaned:
        return None, diagnosis, "no usable blocks in response"
    try:
        return list(_BLOCKS_ADAPTER.validate_python(cleaned)), diagnosis, ""
    except ValidationError as exc:
        return None, diagnosis, str(exc)[:1200]


def restructure_fragment(
    text: str,
    hint: str | None = None,
    settings: Settings | None = None,
    model: str | None = None,
    max_retries: int = 2,
    reason: str | None = None,
) -> tuple[list[Block], str]:
    """Re-run ONE block's text through the AI: CHECK it, then return ``(corrected blocks, diagnosis)``
    (no banner, layout="auto").

    Reuses the configured engine + Gemini key pool via :func:`_gen_text`. ``hint`` is the user's
    instruction (a quick-action string and/or free text); ``reason`` is the local "looks broken" hint
    (if any), passed to the model so it checks against the same concern. Raises on persistent failure;
    re-raises the Claude-missing message immediately so the UI can prompt to install / switch engine."""
    if not (text or "").strip():
        raise ValueError("Nothing to restructure (the block is empty).")
    settings = settings or Settings()
    model = model or settings.models.structure
    base_prompt = _build_fragment_prompt(text, hint, reason)
    last_error, last_stderr = "unknown error", []
    for attempt in range(max_retries + 1):
        if attempt:
            time.sleep(min(2 ** attempt, 8))
        prompt = base_prompt
        if attempt:
            prompt += (
                f"\n\nYour previous response was invalid ({last_error}). "
                'Return ONLY a corrected JSON object: {"diagnosis":"...","blocks":[...]} with no banner.'
            )
        try:
            out, last_stderr = _gen_text(prompt, model, settings, settings.providers.notes, FRAGMENT_SYSTEM_PROMPT)
        except RuntimeError as exc:
            if str(exc) == _CLAUDE_MISSING:
                raise  # not transient — surface the install/switch hint
            last_error, out = str(exc), ""
        if out:
            blocks, diagnosis, last_error = _blocks_from_fragment_response(out)
            if blocks is not None:
                return blocks, diagnosis
    raise _failure(max_retries, last_error, last_stderr, settings.providers.notes)


# --- "Check note with AI": one call that judges EVERY content block, refining the instant heuristic --
SCAN_SYSTEM_PROMPT = """\
You are a QUALITY CHECKER for study-note blocks. You receive a JSON array of blocks, each with an
integer "i" (its index), a "type", and its "text". For EACH block decide if it is STRUCTURALLY BROKEN
— the text is in the wrong block type or left as an unstructured dump: a wall of raw text that should
be a list/table, a list whose rows are really table columns, LaTeX/math left as plain text, or a
ragged/garbled table.

BE CONSERVATIVE. The DEFAULT is that a block is FINE — most blocks are. Flag a block ONLY when you are
confident it is genuinely structurally broken. Do NOT flag a block for being short, terse, informal,
plain, or merely for wording you would phrase differently. When in doubt, do NOT flag it.

Respond with a SINGLE JSON object and nothing else (no prose, no code fences):
{"broken": [ {"i": <index>, "reason": "<8 words or fewer>"} ]}
Omit every block that is fine. If nothing is broken, return {"broken": []}.
"""

# Content blocks worth sending to the scan (FIXABLE_BLOCK_TYPES minus subheading — a short title is
# never "broken" in a way a fix could help).
_SCANNABLE_TYPES = frozenset({"body", "term_definition", "list", "table", "callout", "quote"})


def scan_note_blocks(
    note,
    settings: Settings | None = None,
    model: str | None = None,
    max_retries: int = 1,
) -> dict[int, str]:
    """Ask the AI, in ONE call, which of the note's content blocks are genuinely malformed. Returns
    ``{block_index: reason}``. Advisory: never raises for bad model output (returns what it can, or
    ``{}``); re-raises only the Claude-missing hint so the UI can prompt to install / switch engine."""
    settings = settings or Settings()
    model = model or settings.models.structure
    payload = [
        {"i": i, "type": b.type, "text": _block_to_text(b)[:600]}
        for i, b in enumerate(note.blocks)
        if b.type in _SCANNABLE_TYPES
    ]
    if not payload:
        return {}
    prompt = ("Blocks:\n" + json.dumps(payload, ensure_ascii=False)
              + "\nReturn the broken ones as described.")
    n = len(note.blocks)
    for attempt in range(max_retries + 1):
        if attempt:
            time.sleep(min(2 ** attempt, 8))
        try:
            out, _ = _gen_text(prompt, model, settings, settings.providers.notes, SCAN_SYSTEM_PROMPT)
        except RuntimeError as exc:
            if str(exc) == _CLAUDE_MISSING:
                raise
            continue
        data = _extract_json(out) if out else None
        if isinstance(data, dict) and isinstance(data.get("broken"), list):
            flags: dict[int, str] = {}
            for item in data["broken"]:
                if not isinstance(item, dict):
                    continue
                try:
                    idx = int(item["i"])
                except (TypeError, ValueError, KeyError):
                    continue
                if 0 <= idx < n:
                    flags[idx] = str(item.get("reason") or "Looks malformed").strip()[:80]
            return flags
    return {}


def _options(model: str, system: str, stderr_sink) -> ClaudeAgentOptions:
    kwargs = dict(
        model=model,
        system_prompt=system,
        allowed_tools=[],
        max_turns=1,
        setting_sources=[],  # ignore project/user/local settings for a clean call
        permission_mode="bypassPermissions",
        # Clear the nested-session flag so the CLI runs from inside a Claude Code session.
        env={"CLAUDECODE": ""},
        stderr=stderr_sink,
    )
    # In the packaged build the bundled CLI was stripped; point the SDK at a system-installed
    # Claude Code CLI (which uses the user's logged-in subscription).
    if getattr(sys, "frozen", False):
        cli = _find_claude_cli()
        if cli:
            kwargs["cli_path"] = cli
    return ClaudeAgentOptions(**kwargs)


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


_CLAUDE_TIMEOUT = 300.0  # wall-clock cap for one Claude structuring call (was unbounded)


def _claude_cli_error(exc: Exception, stderr: list[str]) -> RuntimeError:
    """Turn an SDK process/connection failure into a RuntimeError that CARRIES the CLI's stderr. The
    retry loops only catch RuntimeError, but a ProcessError ("Command failed with exit code 1") is a
    plain ClaudeSDKError — so without this it escaped UNCAUGHT (no retry, hard failure) AND hid the real
    reason (e.g. a rate/usage limit) behind the SDK's generic 'Check stderr output for details'."""
    tail = " | ".join(s.strip() for s in stderr[-6:] if s.strip())
    return RuntimeError(f"Claude CLI failed: {exc}{(' — ' + tail) if tail else ''}")


async def _run_text(prompt: str, model: str, system: str = SYSTEM_PROMPT) -> tuple[str, list[str]]:
    stderr: list[str] = []
    try:
        text = await asyncio.wait_for(
            _collect(query(prompt=prompt, options=_options(model, system, stderr.append))),
            timeout=_CLAUDE_TIMEOUT,
        )
    except (asyncio.TimeoutError, TimeoutError):
        raise
    except Exception as exc:  # noqa: BLE001 — convert to a retryable RuntimeError carrying the stderr
        if _CLINotFound is not None and isinstance(exc, _CLINotFound):
            raise
        raise _claude_cli_error(exc, stderr) from exc
    return text, stderr


async def _run_multimodal(
    content: list[dict], model: str, system: str = SYSTEM_PROMPT
) -> tuple[str, list[str]]:
    stderr: list[str] = []

    async def _stream():
        yield {"type": "user", "message": {"role": "user", "content": content}}

    try:
        text = await _collect(query(prompt=_stream(), options=_options(model, system, stderr.append)))
    except (asyncio.TimeoutError, TimeoutError):
        raise
    except Exception as exc:  # noqa: BLE001 — convert to a retryable RuntimeError carrying the stderr
        if _CLINotFound is not None and isinstance(exc, _CLINotFound):
            raise
        raise _claude_cli_error(exc, stderr) from exc
    return text, stderr


def _gen_text(prompt: str, model: str, settings: Settings, provider: str, system: str) -> tuple[str, list[str]]:
    """Run a text completion through the chosen backend. Returns (text, stderr lines)."""
    if provider == "ollama":
        cfg = settings.providers
        return _providers.ollama_complete(system, prompt, cfg.ollama_model, cfg.ollama_host), []
    if provider == "gemini":
        cfg = settings.providers
        return _providers.gemini_complete_pooled(
            system, prompt, cfg.gemini_model,
            fallback_key=os.environ.get("GEMINI_API_KEY", ""),
        ), []
    try:
        return asyncio.run(_run_text(prompt, model, system=system))
    except Exception as exc:
        if _CLINotFound is not None and isinstance(exc, _CLINotFound):
            raise RuntimeError(_CLAUDE_MISSING) from None
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            raise RuntimeError("Claude timed out on this section — retrying.") from None
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
            text = _providers.gemini_complete_pooled(
                SYSTEM_PROMPT, prompt_text, cfg.gemini_model,
                images=b64, timeout=300,  # vision generations run longer than the text default
                fallback_key=os.environ.get("GEMINI_API_KEY", ""),
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


# Big documents are split into chunks so each AI call stays well under the timeout and output cap
# (one giant call times out and can truncate), and the chunks are structured CONCURRENTLY so a huge
# file finishes in a reasonable time instead of dozens of serial calls.
# Kept deliberately SMALL: a dense, formula-heavy chunk expands 2-3x when transcribed into
# LaTeX-rich JSON (every backslash is doubled), so a big chunk's output can blow past the model's
# output-token cap (Gemini MAX_TOKENS / Claude truncated JSON) and fail every retry. Smaller chunks
# keep each call's output well under the cap; _structure_one also bisects any chunk that still overflows.
_CHUNK_TARGET = 4500   # aim for ~this many characters per chunk
_CHUNK_THRESHOLD = 6000  # only split inputs larger than this
_BISECT_FLOOR = 2500   # don't split a chunk below this when recovering from an output overflow
# Concurrent AI calls per provider: the SHARED free Gemini key has a tight rate limit, so go gentle;
# Claude (the user's own subscription) and a local Ollama have headroom.
# Claude (esp. Opus) has a tight per-minute rate limit; firing many concurrent calls rate-limits the
# subscription and the CLI exits 1. Keep it LOW (a rate-limited chunk also retries with backoff).
_PARALLEL = {"gemini": 2, "claude": 2, "ollama": 1}


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


def _is_overflow(error: str, text: str) -> bool:
    """Did the model's OUTPUT exceed its token cap? Gemini reports 'reply was cut off' (MAX_TOKENS);
    otherwise a truncated reply is LONG, starts like JSON ('{') but has no closing brace. A short
    non-JSON reply is a plain error, NOT an overflow — so re-prompting (not bisecting) is right there."""
    e = (error or "").lower()
    if "cut off" in e or "too long" in e or "max_tokens" in e:
        return True
    s = (text or "").strip()
    return len(s) > 2000 and s.startswith("{") and not s.endswith("}")


def _bisect(text: str) -> list[str]:
    """Split ``text`` into two parts at the paragraph (else line, else sentence) boundary nearest the
    middle; returns ``[text]`` if it can't be split. Used to recover from an output overflow."""
    mid = len(text) // 2
    best: tuple[int, int] | None = None
    for sep in ("\n\n", "\n", ". "):
        for pos in (text.rfind(sep, 0, mid), text.find(sep, mid)):
            if pos > 0 and (best is None or abs(pos - mid) < best[0]):
                best = (abs(pos - mid), pos + len(sep))
        if best:
            break
    cut = best[1] if best else mid
    left, right = text[:cut].strip(), text[cut:].strip()
    return [left, right] if left and right else [text]


def _merge_into(note: Note, extra: Note) -> None:
    """Append ``extra``'s blocks to ``note``, dropping a leading duplicate banner."""
    blocks = extra.blocks[1:] if extra.blocks and extra.blocks[0].type == "banner" else extra.blocks
    note.blocks.extend(blocks)


def _looks_understructured(note: Note, raw_text: str) -> bool:
    """True if the model DUMPED the chunk as plain body text instead of structuring it (a "wall"):
    every content block is a body, one of them is long, and together they cover most of the input.
    A properly structured note uses lists/tables/term_definitions, so this stays false for those."""
    content = [b for b in note.blocks if b.type not in ("banner", "script_heading")]
    if not content or not all(b.type == "body" for b in content):
        return False
    lengths = [len((getattr(b, "text", "") or "").strip()) for b in content]
    return max(lengths, default=0) >= 700 and sum(lengths) >= 0.5 * len(raw_text.strip())


def _structure_one(
    raw_text: str, title: str | None, theme: str, pack: str, model: str,
    settings: Settings, max_retries: int,
) -> Note:
    """Structure ONE chunk of text into a Note. Retries on invalid output and transient provider
    errors; if the model's output OVERFLOWS its token cap (reply cut off / truncated JSON), bisects
    the chunk and structures each half; and if the model returns an unstructured WALL of body text, it
    retries ONCE with a forceful "structure it" nudge."""
    base_prompt = _build_user_prompt(raw_text, title)
    last_error, last_stderr, last_text = "unknown error", [], ""
    nudge_wall, wall_retried = False, False
    for attempt in range(max_retries + 1):
        overflow = _is_overflow(last_error, last_text)
        if attempt:
            # A rate-limit needs the per-minute window to clear; ordinary errors just need a moment.
            low = last_error.lower()
            rate_limited = (any(t in low for t in ("limit was hit", "rate limit", "usage limit",
                                                   "overloaded", "429", "quota", "too many requests"))
                            or "claude cli failed" in low)  # batch CLI exit-1 is usually a rate limit
            time.sleep(22 if rate_limited else min(2 ** attempt, 8))
        # An output overflow won't fix itself on retry — split the chunk and structure each half.
        if attempt and overflow and len(raw_text) > _BISECT_FLOOR:
            halves = _bisect(raw_text)
            if len(halves) == 2:
                note = _structure_one(halves[0], title, theme, pack, model, settings, max_retries)
                _merge_into(note, _structure_one(halves[1], None, theme, pack, model, settings, max_retries))
                return note
        prompt = base_prompt
        if nudge_wall:  # the previous reply was a raw-text wall — demand real structure
            prompt += (
                "\n\nYour previous response was a WALL of unstructured text (a long body block). That is "
                "WRONG. Re-structure the SAME content into a script_heading + list card(s), "
                "term_definition blocks and tables per the rules; a body block must be at most 1–2 short "
                "sentences. Return ONLY the corrected single JSON object."
            )
        elif attempt and not overflow:  # a cut-off won't be fixed by re-asking, only by a smaller chunk
            prompt += (
                f"\n\nYour previous response was invalid ({last_error}). "
                "Return ONLY a corrected single JSON object."
            )
        nudge_wall = False  # consumed
        try:
            text, last_stderr = _gen_text(prompt, model, settings, settings.providers.notes, SYSTEM_PROMPT)
        except RuntimeError as exc:
            if str(exc) == _CLAUDE_MISSING:
                raise  # not transient — fail fast with the clear message
            last_error, text = str(exc), ""  # transient (timeout/network/overflow) — retry
        last_text = text
        if text:
            note, last_error = _note_from_response(text, title, theme, pack)
            if note is not None:
                # One re-try if the model dumped a wall instead of structuring (the "plain text" bug).
                if not wall_retried and attempt < max_retries and _looks_understructured(note, raw_text):
                    wall_retried, nudge_wall, last_error, last_text = True, True, "unstructured wall", ""
                    continue
                return note
    raise _failure(max_retries, last_error, last_stderr, settings.providers.notes)


def _structure_one_safe(
    raw_text: str, title: str | None, theme: str, pack: str, model: str,
    settings: Settings, max_retries: int, is_first: bool,
) -> Note:
    """Like :func:`_structure_one` but NEVER raises (used in the parallel path): if a chunk can't be
    structured after retries, keep its raw text as a low-confidence body block so no content is lost
    and the rest of the big import still succeeds. The Claude-missing error still propagates."""
    try:
        return _structure_one(raw_text, title, theme, pack, model, settings, max_retries)
    except RuntimeError as exc:
        if str(exc) == _CLAUDE_MISSING:
            raise
        blocks = ([BannerBlock(text=title)] if (is_first and title) else [])
        blocks.append(BodyBlock(text=raw_text.strip()[:4000], confidence="low"))
        return Note(title=title or "Notes", theme=theme, pack=pack, blocks=blocks)


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
    small AI calls structured CONCURRENTLY (so a big file can't time out and finishes quickly), and
    the resulting blocks are merged into one note (keeping a single banner). ``on_progress(done,
    total)`` is called as each chunk completes, for UI progress."""
    if not raw_text.strip():
        raise ValueError("Cannot structure empty text.")
    settings = settings or Settings()
    model = model or settings.models.structure
    chunks = _split_for_structuring(raw_text)

    if len(chunks) == 1:
        if on_progress:
            on_progress(1, 1)
        return _structure_one(chunks[0], title, theme, pack, model, settings, max_retries)

    # Structure the chunks concurrently (provider-aware: gentle on the shared free key), keeping
    # results in document order for a clean merge. Extra retries so a rate-limited chunk recovers.
    workers = min(_PARALLEL.get(settings.providers.notes, 2), len(chunks))
    chunk_retries = max(max_retries, 3)
    results: list[Note | None] = [None] * len(chunks)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_structure_one_safe, chunk, title if i == 0 else None,
                        theme, pack, model, settings, chunk_retries, i == 0): i
            for i, chunk in enumerate(chunks)
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()
            done += 1
            if on_progress:
                on_progress(done, len(chunks))

    merged = results[0]
    for note in results[1:]:
        extra = note.blocks
        if extra and extra[0].type == "banner":  # only the first chunk keeps the chapter banner
            extra = extra[1:]
        merged.blocks.extend(extra)
    return merged


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
