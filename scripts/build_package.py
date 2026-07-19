"""Build the complete, manifested V8 handoff archive.

Package contents: the full source tree (INCLUDING all 113 PNG assets) plus
versioned receipts, EXCLUDING regenerated artifacts/ and caches.
Internal root: EAGLE_EYE_ZENITH_FABLE_HANDOFF_V8. Every member is listed in
DOWNLOAD_MANIFEST_SHA256.txt; the manifest passes from a clean extraction
(scripts/verify_package.py --tree / --zip).

usage:
  python scripts/build_package.py --manifest-only        # (re)write the manifest
  python scripts/build_package.py <output.zip>           # manifest + archive
"""

from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "DOWNLOAD_MANIFEST_SHA256.txt"
INTERNAL_ROOT = "EAGLE_EYE_ZENITH_FABLE_HANDOFF_V8"
EXCLUDE_DIRS = {"artifacts", "__pycache__", ".venv", ".pytest_cache", ".git"}
# build-generated metadata must never be manifested/shipped: it is regenerated
# by `pip install -e .` and its content/paths are environment-dependent.
EXCLUDE_SUFFIXES = (".egg-info", ".egg-link", ".dist-info")
EXCLUDE_FILES = {MANIFEST}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def packaged_files() -> list[Path]:
    files = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if any(part.endswith(EXCLUDE_SUFFIXES) for part in rel.parts):
            continue
        if str(rel) in EXCLUDE_FILES:
            continue
        files.append(path)
    return files


def write_manifest(files: list[Path]) -> Path:
    lines = [f"{sha256_file(p)}  {p.relative_to(ROOT)}" for p in files]
    manifest_path = ROOT / MANIFEST
    manifest_path.write_text("\n".join(lines) + "\n")
    print(f"MANIFEST_ENTRIES={len(lines)} -> {manifest_path}")
    return manifest_path


def main() -> int:
    manifest_only = "--manifest-only" in sys.argv
    out = None if manifest_only else Path(sys.argv[1]).resolve()
    # A repeated in-tree build must not ingest its prior archive as payload.
    # Remove only the exact requested output before enumerating package files.
    if out is not None and out.parent == ROOT and out.exists():
        out.unlink()
    files = packaged_files()
    manifest_path = write_manifest(files)
    if manifest_only:
        return 0
    assert out is not None
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files + [manifest_path]:
            zf.write(path, f"{INTERNAL_ROOT}/{path.relative_to(ROOT)}")
    digest = sha256_file(out)
    print(f"ARCHIVE={out}")
    print(f"ARCHIVE_SHA256={digest}")
    print(f"ARCHIVE_BYTES={out.stat().st_size}")
    print(f"ARCHIVE_MEMBERS={len(files) + 1}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
