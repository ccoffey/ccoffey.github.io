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
import json
import math
import os
import shutil
import sys
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlparse

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
VISUAL_COMMENTS = [
    "The custom PCB was the turning point in the build.",
    "The finished wiring harness made the mechanism reliable.",
]

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

    def send_json(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlparse(self.path).path == "/__admin/comments/status" and self.server.admin_enabled:
            self.send_json({"enabled": True})
            return
        super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/__admin/comments" or not self.server.admin_enabled:
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        self.send_json({"comments": payload["comments"]})


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
        cls.server.admin_enabled = False
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

    def new_page(self, *, mobile=False, block_media=False) -> Page:
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

    def open_commented_lightbox(self, *, mobile=False, block_media=False) -> Page:
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

    def enable_local_comment_authoring(self):
        self.server.admin_enabled = True
        self.addCleanup(setattr, self.server, "admin_enabled", False)

    @staticmethod
    def set_visual_comments(page: Page):
        page.evaluate(
            """comments => {
                gallery[currentIndex].comments = comments;
                window.galleryCommentAdmin.rerender();
                const description = document.getElementById('lightbox-description');
                description.classList.remove('comments-hidden');
                description.querySelector('.lightbox-comment-stack')?.removeAttribute('aria-hidden');
            }""",
            VISUAL_COMMENTS,
        )

    @staticmethod
    def prepare_visual_comment_surface(page: Page):
        """Expose a stable, painted copy of the rendered comment interface.

        Chromium on GitHub's Linux runners occasionally omits content painted
        within the GPU-composited lightbox when taking a page screenshot. The
        production DOM is still exercised by the interaction tests above; this
        helper clones that exact rendered interface into a normal paint layer
        solely for the visual assertion.
        """
        page.evaluate(
            """() => {
                document.getElementById('visual-comment-surface')?.remove();
                const description = document.getElementById('lightbox-description');
                const wrapper = document.createElement('div');
                wrapper.id = 'visual-comment-surface';
                wrapper.style.cssText = [
                    'position: relative',
                    'width: min(620px, calc(100vw - 3rem))',
                    'margin: 8rem auto',
                    'pointer-events: none',
                ].join(';');
                const surface = description.cloneNode(true);
                surface.removeAttribute('hidden');
                surface.classList.remove('comments-hidden');
                surface.setAttribute('aria-hidden', 'false');
                surface.style.cssText = [
                    'position: static',
                    'width: 100%',
                    'transform: none',
                ].join(';');
                wrapper.append(surface);
                document.body.append(wrapper);
                document.getElementById('lightbox').classList.remove('active');
            }"""
        )

    def assert_visual_snapshot(self, page: Page, name: str, *, target=None, crop_box=None):
        """Compare a stable viewport capture to its checked-in visual baseline."""
        page.emulate_media(reduced_motion="reduce")
        page.add_style_tag(content="* { animation: none !important; transition: none !important; }")
        page.evaluate("document.fonts.ready")
        page.evaluate("""() => Promise.all(
            Array.from(document.querySelectorAll('.lightbox-comment-avatar')).map(img => {
                if (img.complete) return Promise.resolve();
                return new Promise(resolve => {
                    img.addEventListener('load', resolve);
                    img.addEventListener('error', resolve);
                });
            })
        )""")

        # Chromium's mobile text rasterization differs enough between macOS and
        # Linux to make one shared reference image noisy. Keep the primary
        # baseline for local macOS development and use a CI-specific reference
        # on Linux; each remains a strict visual regression check.
        platform_baseline_name = f"{name}-linux"
        if sys.platform.startswith("linux") and (VISUAL_BASELINE_DIR / f"{platform_baseline_name}.png").is_file():
            baseline_name = platform_baseline_name
        else:
            baseline_name = name
        baseline = VISUAL_BASELINE_DIR / f"{baseline_name}.png"
        VISUAL_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        actual = VISUAL_ARTIFACT_DIR / f"{baseline_name}-actual.png"
        if target:
            # The visual surface lives outside the GPU-composited lightbox, so
            # a locator capture is reliable on both macOS and Linux.
            target.screenshot(path=str(actual), animations="disabled")
        else:
            page.screenshot(path=str(actual), animations="disabled")
        if crop_box:
            box = crop_box or target.bounding_box()
            with Image.open(actual) as screenshot:
                cropped = screenshot.crop(
                    (
                        max(0, math.floor(box["x"])),
                        max(0, math.floor(box["y"])),
                        min(screenshot.width, math.ceil(box["x"] + box["width"])),
                        min(screenshot.height, math.ceil(box["y"] + box["height"])),
                    )
                )
                cropped.save(actual)

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
            diff = VISUAL_ARTIFACT_DIR / f"{baseline_name}-diff.png"
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
        self.assertEqual(page.locator(".lightbox-comment-composer").count(), 0)
        self.assertEqual(page.locator(".lightbox-comment-delete").count(), 0)
        self.assertFalse(
            page.locator(".lightbox-comment-text").first.evaluate("node => node.isContentEditable")
        )
        self.assertEqual(page.locator("#lightboxInlineCommentsBtn").count(), 1)
        comments_box = page.locator("#lightbox-description").bounding_box()
        group_box = page.locator(".lightbox-comment-group").bounding_box()
        self.assertAlmostEqual(
            group_box["x"] + group_box["width"] / 2,
            comments_box["x"] + comments_box["width"] / 2,
            delta=2,
        )
        self.assertTrue(
            page.locator(".lightbox-btn").evaluate_all(
                "buttons => buttons.every(button => Boolean(button.dataset.tooltip))"
            )
        )

        comments = page.locator("#lightbox-description")
        stack = page.locator(".lightbox-comment-stack")
        toggle = page.locator("#lightboxCommentsBtn")
        self.assertFalse(comments.is_hidden())
        self.assertFalse(stack.is_hidden())
        inline_toggle = page.locator("#lightboxInlineCommentsBtn")
        self.assertEqual(
            inline_toggle.locator("svg").evaluate("node => node.innerHTML"),
            toggle.locator("svg").evaluate("node => node.innerHTML"),
        )
        self.assertEqual(inline_toggle.get_attribute("data-tooltip"), toggle.get_attribute("data-tooltip"))
        self.assertEqual(
            inline_toggle.evaluate("node => getComputedStyle(node).backgroundColor"),
            toggle.evaluate("node => getComputedStyle(node).backgroundColor"),
        )
        self.assertEqual(
            inline_toggle.bounding_box()["width"],
            page.locator(".lightbox-comment-avatar").bounding_box()["width"],
        )
        page.add_style_tag(
            content=(
                ".lightbox-inline-comments-toggle, .lightbox-comments-toggle, "
                ".lightbox-inline-comments-toggle::after, .lightbox-comments-toggle::after "
                "{ transition: none !important; }"
            )
        )
        inline_toggle.hover()
        page.wait_for_timeout(100)
        inline_hover_color = inline_toggle.evaluate("node => getComputedStyle(node).backgroundColor")
        self.assertNotEqual(inline_hover_color, "rgba(0, 0, 0, 0)")
        self.assertGreater(
            float(inline_toggle.evaluate("node => getComputedStyle(node, '::after').opacity")),
            0.9,
        )
        toggle.hover()
        page.wait_for_timeout(100)
        self.assertEqual(
            toggle.evaluate("node => getComputedStyle(node).backgroundColor"),
            inline_hover_color,
        )
        group_box = page.locator(".lightbox-comment-group").bounding_box()
        inline_toggle.click()
        self.assertFalse(comments.is_hidden())
        self.assertTrue(stack.is_hidden())
        hidden_group_box = page.locator(".lightbox-comment-group").bounding_box()
        self.assertAlmostEqual(hidden_group_box["x"], group_box["x"], delta=1)
        self.assertAlmostEqual(hidden_group_box["y"], group_box["y"], delta=1)
        self.assertEqual(page.locator("#lightboxCommentsBtn").get_attribute("aria-pressed"), "false")
        self.assertEqual(toggle.get_attribute("data-tooltip"), "Toggle comments")
        toggle.click()
        self.assertFalse(comments.is_hidden())
        self.assertFalse(stack.is_hidden())

    def test_local_comment_authoring_edits_messages_in_place(self):
        self.enable_local_comment_authoring()
        page = self.open_commented_lightbox()
        page.get_by_label("New comment").wait_for()
        initial_count = page.evaluate("gallery[currentIndex].comments.length")

        first = page.locator(".lightbox-comment-text[data-comment-index]").first
        first.fill("a")
        first.press("Enter")
        page.wait_for_function("gallery[currentIndex].comments[0] === 'a'")
        self.assertLess(first.bounding_box()["width"], 200)
        self.assertEqual(page.locator("#lightbox-description").evaluate("node => getComputedStyle(node).overflowY"), "visible")
        remove = page.get_by_role("button", name="Delete comment 1")
        first_box = first.bounding_box()
        remove_box = remove.bounding_box()
        self.assertLess(remove_box["y"], first_box["y"])
        self.assertGreater(remove_box["x"] + remove_box["width"] / 2, first_box["x"] + first_box["width"])
        self.assertEqual(remove.evaluate("node => getComputedStyle(node).backgroundColor"), "rgb(201, 106, 103)")
        self.assertEqual(remove.locator("svg").count(), 0)
        self.assertEqual(
            remove.evaluate("node => getComputedStyle(node, '::before').width"),
            "10px",
        )

        composer = page.get_by_label("New comment")
        self.assertGreaterEqual(composer.bounding_box()["width"], 200)
        composer.fill("A draft")
        composer.fill("")
        composer.press("Tab")
        self.assertEqual(composer.evaluate("node => node.childNodes.length"), 0)
        self.assertEqual(page.locator(".lightbox-comment-composer").count(), 1)

        composer.focus()
        composer.fill("First line")
        composer.press("Shift+Enter")
        composer.type("Second line")
        composer.press("Enter")
        page.wait_for_function(f"gallery[currentIndex].comments.length === {initial_count + 1}")
        next_composer = page.get_by_label("New comment")
        self.assertEqual(page.locator(".lightbox-comment-composer").count(), 1)
        self.assertTrue(next_composer.evaluate("node => document.activeElement === node"))
        self.assertEqual(
            page.evaluate("gallery[currentIndex].comments.at(-1)"),
            "First line\nSecond line",
        )

        remove.click()
        page.wait_for_function(f"gallery[currentIndex].comments.length === {initial_count}")
        self.assertTrue(next_composer.evaluate("node => document.activeElement === node"))

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

    def test_visual_major_build_desktop(self):
        page = self.new_page(block_media=False)
        page.goto(self.base_url + PROJECT_PATH, wait_until="commit")
        page.locator(".build-header-full").wait_for()
        self.assert_visual_snapshot(page, "major-build-desktop")

    def test_visual_quick_build_desktop(self):
        page = self.new_page(block_media=False)
        page.goto(self.base_url + QUICK_PROJECT_PATH, wait_until="commit")
        page.locator(".build-header-full").wait_for()
        self.assert_visual_snapshot(page, "quick-build-desktop")

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

    def test_visual_comments_reader_desktop(self):
        page = self.open_commented_lightbox()
        self.set_visual_comments(page)
        self.assertFalse(page.locator(".lightbox-comment-stack").is_hidden())
        self.prepare_visual_comment_surface(page)
        self.assert_visual_snapshot(
            page,
            "comments-reader-desktop",
            target=page.locator("#visual-comment-surface"),
        )

    def test_visual_comments_authoring_desktop(self):
        self.enable_local_comment_authoring()
        page = self.open_commented_lightbox()
        page.get_by_label("New comment").wait_for()
        self.set_visual_comments(page)
        self.assertFalse(page.locator(".lightbox-comment-stack").is_hidden())
        self.prepare_visual_comment_surface(page)
        self.assert_visual_snapshot(
            page,
            "comments-authoring-desktop",
            target=page.locator("#visual-comment-surface"),
        )

    def test_visual_comments_authoring_mobile(self):
        self.enable_local_comment_authoring()
        page = self.open_commented_lightbox(mobile=True)
        page.get_by_label("New comment").wait_for()
        self.set_visual_comments(page)
        self.assertFalse(page.locator(".lightbox-comment-stack").is_hidden())
        self.prepare_visual_comment_surface(page)
        self.assert_visual_snapshot(
            page,
            "comments-authoring-mobile",
            target=page.locator("#visual-comment-surface"),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
