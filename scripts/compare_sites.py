#!/usr/bin/env python3
"""Compare a generated site directory with the public files in a Git revision."""

import argparse
import difflib
from pathlib import Path
import re
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ONLY_PREFIXES = (".github/", ".vscode/", "scripts/", "templates/")
SOURCE_ONLY_FILES = {".gitignore", "dev_server.py", "generate_site.py", "requirements.txt", "test_site.py"}


def git(*args, text=True):
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=text,
    ).stdout


def is_public(path):
    if path in SOURCE_ONLY_FILES or path.startswith(SOURCE_ONLY_PREFIXES):
        return False
    if path.endswith(("/build.json", "/project.json", ".optimized.mp4", ".pyc", ".DS_Store")):
        return False
    return True


def baseline_files(revision):
    output = git("ls-tree", "-r", "--format=%(objectname) %(path)", revision)
    result = {}
    for line in output.splitlines():
        object_name, path = line.split(" ", 1)
        if is_public(path):
            result[path] = object_name
    return result


def candidate_files(root):
    return {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file() and is_public(path.relative_to(root).as_posix())
    }


def normalized_html(content):
    text = content.decode("utf-8")
    return re.sub(r"([?&]v=)[^\"'&<\s]+", r"\1BUILD_ID", text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default="HEAD", help="Git revision representing the deployed site")
    parser.add_argument("--candidate", default="_site", help="Generated site directory")
    args = parser.parse_args()

    candidate_root = Path(args.candidate).resolve()
    if not candidate_root.is_dir():
        raise SystemExit(f"Candidate directory does not exist: {candidate_root}")

    baseline = baseline_files(args.baseline_ref)
    candidate = candidate_files(candidate_root)
    missing = sorted(set(baseline) - set(candidate))
    unexpected = sorted(set(candidate) - set(baseline))
    changed = []
    html_diffs = []

    for path in sorted(set(baseline) & set(candidate)):
        candidate_path = candidate[path]
        if path.endswith(".html"):
            baseline_content = git("show", f"{args.baseline_ref}:{path}", text=False)
            candidate_content = candidate_path.read_bytes()
            baseline_html = normalized_html(baseline_content)
            candidate_html = normalized_html(candidate_content)
            if baseline_html != candidate_html:
                changed.append(path)
                if len(html_diffs) < 3:
                    diff = difflib.unified_diff(
                        baseline_html.splitlines(),
                        candidate_html.splitlines(),
                        fromfile=f"{args.baseline_ref}:{path}",
                        tofile=f"candidate:{path}",
                        lineterm="",
                        n=2,
                    )
                    html_diffs.append("\n".join(list(diff)[:80]))
        else:
            candidate_hash = git("hash-object", "--no-filters", str(candidate_path)).strip()
            if candidate_hash != baseline[path]:
                changed.append(path)

    if missing or unexpected or changed:
        print("Site comparison failed.")
        if missing:
            print(f"\nMissing from candidate ({len(missing)}):")
            print("\n".join(f"  {path}" for path in missing[:50]))
        if unexpected:
            print(f"\nUnexpected candidate files ({len(unexpected)}):")
            print("\n".join(f"  {path}" for path in unexpected[:50]))
        if changed:
            print(f"\nChanged files ({len(changed)}):")
            print("\n".join(f"  {path}" for path in changed[:50]))
        for diff in html_diffs:
            print(f"\n{diff}")
        return 1

    total_bytes = sum(path.stat().st_size for path in candidate.values())
    print(
        f"Site comparison passed: {len(candidate)} public files, "
        f"{total_bytes / 1024 / 1024:.1f} MiB, no unexpected differences."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
