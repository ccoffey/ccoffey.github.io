#!/usr/bin/env python3
"""Extract inline JavaScript from HTML templates for ESLint."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPO_ROOT / "src", "templates"
OUTPUT_DIR = REPO_ROOT / ".lint-tmp"
INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
TEMPLATE_EXPRESSION = re.compile(r"{{.*?}}", re.DOTALL)


def main():
    shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
    OUTPUT_DIR.mkdir()

    for template in sorted(TEMPLATE_DIR.glob("*.html")):
        content = template.read_text(encoding="utf-8")
        for index, script in enumerate(INLINE_SCRIPT.findall(content), start=1):
            # Template values are either already inside a JavaScript string or
            # stand in for a value/expression. An identifier keeps both forms
            # syntactically valid for static analysis.
            normalized = TEMPLATE_EXPRESSION.sub("TEMPLATE_VALUE", script)
            output = OUTPUT_DIR / f"{template.stem}-{index}.js"
            output.write_text(normalized, encoding="utf-8")


if __name__ == "__main__":
    main()
