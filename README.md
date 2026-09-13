# Cathal Coffey Portfolio

This repository contains the source content and custom static site generator for [cathalcoffey.com](https://cathalcoffey.com). 

<div align="center">
  <img src="tests/visual-baselines/home-desktop.png" width="48%" alt="Home Page">
  <img src="tests/visual-baselines/gallery-desktop.png" width="48%" alt="Gallery View">
</div>

## ✨ Features

- **Blazing Fast Static Generation:** A custom Python pipeline compiles templates, JSON metadata, and media into a highly optimized, dependency-free static site.
- **Media Optimization:** A Git pre-commit hook automatically strips EXIF data, resizes large images, and re-encodes videos for the web.
- **Immersive Gallery:** A responsive full-screen media viewer with deep-linking, touch support, and keyboard navigation.
- **Inline Comments:** 
  - **In-Prod (Reader Mode):** Visitors can view context-rich comments tied to specific photos or videos in the gallery.
  - **Local Authoring Mode:** When running the local development server, you can add, edit, or delete comments directly from the gallery UI. Changes are automatically saved back to the underlying `build.json` files!

<div align="center">
  <img src="tests/visual-baselines/comments-authoring-desktop.png" width="60%" alt="Local Comment Authoring">
  <br/>
  <em>Local Comment Authoring Interface</em>
</div>

---

## 🚀 Getting Up and Running

### 1. Initial Setup

Install the required system dependencies (like FFmpeg for video processing), Python packages, and enable the Git hooks.

```bash
# Install FFmpeg (macOS example)
brew install ffmpeg

# Install Python dependencies
python3 -m pip install -r requirements.txt

# Enable the repository's tracked Git hooks
git config core.hooksPath .githooks
```
> **Note**: The hook setting is local to this clone. Run the `git config` command again if you clone the repository onto another computer.

### 2. Local Development Server (Recommended)

To start a watched preview that automatically rebuilds when source files (HTML, CSS, JS, JSON) change, run:

```bash
python3 dev_server.py
```
Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/). 

**Authoring Comments:** When accessed via this dev server, the gallery includes the **Local Comment Authoring** feature. Click a comment bubble to edit it in place, type into the always-ready *Write a comment…* bubble, or click the `×` to delete it. Changes save directly to your local JSON metadata and trigger a rebuild. 

*(These authoring endpoints do not exist on the deployed production site).*

### 3. Manual Build & Preview

If you just want to build and serve an isolated copy without file watching:

```bash
python3 scripts/build_site.py --output _site
python3 -m http.server 8000 --directory _site
```
The `_site/` directory is disposable and ignored by Git. 

> **Warning**: The VS Code tasks provide the same isolated build and preview workflow. Do not run `generate_site.py` directly from the repository root: that generator is intended to run inside the isolated build and can rewrite source media in place.

---

## 📸 Adding Content (Images/Videos)

1. Copy your media into the relevant project directory under `major-builds/` or `quick-builds/`. 
   *(Do not create or edit a `thumbs/` directory—the pipeline handles thumbnails automatically).*
2. Supported formats: `.jpg`, `.jpeg`, `.png`, `.webp`, `.mp4`, `.mov`, `.webm`.
3. Update the project's `build.json` (or `project.json`) when changing its cover image, hero video, or text metadata.
4. Stage and commit:
   ```bash
   git add major-builds/claw-machine
   git commit -m "Add claw machine media"
   ```

Before the commit is created, the `.githooks/pre-commit` hook automatically optimizes newly staged media and re-stages it.

### Manual Comment Configuration

While you can use the Local Authoring Mode via `dev_server.py`, you can also manually add comments to a project's `build.json`:

```json
"media_descriptions": {
  "PXL_20260226_150354165.jpg": [
    "The early control system was spread across several breadboards before the custom PCB brought everything together."
  ],
  "demo.mp4": "The first successful end-to-end test."
}
```
A speech-bubble marker on a thumbnail indicates that comments are available for that item.

---

## 🧪 Testing and Linting

The repository includes a comprehensive browser regression suite that runs in headless Chromium (just like in CI).

### Browser Regression Tests
```bash
python3 -m pip install -r requirements-test.txt
python3 -m playwright install chromium
SITE_ROOT=_site python3 scripts/test_browser.py
```
If you make an intentional visual change, you can update the visual baselines by running:
```bash
SITE_ROOT=_site python3 scripts/test_browser.py --update-snapshots
```

### Linting
**Python:**
```bash
python3 -m pip install -r requirements-test.txt
python3 -m ruff check .
```
**HTML / CSS / JS:**
```bash
npm ci
npm run lint:js
npm run lint:css
python3 scripts/build_site.py --output _site
npm run lint:html
```

---

## 🏗️ Architecture & Responsibilities

- **Source Repository:** Project JSON, templates, CSS, JavaScript, and source media.
- **Pre-commit Hook:** Optimizes only newly staged source images and videos.
- **Generated `_site/`:** Temporary local or CI output; **never commit it**.
- **GitHub Actions:** Generates thumbnails/posters, extracts robots.txt/sitemap, runs tests, and deploys the complete static site to GitHub Pages.
