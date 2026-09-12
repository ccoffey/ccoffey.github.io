#!/usr/bin/env python3
"""
Comprehensive Automated Test Suite for ccoffey.github.io

Tiers:
1. Asset & Media Integrity (Dead links, missing images/videos, missing posters)
2. SEO, Social & Metadata Contracts (Canonical URLs, OG/Twitter tags, Sitemap, Robots)
3. Performance & Asset Budgets (WebP companion presence, thumbnail & image weight budgets)
4. Site Generator Invariants (Date parsing, sort keys, deduplication hashing)
5. Headless Browser UX Stability (CDP layout shift & zoom assertions via --ux flag)

Usage:
  python3 scripts/build_site.py --output _site  # Build and test the generated site
  SITE_ROOT=_site python3 test_site.py          # Re-test an existing build
  SITE_ROOT=_site python3 test_site.py --ux     # Include Headless Chrome UX tests
"""

import os
import sys
import glob
import json
from pathlib import Path
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

SOURCE_ROOT = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.environ.get('SITE_ROOT', SOURCE_ROOT))
sys.path.insert(0, SOURCE_ROOT)

import generate_site
from scripts import optimize_staged_media
from scripts import validate_project_media


class HTMLAssetScraper(HTMLParser):
    """Parses an HTML document and collects all asset references, hyperlinks, and metadata."""
    def __init__(self):
        super().__init__()
        self.assets = []
        self.links = []
        self.meta = {}
        self.rel_links = {}
        self.title = ''
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        if tag == 'title':
            self._in_title = True
        elif tag == 'meta':
            key = attr_dict.get('name') or attr_dict.get('property')
            val = attr_dict.get('content')
            if key and val is not None:
                self.meta[key] = val
        elif tag == 'link':
            rel = attr_dict.get('rel', '')
            href = attr_dict.get('href', '')
            if rel and href:
                self.rel_links[rel] = href
                self.assets.append(('link-' + rel, href))
        elif tag == 'img' and 'src' in attr_dict:
            self.assets.append(('img', attr_dict['src']))
        elif tag == 'source' and 'srcset' in attr_dict:
            self.assets.append(('source', attr_dict['srcset']))
        elif tag == 'video':
            if 'src' in attr_dict:
                self.assets.append(('video', attr_dict['src']))
            if 'poster' in attr_dict:
                self.assets.append(('poster', attr_dict['poster']))
        elif tag == 'script' and 'src' in attr_dict:
            self.assets.append(('script', attr_dict['src']))
        elif tag == 'a' and 'href' in attr_dict:
            self.links.append(attr_dict['href'])

    def handle_data(self, data):
        if self._in_title:
            self.title += data

    def handle_endtag(self, tag):
        if tag == 'title':
            self._in_title = False


def get_html_pages():
    """Returns a list of all root-level and build-level generated HTML pages."""
    pages = [os.path.join(REPO_ROOT, 'index.html')]
    pages.extend(glob.glob(os.path.join(REPO_ROOT, 'major-builds', '*', 'index.html')))
    pages.extend(glob.glob(os.path.join(REPO_ROOT, 'quick-builds', '*', 'index.html')))
    return sorted(pages)


