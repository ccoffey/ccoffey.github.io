#!/usr/bin/env python3
"""Fail when committed project media has bypassed the pre-commit optimizer."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.optimize_staged_media import (
    IMAGE_DIMENSION_LIMIT,
    IMAGE_EXTENSIONS,
    IMAGE_SIZE_LIMIT,
    VIDEO_EXTENSIONS,
    VIDEO_OPTIMIZE_THRESHOLD,
    is_project_media,
)


def jpeg_has_app1_segment(path: Path) -> bool:
    """Return whether a JPEG contains an APP1 metadata segment.

    This matches ``generate_site.strip_exif_from_file``, which removes APP1
    segments containing EXIF, GPS, and XMP metadata.
    """
    data = path.read_bytes()
    if not data.startswith(b"\xff\xd8"):
        return False

    position = 2
    while position + 1 < len(data):
        if data[position] != 0xFF:
            return False  # Start of scan data; no more metadata segments follow.
        marker = data[position + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            position += 2
            continue
        if position + 3 >= len(data):
            return False
        length = int.from_bytes(data[position + 2 : position + 4], "big")
        if length < 2 or position + 2 + length > len(data):
            return False
        if marker == 0xE1:
            return True
        position += 2 + length
    return False


def changed_project_media(base_ref: str) -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", "-z", f"{base_ref}...HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return [
        Path(os.fsdecode(value))
        for value in result.stdout.split(b"\0")
        if value and is_project_media(Path(os.fsdecode(value)))
    ]


def all_project_media() -> list[Path]:
    return [
        path.relative_to(REPO_ROOT)
        for directory in (REPO_ROOT / "major-builds", REPO_ROOT / "quick-builds")
        for path in directory.glob("*/*")
        if path.is_file() and not path.is_symlink() and is_project_media(path.relative_to(REPO_ROOT))
    ]


def validation_errors(paths: list[Path]) -> list[str]:
    try:
        from PIL import Image
    except ImportError as error:
        raise RuntimeError("Pillow is required; install dependencies with: python -m pip install -r requirements.txt") from error

    from generate_site import is_video_optimized

    errors = []
    for relative in paths:
        path = REPO_ROOT / relative
        if not path.is_file() or path.is_symlink():
            continue
        suffix = path.suffix.lower()
        if suffix in IMAGE_EXTENSIONS:
            with Image.open(path) as image:
                largest_dimension = max(image.size)
            if largest_dimension > IMAGE_DIMENSION_LIMIT:
                errors.append(f"{relative}: {largest_dimension}px exceeds {IMAGE_DIMENSION_LIMIT}px")
            if path.stat().st_size > IMAGE_SIZE_LIMIT:
                errors.append(f"{relative}: {path.stat().st_size / 1024 / 1024:.1f} MB exceeds 2.5 MB")
            if suffix in {".jpg", ".jpeg"} and jpeg_has_app1_segment(path):
                errors.append(f"{relative}: JPEG APP1 (EXIF/XMP) metadata is present")
        elif suffix in VIDEO_EXTENSIONS and path.stat().st_size > VIDEO_OPTIMIZE_THRESHOLD:
            if not is_video_optimized(str(path)):
                errors.append(f"{relative}: video exceeds 25 MB and lacks the optimizer marker")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="Validate only project media changed from this Git ref to HEAD")
    args = parser.parse_args()
    paths = changed_project_media(args.base) if args.base else all_project_media()
    errors = validation_errors(paths)
    if errors:
        print("Project media bypassed the required pre-commit optimization:", file=sys.stderr)
        print(*[f"  - {error}" for error in errors], sep="\n", file=sys.stderr)
        print("Run the configured pre-commit hook to optimize and re-stage the media.", file=sys.stderr)
        return 1
    print(f"Validated {len(paths)} project media file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
