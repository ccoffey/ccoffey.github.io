#!/usr/bin/env python3
"""
Comprehensive Automated Test Suite for ccoffey.github.io

Tiers:
1. Asset & Media Integrity (Dead links, missing images/videos, missing posters)
2. SEO, Social & Metadata Contracts (Canonical URLs, OG/Twitter tags, Sitemap, Robots)
3. Performance & Asset Budgets (WebP companion presence, thumbnail & image weight budgets)
4. Site Generator Invariants (Date parsing, sort keys, deduplication hashing)

Usage:
  python3 scripts/build_site.py --output _site  # Build and test the generated site
  SITE_ROOT=_site python3 test_site.py          # Re-test an existing build
"""

import glob
import json
import os
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(TESTS_DIR, ".."))
SITE_ROOT = os.path.abspath(os.environ.get("SITE_ROOT", REPO_ROOT))
SITE_URL = os.environ.get('SITE_URL', 'https://example.com').rstrip('/')
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import build_site  # noqa: E402
import check_performance  # noqa: E402
import generate_site  # noqa: E402
import optimize_staged_media  # noqa: E402
import validate_project_media  # noqa: E402

import dev_server  # noqa: E402


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
    pages = [os.path.join(SITE_ROOT, 'index.html')]
    pages.extend(glob.glob(os.path.join(SITE_ROOT, 'major-builds', '*', 'index.html')))
    pages.extend(glob.glob(os.path.join(SITE_ROOT, 'quick-builds', '*', 'index.html')))
    return sorted(pages)


