#!/usr/bin/env python3
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, 'scripts'))
import generate_site  # noqa: E402

MAJOR_BUILDS_DIR = os.path.join(BASE_DIR, 'src', 'major-builds')
QUICK_BUILDS_DIR = os.path.join(BASE_DIR, 'src', 'quick-builds')
# Source and generator inputs that affect the served output.
WATCH_DIRS = [
    os.path.join(BASE_DIR, 'src'),
]
WATCH_FILES = [
    os.path.join(BASE_DIR, 'scripts', 'generate_site.py'),
    os.path.join(BASE_DIR, 'scripts', 'build_site.py'),
    os.path.join(BASE_DIR, 'dev_server.py'),
]
BUILD_SCRIPT = os.path.join(BASE_DIR, 'scripts', 'build_site.py')
OUTPUT_DIR = os.path.join(BASE_DIR, '_site')

MEDIA_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.mp4', '.mov', '.webm'}
BUILD_SLUG_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9+-]*[a-z0-9])?")


def get_build_config_path(slug):
    """Return the source configuration for a valid major or quick build."""
    if not isinstance(slug, str) or not BUILD_SLUG_PATTERN.fullmatch(slug):
        return None
    for root in (MAJOR_BUILDS_DIR, QUICK_BUILDS_DIR):
        build_dir = os.path.join(root, slug)
        for config_name in ('build.json',):
            config_path = os.path.join(build_dir, config_name)
            if os.path.isfile(config_path):
                return config_path
    return None


def write_media_comments(config_path, filename, comments):
    """Atomically persist normalized comments to one build configuration."""
    with open(config_path, encoding='utf-8') as config_file:
        config = json.load(config_file)

    normalized = [comment.strip() for comment in comments if isinstance(comment, str) and comment.strip()]
    descriptions = config.get('media_descriptions')
    if not isinstance(descriptions, dict):
        descriptions = {}
        config['media_descriptions'] = descriptions
    if normalized:
        descriptions[filename] = normalized
    else:
        descriptions.pop(filename, None)

    config_dir = os.path.dirname(config_path)
    with tempfile.NamedTemporaryFile(
        mode='w', encoding='utf-8', dir=config_dir, delete=False, suffix='.json'
    ) as temporary_file:
        json.dump(config, temporary_file, indent=2)
        temporary_file.write('\n')
        temporary_path = temporary_file.name
    os.replace(temporary_path, config_path)
    return normalized


def write_gallery_order(config_path, ordered_filenames):
    """Atomically persist gallery photo order indices to one build configuration."""
    with open(config_path, encoding='utf-8') as config_file:
        config = json.load(config_file)

    media_dir = os.path.join(os.path.dirname(config_path), 'media')
    media_files = set(os.listdir(media_dir)) if os.path.exists(media_dir) else set()

    normalized_order = []
    seen = set()
    for fn in ordered_filenames:
        if isinstance(fn, str) and fn in media_files and fn not in seen:
            normalized_order.append(fn)
            seen.add(fn)

    existing_photos = config.get('photos', {})
    remaining = [fn for fn in existing_photos if fn in media_files and fn not in seen]
    for fn in sorted(remaining, key=lambda x: existing_photos.get(x, 9999)):
        normalized_order.append(fn)
        seen.add(fn)

    photos_dict = {fn: idx for idx, fn in enumerate(normalized_order)}
    config['photos'] = photos_dict

    config_dir = os.path.dirname(config_path)
    with tempfile.NamedTemporaryFile(
        mode='w', encoding='utf-8', dir=config_dir, delete=False, suffix='.json'
    ) as temporary_file:
        json.dump(config, temporary_file, indent=2)
        temporary_file.write('\n')
        temporary_path = temporary_file.name
    os.replace(temporary_path, config_path)
    return photos_dict


def delete_gallery_photo(config_path, filename):
    """Delete a photo/video file from the media dir and update build configuration."""
    with open(config_path, encoding='utf-8') as config_file:
        config = json.load(config_file)

    media_dir = os.path.join(os.path.dirname(config_path), 'media')
    media_path = os.path.join(media_dir, filename)
    if os.path.isfile(media_path):
        os.remove(media_path)

    # Prune from media_descriptions if present
    descriptions = config.get('media_descriptions')
    if isinstance(descriptions, dict):
        descriptions.pop(filename, None)

    # Prune from photos order map and re-index 0..N-1
    existing_photos = config.get('photos', {})
    remaining_media = set(os.listdir(media_dir)) if os.path.exists(media_dir) else set()
    ordered = [fn for fn in sorted(existing_photos, key=lambda x: existing_photos.get(x, 9999))
               if fn != filename and fn in remaining_media]
    photos_dict = {fn: idx for idx, fn in enumerate(ordered)}
    config['photos'] = photos_dict

    # Check cover_image or hero_video
    if config.get('cover_image') == filename:
        config['cover_image'] = ordered[-1] if ordered else ''
    if config.get('hero_video') == filename:
        config.pop('hero_video', None)

    config_dir = os.path.dirname(config_path)
    with tempfile.NamedTemporaryFile(
        mode='w', encoding='utf-8', dir=config_dir, delete=False, suffix='.json'
    ) as temporary_file:
        json.dump(config, temporary_file, indent=2)
        temporary_file.write('\n')
        temporary_path = temporary_file.name
    os.replace(temporary_path, config_path)
    return photos_dict


