"""V8 package/manifest verification.

Modes:
  --tree           verify the CURRENT tree against DOWNLOAD_MANIFEST_SHA256.txt
                   (source section: everything except regenerated artifacts/).
                   Used as a gate inside make check, including from a clean
                   extraction.
  --zip <path>     verify a built archive: path safety (no absolute paths, no
                   traversal, no symlinks), internal root name, EVERY member
                   manifested (no unmanifested payloads), every manifest entry
                   present (no missing files), hash equality, and the 113 PNG
                   asset count.

usage:
  PYTHONPATH=src python scripts/verify_package.py --tree
  PYTHONPATH=src python scripts/verify_package.py --zip EAGLE_EYE_ZENITH_FABLE_HANDOFF_V8.zip
"""

from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "DOWNLOAD_MANIFEST_SHA256.txt"
EXPECTED_INTERNAL_ROOT = "EAGLE_EYE_ZENITH_FABLE_HANDOFF_V8"
EXPECTED_PNG_COUNT = 113


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(text: str) -> dict[str, str]:
    entries = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, rel = line.split(maxsplit=1)
        entries[rel.strip()] = digest
    return entries


def verify_tree() -> int:
    manifest_path = ROOT / MANIFEST
    if not manifest_path.exists():
        print(f"PACKAGE_VERIFY_FAIL=manifest missing at {manifest_path} (run scripts/build_package.py --manifest-only)")
        return 1
    entries = load_manifest(manifest_path.read_text())
    missing, mismatched = [], []
    for rel, digest in sorted(entries.items()):
        path = ROOT / rel
        if not path.exists():
            missing.append(rel)
        elif sha256_file(path) != digest:
            mismatched.append(rel)
    ok = not missing and not mismatched
    print(f"MANIFEST_ENTRIES={len(entries)}")
    print(f"MISSING={len(missing)}{' ' + str(missing[:5]) if missing else ''}")
    print(f"MISMATCHED={len(mismatched)}{' ' + str(mismatched[:5]) if mismatched else ''}")
    pngs = [rel for rel in entries if rel.startswith("web/assets/nodes/") and rel.endswith(".png")]
    print(f"PNG_ASSETS_MANIFESTED={len(pngs)}")
    ok = ok and len(pngs) == EXPECTED_PNG_COUNT
    print(f"PACKAGE_VERIFY_{'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def verify_zip(zip_path: Path) -> int:
    failures = []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        # path safety
        for info in zf.infolist():
            name = info.filename
            if name.startswith("/") or ".." in Path(name).parts:
                failures.append(f"unsafe path: {name}")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                failures.append(f"symlink member refused: {name}")
        roots = {n.split("/", 1)[0] for n in names}
        if roots != {EXPECTED_INTERNAL_ROOT}:
            failures.append(f"internal root must be exactly {EXPECTED_INTERNAL_ROOT}, got {sorted(roots)}")
        prefix = EXPECTED_INTERNAL_ROOT + "/"
        manifest_name = prefix + MANIFEST
        if manifest_name not in names:
            failures.append("manifest missing from archive")
            entries = {}
        else:
            entries = load_manifest(zf.read(manifest_name).decode())
        members = {n[len(prefix):] for n in names if not n.endswith("/") and n != manifest_name}
        unmanifested = sorted(members - set(entries))
        absent = sorted(set(entries) - members)
        if unmanifested:
            failures.append(f"unmanifested payloads: {unmanifested[:5]} (+{max(0, len(unmanifested)-5)})")
        if absent:
            failures.append(f"manifest entries missing from archive: {absent[:5]} (+{max(0, len(absent)-5)})")
        bad_hash = []
        for rel, digest in entries.items():
            member = prefix + rel
            if member in names:
                h = hashlib.sha256(zf.read(member)).hexdigest()
                if h != digest:
                    bad_hash.append(rel)
        if bad_hash:
            failures.append(f"hash mismatches: {bad_hash[:5]}")
        pngs = [rel for rel in entries if rel.startswith("web/assets/nodes/") and rel.endswith(".png")]
        if len(pngs) != EXPECTED_PNG_COUNT:
            failures.append(f"png count {len(pngs)} != {EXPECTED_PNG_COUNT}")
        print(f"ZIP_MEMBERS={len(names)}")
        print(f"MANIFEST_ENTRIES={len(entries)}")
        print(f"PNG_ASSETS={len(pngs)}")
    for failure in failures:
        print(f"FAIL: {failure}")
    print(f"PACKAGE_VERIFY_{'PASS' if not failures else 'FAIL'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    if "--zip" in sys.argv:
        raise SystemExit(verify_zip(Path(sys.argv[sys.argv.index("--zip") + 1])))
    raise SystemExit(verify_tree())
