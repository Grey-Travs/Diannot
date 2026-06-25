"""Pydantic v2 models for Diannot study-note blocks.

A :class:`Note` is an ordered list of typed blocks. Blocks form a discriminated
union keyed on the ``type`` field, so JSON on disk round-trips cleanly and
validates. Every block carries a ``layout`` override for the two-column flow.
"""
from __future__ import annotations

import json
import uuid
from typing import Annotated, Callable, Literal, Optional, Union

from pydantic import BaseModel, Field, PrivateAttr, TypeAdapter, model_serializer

# On-disk format version for ``*.note.json``. Bump this — and register a forward-only migrator in
# ``_MIGRATIONS`` — whenever a change could make an OLDER build mis-read a note written by a NEWER
# one (a new top-level field, a new block ``type``, a new enum value). Notes written before
# versioning carry no field and are treated as version 1; ``load_note`` backfills them. Keep schema
# evolution ADDITIVE-ONLY (new fields default-valued, never renamed/removed in place) so this stays
# a one-way ratchet.
SCHEMA_VERSION = 1

# Per-block layout override within the two-column flow.
# "auto" = flow normally (full width); "full" = span both columns; "col1"/"col2" pin the block to
# the left/right column so paired content renders side by side (the editor's Left/Right control).
Layout = Literal["auto", "full", "col1", "col2"]


class Box(BaseModel):
    """Absolute position on a fixed canvas page, as percentages (0–100) of the page width/height.

    Used only by canvas-mode notes (:attr:`Note.layout_mode` == ``"canvas"``); ``None`` for flow
    notes, which the standard two-column renderer keeps untouched. The editor clamps values to the
    page and the renderer clips overflow, so no upper bounds are enforced here.
    """

    x: float = 0.0
    y: float = 0.0
    w: float = 30.0
    h: float = 12.0
    z: int = 0


class _Block(BaseModel):
    """Fields shared by every block."""

    layout: Layout = "auto"
    # Provenance + confidence (set during ingestion; optional for hand-authored notes).
    source_page: Optional[int] = None
    confidence: Optional[Literal["high", "medium", "low"]] = None
    # Canvas mode only: a stable id (so a position can be attached to this block) + its absolute
    # box. Both are None for flow notes and ignored by the two-column renderer.
    id: Optional[str] = None
    box: Optional[Box] = None


class BannerBlock(_Block):
    """Poster-style chapter header (chunky outlined font + drop shadow)."""

    type: Literal["banner"] = "banner"
    text: str
    subtitle: Optional[str] = None
    images: list[str] = Field(default_factory=list, description="Paths to themed illustrations.")
    layout: Layout = "full"


class ScriptHeadingBlock(_Block):
    """Major section title in the script/handwritten font."""

    type: Literal["script_heading"] = "script_heading"
    text: str


class SubheadingBlock(_Block):
    """Heavy bold-sans sub-heading; ``caps`` renders it uppercase."""

    type: Literal["subheading"] = "subheading"
    text: str
    caps: bool = False


class BodyBlock(_Block):
    """Body paragraph. ``text`` supports inline ``**bold**`` for testable terms."""

    type: Literal["body"] = "body"
    text: str


class TermDefinitionBlock(_Block):
    """Renders as **Term** — definition (bold colored term, em dash, definition)."""

    type: Literal["term_definition"] = "term_definition"
    term: str
    definition: str


class ListItem(BaseModel):
    """A list item that may nest child items."""

    text: str
    children: list["ListItem"] = Field(default_factory=list)


class ListBlock(_Block):
    """Ordered or unordered, nestable list."""

    type: Literal["list"] = "list"
    ordered: bool = False
    items: list[ListItem]


class TableBlock(_Block):
    """Comparison table with a colored header row."""

    type: Literal["table"] = "table"
    headers: list[str]
    rows: list[list[str]]
    caption: Optional[str] = None
    layout: Layout = "full"


class ImageBlock(_Block):
    """Image with optional caption and source credit."""

    type: Literal["image"] = "image"
    src: str
    alt: Optional[str] = None
    caption: Optional[str] = None
    source_credit: Optional[str] = None
    width: Optional[int] = Field(default=None, ge=10, le=100, description="Display width as % of the column (10–100); None = 100%.")


