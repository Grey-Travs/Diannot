"""Pydantic v2 models for Diannot study-note blocks.

A :class:`Note` is an ordered list of typed blocks. Blocks form a discriminated
union keyed on the ``type`` field, so JSON on disk round-trips cleanly and
validates. Every block carries a ``layout`` override for the two-column flow.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

# Per-block layout override within the two-column flow.
# "auto" = flow normally (full width); "full" = span both columns; "col1"/"col2" pin the block to
# the left/right column so paired content renders side by side (the editor's Left/Right control).
Layout = Literal["auto", "full", "col1", "col2"]


class _Block(BaseModel):
    """Fields shared by every block."""

    layout: Layout = "auto"
    # Provenance + confidence (set during ingestion; optional for hand-authored notes).
    source_page: Optional[int] = None
    confidence: Optional[Literal["high", "medium", "low"]] = None


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

    title: str
    theme: str = "circulatory"
    pack: str = "study_notes"
    subject: Optional[str] = None
    source: Optional[str] = None  # source file this note was ingested from
    blocks: list[Block] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


ListItem.model_rebuild()