class TestAssetIntegrity(unittest.TestCase):
    """Validates that all asset references and internal hyperlinks resolve to existing files on disk."""

    def test_homepage_links_to_configured_source_repository(self):
        with open(os.path.join(SITE_ROOT, 'site.json'), encoding='utf-8') as source_file:
            source_url = json.load(source_file)['site_source_url']
        with open(os.path.join(SITE_ROOT, 'index.html'), encoding='utf-8') as homepage:
            content = homepage.read()

        self.assertIn(f'href="{source_url}"', content)
        self.assertIn('data-contact="site-source"', content)
        self.assertIn('Site source', content)

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
            with open(page, encoding='utf-8') as f:
                scraper.feed(f.read())

            page_dir = os.path.dirname(page)
            for atype, src in scraper.assets:
                if src.startswith(('http://', 'https://', '//', 'data:')):
                    continue
                checked_count += 1
                clean_src = src.split('?')[0].split('#')[0]
                if clean_src.startswith('/'):
                    target = os.path.join(SITE_ROOT, clean_src.lstrip('/'))
                else:
                    target = os.path.normpath(os.path.join(page_dir, clean_src))

                if not os.path.exists(target):
                    rel_page = os.path.relpath(page, SITE_ROOT)
                    broken_assets.append(f"{rel_page} -> [{atype}] {src} (target: {target})")

        self.assertEqual(broken_assets, [], f"Found {len(broken_assets)} broken asset references:\n" + "\n".join(broken_assets))
        self.assertGreater(checked_count, 100, f"Expected >100 assets checked, got {checked_count}")

    def test_internal_hyperlinks(self):
        pages = get_html_pages()
        checked_count = 0
        broken_links = []

        for page in pages:
            scraper = HTMLAssetScraper()
            with open(page, encoding='utf-8') as f:
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
                    target = os.path.join(SITE_ROOT, clean_href.lstrip('/'))
                else:
                    target = os.path.normpath(os.path.join(page_dir, clean_href))

                if os.path.isdir(target):
                    target = os.path.join(target, 'index.html')

                if not os.path.exists(target):
                    rel_page = os.path.relpath(page, SITE_ROOT)
                    broken_links.append(f"{rel_page} -> {href} (target: {target})")

        self.assertEqual(broken_links, [], f"Found {len(broken_links)} broken internal links:\n" + "\n".join(broken_links))
        self.assertGreater(checked_count, 50, f"Expected >50 internal links checked, got {checked_count}")

    def test_gallery_json_media_references(self):
        build_pages = glob.glob(os.path.join(SITE_ROOT, 'major-builds', '*', 'index.html')) + \
                      glob.glob(os.path.join(SITE_ROOT, 'quick-builds', '*', 'index.html'))
        total_items = 0
        broken_media = []

        for page in build_pages:
            with open(page, encoding='utf-8') as f:
                content = f.read()
            match = re.search(r'const gallery = (\[.*?\]);', content, re.DOTALL)
            if not match:
                continue

            items = json.loads(match.group(1))
            total_items += len(items)
            page_dir = os.path.dirname(page)
            rel_page = os.path.relpath(page, SITE_ROOT)

            for item in items:
                # 1. Full-size filename
                fn = item.get('filename')
                if fn:
                    fn_path = os.path.join(page_dir, "media", fn)
                    if not os.path.exists(fn_path):
                        broken_media.append(f"{rel_page} [filename]: {fn}")

                # 2. Thumbnail
                thumb = item.get('thumb')
                if thumb:
                    t_path = os.path.join(SITE_ROOT, thumb.lstrip('/')) if thumb.startswith('/') else os.path.join(page_dir, thumb)
                    if not os.path.exists(t_path):
                        broken_media.append(f"{rel_page} [thumb]: {thumb}")

                # 3. WebP Thumbnail
                thumb_webp = item.get('thumb_webp')
                if thumb_webp:
                    w_path = os.path.join(SITE_ROOT, thumb_webp.lstrip('/')) if thumb_webp.startswith('/') else os.path.join(page_dir, thumb_webp)
                    if not os.path.exists(w_path):
                        broken_media.append(f"{rel_page} [thumb_webp]: {thumb_webp}")

                # 4. Poster (for video items, poster is referenced in thumb / thumb_webp)
                if item.get('type') == 'video':
                    poster = item.get('thumb')
                    self.assertTrue(poster, f"{rel_page} video item missing poster/thumb: {fn}")
                    p_path = os.path.join(SITE_ROOT, poster.lstrip('/')) if poster.startswith('/') else os.path.join(page_dir, poster)
                    if not os.path.exists(p_path):
                        broken_media.append(f"{rel_page} [poster/thumb]: {poster}")

        self.assertEqual(broken_media, [], f"Found {len(broken_media)} broken gallery media items:\n" + "\n".join(broken_media))
        self.assertGreater(total_items, 100, f"Expected >100 gallery items across builds, got {total_items}")

    def test_gallery_comment_contract(self):
        """Comments are safe lists and generated galleries preserve their grouped UI."""
        build_pages = glob.glob(os.path.join(SITE_ROOT, 'major-builds', '*', 'index.html')) + \
                      glob.glob(os.path.join(SITE_ROOT, 'quick-builds', '*', 'index.html'))
        commented_items = []

        for page in build_pages:
            with open(page, encoding='utf-8') as f:
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

    def test_build_pages_share_the_gallery_runtime_contract(self):
        """Major and quick builds use the same generated gallery surface."""
        build_pages = glob.glob(os.path.join(SITE_ROOT, 'major-builds', '*', 'index.html')) + \
                      glob.glob(os.path.join(SITE_ROOT, 'quick-builds', '*', 'index.html'))

        self.assertGreaterEqual(len(build_pages), 2, "Expected major and quick build pages.")
        for page in build_pages:
            with open(page, encoding='utf-8') as f:
                content = f.read()
            rel_page = os.path.relpath(page, SITE_ROOT)
            self.assertIn('window.buildPageConfig = {', content, f"Missing shared page config in {rel_page}")
            self.assertIn('/js/major-build.js', content, f"Missing shared major-build enhancement in {rel_page}")
            self.assertIn('function openLightbox(', content, f"Missing shared gallery runtime in {rel_page}")


