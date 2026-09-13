#!/usr/bin/env python3
"""Check deterministic, Lighthouse-style budgets for a built site.

The check measures the resources every visitor needs before interacting with a
page: its document, CSS, JavaScript, and any assets loaded eagerly. Gallery
thumbnails are deliberately lazy-loaded and have separate per-file budgets in
``tests/test_site.py``.

Usage:
  python3 scripts/check_performance.py [SITE_ROOT]
"""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SITE_ROOT = REPO_ROOT / "_site"

# These values are intentionally small enough to catch accidental bloat while
# leaving room for the current generated gallery data. Changing one requires a
# conscious review and an explanation in the commit.
MAX_HTML_BYTES = 128 * 1024
MAX_CSS_BYTES = 50 * 1024
MAX_JAVASCRIPT_BYTES = 20 * 1024
MAX_EAGER_PAGE_BYTES = 160 * 1024


class InitialLoadParser(HTMLParser):
    """Collect local resources that a browser loads without scrolling."""

    def __init__(self):
        super().__init__()
        self.eager_paths: set[str] = set()
        self.non_lazy_thumbnails: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        attributes = dict(attrs)
        candidate = ""

        if tag == "link" and "stylesheet" in attributes.get("rel", ""):
            candidate = attributes.get("href", "")
        elif tag == "script":
            candidate = attributes.get("src", "")
        elif tag == "img":
            candidate = attributes.get("src", "")
            if "/thumbs/" in candidate and attributes.get("loading") != "lazy":
                self.non_lazy_thumbnails.append(candidate)

            if attributes.get("loading") == "lazy":
                return

        if candidate.startswith("/"):
            self.eager_paths.add(urlsplit(candidate).path)


def generated_pages(site_root: Path) -> list[Path]:
    """Return public HTML documents, excluding copied source templates."""
    pages = [site_root / "index.html"]
    for build_type in ("major-builds", "quick-builds"):
        pages.extend((site_root / build_type).glob("*/index.html"))
    return sorted(pages)


def format_bytes(size: int) -> str:
    return f"{size / 1024:.1f} KiB"


def check_site(site_root: Path) -> list[str]:
    """Return actionable budget violations for ``site_root``."""
    errors: list[str] = []
    pages = generated_pages(site_root)
    if not pages:
        return [f"No generated pages found in {site_root}"]

    css_bytes = sum(path.stat().st_size for path in (site_root / "css").glob("**/*.css"))
    javascript_bytes = sum(path.stat().st_size for path in (site_root / "js").glob("**/*.js"))
    if css_bytes > MAX_CSS_BYTES:
        errors.append(f"CSS is {format_bytes(css_bytes)}; budget is {format_bytes(MAX_CSS_BYTES)}")
    if javascript_bytes > MAX_JAVASCRIPT_BYTES:
        errors.append(
            f"JavaScript is {format_bytes(javascript_bytes)}; budget is {format_bytes(MAX_JAVASCRIPT_BYTES)}"
        )

    for page in pages:
        relative_page = page.relative_to(site_root)
        page_bytes = page.stat().st_size
        if page_bytes > MAX_HTML_BYTES:
            errors.append(
                f"{relative_page} is {format_bytes(page_bytes)}; HTML budget is {format_bytes(MAX_HTML_BYTES)}"
            )

        parser = InitialLoadParser()
        parser.feed(page.read_text(encoding="utf-8"))
        parser.close()
        eager_bytes = page_bytes
        missing_assets = []
        for asset_path in parser.eager_paths:
            asset = site_root / asset_path.lstrip("/")
            if asset.is_file():
                eager_bytes += asset.stat().st_size
            else:
                missing_assets.append(asset_path)
        if missing_assets:
            errors.append(f"{relative_page} references missing eager assets: {', '.join(sorted(missing_assets))}")
        if eager_bytes > MAX_EAGER_PAGE_BYTES:
            errors.append(
                f"{relative_page} initial page shell is {format_bytes(eager_bytes)}; "
                f"budget is {format_bytes(MAX_EAGER_PAGE_BYTES)}"
            )
        if parser.non_lazy_thumbnails:
            errors.append(
                f"{relative_page} eagerly loads gallery thumbnails: {', '.join(parser.non_lazy_thumbnails)}"
            )

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site_root", nargs="?", default=DEFAULT_SITE_ROOT, type=Path)
    args = parser.parse_args()
    site_root = args.site_root.resolve()

    errors = check_site(site_root)
    if errors:
        joined = "\n".join(f"- {error}" for error in errors)
        raise SystemExit(
            "Performance budget check failed. Optimize the generated output, or deliberately "
            f"review and update the budget.\n{joined}"
        )

    print(
        "Performance budgets passed: "
        f"HTML <= {format_bytes(MAX_HTML_BYTES)}, CSS <= {format_bytes(MAX_CSS_BYTES)}, "
        f"JavaScript <= {format_bytes(MAX_JAVASCRIPT_BYTES)}, "
        f"initial page shell <= {format_bytes(MAX_EAGER_PAGE_BYTES)}."
    )


if __name__ == "__main__":
    main()
