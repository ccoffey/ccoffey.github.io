#!/usr/bin/env python3
"""Build an isolated, deployable copy of the static site."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


SOURCE_ROOT = Path(__file__).resolve().parent.parent
GENERATED_ROOT_FILES = ("index.html", "robots.txt", "sitemap.xml")


def default_build_id():
    configured = os.environ.get("BUILD_ID")
    if configured:
        return configured
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=SOURCE_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "local"


def default_site_lastmod():
    configured = os.environ.get("SITE_LASTMOD")
    if configured:
        return configured
    try:
        return subprocess.run(
            ["git", "show", "-s", "--format=%cs", "HEAD"],
            cwd=SOURCE_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "1970-01-01"


def safe_output_path(value):
    output = Path(value)
    if not output.is_absolute():
        output = SOURCE_ROOT / output
    output = output.resolve()
    if output in {Path("/"), SOURCE_ROOT, SOURCE_ROOT.parent} or len(output.parts) < 3:
        raise ValueError(f"Refusing unsafe output directory: {output}")
    return output


MEDIA_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.mp4', '.mov', '.webm'}


def copy_source_tree(output, incremental=False):
    ignored_names = {".git", "_site", "__pycache__", ".DS_Store"}

    def ignore(_directory, names):
        return [name for name in names if name in ignored_names or name.endswith(".pyc")]

    if output.exists() and not incremental:
        shutil.rmtree(output)
    if not incremental:
        shutil.copytree(SOURCE_ROOT, output, ignore=ignore)
        return

    # A metadata/template/CSS edit does not need to recopy hundreds of MiB of
    # media.  The existing isolated output already contains the source media
    # and its generated thumbnails/posters, so sync just the non-media inputs.
    for source in SOURCE_ROOT.rglob('*'):
        relative = source.relative_to(SOURCE_ROOT)
        if any(part in ignored_names for part in relative.parts) or source.is_dir():
            continue
        if source.suffix.lower() in MEDIA_EXTENSIONS or source.name.endswith('.pyc'):
            continue
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def remove_generated_output(output, preserve_media_derivatives=False):
    """Ensure the candidate is recreated from source rather than copied artifacts."""
    for relative in GENERATED_ROOT_FILES:
        target = output / relative
        if target.exists():
            target.unlink()

    for build_root in (output / "major-builds", output / "quick-builds"):
        if not build_root.is_dir():
            continue
        for target in build_root.glob("*/index.html"):
            target.unlink()
        if not preserve_media_derivatives:
            for target in build_root.glob("*/thumbs"):
                if target.is_dir():
                    shutil.rmtree(target)


def remove_build_sources(output):
    for relative in (
        ".github",
        ".githooks",
        ".gitignore",
        ".vscode",
        "README.md",
        "dev_server.py",
        "generate_site.py",
        "requirements.txt",
        "scripts",
        "templates",
        "test_site.py",
    ):
        target = output / relative
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    for pattern in ("build.json", "project.json", "*.optimized.mp4", ".DS_Store", "*.pyc"):
        for target in output.rglob(pattern):
            if target.is_file():
                target.unlink()


def validate_output(output):
    required = [
        output / "index.html",
        output / "css" / "style.css",
        output / "js" / "navigation.js",
        output / ".nojekyll",
    ]
    missing = [str(path.relative_to(output)) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Build output is missing required files: {', '.join(missing)}")

    links = [path for path in output.rglob("*") if path.is_symlink()]
    if links:
        rendered = ", ".join(str(path.relative_to(output)) for path in links)
        raise RuntimeError(f"Build output contains unsupported symbolic links: {rendered}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="_site", help="Destination directory")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Reuse existing copied media and generated derivatives (for local metadata/template edits).",
    )
    parser.add_argument("--build-id", default=default_build_id(), help="Cache-busting build identifier")
    parser.add_argument(
        "--site-lastmod",
        default=default_site_lastmod(),
        help="Deterministic YYYY-MM-DD value written to sitemap.xml",
    )
    args = parser.parse_args()

    output = safe_output_path(args.output)
    if args.incremental and not output.exists():
        args.incremental = False
    copy_source_tree(output, incremental=args.incremental)
    remove_generated_output(output, preserve_media_derivatives=args.incremental)

    env = os.environ.copy()
    env["BUILD_ID"] = args.build_id
    env["SITE_LASTMOD"] = args.site_lastmod
    subprocess.run([sys.executable, "generate_site.py"], cwd=output, env=env, check=True)
    subprocess.run([sys.executable, "test_site.py", "-v"], cwd=output, env=env, check=True)

    remove_build_sources(output)
    validate_output(output)

    files = [path for path in output.rglob("*") if path.is_file()]
    total_bytes = sum(path.stat().st_size for path in files)
    print(f"Built {len(files)} files in {output} ({total_bytes / 1024 / 1024:.1f} MiB)")


if __name__ == "__main__":
    main()
