"""Home / Library — browse the workspace, make/open notes, change folder."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from nicegui import ui

from ...models import BannerBlock, BodyBlock, Note, ScriptHeadingBlock
from ..layout import studio_layout
from ..onboarding import maybe_first_run
from ..workspace import SAMPLE_DIR, current_workspace, list_notes, set_workspace


def _new_note(workspace: Path) -> None:
    note = Note(
        title="Untitled Note",
        blocks=[
            BannerBlock(text="Untitled Note"),
            ScriptHeadingBlock(text="Section title"),
            BodyBlock(text="Write your **notes** here. Bold the **testable** terms."),
        ],
    )
    dest = Path(workspace) / "untitled.note.json"
    n = 1
    while dest.exists():
        dest = Path(workspace) / f"untitled-{n}.note.json"
        n += 1
    dest.write_text(note.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
    ui.navigate.to(f"/note?path={quote(str(dest))}")


def _change_folder_dialog(workspace: Path | None) -> None:
    with ui.dialog() as dialog, ui.card().classes("p-4 gap-2"):
        ui.label("Choose your notes folder").classes("text-subtitle1")
        field = ui.input(label="Folder path", value=str(workspace or "")).classes("w-96")

        def apply() -> None:
            path = Path(field.value).expanduser()
            if path.is_dir():
                set_workspace(path)
                dialog.close()
                ui.navigate.to("/")
            else:
                ui.notify("That folder doesn't exist.", type="negative")

        with ui.row().classes("justify-end gap-2 w-full"):
            if SAMPLE_DIR.exists():
                ui.button("Use sample", icon="folder_open",
                          on_click=lambda: (set_workspace(SAMPLE_DIR), dialog.close(), ui.navigate.to("/"))).props("flat no-caps")
            ui.button("Apply", icon="check", on_click=apply).props("color=primary no-caps")
    dialog.open()


@ui.page("/")
def home_page() -> None:
    studio_layout("")
    maybe_first_run()
    workspace = current_workspace()
    with ui.column().classes("w-full p-4 gap-4"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("Your notes").classes("text-h5")
            with ui.row().classes("gap-2"):
                ui.button("New note", icon="note_add",
                          on_click=lambda: workspace and _new_note(workspace)).props("outline no-caps")
                ui.button("Make notes from a file", icon="auto_awesome",
                          on_click=lambda: ui.navigate.to("/import")).props("color=primary no-caps")
        with ui.row().classes("items-center gap-2"):
            ui.label(f"Folder: {workspace}" if workspace else "No folder selected").classes("text-caption text-grey")
            ui.button("Change folder", icon="folder",
                      on_click=lambda: _change_folder_dialog(workspace)).props("flat dense no-caps")

        notes = list_notes(workspace) if workspace else []
        if not notes:
            with ui.card().classes("p-4"):
                ui.label("No notes here yet.").classes("text-subtitle1")
                ui.label("Import a file to make notes, or load the sample notebook to look around.").classes("text-grey")
                if SAMPLE_DIR.exists():
                    ui.button("Load the sample notebook", icon="folder_open",
                              on_click=lambda: (set_workspace(SAMPLE_DIR), ui.navigate.to("/"))).props("no-caps")
        else:
            with ui.row().classes("flex-wrap gap-4"):
                for path, note in notes:
                    with ui.card().classes("w-60"):
                        ui.label(note.title).classes("text-subtitle1 text-bold")
                        ui.label(note.subject or note.theme).classes("text-caption text-grey")
                        with ui.row().classes("gap-1"):
                            ui.button("Open", icon="edit",
                                      on_click=lambda p=path: ui.navigate.to(f"/note?path={quote(p)}")).props("flat dense no-caps")
                            ui.button("Study", icon="school",
                                      on_click=lambda p=path: ui.navigate.to(f"/study?path={quote(p)}")).props("flat dense no-caps")