class TestSEOAndMetadataContracts(unittest.TestCase):
    """Validates SEO metadata, OpenGraph tags, sitemap.xml, and robots.txt."""

    def test_seo_and_social_tags(self):
        pages = get_html_pages()
        for page in pages:
            rel_page = os.path.relpath(page, SITE_ROOT)
            scraper = HTMLAssetScraper()
            with open(page, encoding='utf-8') as f:
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
            self.assertTrue(canonical.startswith(f'{SITE_URL}/'), f"Invalid canonical in {rel_page}: {canonical}")

            # OpenGraph tags
            self.assertIn('og:title', scraper.meta, f"Missing og:title in {rel_page}")
            self.assertIn('og:description', scraper.meta, f"Missing og:description in {rel_page}")
            self.assertIn('og:url', scraper.meta, f"Missing og:url in {rel_page}")
            og_img = scraper.meta.get('og:image', '')
            self.assertTrue(og_img.startswith(f'{SITE_URL}/'), f"Invalid og:image in {rel_page}: {og_img}")

            # OpenGraph image must exist locally
            local_og_img = os.path.join(SITE_ROOT, og_img.replace(f'{SITE_URL}/', ''))
            self.assertTrue(os.path.exists(local_og_img), f"og:image does not exist on disk for {rel_page}: {local_og_img}")

            # Twitter card tags
            self.assertEqual(scraper.meta.get('twitter:card'), 'summary_large_image', f"Invalid twitter:card in {rel_page}")
            self.assertTrue(scraper.meta.get('twitter:image', '').startswith(f'{SITE_URL}/'), f"Invalid twitter:image in {rel_page}")

    def test_sitemap_xml(self):
        sitemap_path = os.path.join(SITE_ROOT, 'sitemap.xml')
        self.assertTrue(os.path.isfile(sitemap_path), "sitemap.xml not found.")

        tree = ET.parse(sitemap_path)
        root = tree.getroot()
        ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        locs = [elem.text.strip() for elem in root.findall('ns:url/ns:loc', ns) if elem.text]

        self.assertGreaterEqual(len(locs), 9, "Expected at least 9 URLs in sitemap.xml")

        # Verify every URL in sitemap points to an existing file
        for loc in locs:
            self.assertTrue(loc.startswith(f'{SITE_URL}/'), f"Sitemap URL must start with domain: {loc}")
            rel_path = loc.replace(f'{SITE_URL}/', '')
            target = os.path.join(SITE_ROOT, rel_path, 'index.html') if rel_path else os.path.join(SITE_ROOT, 'index.html')
            self.assertTrue(os.path.isfile(target), f"Sitemap entry points to non-existent HTML file: {loc} -> {target}")

        # Verify every generated build page is listed in the sitemap
        sitemap_set = set(locs)
        self.assertIn(f'{SITE_URL}/', sitemap_set)
        for page in get_html_pages():
            rel = os.path.relpath(page, SITE_ROOT)
            if rel == 'index.html':
                continue
            folder = os.path.dirname(rel)
            expected_url = f"{SITE_URL}/{folder}/"
            self.assertIn(expected_url, sitemap_set, f"Generated build page missing from sitemap.xml: {expected_url}")

    def test_robots_txt(self):
        robots_path = os.path.join(SITE_ROOT, 'robots.txt')
        self.assertTrue(os.path.isfile(robots_path), "robots.txt not found.")
        with open(robots_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn('Allow: /', content, "robots.txt must allow root crawling.")
        self.assertIn(f'Sitemap: {SITE_URL}/sitemap.xml', content, "robots.txt must declare sitemap URL.")


class TestPerformanceAndBudgets(unittest.TestCase):
    """Validates thumbnail companions, file weight limits, and image optimization standards."""

    def test_webp_companion_thumbnails(self):
        thumbs = glob.glob(os.path.join(SITE_ROOT, 'major-builds', '*', 'thumbs', '*')) + \
                 glob.glob(os.path.join(SITE_ROOT, 'quick-builds', '*', 'thumbs', '*'))
        
        jpg_thumbs = [t for t in thumbs if t.lower().endswith(('.jpg', '.jpeg', '.png'))]
        self.assertGreater(len(jpg_thumbs), 50, "Expected >50 raster thumbnails.")

        missing_webp = []
        for thumb in jpg_thumbs:
            base, _ = os.path.splitext(thumb)
            webp_path = base + '.webp'
            if not os.path.exists(webp_path):
                missing_webp.append(os.path.relpath(thumb, SITE_ROOT))

        self.assertEqual(missing_webp, [], f"Found {len(missing_webp)} thumbnails without WebP companions:\n" + "\n".join(missing_webp[:10]))

    def test_thumbnail_weight_budget(self):
        thumbs = glob.glob(os.path.join(SITE_ROOT, 'major-builds', '*', 'thumbs', '*')) + \
                 glob.glob(os.path.join(SITE_ROOT, 'quick-builds', '*', 'thumbs', '*'))

        over_budget = []
        for thumb in thumbs:
            size_kb = os.path.getsize(thumb) / 1024
            ext = os.path.splitext(thumb)[1].lower()
            rel = os.path.relpath(thumb, SITE_ROOT)
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
            for root, _dirs, files in os.walk(os.path.join(SITE_ROOT, base)):
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
                over_budget.append(f"{os.path.relpath(photo, SITE_ROOT)} ({size_mb:.2f} MB > 3.5 MB)")

        self.assertEqual(over_budget, [], f"Found {len(over_budget)} full-size photos exceeding 3.5 MB:\n" + "\n".join(over_budget))

    def test_initial_page_shell_budget(self):
        """Keep first-load HTML, CSS, JavaScript, and eager assets lightweight."""
        errors = check_performance.check_site(Path(SITE_ROOT))
        self.assertEqual(errors, [], "Performance budget violations:\n" + "\n".join(errors))


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

    def test_build_config_rejects_unknown_and_invalid_fields(self):
        with self.assertRaisesRegex(ValueError, "unsupported field"):
            generate_site.validate_build_config({'titlle': 'Typo'}, 'test-build')
        with self.assertRaisesRegex(ValueError, "'order' must be an integer"):
            generate_site.validate_build_config({'order': True}, 'test-build')
        with self.assertRaisesRegex(ValueError, "non-empty list"):
            generate_site.validate_build_config({'tags': []}, 'test-build')

    def test_build_slug_allows_existing_plus_signs_but_rejects_paths(self):
        generate_site.validate_build_slug('prusa-mk3s+-hotend-repair')
        with self.assertRaisesRegex(ValueError, "Invalid build directory"):
            generate_site.validate_build_slug('../test-build')

    def test_media_references_must_exist_and_match_their_type(self):
        with self.assertRaisesRegex(ValueError, "missing media file"):
            generate_site.validate_media_references(
                {'cover_image': 'missing.jpg'}, 'test-build', ['actual.jpg']
            )
        with self.assertRaisesRegex(ValueError, "must reference an image"):
            generate_site.validate_media_references(
                {'cover_image': 'clip.mp4'}, 'test-build', ['clip.mp4']
            )
        with self.assertRaisesRegex(ValueError, "must be a plain filename"):
            generate_site.validate_media_references(
                {'hero_video': '../clip.mp4'}, 'test-build', ['clip.mp4']
            )

    def test_comment_json_is_safe_for_inline_script(self):
        payload = {'comments': ['A story </script><script>alert("no")</script>']}
        serialized = generate_site.json_for_script(payload)

        self.assertNotIn('</script', serialized.lower())
        self.assertEqual(json.loads(serialized), payload)

    def test_local_comment_editor_persists_and_removes_comments(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            config_path = Path(temporary_dir) / 'build.json'
            config_path.write_text(
                json.dumps({
                    'title': 'Test',
                    'tags': ['Preserve this'],
                    'media_descriptions': {
                        'photo.jpg': ['Existing'],
                        'other.jpg': ['Keep this comment'],
                    },
                }),
                encoding='utf-8',
            )

            saved = dev_server.write_media_comments(
                str(config_path), 'photo.jpg', [' First ', '', 'Second ']
            )
            self.assertEqual(saved, ['First', 'Second'])
            self.assertEqual(
                json.loads(config_path.read_text(encoding='utf-8'))['media_descriptions']['photo.jpg'],
                ['First', 'Second'],
            )
            self.assertEqual(
                json.loads(config_path.read_text(encoding='utf-8'))['media_descriptions']['other.jpg'],
                ['Keep this comment'],
            )

            saved = dev_server.write_media_comments(str(config_path), 'photo.jpg', [])
            self.assertEqual(saved, [])
            self.assertNotIn(
                'photo.jpg',
                json.loads(config_path.read_text(encoding='utf-8'))['media_descriptions'],
            )
            self.assertEqual(
                json.loads(config_path.read_text(encoding='utf-8'))['tags'],
                ['Preserve this'],
            )

    def test_parse_photo_date(self):
        filenames = (
            '20260906.jpg',
            '2026-09-06.jpg',
            '2026_09_06.jpg',
            '2026.09.06.jpg',
            'IMG_20260906_064952583.jpg',
            'Screenshot 2026-09-06 at 06.49.52.png',
        )
        for filename in filenames:
            with self.subTest(filename=filename):
                long_d, short_d = generate_site.parse_photo_date(filename)
                self.assertEqual(long_d, 'September 6, 2026')
                self.assertEqual(short_d, 'Sep 6, 2026')

    def test_parse_photo_date_rejects_undated_filenames(self):
        with self.assertRaisesRegex(ValueError, "Couldn't parse a date from media filename 'photo.jpg'"):
            generate_site.parse_photo_date('photo.jpg')

    def test_get_photo_sort_key(self):
        k1 = generate_site.get_photo_sort_key('PXL_20260115_100000000.jpg')
        k2 = generate_site.get_photo_sort_key('PXL_20260601_120000000.jpg')
        k3 = generate_site.get_photo_sort_key('PXL_20260906_180000000.jpg')
        self.assertLess(k1, k2)
        self.assertLess(k2, k3)

        # Ensure tuple comparability
        self.assertEqual(len(k1), 6)

    def test_video_mime_type_matches_supported_extensions(self):
        self.assertEqual(generate_site.video_mime_type('demo.mp4'), 'video/mp4')
        self.assertEqual(generate_site.video_mime_type('demo.mov'), 'video/quicktime')
        self.assertEqual(generate_site.video_mime_type('demo.webm'), 'video/webm')

    def test_sha256_computation(self):
        with tempfile.NamedTemporaryFile() as test_file:
            test_file.write(b'content to hash')
            test_file.flush()
            h1 = generate_site.compute_sha256(test_file.name)
            h2 = generate_site.compute_sha256(test_file.name)
            self.assertEqual(h1, h2)
            self.assertEqual(len(h1), 64)


class TestBuildAndWatcherContracts(unittest.TestCase):
    """Guard local-only build and watch behavior that CI clean builds do not exercise."""

    def test_incremental_copy_syncs_only_the_source_tree(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / 'src'
            (source / 'js').mkdir(parents=True)
            (source / 'js' / 'app.js').write_text('first', encoding='utf-8')
            (root / 'stylelint.config.mjs').write_text('outside source tree', encoding='utf-8')
            output = root / 'output'

            original_root = build_site.SOURCE_ROOT
            try:
                build_site.SOURCE_ROOT = root
                build_site.copy_source_tree(output)
                (source / 'js' / 'app.js').write_text('second', encoding='utf-8')
                build_site.copy_source_tree(output, incremental=True)
            finally:
                build_site.SOURCE_ROOT = original_root

            self.assertEqual((output / 'js' / 'app.js').read_text(encoding='utf-8'), 'second')

    def test_site_url_must_be_an_https_origin(self):
        self.assertEqual(build_site.validate_site_url('https://cathalcoffey.com/'), 'https://cathalcoffey.com')
        for value in ('', 'http://cathalcoffey.com', 'https://', 'https://cathalcoffey.com/path', 'not a url'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    build_site.validate_site_url(value)

    def test_watcher_includes_all_source_inputs(self):
        state = dev_server.get_dir_state()
        expected = {
            os.path.join(REPO_ROOT, 'src', 'site.json'),
            os.path.join(REPO_ROOT, 'src', 'js', 'navigation.js'),
            os.path.join(REPO_ROOT, 'src', 'templates', 'home.html'),
            os.path.join(REPO_ROOT, 'scripts', 'generate_site.py'),
            os.path.join(REPO_ROOT, 'scripts', 'build_site.py'),
        }
        self.assertTrue(expected.issubset(state), f'Missing watched inputs: {expected - set(state)}')


class TestStagedMediaOptimizer(unittest.TestCase):
    """Validates the narrow scope and format safety of the pre-commit optimizer."""

    def test_only_direct_project_media_is_selected(self):
        self.assertTrue(optimize_staged_media.is_project_media(Path('src/major-builds/claw-machine/media/new.mp4')))
        self.assertTrue(optimize_staged_media.is_project_media(Path('src/quick-builds/repair/media/new.jpg')))
        self.assertFalse(optimize_staged_media.is_project_media(Path('src/major-builds/claw-machine/build.json')))
        self.assertFalse(optimize_staged_media.is_project_media(Path('src/major-builds/claw-machine/thumbs/new.jpg')))
        self.assertFalse(optimize_staged_media.is_project_media(Path('major-builds/claw-machine/new.mp4')))
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


def run_tests():
    """Main CLI entry point."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestAssetIntegrity))
    suite.addTests(loader.loadTestsFromTestCase(TestSEOAndMetadataContracts))
    suite.addTests(loader.loadTestsFromTestCase(TestPerformanceAndBudgets))
    suite.addTests(loader.loadTestsFromTestCase(TestGeneratorInvariants))
    suite.addTests(loader.loadTestsFromTestCase(TestBuildAndWatcherContracts))
    suite.addTests(loader.loadTestsFromTestCase(TestStagedMediaOptimizer))
    suite.addTests(loader.loadTestsFromTestCase(TestProjectMediaValidation))

    verbosity = 2 if '-v' in sys.argv or '--verbose' in sys.argv else 1
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    if len(sys.argv) > 1 and any(arg.startswith('-') and arg not in ('-v', '--verbose') for arg in sys.argv[1:]):
        # Fallback to standard unittest CLI if other flags passed
        unittest.main()
    else:
        sys.exit(run_tests())
