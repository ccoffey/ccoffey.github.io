#!/usr/bin/env python3
"""Create or verify a content manifest for a generated site."""

import argparse
import hashlib
import json
from pathlib import Path
import sys


def file_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(site):
    return {
        "files": {
            path.relative_to(site).as_posix(): {
                "bytes": path.stat().st_size,
                "sha256": file_digest(path),
            }
            for path in sorted(site.rglob("*"))
            if path.is_file()
        }
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("site")
    create.add_argument("manifest")

    verify = subparsers.add_parser("verify")
    verify.add_argument("site")
    verify.add_argument("manifest")

    args = parser.parse_args()
    site = Path(args.site).resolve()
    if not site.is_dir():
        raise SystemExit(f"Site directory does not exist: {site}")

    if args.command == "create":
        manifest = build_manifest(site)
        Path(args.manifest).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"Recorded {len(manifest['files'])} files in {args.manifest}")
        return 0

    expected = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    actual = build_manifest(site)
    if actual != expected:
        expected_files = expected.get("files", {})
        actual_files = actual["files"]
        missing = sorted(set(expected_files) - set(actual_files))
        unexpected = sorted(set(actual_files) - set(expected_files))
        changed = sorted(
            path for path in set(expected_files) & set(actual_files)
            if expected_files[path] != actual_files[path]
        )
        print(f"Manifest verification failed: {len(missing)} missing, {len(unexpected)} unexpected, {len(changed)} changed.")
        for label, paths in (("Missing", missing), ("Unexpected", unexpected), ("Changed", changed)):
            if paths:
                print(f"{label}: {', '.join(paths[:30])}")
        return 1

    print(f"Manifest verification passed: all {len(actual['files'])} files match.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