class TestAssetIntegrity(unittest.TestCase):
    """Validates that all asset references and internal hyperlinks resolve to existing files on disk."""

    def test_all_pages_exist(self):
        pages = get_html_pages()
        self.assertGreaterEqual(len(pages), 9, "Expected at least 9 main HTML pages.")
        for page in pages:
            self.assertTrue(os.path.isfile(page), f"HTML page does not exist: {page}")

    def test_html_asset_references(self):
        pages = get_html_pages()
        checked_count = 0
        broken_assets = []

        for page in pages:
            scraper = HTMLAssetScraper()
            with open(page, 'r', encoding='utf-8') as f:
                scraper.feed(f.read())

            page_dir = os.path.dirname(page)
            for atype, src in scraper.assets:
                if src.startswith(('http://', 'https://', '//', 'data:')):
                    continue
                checked_count += 1
                clean_src = src.split('?')[0].split('#')[0]
                if clean_src.startswith('/'):
                    target = os.path.join(REPO_ROOT, clean_src.lstrip('/'))
                else:
                    target = os.path.normpath(os.path.join(page_dir, clean_src))

                if not os.path.exists(target):
                    rel_page = os.path.relpath(page, REPO_ROOT)
                    broken_assets.append(f"{rel_page} -> [{atype}] {src} (target: {target})")

        self.assertEqual(broken_assets, [], f"Found {len(broken_assets)} broken asset references:\n" + "\n".join(broken_assets))
        self.assertGreater(checked_count, 100, f"Expected >100 assets checked, got {checked_count}")

    def test_internal_hyperlinks(self):
        pages = get_html_pages()
        checked_count = 0
        broken_links = []

        for page in pages:
            scraper = HTMLAssetScraper()
            with open(page, 'r', encoding='utf-8') as f:
                scraper.feed(f.read())

            page_dir = os.path.dirname(page)
            for href in scraper.links:
                if href.startswith(('http://', 'https://', 'mailto:', 'tel:', '#', 'javascript:')):
                    continue
                clean_href = href.split('?')[0].split('#')[0]
                if not clean_href:
                    continue
                checked_count += 1
                if clean_href.startswith('/'):
                    target = os.path.join(REPO_ROOT, clean_href.lstrip('/'))
                else:
                    target = os.path.normpath(os.path.join(page_dir, clean_href))

                if os.path.isdir(target):
                    target = os.path.join(target, 'index.html')

                if not os.path.exists(target):
                    rel_page = os.path.relpath(page, REPO_ROOT)
                    broken_links.append(f"{rel_page} -> {href} (target: {target})")

        self.assertEqual(broken_links, [], f"Found {len(broken_links)} broken internal links:\n" + "\n".join(broken_links))
        self.assertGreater(checked_count, 50, f"Expected >50 internal links checked, got {checked_count}")

    def test_gallery_json_media_references(self):
        build_pages = glob.glob(os.path.join(REPO_ROOT, 'major-builds', '*', 'index.html')) + \
                      glob.glob(os.path.join(REPO_ROOT, 'quick-builds', '*', 'index.html'))
        total_items = 0
        broken_media = []

        for page in build_pages:
            with open(page, 'r', encoding='utf-8') as f:
                content = f.read()
            match = re.search(r'const gallery = (\[.*?\]);', content, re.DOTALL)
            if not match:
                continue

            items = json.loads(match.group(1))
            total_items += len(items)
            page_dir = os.path.dirname(page)
            rel_page = os.path.relpath(page, REPO_ROOT)

            for item in items:
                # 1. Full-size filename
                fn = item.get('filename')
                if fn:
                    fn_path = os.path.join(page_dir, fn)
                    if not os.path.exists(fn_path):
                        broken_media.append(f"{rel_page} [filename]: {fn}")

                # 2. Thumbnail
                thumb = item.get('thumb')
                if thumb:
                    t_path = os.path.join(REPO_ROOT, thumb.lstrip('/')) if thumb.startswith('/') else os.path.join(page_dir, thumb)
                    if not os.path.exists(t_path):
                        broken_media.append(f"{rel_page} [thumb]: {thumb}")

                # 3. WebP Thumbnail
                thumb_webp = item.get('thumb_webp')
                if thumb_webp:
                    w_path = os.path.join(REPO_ROOT, thumb_webp.lstrip('/')) if thumb_webp.startswith('/') else os.path.join(page_dir, thumb_webp)
                    if not os.path.exists(w_path):
                        broken_media.append(f"{rel_page} [thumb_webp]: {thumb_webp}")

                # 4. Poster (for video items, poster is referenced in thumb / thumb_webp)
                if item.get('type') == 'video':
                    poster = item.get('thumb')
                    self.assertTrue(poster, f"{rel_page} video item missing poster/thumb: {fn}")
                    p_path = os.path.join(REPO_ROOT, poster.lstrip('/')) if poster.startswith('/') else os.path.join(page_dir, poster)
                    if not os.path.exists(p_path):
                        broken_media.append(f"{rel_page} [poster/thumb]: {poster}")

        self.assertEqual(broken_media, [], f"Found {len(broken_media)} broken gallery media items:\n" + "\n".join(broken_media))
        self.assertGreater(total_items, 100, f"Expected >100 gallery items across builds, got {total_items}")

    def test_gallery_comment_contract(self):
        """Comments are safe lists and generated galleries preserve their grouped UI."""
        build_pages = glob.glob(os.path.join(REPO_ROOT, 'major-builds', '*', 'index.html')) + \
                      glob.glob(os.path.join(REPO_ROOT, 'quick-builds', '*', 'index.html'))
        commented_items = []

        for page in build_pages:
            with open(page, 'r', encoding='utf-8') as f:
                content = f.read()
            match = re.search(r'const gallery = (\[.*?\]);', content, re.DOTALL)
            self.assertIsNotNone(match, f"Missing gallery data in {page}")
            items = json.loads(match.group(1))

            self.assertIn('function renderLightboxComments(comments)', content)
            self.assertIn('lightbox-comment-group', content)
            self.assertIn('lightbox-comment-stack', content)
            self.assertIn('id="lightboxCommentsBtn"', content)

            for item in items:
                comments = item.get('comments', [])
                self.assertIsInstance(comments, list, f"Comments must be a list for {item.get('filename')}")
                self.assertTrue(all(isinstance(comment, str) and comment.strip() for comment in comments))
                if comments:
                    commented_items.append((page, item))

        self.assertGreaterEqual(len(commented_items), 1, "Expected at least one commented gallery item.")


