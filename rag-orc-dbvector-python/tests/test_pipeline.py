"""Directory scanning: recursive selection + filtering of unsupported/junk files."""

from __future__ import annotations

from src.ingest.pipeline import iter_ingestable


def test_iter_ingestable_is_recursive_and_filters(tmp_path):
    # Supported files at various depths.
    (tmp_path / "a.pdf").write_bytes(b"x")
    deep = tmp_path / "sub" / "deep"
    deep.mkdir(parents=True)
    (deep / "b.pptx").write_bytes(b"x")
    (tmp_path / "sub" / "c.xlsx").write_bytes(b"x")
    (tmp_path / "d.PNG").write_bytes(b"x")  # case-insensitive

    # Unsupported types and macOS archive junk — must be skipped.
    (tmp_path / "notes.txt").write_bytes(b"x")
    (tmp_path / "legacy.ppt").write_bytes(b"x")
    macosx = tmp_path / "__MACOSX"
    macosx.mkdir()
    (macosx / "e.pdf").write_bytes(b"x")
    (tmp_path / "._resource.pdf").write_bytes(b"x")

    names = sorted(p.name for p in iter_ingestable(tmp_path))
    assert names == ["a.pdf", "b.pptx", "c.xlsx", "d.PNG"]