def save_gallery_upload(config_path, original_filename, file_bytes):
    """Save an uploaded media file to the build's media directory and append to photos order."""
    ext = os.path.splitext(original_filename)[1].lower()
    if ext not in MEDIA_EXTENSIONS:
        raise ValueError(f"Unsupported file format '{ext}'. Allowed: {', '.join(sorted(MEDIA_EXTENSIONS))}")

    raw_base = os.path.splitext(os.path.basename(original_filename))[0]
    safe_base = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', raw_base).strip('._')
    if not safe_base:
        safe_base = f"upload_{int(time.time())}"

    media_dir = os.path.join(os.path.dirname(config_path), 'media')
    os.makedirs(media_dir, exist_ok=True)

    target_filename = f"{safe_base}{ext}"
    target_path = os.path.join(media_dir, target_filename)

    counter = 1
    while os.path.exists(target_path):
        target_filename = f"{safe_base}_{counter}{ext}"
        target_path = os.path.join(media_dir, target_filename)
        counter += 1

    with tempfile.NamedTemporaryFile(mode='wb', dir=media_dir, delete=False, suffix=ext) as temp_media:
        temp_media.write(file_bytes)
        temp_path = temp_media.name
    os.replace(temp_path, target_path)

    with open(config_path, encoding='utf-8') as config_file:
        config = json.load(config_file)

    existing_photos = config.get('photos', {})
    existing_media = set(os.listdir(media_dir))
    ordered = [fn for fn in sorted(existing_photos, key=lambda x: existing_photos.get(x, 9999))
               if fn in existing_media and fn != target_filename]
    ordered.append(target_filename)
    photos_dict = {fn: idx for idx, fn in enumerate(ordered)}
    config['photos'] = photos_dict

    config_dir = os.path.dirname(config_path)
    with tempfile.NamedTemporaryFile(
        mode='w', encoding='utf-8', dir=config_dir, delete=False, suffix='.json'
    ) as temporary_file:
        json.dump(config, temporary_file, indent=2)
        temporary_file.write('\n')
        temporary_path = temporary_file.name
    os.replace(temporary_path, config_path)

    return target_filename, photos_dict



BUILD_LOCK = threading.Lock()
HANDLED_MTIMES = {}


def record_handled_mtime(path):
    """Mark a file's current mtime as handled by server actions so watcher doesn't double-rebuild."""
    try:
        if os.path.exists(path):
            HANDLED_MTIMES[os.path.abspath(path)] = os.path.getmtime(path)
    except OSError:
        pass


def run_builder(incremental=False, skip_tests=True):
    with BUILD_LOCK:
        try:
            command = [sys.executable, BUILD_SCRIPT, '--output', OUTPUT_DIR]
            if incremental:
                command.append('--incremental')
            if skip_tests:
                command.append('--skip-tests')
            subprocess.run(command, check=True)
        except Exception as e:
            print(f"[Watcher] Error during isolated build: {e}")


def get_dir_state():
    state = {}
    for watched_file in WATCH_FILES:
        if os.path.exists(watched_file):
            try:
                state[os.path.abspath(watched_file)] = os.path.getmtime(watched_file)
            except OSError:
                pass

    for watched_dir in WATCH_DIRS:
        if not os.path.exists(watched_dir):
            continue
        for root, dirs, files in os.walk(watched_dir):
            dirs[:] = [directory for directory in dirs if directory != 'thumbs']
            for f in files:
                if f.startswith('.') or f == 'index.html':
                    continue
                path = os.path.abspath(os.path.join(root, f))
                try:
                    state[path] = os.path.getmtime(path)
                except OSError:
                    pass

    return state


