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
MAJOR_BUILDS_DIR = os.path.join(BASE_DIR, 'src', 'major-builds')
QUICK_BUILDS_DIR = os.path.join(BASE_DIR, 'src', 'quick-builds')
# Source and generator inputs that affect the served output.
WATCH_DIRS = [
    os.path.join(BASE_DIR, 'src'),
]
WATCH_FILES = [
    os.path.join(BASE_DIR, 'scripts', 'generate_site.py'),
    os.path.join(BASE_DIR, 'scripts', 'build_site.py'),
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
    for watched_file in WATCH_FILES:
        if os.path.exists(watched_file):
            try:
                state[watched_file] = os.path.getmtime(watched_file)
            except OSError:
                pass

    for watched_dir in WATCH_DIRS:
        if not os.path.exists(watched_dir):
            continue
        for root, dirs, files in os.walk(watched_dir):
            # Derivatives are generated into the preview and should never
            # trigger a source rebuild. Do not descend into them either.
            dirs[:] = [directory for directory in dirs if directory != 'thumbs']
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
            print("[Watcher] Detected changes in source files. Running isolated build...")
            run_builder(incremental=True)
            last_state = get_dir_state()

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
            # Reloading after a local rebuild cancels in-flight image and media
            # requests. The browser has intentionally gone away, so there is
            # nothing actionable to report in the development-server console.
            pass

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
            media_path = os.path.join(os.path.dirname(config_path), 'media', filename)
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
    run_builder(incremental=True)
    
    t = threading.Thread(target=watcher_loop, daemon=True)
    t.start()
    
    server = ThreadingHTTPServer(('127.0.0.1', port), CustomHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
