"""First-run downloads: the manifest is pinned and consistent with where the app reads, and a
file only lands once its checksum matches. Downloads go to a stand-in server on loopback."""

from __future__ import annotations

import hashlib
import io
import re
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import download, endpoint, lfm3, servers  # noqa: E402


def test_every_source_is_pinned_and_checked():
    for item in download.ITEMS:
        assert re.fullmatch(r"[0-9a-f]{64}", item.sha256), item.name
        assert item.size > 0 and item.licence, item.name
        assert item.url.startswith("https://"), item.name
        assert "/main/" not in item.url and "/master/" not in item.url, \
            "%s follows a moving branch" % item.name
    for rev in (download.QWEN[1], download.LFM3[1], download.MINILM[1], download.SILERO):
        assert re.fullmatch(r"[0-9a-f]{40}", rev)


def test_downloads_land_where_the_app_reads_them():
    dests = {download.ROOT / i.dest for i in download.ITEMS if not i.archive}
    assert {servers.LLM_FILE, servers.EMBED_FILE, lfm3.MODEL, lfm3.MMPROJ,
            endpoint.MODEL} <= dests
    runtime = {download.ROOT / i.dest for i in download.ITEMS if i.archive}
    assert runtime == {download.ROOT / "runtime" / "llama.cpp"}


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "ROOT", tmp_path)
    return tmp_path


@pytest.fixture()
def serve():
    files: dict[str, bytes] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = files.get(self.path)
            self.send_response(200 if body is not None else 404)
            self.send_header("Content-Length", str(len(body or b"")))
            self.end_headers()
            self.wfile.write(body or b"")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    yield base, files
    srv.shutdown()


def _item(base, files, name, data, dest="models/x/file.bin", archive=False, sha=None):
    files["/" + name] = data
    return download.Item(name, dest, "%s/%s" % (base, name),
                         sha or hashlib.sha256(data).hexdigest(), len(data), "MIT", archive)


def test_a_file_that_matches_its_checksum_is_put_in_place(root, serve):
    item = _item(*serve, "model.gguf", b"weights" * 1000)
    assert not download.present(item)
    download.get(item, say=lambda *a: None)
    assert (root / item.dest).read_bytes() == b"weights" * 1000
    assert download.present(item)
    assert not list((root / "models" / "x").glob("*.part"))


def test_a_file_that_does_not_match_is_deleted_and_reported(root, serve):
    item = _item(*serve, "model.gguf", b"tampered", sha="0" * 64)
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        download.get(item, say=lambda *a: None)
    assert not (root / item.dest).exists()
    assert not list(root.rglob("*.part"))


def test_an_archive_is_unpacked_and_remembered(root, serve):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("llama-server.exe", b"MZ")
    item = _item(*serve, "runtime.zip", buf.getvalue(), dest="runtime/llama.cpp", archive=True)
    download.get(item, say=lambda *a: None)
    assert (root / "runtime" / "llama.cpp" / "llama-server.exe").read_bytes() == b"MZ"
    assert download.present(item)
    assert not list((root / "runtime" / "llama.cpp").glob(".download-*")), "the zip is not kept"


def test_an_archive_that_would_write_outside_its_folder_is_refused(root, serve):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../escaped.txt", b"no")
    item = _item(*serve, "evil.zip", buf.getvalue(), dest="runtime/llama.cpp", archive=True)
    with pytest.raises(RuntimeError, match="unsafe path"):
        download.get(item, say=lambda *a: None)
    assert not (root / "runtime" / "escaped.txt").exists()


def test_a_matching_local_copy_is_used_instead_of_the_network(root, tmp_path_factory):
    src = tmp_path_factory.mktemp("held")
    data = b"already here"
    (src / "file.bin").write_bytes(data)
    item = download.Item("model", "models/x/file.bin", "https://127.0.0.1:9/file.bin",
                         hashlib.sha256(data).hexdigest(), len(data), "MIT")
    found = download._local(item, [src])
    assert found == src / "file.bin"
    download.get(item, found, say=lambda *a: None)
    assert (root / item.dest).read_bytes() == data


def test_a_local_copy_with_the_wrong_bytes_is_not_used(tmp_path):
    (tmp_path / "file.bin").write_bytes(b"other bytes!")
    item = download.Item("model", "models/x/file.bin", "https://127.0.0.1:9/file.bin",
                         "0" * 64, 12, "MIT")
    assert download._local(item, [tmp_path]) is None


def test_an_install_reports_the_revision_it_was_built_from(tmp_path, monkeypatch):
    """An install has no git; without the stamp every session recorded `unknown`."""
    from app import provenance

    stamp = tmp_path / "BUILD"
    stamp.write_text("0.2.0 4baeff2\n", encoding="ascii")
    monkeypatch.setattr(provenance, "BUILD", stamp)
    assert provenance.code_revision() == "0.2.0 4baeff2"