def sync_build_to_output(slug, config_path, media_filename=None, deleted_filename=None):
    """
    Sync source build changes directly to the _site directory and re-render only the affected page.
    Runs in <10ms for instant editing feedback.
    """
    rel_path = os.path.relpath(os.path.dirname(config_path), os.path.join(BASE_DIR, 'src'))
    site_build_dir = os.path.join(OUTPUT_DIR, rel_path)
    os.makedirs(site_build_dir, exist_ok=True)

    # 1. Sync build.json
    site_config = os.path.join(site_build_dir, 'build.json')
    shutil.copy2(config_path, site_config)
    record_handled_mtime(config_path)

    # 2. Sync media file if uploaded
    if media_filename:
        src_media = os.path.join(os.path.dirname(config_path), 'media', media_filename)
        dst_media_dir = os.path.join(site_build_dir, 'media')
        dst_thumbs_dir = os.path.join(site_build_dir, 'thumbs')
        os.makedirs(dst_media_dir, exist_ok=True)
        os.makedirs(dst_thumbs_dir, exist_ok=True)
        dst_media = os.path.join(dst_media_dir, media_filename)
        shutil.copy2(src_media, dst_media)
        record_handled_mtime(src_media)

        # Process derivatives for just this single file in _site
        generate_site.process_single_media_file(dst_media_dir, dst_thumbs_dir, media_filename, slug)

    # 3. Remove deleted media & thumbnails if deleted
    if deleted_filename:
        dst_media = os.path.join(site_build_dir, 'media', deleted_filename)
        if os.path.isfile(dst_media):
            os.remove(dst_media)
        stem = os.path.splitext(deleted_filename)[0]
        for thumb_name in (deleted_filename, f"{stem}.webp", f"{stem}_poster.jpg", f"{stem}_poster.webp"):
            t_path = os.path.join(site_build_dir, 'thumbs', thumb_name)
            if os.path.isfile(t_path):
                os.remove(t_path)

    # 4. Re-render only this build page into _site atomically
    generate_site.set_base_dir(OUTPUT_DIR)
    generate_site.render_single_build_page(slug, site_root=OUTPUT_DIR)