class DiagramBlock(_Block):
    """Mermaid diagram source (rendered client-side when the note is viewed/exported)."""

    type: Literal["diagram"] = "diagram"
    mermaid: str
    caption: Optional[str] = None


class CalloutBlock(_Block):
    """Visually distinct box. ``body`` and/or ``items`` may be supplied."""

    type: Literal["callout"] = "callout"
    variant: Literal["tutor_tip", "key_points", "warning"] = "tutor_tip"
    title: Optional[str] = None
    body: Optional[str] = None
    items: list[str] = Field(default_factory=list)


class QuoteBlock(_Block):
    """Pull-quote with optional attribution."""

    type: Literal["quote"] = "quote"
    text: str
    attribution: Optional[str] = None


Block = Annotated[
    Union[
        BannerBlock,
        ScriptHeadingBlock,
        SubheadingBlock,
        BodyBlock,
        TermDefinitionBlock,
        ListBlock,
        TableBlock,
        ImageBlock,
        DiagramBlock,
        CalloutBlock,
        QuoteBlock,
    ],
    Field(discriminator="type"),
]


class Note(BaseModel):
    """A single study note: metadata + ordered blocks."""

    # On-disk format version. Defaults to the current version for freshly-made notes; ``load_note``
    # backfills it to 1 for pre-versioning notes. OMITTED from saved JSON while it equals 1 (the
    # baseline — see ``_serialize``) so versioned-build notes stay byte-identical to legacy notes and
    # currently-deployed builds (which ``extra="forbid"`` and don't know this field) keep reading
    # them. It is written once it exceeds 1, which is exactly when a newer note must announce itself
    # so a tolerant older build can refuse to silently downgrade it (see ``load_note``).
    schema_version: int = SCHEMA_VERSION
    title: str
    theme: str = "circulatory"
    pack: str = "study_notes"
    subject: Optional[str] = None
    source: Optional[str] = None  # source file this note was ingested from
    # "flow" = the signature auto-styled two-column note (default). "canvas" = free positioning,
    # where each block carries an absolute :class:`Box`. Old notes lack this field -> "flow".
    layout_mode: Literal["flow", "canvas"] = "flow"
    blocks: list[Block] = Field(default_factory=list)
    # Outcome of AI structuring. None == healthy (the common case) so it is omitted on save
    # (model_dump_json(exclude_none=True)) and older builds keep reading normal notes. Only a
    # degraded note carries a status: "partial" (some chunks fell back to raw text) or "failed"
    # (all of it did). ``source_text`` holds the FULL original text so the user can re-organize it.
    extraction_status: Optional[Literal["ok", "partial", "failed"]] = None
    source_text: Optional[str] = None
    # The VISION counterpart of ``source_text``: relative PNG filenames inside ``<note>.assets/`` of
    # the page images a failed vision structuring fell back to, so the user can re-run vision on them.
    # Optional + default None so healthy notes omit it on save and older builds keep reading normal
    # notes (same back-compat property as ``source_text``/``extraction_status``).
    source_images: Optional[list[str]] = None

    model_config = {"extra": "forbid"}

    # Transient (never serialized): the raw page-image bytes a failed vision structuring preserved,
    # carried out of the structuring layer so the ingest caller — which alone knows the final note
    # path — can write them under ``<note>.assets/`` and fill ``source_images``. PrivateAttr so
    # ``extra="forbid"`` and ``model_dump_json`` both leave it out.
    _pending_page_images: list[bytes] = PrivateAttr(default_factory=list)

    # Set by ``load_note`` to the ``schema_version`` actually found on disk (None for in-memory notes
    # that were never loaded). When it exceeds ``SCHEMA_VERSION`` the note was made by a NEWER build
    # and was loaded read-only in "safe mode" (unknown fields/blocks dropped); callers must not
    # overwrite it — see ``is_future_schema``. PrivateAttr so it never serializes.
    _on_disk_schema_version: Optional[int] = PrivateAttr(default=None)

    @property
    def is_future_schema(self) -> bool:
        """True if this note came from a NEWER on-disk schema than this build understands.

        Such a note was parsed best-effort (newer fields/blocks dropped from the in-memory view), so
        it is **read-only**: saving it would clobber the on-disk file and silently drop the content
        this build couldn't parse. Editing surfaces must refuse to write it back.
        """
        v = self._on_disk_schema_version
        return v is not None and v > SCHEMA_VERSION

    @model_serializer(mode="wrap")
    def _serialize(self, handler):  # type: ignore[no-untyped-def]
        """Omit ``schema_version`` from the output while it equals the baseline (1).

        This keeps baseline notes byte-identical to pre-versioning notes, so older builds — which
        forbid extra fields and don't know ``schema_version`` — keep reading notes written by a
        versioned build. The field reappears once it exceeds 1, which is precisely when an older
        (but tolerant) build needs to see it to enter safe mode. ``handler`` applies the active dump
        options (``exclude_none`` etc.); we only drop the one baseline key.
        """
        data = handler(self)
        if data.get("schema_version") == 1:
            data.pop("schema_version", None)
        return data


