#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.join(BASE_DIR, '_site')
MAJOR_BUILDS_DIR = os.path.join(BASE_DIR, 'src', 'major-builds')
QUICK_BUILDS_DIR = os.path.join(BASE_DIR, 'src', 'quick-builds')
TEMPLATES_DIR = os.path.join(BASE_DIR, 'src', 'templates')
CSS_DIR = os.path.join(BASE_DIR, 'src', 'css')
GENERATOR_SCRIPT = os.path.join(BASE_DIR, 'scripts', 'generate_site.py')

# Directories to watch
WATCH_DIRS = [
    os.path.join(BASE_DIR, 'src'),
]
BUILD_SCRIPT = os.path.join(BASE_DIR, 'scripts', 'build_site.py')
OUTPUT_DIR = os.path.join(BASE_DIR, '_site')

MEDIA_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.mp4', '.mov', '.webm'}
BUILD_SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def get_build_config_path(slug):
    """Return the source configuration for a valid major or quick build."""
    if not isinstance(slug, str) or not BUILD_SLUG_PATTERN.fullmatch(slug):
        return None
    for root in (MAJOR_BUILDS_DIR, QUICK_BUILDS_DIR):
        build_dir = os.path.join(root, slug)
        for config_name in ('build.json', 'project.json'):
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


def run_builder(incremental=False):
    try:
        command = [sys.executable, BUILD_SCRIPT, '--output', OUTPUT_DIR]
        if incremental:
            command.append('--incremental')
        subprocess.run(command, check=True)
    except Exception as e:
        print(f"[Watcher] Error during isolated build: {e}")

def get_dir_state():
    state = {}
    if os.path.exists(GENERATOR_SCRIPT):
        try:
            state[GENERATOR_SCRIPT] = os.path.getmtime(GENERATOR_SCRIPT)
        except OSError:
            pass

    if os.path.exists(TEMPLATES_DIR):
        for root, _dirs, files in os.walk(TEMPLATES_DIR):
            for f in files:
                p = os.path.join(root, f)
                try:
                    state[p] = os.path.getmtime(p)
                except OSError:
                    pass

    if os.path.exists(CSS_DIR):
        for root, _dirs, files in os.walk(CSS_DIR):
            for f in files:
                p = os.path.join(root, f)
                try:
                    state[p] = os.path.getmtime(p)
                except OSError:
                    pass

    for d in (MAJOR_BUILDS_DIR, QUICK_BUILDS_DIR):
        if os.path.exists(d):
            for root, _dirs, files in os.walk(d):
                if 'thumbs' in root:
                    continue
                for f in files:
                    if f.startswith('.') or f == 'index.html':
                        continue
                    path = os.path.join(root, f)
                    try:
                        state[path] = os.path.getmtime(path)
                    except OSError:
                        pass

    return state

def watcher_loop():
    last_state = get_dir_state()
    while True:
        time.sleep(1.0)
        current_state = get_dir_state()
        if current_state != last_state:
            changed_paths = {
                path for path in set(last_state) | set(current_state)
                if last_state.get(path) != current_state.get(path)
            }
            # Only unchanged file sets containing non-media edits can reuse the
            # copied media. New, removed, or changed photos/videos need a clean
            # build so the preview exactly mirrors the source tree.
            incremental = (
                set(last_state) == set(current_state)
                and all(os.path.splitext(path)[1].lower() not in MEDIA_EXTENSIONS for path in changed_paths)
            )
            mode = "incremental" if incremental else "full"
            print(f"[Watcher] Detected changes in source files. Running {mode} isolated build...")
            run_builder(incremental=incremental)
            last_state = get_dir_state()

class CustomHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=OUTPUT_DIR, **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def send_json(self, status, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlparse(self.path).path == '/__admin/comments/status':
            self.send_json(200, {'enabled': True})
            return
        super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != '/__admin/comments':
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
            media_path = os.path.join(os.path.dirname(config_path), filename)
            if not os.path.isfile(media_path):
                raise ValueError('Unknown media file.')
            saved_comments = write_media_comments(config_path, filename, comments)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self.send_json(400, {'error': str(error)})
            return
        self.send_json(200, {'comments': saved_comments})

if __name__ == '__main__':
    port = 8000
    print(f"Starting auto-syncing dev server on http://localhost:{port} ...")
    run_builder()
    
    t = threading.Thread(target=watcher_loop, daemon=True)
    t.start()
    
    server = ThreadingHTTPServer(('127.0.0.1', port), CustomHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