def watcher_loop():
    last_state = get_dir_state()
    dev_server_path = os.path.abspath(os.path.join(BASE_DIR, 'dev_server.py'))
    last_dev_server_mtime = last_state.get(dev_server_path)

    while True:
        time.sleep(0.5)
        current_state = get_dir_state()
        if current_state != last_state:
            # Check dev_server.py restart first
            current_dev_server_mtime = current_state.get(dev_server_path)
            if current_dev_server_mtime != last_dev_server_mtime:
                print("[Watcher] Detected changes in dev_server.py. Restarting dev server...")
                os.execv(sys.executable, [sys.executable] + sys.argv)

            # Determine changed paths
            changed = [p for p, mtime in current_state.items() if last_state.get(p) != mtime]
            deleted = [p for p in last_state if p not in current_state]

            # Filter out changes already handled by admin endpoints
            unhandled = []
            for p in changed:
                if HANDLED_MTIMES.get(p) == current_state.get(p):
                    continue
                unhandled.append(p)

            last_state = current_state
            if not unhandled and not deleted:
                continue

            # Check what kind of files changed
            has_scripts = any('scripts' in p for p in unhandled + deleted)
            has_templates = any('templates' in p or p.endswith('site.json') for p in unhandled + deleted)
            has_static_asset = any(re.search(r'/src/(css|js|favicon|assets)/', p) for p in unhandled + deleted)

            if has_scripts:
                print("[Watcher] Generator scripts modified. Running full isolated build...")
                run_builder(incremental=True, skip_tests=True)
            elif has_templates:
                print("[Watcher] Templates or site configuration modified. Re-rendering all pages...")
                copy_source_dirs = ['css', 'js', 'templates', 'favicon.png', 'site.json']
                for item in copy_source_dirs:
                    src_p = os.path.join(BASE_DIR, 'src', item)
                    dst_p = os.path.join(OUTPUT_DIR, item)
                    if os.path.isfile(src_p):
                        shutil.copy2(src_p, dst_p)
                    elif os.path.isdir(src_p):
                        shutil.copytree(src_p, dst_p, dirs_exist_ok=True)
                generate_site.render_all_html_pages(site_root=OUTPUT_DIR)
            elif has_static_asset:
                print("[Watcher] Static assets modified. Copying to output...")
                for p in unhandled:
                    rel = os.path.relpath(p, os.path.join(BASE_DIR, 'src'))
                    dst = os.path.join(OUTPUT_DIR, rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(p, dst)
            else:
                # Check for single build modifications (e.g. external edits to build.json)
                build_slugs_to_render = set()
                for p in unhandled:
                    m = re.search(r'/src/(?:major-builds|quick-builds)/([^/]+)/', p)
                    if m:
                        slug = m.group(1)
                        build_slugs_to_render.add(slug)
                        cfg = get_build_config_path(slug)
                        if cfg:
                            sync_build_to_output(slug, cfg)

                if not build_slugs_to_render and (unhandled or deleted):
                    print("[Watcher] Other source changes detected. Running fast incremental build...")
                    run_builder(incremental=True, skip_tests=True)


class CustomHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=OUTPUT_DIR, **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def copyfile(self, source, outputfile):
        try:
            super().copyfile(source, outputfile)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_json(self, status, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_head(self):
        return super().send_head()

    def list_directory(self, path):
        index = os.path.join(path, 'index.html')
        if os.path.isfile(index):
            self.send_response(302)
            parts = urlparse(self.path)
            new_path = parts.path if parts.path.endswith('/') else parts.path + '/'
            self.send_header('Location', new_path)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return None
        self.send_error(404, "File not found")
        return None

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ('/__admin/comments/status', '/__admin/gallery/status', '/__admin/status'):
            self.send_json(200, {'enabled': True})
            return
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == '/__admin/gallery-order':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536:
                    raise ValueError('Request body must be between 1 and 65536 bytes.')
                payload = json.loads(self.rfile.read(length))
                slug = payload.get('slug')
                order = payload.get('order')
                config_path = get_build_config_path(slug)
                if not config_path:
                    raise ValueError('Unknown build.')
                if not isinstance(order, list) or any(not isinstance(fn, str) or os.path.basename(fn) != fn for fn in order):
                    raise ValueError('Order must be a list of media filenames.')
                saved_photos = write_gallery_order(config_path, order)
                sync_build_to_output(slug, config_path)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                self.send_json(400, {'error': str(error)})
                return
            self.send_json(200, {'photos': saved_photos})
            return

        if path == '/__admin/gallery/delete':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536:
                    raise ValueError('Request body must be between 1 and 65536 bytes.')
                payload = json.loads(self.rfile.read(length))
                slug = payload.get('slug')
                filename = payload.get('filename')
                config_path = get_build_config_path(slug)
                if not config_path:
                    raise ValueError('Unknown build.')
                if not isinstance(filename, str) or os.path.basename(filename) != filename:
                    raise ValueError('Invalid filename.')
                media_path = os.path.join(os.path.dirname(config_path), 'media', filename)
                if not os.path.isfile(media_path):
                    raise ValueError('Media file not found.')
                photos_dict = delete_gallery_photo(config_path, filename)
                sync_build_to_output(slug, config_path, deleted_filename=filename)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                self.send_json(400, {'error': str(error)})
                return
            self.send_json(200, {'deleted': filename, 'photos': photos_dict})
            return

        if path == '/__admin/gallery/upload':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 100 * 1024 * 1024:  # up to 100MB
                    raise ValueError('Upload size must be between 1 byte and 100MB.')
                slug = self.headers.get('X-Build-Slug') or ''
                filename = self.headers.get('X-File-Name') or ''
                config_path = get_build_config_path(slug)
                if not config_path:
                    raise ValueError('Unknown build.')
                if not filename or os.path.basename(filename) != filename:
                    raise ValueError('Invalid filename.')
                file_bytes = self.rfile.read(length)
                saved_filename, photos_dict = save_gallery_upload(config_path, filename, file_bytes)
                sync_build_to_output(slug, config_path, media_filename=saved_filename)
            except (OSError, ValueError) as error:
                self.send_json(400, {'error': str(error)})
                return
            self.send_json(200, {'filename': saved_filename, 'photos': photos_dict})
            return

        if path != '/__admin/comments':
            self.send_json(404, {'error': 'Not found'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 65536:
                raise ValueError('Request body must be between 1 and 65536 bytes.')
            payload = json.loads(self.rfile.read(length))
            slug = payload.get('slug')
            filename = payload.get('filename')
            comments = payload.get('comments')
            config_path = get_build_config_path(slug)
            if not config_path or not isinstance(filename, str) or os.path.basename(filename) != filename:
                raise ValueError('Unknown build or media file.')
            if not isinstance(comments, list) or any(not isinstance(comment, str) for comment in comments):
                raise ValueError('Comments must be a list of strings.')
            media_path = os.path.join(os.path.dirname(config_path), 'media', filename)
            if not os.path.isfile(media_path):
                raise ValueError('Unknown media file.')
            saved_comments = write_media_comments(config_path, filename, comments)
            sync_build_to_output(slug, config_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self.send_json(400, {'error': str(error)})
            return
        self.send_json(200, {'comments': saved_comments})


if __name__ == '__main__':
    port = 8000
    print(f"Starting auto-syncing dev server on http://localhost:{port} ...")
    run_builder(incremental=True, skip_tests=True)

    t = threading.Thread(target=watcher_loop, daemon=True)
    t.start()

    server = ThreadingHTTPServer(('', port), CustomHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
