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
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

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


class TestProjectOrder(unittest.TestCase):
    def test_new_projects_precede_saved_order_and_removed_projects_are_ignored(self):
        projects = [{'slug': slug} for slug in ('z-new', 'old-b', 'old-a', 'a-new')]
        config = {'project_order': {'major-builds': ['old-a', 'removed', 'old-b']}}
        with patch.object(generate_site, 'SITE_CONFIG', config):
            result = generate_site.order_projects(projects, 'major-builds')
            self.assertEqual([p['slug'] for p in result], ['a-new', 'z-new', 'old-a', 'old-b'])
            self.assertEqual([p['slug'] for p in generate_site.order_projects(projects, 'quick-builds')],
                             ['a-new', 'old-a', 'old-b', 'z-new'])

    def test_invalid_site_sequences_fail_clearly(self):
        for order in ([], {'other': []}, {'major-builds': 'bad'},
                      {'major-builds': ['a', 'a']}, {'quick-builds': ['../a']}):
            with self.subTest(order=order), patch.object(generate_site, 'SITE_CONFIG', {'project_order': order}):
                with self.assertRaises(ValueError):
                    generate_site.order_projects([], 'major-builds')

    def test_save_preserves_project_metadata_and_other_site_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / 'site.json'
            config_path.write_text(json.dumps({'author_name': 'Test', 'project_order': {'major-builds': ['major']}}))
            for slug in ('one', 'two'):
                project = root / 'quick-builds' / slug
                project.mkdir(parents=True)
                (project / 'build.json').write_text('{"title": "Unchanged"}')
            saved = dev_server.write_project_order(config_path, 'quick-builds', ['two', 'one'])
            self.assertEqual(saved, ['two', 'one'])
            config = json.loads(config_path.read_text())
            self.assertEqual(config['author_name'], 'Test')
            self.assertEqual(config['project_order'], {'major-builds': ['major'], 'quick-builds': ['two', 'one']})
            for project in root.glob('quick-builds/*/build.json'):
                self.assertEqual(project.read_text(), '{"title": "Unchanged"}')
            before = config_path.read_bytes()
            for order in (['one'], ['one', 'two', 'missing'], ['one', 'one'], ['../one', 'two'], 'one', [1]):
                with self.subTest(order=order), self.assertRaises(ValueError):
                    dev_server.write_project_order(config_path, 'quick-builds', order)
                self.assertEqual(before, config_path.read_bytes())
            with self.assertRaises(ValueError):
                dev_server.write_project_order(config_path, '../quick-builds', ['two', 'one'])

    def test_homepage_and_navigation_use_the_same_central_order(self):
        config = json.loads(Path(SITE_ROOT, 'site.json').read_text())
        home = Path(SITE_ROOT, 'index.html').read_text()
        with patch.object(generate_site, 'SITE_CONFIG', config):
            for kind in ('major-builds', 'quick-builds'):
                projects = [{'slug': p.parent.name} for p in Path(SITE_ROOT, kind).glob('*/build.json')]
                expected = [p['slug'] for p in generate_site.order_projects(projects, kind)]
                cards = re.findall(rf'<a href="/{kind}/([^/]+)/" class="major-build-card-link"', home)
                nav = re.findall(rf'<a href="/{kind}/([^/]+)/" class="nav-dropdown-item', home)
                self.assertEqual(cards, expected)
                self.assertEqual(nav, expected)
                for path in Path(SITE_ROOT, kind).glob('*/build.json'):
                    self.assertNotIn('order', json.loads(path.read_text()))


