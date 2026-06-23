"""Batch import core: _run_import_batch isolates per-file errors and cleans up (no GUI, no live AI)."""
import asyncio
from pathlib import Path

from diannot.config import Settings
from diannot.models import BodyBlock, Note
from diannot.studio.pages import import_ as I


def _job(files):
    return {
        "status": "running",
        "files": [{"name": f["name"], "status": "pending", "step": "", "error": None,
                   "note_path": None} for f in files],
        "total": len(files), "done": 0, "current": 0, "created": [], "failed": [], "t0": 0.0,
    }


def _stage(tmp_path, names):
    imports = tmp_path / "_imports"
    imports.mkdir(parents=True, exist_ok=True)
    files = []
    for name in names:
        p = imports / name
        p.write_text("content", encoding="utf-8")
        files.append({"path": str(p), "name": name})
    return imports, files


def _patch_ingest(monkeypatch):
    """Fake ingest_file: raises on a 'bad' filename, else returns a 1-block note titled by `title`.
    Also make run_blocking call straight through (no thread/loop indirection)."""
    def fake_ingest(path, *, settings, on_progress, title, **kw):
        on_progress(1, 1)
        if "bad" in Path(path).name:
            raise RuntimeError("boom")
        return Note(title=title, blocks=[BodyBlock(text="hi")])

    async def fake_run_blocking(fn, *a, **k):
        return fn(*a, **k)

    monkeypatch.setattr(I, "ingest_file", fake_ingest)
    monkeypatch.setattr(I, "run_blocking", fake_run_blocking)


def test_batch_isolates_errors_and_cleans_up(tmp_path, monkeypatch):
    _patch_ingest(monkeypatch)
    imports, files = _stage(tmp_path, ["good1.txt", "bad.txt", "good2.txt"])
    job = _job(files)

    asyncio.run(I._run_import_batch(str(tmp_path), job, files,
                                    {"theme": "circulatory", "pack": "study_notes"}, Settings()))

    assert job["status"] == "done" and job["done"] == 3
    assert len(job["created"]) == 2 and len(job["failed"]) == 1   # one bad file didn't abort the rest
    assert job["failed"][0]["name"] == "bad.txt" and "boom" in job["failed"][0]["error"]
    assert [fe["status"] for fe in job["files"]] == ["done", "error", "done"]
    # the two good notes were written, titled from their file names
    assert (tmp_path / "Good1.note.json").exists() and (tmp_path / "Good2.note.json").exists()
    # temp uploads were removed (success AND failure paths clean up)
    assert list(imports.iterdir()) == []


def test_batch_title_override_single(tmp_path, monkeypatch):
    _patch_ingest(monkeypatch)
    _imports, files = _stage(tmp_path, ["whatever.txt"])
    job = _job(files)

    asyncio.run(I._run_import_batch(str(tmp_path), job, files,
                                    {"theme": "circulatory", "pack": "study_notes", "title": "My Title"},
                                    Settings()))

    assert job["created"][0]["name"] == "My_Title.note.json"   # explicit title beats the filename


def test_unique_note_path_dedup(tmp_path):
    a = I._unique_note_path(str(tmp_path), "Chapter 1")
    a.write_text("{}", encoding="utf-8")
    b = I._unique_note_path(str(tmp_path), "Chapter 1")
    assert a.name == "Chapter_1.note.json" and b.name == "Chapter_1-1.note.json"
