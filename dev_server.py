#!/usr/bin/env python3
import os, sys, time, threading, subprocess
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAJOR_BUILDS_DIR = os.path.join(BASE_DIR, 'major-builds')
QUICK_BUILDS_DIR = os.path.join(BASE_DIR, 'quick-builds')
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')
CSS_DIR = os.path.join(BASE_DIR, 'css')
GENERATOR_SCRIPT = os.path.join(BASE_DIR, 'generate_site.py')
BUILD_SCRIPT = os.path.join(BASE_DIR, 'scripts', 'build_site.py')
OUTPUT_DIR = os.path.join(BASE_DIR, '_site')

MEDIA_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.mp4', '.mov', '.webm'}


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
        for root, dirs, files in os.walk(TEMPLATES_DIR):
            for f in files:
                p = os.path.join(root, f)
                try:
                    state[p] = os.path.getmtime(p)
                except OSError:
                    pass

    if os.path.exists(CSS_DIR):
        for root, dirs, files in os.walk(CSS_DIR):
            for f in files:
                p = os.path.join(root, f)
                try:
                    state[p] = os.path.getmtime(p)
                except OSError:
                    pass

    for d in (MAJOR_BUILDS_DIR, QUICK_BUILDS_DIR):
        if os.path.exists(d):
            for root, dirs, files in os.walk(d):
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

if __name__ == '__main__':
    port = 8000
    print(f"Starting auto-syncing dev server on http://localhost:{port} ...")
    run_builder()
    
    t = threading.Thread(target=watcher_loop, daemon=True)
    t.start()
    
    server = ThreadingHTTPServer(('0.0.0.0', port), CustomHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