class TestSEOAndMetadataContracts(unittest.TestCase):
    """Validates SEO metadata, OpenGraph tags, sitemap.xml, and robots.txt."""

    def test_seo_and_social_tags(self):
        pages = get_html_pages()
        for page in pages:
            rel_page = os.path.relpath(page, REPO_ROOT)
            scraper = HTMLAssetScraper()
            with open(page, 'r', encoding='utf-8') as f:
                scraper.feed(f.read())

            # Title
            title = scraper.title.strip()
            self.assertTrue(title, f"Missing title in {rel_page}")
            self.assertIn("Cathal Coffey", title, f"Title does not mention Cathal Coffey in {rel_page}")

            # Description
            desc = scraper.meta.get('description', '').strip()
            self.assertTrue(desc, f"Missing meta description in {rel_page}")
            self.assertGreaterEqual(len(desc), 20, f"Meta description too short in {rel_page}: '{desc}'")

            # Canonical link
            canonical = scraper.rel_links.get('canonical', '')
            self.assertTrue(canonical.startswith('https://cathalcoffey.com/'), f"Invalid canonical in {rel_page}: {canonical}")

            # OpenGraph tags
            self.assertIn('og:title', scraper.meta, f"Missing og:title in {rel_page}")
            self.assertIn('og:description', scraper.meta, f"Missing og:description in {rel_page}")
            self.assertIn('og:url', scraper.meta, f"Missing og:url in {rel_page}")
            og_img = scraper.meta.get('og:image', '')
            self.assertTrue(og_img.startswith('https://cathalcoffey.com/'), f"Invalid og:image in {rel_page}: {og_img}")

            # OpenGraph image must exist locally
            local_og_img = os.path.join(REPO_ROOT, og_img.replace('https://cathalcoffey.com/', ''))
            self.assertTrue(os.path.exists(local_og_img), f"og:image does not exist on disk for {rel_page}: {local_og_img}")

            # Twitter card tags
            self.assertEqual(scraper.meta.get('twitter:card'), 'summary_large_image', f"Invalid twitter:card in {rel_page}")
            self.assertTrue(scraper.meta.get('twitter:image', '').startswith('https://cathalcoffey.com/'), f"Invalid twitter:image in {rel_page}")

    def test_sitemap_xml(self):
        sitemap_path = os.path.join(REPO_ROOT, 'sitemap.xml')
        self.assertTrue(os.path.isfile(sitemap_path), "sitemap.xml not found.")

        tree = ET.parse(sitemap_path)
        root = tree.getroot()
        ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        locs = [elem.text.strip() for elem in root.findall('ns:url/ns:loc', ns) if elem.text]

        self.assertGreaterEqual(len(locs), 9, "Expected at least 9 URLs in sitemap.xml")

        # Verify every URL in sitemap points to an existing file
        for loc in locs:
            self.assertTrue(loc.startswith('https://cathalcoffey.com/'), f"Sitemap URL must start with domain: {loc}")
            rel_path = loc.replace('https://cathalcoffey.com/', '')
            target = os.path.join(REPO_ROOT, rel_path, 'index.html') if rel_path else os.path.join(REPO_ROOT, 'index.html')
            self.assertTrue(os.path.isfile(target), f"Sitemap entry points to non-existent HTML file: {loc} -> {target}")

        # Verify every generated build page is listed in the sitemap
        sitemap_set = set(locs)
        self.assertIn('https://cathalcoffey.com/', sitemap_set)
        for page in get_html_pages():
            rel = os.path.relpath(page, REPO_ROOT)
            if rel == 'index.html':
                continue
            folder = os.path.dirname(rel)
            expected_url = f"https://cathalcoffey.com/{folder}/"
            self.assertIn(expected_url, sitemap_set, f"Generated build page missing from sitemap.xml: {expected_url}")

    def test_robots_txt(self):
        robots_path = os.path.join(REPO_ROOT, 'robots.txt')
        self.assertTrue(os.path.isfile(robots_path), "robots.txt not found.")
        with open(robots_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('Allow: /', content, "robots.txt must allow root crawling.")
        self.assertIn('Sitemap: https://cathalcoffey.com/sitemap.xml', content, "robots.txt must declare sitemap URL.")


class TestPerformanceAndBudgets(unittest.TestCase):
    """Validates thumbnail companions, file weight limits, and image optimization standards."""

    def test_webp_companion_thumbnails(self):
        thumbs = glob.glob(os.path.join(REPO_ROOT, 'major-builds', '*', 'thumbs', '*')) + \
                 glob.glob(os.path.join(REPO_ROOT, 'quick-builds', '*', 'thumbs', '*'))
        
        jpg_thumbs = [t for t in thumbs if t.lower().endswith(('.jpg', '.jpeg', '.png'))]
        self.assertGreater(len(jpg_thumbs), 50, "Expected >50 raster thumbnails.")

        missing_webp = []
        for thumb in jpg_thumbs:
            base, _ = os.path.splitext(thumb)
            webp_path = base + '.webp'
            if not os.path.exists(webp_path):
                missing_webp.append(os.path.relpath(thumb, REPO_ROOT))

        self.assertEqual(missing_webp, [], f"Found {len(missing_webp)} thumbnails without WebP companions:\n" + "\n".join(missing_webp[:10]))

    def test_thumbnail_weight_budget(self):
        thumbs = glob.glob(os.path.join(REPO_ROOT, 'major-builds', '*', 'thumbs', '*')) + \
                 glob.glob(os.path.join(REPO_ROOT, 'quick-builds', '*', 'thumbs', '*'))

        over_budget = []
        for thumb in thumbs:
            size_kb = os.path.getsize(thumb) / 1024
            ext = os.path.splitext(thumb)[1].lower()
            rel = os.path.relpath(thumb, REPO_ROOT)
            is_poster = '_poster' in thumb

            # Budgets:
            # Full 1080p video posters: WebP <= 150 KB, JPG <= 300 KB
            # Standard photo thumbnails: WebP <= 90 KB, JPG <= 150 KB, PNG <= 500 KB
            if is_poster:
                if ext == '.webp' and size_kb > 150:
                    over_budget.append(f"{rel} ({size_kb:.1f} KB > 150 KB)")
                elif ext in ('.jpg', '.jpeg') and size_kb > 300:
                    over_budget.append(f"{rel} ({size_kb:.1f} KB > 300 KB)")
            else:
                if ext == '.webp' and size_kb > 90:
                    over_budget.append(f"{rel} ({size_kb:.1f} KB > 90 KB)")
                elif ext in ('.jpg', '.jpeg') and size_kb > 150:
                    over_budget.append(f"{rel} ({size_kb:.1f} KB > 150 KB)")
                elif ext == '.png' and size_kb > 500:
                    over_budget.append(f"{rel} ({size_kb:.1f} KB > 500 KB)")

        self.assertEqual(over_budget, [], f"Found {len(over_budget)} thumbnails exceeding size budget:\n" + "\n".join(over_budget))

    def test_full_photo_weight_budget(self):
        photos = []
        for base in ('major-builds', 'quick-builds'):
            for root, dirs, files in os.walk(os.path.join(REPO_ROOT, base)):
                if os.path.basename(root) == 'thumbs':
                    continue
                for f in files:
                    if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                        photos.append(os.path.join(root, f))

        self.assertGreater(len(photos), 50, "Expected >50 full-resolution photos.")
        over_budget = []
        for photo in photos:
            size_mb = os.path.getsize(photo) / (1024 * 1024)
            # Budget: full-size photo <= 3.5 MB
            if size_mb > 3.5:
                over_budget.append(f"{os.path.relpath(photo, REPO_ROOT)} ({size_mb:.2f} MB > 3.5 MB)")

        self.assertEqual(over_budget, [], f"Found {len(over_budget)} full-size photos exceeding 3.5 MB:\n" + "\n".join(over_budget))


class TestGeneratorInvariants(unittest.TestCase):
    """Validates date parsing, sort key consistency, and deduplication logic."""

    def test_media_descriptions_normalize_to_comment_lists(self):
        config = {
            'media_descriptions': {
                'one.jpg': ' One comment ',
                'many.jpg': [' First comment ', '', 12, 'Second comment'],
                'invalid.jpg': {'text': 'not supported'}
            }
        }
        self.assertEqual(
            generate_site.load_media_descriptions(config, 'test-build'),
            {
                'one.jpg': ['One comment'],
                'many.jpg': ['First comment', 'Second comment']
            }
        )

    def test_parse_photo_date(self):
        # Pixel phone filename
        long_d, short_d = generate_site.parse_photo_date('PXL_20260906_064952583.jpg')
        self.assertEqual(long_d, 'September 6, 2026')
        self.assertEqual(short_d, 'Sep 6, 2026')

        # WhatsApp image filename
        long_d, short_d = generate_site.parse_photo_date('IMG-20260607-WA0003.jpg')
        self.assertEqual(long_d, 'June 7, 2026')
        self.assertEqual(short_d, 'Jun 7, 2026')

        # Custom named graphics
        long_d, short_d = generate_site.parse_photo_date('control_panel_graphic.png')
        self.assertIn('September 5, 2026', long_d)
        self.assertEqual(short_d, 'Control Panel Artwork')

        # Generic fallback
        long_d, short_d = generate_site.parse_photo_date('random_photo_test.jpg')
        self.assertEqual(long_d, 'Build Photo')
        self.assertEqual(short_d, 'Photo')

    def test_get_photo_sort_key(self):
        k1 = generate_site.get_photo_sort_key('PXL_20260115_100000000.jpg')
        k2 = generate_site.get_photo_sort_key('PXL_20260601_120000000.jpg')
        k3 = generate_site.get_photo_sort_key('PXL_20260906_180000000.jpg')
        self.assertLess(k1, k2)
        self.assertLess(k2, k3)

        # Ensure tuple comparability
        self.assertEqual(len(k1), 6)

    def test_sha256_computation(self):
        test_file = os.path.join(REPO_ROOT, 'robots.txt')
        h1 = generate_site.compute_sha256(test_file)
        h2 = generate_site.compute_sha256(test_file)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)


