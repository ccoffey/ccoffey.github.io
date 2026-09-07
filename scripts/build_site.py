#!/usr/bin/env python3
"""Build an isolated, deployable copy of the static site."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


SOURCE_ROOT = Path(__file__).resolve().parent.parent


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


def safe_output_path(value):
    output = Path(value)
    if not output.is_absolute():
        output = SOURCE_ROOT / output
    output = output.resolve()
    if output in {Path("/"), SOURCE_ROOT, SOURCE_ROOT.parent} or len(output.parts) < 3:
        raise ValueError(f"Refusing unsafe output directory: {output}")
    return output


def copy_source_tree(output):
    ignored_names = {".git", "_site", "__pycache__", ".DS_Store"}

    def ignore(_directory, names):
        return [name for name in names if name in ignored_names or name.endswith(".pyc")]

    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(SOURCE_ROOT, output, ignore=ignore)


def remove_build_sources(output):
    for relative in (
        ".github",
        ".gitignore",
        ".vscode",
        "dev_server.py",
        "generate_site.py",
        "requirements.txt",
        "scripts",
        "templates",
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
        output / "CNAME",
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
    parser.add_argument("--build-id", default=default_build_id(), help="Cache-busting build identifier")
    args = parser.parse_args()

    output = safe_output_path(args.output)
    copy_source_tree(output)

    env = os.environ.copy()
    env["BUILD_ID"] = args.build_id
    subprocess.run([sys.executable, "generate_site.py"], cwd=output, env=env, check=True)

    remove_build_sources(output)
    validate_output(output)

    files = [path for path in output.rglob("*") if path.is_file()]
    total_bytes = sum(path.stat().st_size for path in files)
    print(f"Built {len(files)} files in {output} ({total_bytes / 1024 / 1024:.1f} MiB)")


if __name__ == "__main__":
    main()
