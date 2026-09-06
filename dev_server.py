#!/usr/bin/env python3
import os, sys, time, threading, subprocess
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAJOR_BUILDS_DIR = os.path.join(BASE_DIR, 'major-builds')
QUICK_BUILDS_DIR = os.path.join(BASE_DIR, 'quick-builds')
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')
CSS_DIR = os.path.join(BASE_DIR, 'css')
GENERATOR_SCRIPT = os.path.join(BASE_DIR, 'generate_site.py')

def run_generator():
    try:
        subprocess.run([sys.executable, GENERATOR_SCRIPT], check=True)
    except Exception as e:
        print(f"[Watcher] Error during sync: {e}")

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
            print("[Watcher] Detected changes in source files. Regenerating site...")
            run_generator()
            last_state = get_dir_state()

class CustomHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

if __name__ == '__main__':
    port = 8000
    print(f"Starting auto-syncing dev server on http://localhost:{port} ...")
    run_generator()
    
    t = threading.Thread(target=watcher_loop, daemon=True)
    t.start()
    
    server = ThreadingHTTPServer(('0.0.0.0', port), CustomHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