class TestStagedMediaOptimizer(unittest.TestCase):
    """Validates the narrow scope and format safety of the pre-commit optimizer."""

    def test_only_direct_project_media_is_selected(self):
        self.assertTrue(optimize_staged_media.is_project_media(Path('major-builds/claw-machine/new.mp4')))
        self.assertTrue(optimize_staged_media.is_project_media(Path('quick-builds/repair/new.jpg')))
        self.assertFalse(optimize_staged_media.is_project_media(Path('major-builds/claw-machine/build.json')))
        self.assertFalse(optimize_staged_media.is_project_media(Path('major-builds/claw-machine/thumbs/new.jpg')))
        self.assertFalse(optimize_staged_media.is_project_media(Path('images/new.jpg')))

    def test_oversized_png_keeps_its_format(self):
        from PIL import Image

        with tempfile.TemporaryDirectory(prefix='portfolio-media-test-') as directory:
            path = Path(directory) / 'large.png'
            Image.new('RGB', (3000, 1800), '#345678').save(path, 'PNG')

            optimize_staged_media.optimize_image(path)

            with Image.open(path) as optimized:
                self.assertEqual(optimized.format, 'PNG')
                self.assertEqual(optimized.size, (2560, 1536))


class TestProjectMediaValidation(unittest.TestCase):
    """Validates the non-mutating CI guard for pre-commit media requirements."""

    def test_jpeg_app1_metadata_is_detected(self):
        with tempfile.TemporaryDirectory(prefix='portfolio-media-test-') as directory:
            path = Path(directory) / 'metadata.jpg'
            path.write_bytes(
                b'\xff\xd8'  # SOI
                b'\xff\xe1\x00\x08Exif\x00\x00'  # APP1 metadata segment
                b'\xff\xd9'  # EOI
            )
            self.assertTrue(validate_project_media.jpeg_has_app1_segment(path))

    def test_jpeg_without_app1_metadata_is_accepted(self):
        with tempfile.TemporaryDirectory(prefix='portfolio-media-test-') as directory:
            path = Path(directory) / 'clean.jpg'
            path.write_bytes(b'\xff\xd8\xff\xd9')
            self.assertFalse(validate_project_media.jpeg_has_app1_segment(path))