class TestRSS(unittest.TestCase):
    def test_published_feed_covers_every_project_and_resolves_images(self):
        channel = ET.parse(Path(SITE_ROOT, 'feed.xml')).getroot().find('channel')
        configs = list(Path(SITE_ROOT).glob('*-builds/*/build.json'))
        items = channel.findall('item')
        self.assertEqual(len(items), len(configs))
        self.assertEqual(len({item.findtext('guid') for item in items}), len(configs))
        expected = {f"urn:project:{p.parent.parent.name}:{p.parent.name}" for p in configs}
        self.assertEqual({item.findtext('guid') for item in items}, expected)
        for item in items:
            scraper = HTMLAssetScraper()
            scraper.feed(item.findtext('description'))
            self.assertTrue(scraper.assets, 'Expected a project cover image')
            for _, url in scraper.assets:
                from urllib.parse import unquote, urlparse
                self.assertTrue(Path(SITE_ROOT, unquote(urlparse(url).path).lstrip('/')).is_file(), url)
        for page in get_html_pages():
            scraper = HTMLAssetScraper()
            scraper.feed(Path(page).read_text())
            self.assertEqual(scraper.rel_links.get('alternate'), '/feed.xml')

    def test_feed_is_deterministic_escaped_sorted_and_stable_on_edits(self):
        with tempfile.TemporaryDirectory() as temporary_dir, patch.object(generate_site, 'BASE_DIR', temporary_dir):
            project = Path(temporary_dir, 'quick-builds', 'demo')
            (project / 'media').mkdir(parents=True)
            (project / 'media' / '2026-01-01 photo.jpg').touch()
            config = {'title': 'A & B <test>', 'subtitle': '<script>alert("test")</script>',
                      'published_date': '2026-10-23'}
            config_path = project / 'build.json'
            config_path.write_text(json.dumps(config))
            generate_site.generate_rss('https://example.com')
            feed = Path(temporary_dir, 'feed.xml')
            initial = feed.read_bytes()
            generate_site.generate_rss('https://example.com')
            self.assertEqual(initial, feed.read_bytes())
            first = ET.fromstring(initial).find('channel/item')
            self.assertEqual(first.findtext('title'), config['title'])
            self.assertIn('&lt;script&gt;', first.findtext('description'))
            self.assertIn('2026-01-01%20photo.jpg', first.findtext('description'))
            config['title'] = 'Edited title'
            config_path.write_text(json.dumps(config))
            newer = Path(temporary_dir, 'major-builds', 'new-project')
            (newer / 'media').mkdir(parents=True)
            (newer / 'build.json').write_text(json.dumps({**config, 'published_date': '2026-10-24'}))
            generate_site.generate_rss('http://127.0.0.1:8000')
            items = ET.parse(feed).findall('channel/item')
            self.assertEqual(len(items), 2)
            self.assertIn('new-project', items[0].findtext('guid'))
            self.assertEqual(first.findtext('guid'), items[1].findtext('guid'))
            self.assertEqual(first.findtext('pubDate'), items[1].findtext('pubDate'))
            self.assertEqual(items[1].findtext('link'), 'http://127.0.0.1:8000/quick-builds/demo/')
            self.assertIn('http://127.0.0.1:8000/', items[1].findtext('description'))
            shutil.rmtree(newer)
            generate_site.generate_rss('http://127.0.0.1:8000')
            self.assertEqual(len(ET.parse(feed).findall('channel/item')), 1)

    def test_invalid_publication_dates_are_rejected(self):
        for value in ('2026-02-30', '23 October 2026', '2026-1-1', 20261023):
            with self.subTest(value=value), self.assertRaises(ValueError):
                generate_site.validate_build_config({'published_date': value}, 'demo')


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
                clean_src = unquote(src.split('?')[0].split('#')[0])
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

    def test_srcset_encodes_media_filenames_in_gallery_and_homepage(self):
        filename = "Photo 1, #50% café's.webp"
        path = f"/quick-builds/demo/thumbs/{filename}"
        gallery = generate_site.render_gallery_card({'thumb': path, 'thumb_webp': path}, 'Demo', 0)
        project = {'slug': 'demo', 'title': 'Demo', 'subtitle': '',
                   'cover_image': filename, 'tags': [], 'gallery': []}
        with tempfile.TemporaryDirectory() as directory, patch.object(generate_site, 'BASE_DIR', directory):
            homepage = generate_site.render_home_page([project], [project], major_nav='', quick_nav='')
        for markup, expected in ((gallery, [path]), (homepage, [
            f"/major-builds/demo/thumbs/{filename}", path,
        ])):
            scraper = HTMLAssetScraper()
            scraper.feed(markup)
            candidates = [url for kind, url in scraper.assets if kind == 'source']
            self.assertEqual([unquote(url) for url in candidates], expected)
            for url in candidates:
                self.assertFalse(any(character.isspace() or character == ',' for character in url), url)
                self.assertIn('%23', url)
                self.assertIn('%25', url)

    def test_build_config_rejects_unknown_and_invalid_fields(self):
        with self.assertRaisesRegex(ValueError, "unsupported field"):
            generate_site.validate_build_config({'titlle': 'Typo'}, 'test-build')
        with self.assertRaisesRegex(ValueError, "unsupported field"):
            generate_site.validate_build_config({'order': True}, 'test-build')
        with self.assertRaisesRegex(ValueError, "non-empty list"):
            generate_site.validate_build_config({'tags': []}, 'test-build')
        with self.assertRaisesRegex(ValueError, "'photos' must be an object"):
            generate_site.validate_build_config({'photos': ['photo.jpg']}, 'test-build')
        with self.assertRaisesRegex(ValueError, "photo index for 'photo.jpg' must be a non-negative integer"):
            generate_site.validate_build_config({'photos': {'photo.jpg': -1}}, 'test-build')
        with self.assertRaisesRegex(ValueError, "photo index for 'photo.jpg' must be a non-negative integer"):
            generate_site.validate_build_config({'photos': {'photo.jpg': True}}, 'test-build')
        with self.assertRaisesRegex(ValueError, "photo keys must be plain media filenames"):
            generate_site.validate_build_config({'photos': {'../photo.jpg': 0}}, 'test-build')

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
        with self.assertRaisesRegex(ValueError, "photos references missing media file"):
            generate_site.validate_media_references(
                {'photos': {'missing.jpg': 0}}, 'test-build', ['actual.jpg']
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

    def test_local_gallery_reorder_persists_order(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            config_path = Path(temporary_dir) / 'build.json'
            media_dir = Path(temporary_dir) / 'media'
            media_dir.mkdir()
            (media_dir / 'a.jpg').touch()
            (media_dir / 'b.jpg').touch()
            (media_dir / 'c.jpg').touch()

            config_path.write_text(
                json.dumps({
                    'title': 'Test',
                    'photos': {
                        'a.jpg': 0,
                        'b.jpg': 1,
                        'c.jpg': 2,
                    },
                }),
                encoding='utf-8',
            )

            saved = dev_server.write_gallery_order(
                str(config_path), ['c.jpg', 'a.jpg', 'b.jpg']
            )
            self.assertEqual(saved, {'c.jpg': 0, 'a.jpg': 1, 'b.jpg': 2})
            self.assertEqual(
                json.loads(config_path.read_text(encoding='utf-8'))['photos'],
                {'c.jpg': 0, 'a.jpg': 1, 'b.jpg': 2},
            )

    def test_local_gallery_delete_removes_file_and_reindexes(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            config_path = Path(temporary_dir) / 'build.json'
            media_dir = Path(temporary_dir) / 'media'
            media_dir.mkdir()
            (media_dir / 'a.jpg').touch()
            (media_dir / 'b.jpg').touch()
            (media_dir / 'c.jpg').touch()

            config_path.write_text(
                json.dumps({
                    'title': 'Test',
                    'cover_image': 'b.jpg',
                    'photos': {
                        'a.jpg': 0,
                        'b.jpg': 1,
                        'c.jpg': 2,
                    },
                    'media_descriptions': {
                        'b.jpg': ['A comment on b'],
                        'a.jpg': ['A comment on a'],
                    },
                }),
                encoding='utf-8',
            )

            saved = dev_server.delete_gallery_photo(str(config_path), 'b.jpg')
            self.assertFalse((media_dir / 'b.jpg').exists())
            self.assertEqual(saved, {'a.jpg': 0, 'c.jpg': 1})
            data = json.loads(config_path.read_text(encoding='utf-8'))
            self.assertEqual(data['photos'], {'a.jpg': 0, 'c.jpg': 1})
            self.assertNotIn('b.jpg', data['media_descriptions'])
            self.assertEqual(data['media_descriptions']['a.jpg'], ['A comment on a'])
            self.assertEqual(data['cover_image'], 'c.jpg')

    def test_local_gallery_upload_saves_file_and_appends_to_photos(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            config_path = Path(temporary_dir) / 'build.json'
            media_dir = Path(temporary_dir) / 'media'
            media_dir.mkdir()
            (media_dir / 'existing.jpg').touch()

            config_path.write_text(
                json.dumps({
                    'title': 'Test',
                    'photos': {
                        'existing.jpg': 0,
                    },
                }),
                encoding='utf-8',
            )

            file_content = b'fake image data'
            target_fn, saved_photos = dev_server.save_gallery_upload(
                str(config_path), 'My New Photo.jpg', file_content
            )
            self.assertEqual(target_fn, 'My_New_Photo.jpg')
            self.assertTrue((media_dir / 'My_New_Photo.jpg').is_file())
            self.assertEqual((media_dir / 'My_New_Photo.jpg').read_bytes(), file_content)
            self.assertEqual(saved_photos, {'existing.jpg': 0, 'My_New_Photo.jpg': 1})
            data = json.loads(config_path.read_text(encoding='utf-8'))
            self.assertEqual(data['photos'], {'existing.jpg': 0, 'My_New_Photo.jpg': 1})

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

    def test_parse_photo_date_supports_undated_filenames(self):
        long_d, short_d = generate_site.parse_photo_date('photo.jpg')
        self.assertEqual(long_d, '')
        self.assertEqual(short_d, '')

    def test_process_build_supports_undated_media_and_sorts_by_photo_index(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            slug = 'test-undated'
            build_dir = Path(temporary_dir) / slug
            media_dir = build_dir / 'media'
            media_dir.mkdir(parents=True)

            from PIL import Image
            img1 = Image.new('RGB', (100, 100), color='blue')
            img1.save(media_dir / 'step-b.jpg')
            img2 = Image.new('RGB', (100, 100), color='red')
            img2.save(media_dir / 'step-a.jpg')

            (build_dir / 'build.json').write_text(
                json.dumps({
                    'title': 'Undated Build',
                    'photos': {
                        'step-b.jpg': 0,
                        'step-a.jpg': 1,
                    },
                }),
                encoding='utf-8',
            )

            result = generate_site.process_build_dir(temporary_dir, slug, '/major-builds')
            self.assertEqual(len(result['gallery']), 2)
            self.assertEqual(result['gallery'][0]['filename'], 'step-b.jpg')
            self.assertEqual(result['gallery'][1]['filename'], 'step-a.jpg')
            self.assertEqual(result['gallery'][0]['date'], '')
            self.assertEqual(result['gallery'][0]['short_date'], '')

            card_markup = generate_site.render_gallery_card(result['gallery'][0], 'Undated Build', 0)
            self.assertNotIn('photo-date-pill', card_markup)

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

    def test_incremental_copy_handles_media_addition_rename_and_pruning(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / 'src'
            project_media = source / 'quick-builds' / 'demo' / 'media'
            project_media.mkdir(parents=True)
            (project_media.parent / 'build.json').write_text('{}', encoding='utf-8')
            (project_media / 'PXL_20260101_100000000.jpg').write_bytes(b'photo-1')

            output = root / 'output'
            original_root = build_site.SOURCE_ROOT
            try:
                build_site.SOURCE_ROOT = root
                build_site.copy_source_tree(output)

                # Simulate generated thumbnail in output
                thumbs_dir = output / 'quick-builds' / 'demo' / 'thumbs'
                thumbs_dir.mkdir(parents=True)
                (thumbs_dir / 'PXL_20260101_100000000.webp').write_bytes(b'thumb-webp')

                # Rename media in source
                (project_media / 'PXL_20260101_100000000.jpg').unlink()
                (project_media / 'PXL_20260101_110000000.jpg').write_bytes(b'photo-2')

                build_site.copy_source_tree(output, incremental=True)
            finally:
                build_site.SOURCE_ROOT = original_root

            out_media = output / 'quick-builds' / 'demo' / 'media'
            self.assertTrue((out_media / 'PXL_20260101_110000000.jpg').is_file())
            self.assertFalse((out_media / 'PXL_20260101_100000000.jpg').exists())
            # Ensure generated thumbnails were preserved
            self.assertTrue((thumbs_dir / 'PXL_20260101_100000000.webp').is_file())

            # Removing a project config must prune output even if ignored files remain.
            (project_media.parent / 'build.json').unlink()
            (project_media.parent / '.DS_Store').touch()
            try:
                build_site.SOURCE_ROOT = root
                build_site.copy_source_tree(output, incremental=True)
            finally:
                build_site.SOURCE_ROOT = original_root
            self.assertFalse((output / 'quick-builds' / 'demo').exists())

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

    suite.addTests(loader.loadTestsFromTestCase(TestProjectOrder))
    suite.addTests(loader.loadTestsFromTestCase(TestRSS))
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