# Validates a single block against the discriminated union — used by ``load_note``'s safe-mode path
# to test whether this build understands a block from a newer note.
_BlockAdapter: TypeAdapter = TypeAdapter(Block)

# Forward-only migrations: ``_MIGRATIONS[n]`` upgrades a note dict from version ``n`` to ``n + 1``.
# Empty today (v1 is the baseline); add an entry each time ``SCHEMA_VERSION`` is bumped. Each migrator
# takes and returns a plain dict and must be additive/total (never raise on a well-formed older note).
_MIGRATIONS: dict[int, Callable[[dict], dict]] = {}


def _migrate(data: dict, from_version: int) -> dict:
    """Apply forward-only migrations to bring a note dict from ``from_version`` up to the current
    schema. Returns a new dict; never mutates the input. Stops (and leaves the version as-reached) if
    a step is missing so strict validation surfaces the gap rather than mislabelling the note."""
    data = dict(data)
    v = from_version
    while v < SCHEMA_VERSION and v in _MIGRATIONS:
        data = _MIGRATIONS[v](data)
        v += 1
    data["schema_version"] = v
    return data


def _load_tolerant(data: dict) -> "Note":
    """Best-effort parse of a note written by a NEWER build (read-only "safe mode").

    Keep only the top-level fields and the blocks this build understands, so the note still opens for
    viewing instead of hard-failing on ``extra="forbid"`` / an unknown block ``type``. The on-disk
    file is never touched here; the caller marks the result read-only via ``_on_disk_schema_version``.
    """
    known = {k: v for k, v in data.items() if k in Note.model_fields}
    blocks = known.get("blocks")
    if isinstance(blocks, list):
        kept: list = []
        for raw_block in blocks:
            try:
                _BlockAdapter.validate_python(raw_block)  # does this build know the block?
            except Exception:
                continue  # unknown block type / new enum value -> drop from the read-only view
            kept.append(raw_block)
        known["blocks"] = kept
    known["schema_version"] = SCHEMA_VERSION  # represent in-memory as current; is_future_schema flags reality
    return Note.model_validate(known)


def load_note(raw: "str | bytes") -> "Note":
    """Load a :class:`Note` from its JSON text, tolerant of on-disk schema drift.

    - A note at or below the current schema (or with no ``schema_version`` — treated as v1) is
      migrated forward and validated **strictly** (``extra="forbid"`` still catches authoring typos).
    - A note from a NEWER build (``schema_version`` > :data:`SCHEMA_VERSION`) is loaded in read-only
      "safe mode": unknown fields/blocks are dropped so it still opens, and :attr:`Note.is_future_schema`
      is set so editing surfaces refuse to overwrite (and silently drop) the newer content.

    Use this everywhere a note is read from disk, in place of ``Note.model_validate_json``.
    """
    data = json.loads(raw)
    if not isinstance(data, dict):
        return Note.model_validate(data)  # not an object — let strict validation raise the usual error
    on_disk = data.get("schema_version", 1)
    if not isinstance(on_disk, int) or isinstance(on_disk, bool):
        on_disk = 1
    if on_disk <= SCHEMA_VERSION:
        note = Note.model_validate(_migrate(data, on_disk))
    else:
        note = _load_tolerant(data)
    note._on_disk_schema_version = on_disk
    return note


def ensure_ids(note: "Note") -> "Note":
    """Give every block a stable id (canvas positions are keyed by id). Mutates + returns the note."""
    for b in note.blocks:
        if not b.id:
            b.id = uuid.uuid4().hex
    return note


ListItem.model_rebuild()
