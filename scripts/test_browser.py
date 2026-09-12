#!/usr/bin/env python3
"""Run browser-level regression checks against an already-built static site.

Usage:
  SITE_ROOT=_site python3 scripts/test_browser.py

The script starts a private local server for the generated output, then uses
headless Chromium to exercise the gallery and responsive navigation as a user
would. It is intended for CI as well as local verification.
"""

from __future__ import annotations

import functools
import os
import shutil
import sys
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageChops

try:
    from playwright.sync_api import Browser, Page, sync_playwright
except ImportError as error:  # pragma: no cover - makes missing setup actionable
    raise SystemExit(
        "Playwright is required. Install requirements-test.txt, then run "
        "python -m playwright install chromium."
    ) from error


REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_ROOT = Path(os.environ.get("SITE_ROOT", REPO_ROOT / "_site")).resolve()
PROJECT_PATH = "/major-builds/claw-machine/"
QUICK_PROJECT_PATH = "/quick-builds/wall-vent-covers/"
VISUAL_BASELINE_DIR = REPO_ROOT / "tests" / "visual-baselines"
VISUAL_ARTIFACT_DIR = Path(os.environ.get("VISUAL_ARTIFACT_DIR", REPO_ROOT / "test-results" / "visual"))
UPDATE_VISUAL_BASELINES = "--update-snapshots" in sys.argv
MAX_DIFFERING_PIXEL_RATIO = float(os.environ.get("VISUAL_MAX_DIFFERING_PIXEL_RATIO", "0.08"))

if UPDATE_VISUAL_BASELINES:
    sys.argv.remove("--update-snapshots")


class QuietRequestHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format, *_args):
        pass

    def copyfile(self, source, outputfile):
        try:
            super().copyfile(source, outputfile)
        except (BrokenPipeError, ConnectionResetError):
            # Browsers routinely abandon speculative media requests. That is
            # expected and should not make a successful test look like a crash.
            pass


class TestHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


