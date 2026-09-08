#!/usr/bin/env python3
"""Optimize newly staged project media before it enters Git history."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
IMAGE_SIZE_LIMIT = int(2.5 * 1024 * 1024)
IMAGE_DIMENSION_LIMIT = 2560
VIDEO_OPTIMIZE_THRESHOLD = 25 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def staged_paths() -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return [Path(os.fsdecode(value)) for value in result.stdout.split(b"\0") if value]


def is_project_media(path: Path) -> bool:
    parts = path.parts
    return (
        len(parts) == 3
        and parts[0] in {"major-builds", "quick-builds"}
        and path.suffix.lower() in MEDIA_EXTENSIONS
    )


def require_tools(paths: list[Path]) -> None:
    if any(path.suffix.lower() in VIDEO_EXTENSIONS for path in paths):
        missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
        if missing:
            raise RuntimeError(
                f"Missing {', '.join(missing)}. Install FFmpeg first (on macOS: brew install ffmpeg)."
            )


def optimize_image(path: Path) -> None:
    try:
        from PIL import Image
    except ImportError as error:
        raise RuntimeError(
            "Pillow is required. Install the project dependencies with: "
            "python3 -m pip install -r requirements.txt"
        ) from error

    from generate_site import optimize_full_photo, strip_exif_from_file

    optimize_full_photo(str(path), max_dim=IMAGE_DIMENSION_LIMIT, quality=85)
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        strip_exif_from_file(str(path))

    with Image.open(path) as image:
        largest_dimension = max(image.size)
    if largest_dimension > IMAGE_DIMENSION_LIMIT or path.stat().st_size > IMAGE_SIZE_LIMIT:
        raise RuntimeError(
            f"{path} remains too large after optimization "
            f"({largest_dimension}px, {path.stat().st_size / 1024 / 1024:.1f} MB). "
            "Export it as a JPEG or WebP and stage it again."
        )


def optimize_video(path: Path) -> None:
    from generate_site import is_video_optimized, optimize_video_if_needed

    optimize_video_if_needed(str(path))
    if path.stat().st_size > VIDEO_OPTIMIZE_THRESHOLD and not is_video_optimized(str(path)):
        raise RuntimeError(f"{path} could not be optimized. Check the FFmpeg output and stage it again.")


def main() -> int:
    media = [
        path
        for path in staged_paths()
        if is_project_media(path)
        and (REPO_ROOT / path).is_file()
        and not (REPO_ROOT / path).is_symlink()
    ]
    if not media:
        return 0

    require_tools(media)
    changed: list[Path] = []
    print(f"Checking {len(media)} staged media file(s) for web-safe size and metadata...")
    try:
        for relative in media:
            absolute = REPO_ROOT / relative
            before = sha256(absolute)
            if relative.suffix.lower() in IMAGE_EXTENSIONS:
                optimize_image(absolute)
            else:
                optimize_video(absolute)
            if sha256(absolute) != before:
                changed.append(relative)
    except RuntimeError as error:
        print(f"Media optimization failed: {error}", file=sys.stderr)
        return 1

    # Always refresh the index from the validated working-tree versions. This also
    # recovers cleanly if an earlier hook run optimized one file before another
    # staged file failed validation.
    subprocess.run(["git", "add", "--", *map(str, media)], cwd=REPO_ROOT, check=True)
    if changed:
        print(f"Optimized and re-staged {len(changed)} media file(s).")
    else:
        print("Staged media already meets the web limits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
