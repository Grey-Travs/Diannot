"""The document editor's image-upload endpoint (/preview/upload)."""
from starlette.testclient import TestClient


def _client():
    from nicegui import app

    from diannot.studio import previews  # noqa: F401  — importing registers the route
    return TestClient(app), previews


def test_upload_stores_image_and_returns_editorjs_shape(tmp_path):
    client, previews = _client()
    previews.LIVE_ASSETS["tok1"] = tmp_path / "n.assets"
    r = client.post("/preview/upload?token=tok1",
                    files={"image": ("p.png", b"\x89PNG\r\n", "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] == 1
    assert body["file"]["url"].startswith("/file?path=")
    assert (tmp_path / "n.assets" / "p.png").read_bytes() == b"\x89PNG\r\n"


def test_upload_unknown_token_fails_soft():
    client, _ = _client()
    r = client.post("/preview/upload?token=nope",
                    files={"image": ("p.png", b"x", "image/png")})
    assert r.status_code == 200
    assert r.json()["success"] == 0