class TestUXStability(unittest.TestCase):
    """Optionally executes Chrome CDP layout-shift and UX verification."""

    def test_gallery_ux_stability_cdp(self):
        import subprocess
        ux_script = os.path.join(REPO_ROOT, 'scripts', 'test_gallery_ux.py')
        res = subprocess.run([sys.executable, ux_script], capture_output=True, text=True)
        if res.returncode != 0:
            self.fail(f"UX Stability test failed (code {res.returncode}):\n{res.stdout}\n{res.stderr}")


def run_tests():
    """Main CLI entry point."""
    include_ux = '--ux' in sys.argv or '--all' in sys.argv

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestAssetIntegrity))
    suite.addTests(loader.loadTestsFromTestCase(TestSEOAndMetadataContracts))
    suite.addTests(loader.loadTestsFromTestCase(TestPerformanceAndBudgets))
    suite.addTests(loader.loadTestsFromTestCase(TestGeneratorInvariants))
    suite.addTests(loader.loadTestsFromTestCase(TestStagedMediaOptimizer))
    suite.addTests(loader.loadTestsFromTestCase(TestProjectMediaValidation))

    if include_ux:
        suite.addTests(loader.loadTestsFromTestCase(TestUXStability))

    verbosity = 2 if '-v' in sys.argv or '--verbose' in sys.argv else 1
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    if len(sys.argv) > 1 and any(arg.startswith('-') and arg not in ('-v', '--verbose', '--ux', '--all') for arg in sys.argv[1:]):
        # Fallback to standard unittest CLI if other flags passed
        unittest.main()
    else:
        sys.exit(run_tests())