class BrowserRegressionTests(unittest.TestCase):
    """High-value user journeys covering generated pages and gallery controls."""

    @classmethod
    def setUpClass(cls):
        if not (SITE_ROOT / "index.html").is_file():
            raise RuntimeError(f"Built site not found at {SITE_ROOT}")

        handler = functools.partial(QuietRequestHandler, directory=str(SITE_ROOT))
        cls.server = TestHTTPServer(("127.0.0.1", 0), handler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

        cls.playwright = sync_playwright().start()
        cls.browser: Browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=5)

    def new_page(self, *, mobile=False, block_media=True) -> Page:
        if mobile:
            context = self.browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
        else:
            context = self.browser.new_context(viewport={"width": 1440, "height": 960})
        # The interactions under test do not depend on transferring hundreds of
        # megabytes of source media. Blocking it keeps CI deterministic while
        # still loading the generated HTML, CSS, and JavaScript exactly as users
        # receive them.
        if block_media:
            context.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in {"image", "media"}
                and not route.request.url.endswith("/favicon.ico")
                else route.continue_(),
            )
        self.addCleanup(context.close)
        page = context.new_page()
        page.on("pageerror", lambda error: self.fail(f"Unhandled browser error: {error}"))
        return page

    def open_commented_lightbox(self, *, mobile=False, block_media=True) -> Page:
        page = self.new_page(mobile=mobile, block_media=block_media)
        page.goto(self.base_url + PROJECT_PATH, wait_until="commit")
        page.locator(".photo-card").first.wait_for()
        filename = page.evaluate("""() => {
            const item = gallery.find((entry) => entry.comments && entry.comments.length);
            return item && item.filename;
        }""")
        self.assertTrue(filename, "Expected a gallery item with comments")
        page.goto(f"{self.base_url}{PROJECT_PATH}#{quote(filename)}", wait_until="commit")
        page.locator("#lightbox.active").wait_for()
        if not block_media:
            page.wait_for_function(
                """() => {
                    const image = document.getElementById('lightbox-img');
                    const item = gallery[currentIndex];
                    return image.naturalWidth > 0
                        && image.src.endsWith(item.full)
                        && !image.classList.contains('is-loading');
                }""",
                timeout=10_000,
            )
        return page

    def assert_visual_snapshot(self, page: Page, name: str):
        """Compare a stable viewport capture to its checked-in visual baseline."""
        page.emulate_media(reduced_motion="reduce")
        page.add_style_tag(content="* { animation: none !important; transition: none !important; }")
        page.evaluate("document.fonts.ready")

        baseline = VISUAL_BASELINE_DIR / f"{name}.png"
        VISUAL_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        actual = VISUAL_ARTIFACT_DIR / f"{name}-actual.png"
        page.screenshot(path=str(actual), animations="disabled")

        if UPDATE_VISUAL_BASELINES:
            VISUAL_BASELINE_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(actual, baseline)
            return

        self.assertTrue(
            baseline.is_file(),
            f"Missing visual baseline: {baseline}. Run scripts/test_browser.py --update-snapshots.",
        )
        with Image.open(baseline).convert("RGB") as expected, Image.open(actual).convert("RGB") as received:
            self.assertEqual(expected.size, received.size, f"Screenshot size changed for {name}")
            delta = ImageChops.difference(expected, received)
            changed = sum(1 for pixel in delta.get_flattened_data() if max(pixel) > 16)
            ratio = changed / (expected.width * expected.height)

        if ratio > MAX_DIFFERING_PIXEL_RATIO:
            diff = VISUAL_ARTIFACT_DIR / f"{name}-diff.png"
            delta.save(diff)
            self.fail(
                f"Visual regression in {name}: {ratio:.2%} of pixels differ "
                f"(limit {MAX_DIFFERING_PIXEL_RATIO:.2%}). See {diff}."
            )

    def test_primary_pages_render_without_browser_errors(self):
        page = self.new_page()
        for path in ("/", PROJECT_PATH, QUICK_PROJECT_PATH):
            response = page.goto(self.base_url + path, wait_until="commit")
            self.assertIsNotNone(response)
            self.assertEqual(response.status, 200)
            page.locator("body").wait_for()
            self.assertTrue(page.title().strip())
            self.assertGreater(page.locator(".top-nav").count(), 0)

    def test_gallery_open_navigate_and_close_updates_history(self):
        page = self.new_page()
        page.goto(self.base_url + PROJECT_PATH, wait_until="commit")
        page.locator(".photo-card").first.wait_for()

        cards = page.locator(".photo-card")
        self.assertGreater(cards.count(), 2)
        cards.nth(0).click()
        lightbox = page.locator("#lightbox")
        self.assertEqual(lightbox.get_attribute("aria-hidden"), "false")
        first_hash = page.evaluate("window.location.hash")
        self.assertTrue(first_hash.startswith("#"))

        page.get_by_role("button", name="Next").click()
        self.assertNotEqual(page.evaluate("window.location.hash"), first_hash)
        self.assertEqual(lightbox.get_attribute("aria-hidden"), "false")

        page.keyboard.press("Escape")
        self.assertEqual(lightbox.get_attribute("aria-hidden"), "true")
        self.assertEqual(page.evaluate("window.location.hash"), "")

    def test_comment_deep_link_groups_messages_and_can_be_hidden(self):
        page = self.open_commented_lightbox()
        self.assertEqual(page.locator("#lightbox").get_attribute("aria-hidden"), "false")
        expected_count = page.evaluate("gallery[currentIndex].comments.length")
        self.assertEqual(page.locator(".lightbox-comment-avatar").count(), 1)
        self.assertEqual(page.locator(".lightbox-comment-text").count(), expected_count)

        comments = page.locator("#lightbox-description")
        toggle = page.get_by_role("button", name="Hide comments")
        self.assertFalse(comments.is_hidden())
        toggle.click()
        self.assertTrue(comments.is_hidden())
        self.assertEqual(page.locator("#lightboxCommentsBtn").get_attribute("aria-pressed"), "false")
        page.get_by_role("button", name="Show comments").click()
        self.assertFalse(comments.is_hidden())

    def test_back_closes_lightbox_and_forward_restores_it(self):
        page = self.new_page()
        page.goto(self.base_url + PROJECT_PATH, wait_until="commit")
        page.locator(".photo-card").first.wait_for()
        page.locator(".photo-card").nth(0).click()
        first_hash = page.evaluate("window.location.hash")
        page.get_by_role("button", name="Next").click()
        second_hash = page.evaluate("window.location.hash")

        page.go_back(wait_until="commit")
        self.assertNotEqual(second_hash, first_hash)
        self.assertEqual(page.evaluate("window.location.hash"), "")
        self.assertEqual(page.locator("#lightbox").get_attribute("aria-hidden"), "true")
        page.go_forward(wait_until="commit")
        self.assertEqual(page.evaluate("window.location.hash"), second_hash)
        self.assertEqual(page.locator("#lightbox").get_attribute("aria-hidden"), "false")

    def test_mobile_menu_opens_dropdown_and_escape_closes_it(self):
        page = self.new_page(mobile=True)
        page.goto(self.base_url + PROJECT_PATH, wait_until="commit")
        page.locator(".nav-menu-toggle").wait_for()
        menu = page.locator(".nav-menu-toggle")
        menu.click()
        self.assertEqual(menu.get_attribute("aria-expanded"), "true")
        self.assertTrue(page.locator("#site-navigation").evaluate("node => node.classList.contains('is-open')"))

        major_menu = page.locator("#navMajorDropdown .nav-dropdown-trigger")
        major_menu.click()
        self.assertEqual(major_menu.get_attribute("aria-expanded"), "true")
        page.keyboard.press("Escape")
        self.assertEqual(menu.get_attribute("aria-expanded"), "false")

    def test_visual_home_desktop(self):
        page = self.new_page(block_media=False)
        page.goto(self.base_url + "/", wait_until="commit")
        page.locator(".hero").wait_for()
        page.wait_for_function(
            "document.querySelector('.major-build-card img').naturalWidth > 0",
            timeout=10_000,
        )
        self.assert_visual_snapshot(page, "home-desktop")

    def test_visual_home_mobile(self):
        page = self.new_page(mobile=True, block_media=False)
        page.goto(self.base_url + "/", wait_until="commit")
        page.locator(".hero").wait_for()
        self.assert_visual_snapshot(page, "home-mobile")

    def test_visual_gallery_desktop(self):
        page = self.new_page(block_media=False)
        page.goto(self.base_url + PROJECT_PATH, wait_until="commit")
        gallery_header = page.locator(".gallery-header")
        gallery_header.scroll_into_view_if_needed()
        page.wait_for_function(
            "document.querySelector('.photo-grid img').naturalWidth > 0",
            timeout=10_000,
        )
        self.assert_visual_snapshot(page, "gallery-desktop")


if __name__ == "__main__":
    unittest.main(verbosity=2)
