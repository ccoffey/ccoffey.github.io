# Cathal Coffey portfolio

This repository contains the source content and source media for
[cathalcoffey.com](https://cathalcoffey.com). Generated HTML, thumbnails, video
posters, and other deployment output are deliberately not committed.

## One-time local setup

Install Python dependencies and FFmpeg, then enable the repository's tracked Git
hooks:

```bash
brew install ffmpeg
python3 -m pip install --requirement requirements.txt
git config core.hooksPath .githooks
```

The hook setting is local to this clone. Run the `git config` command again after
cloning the repository onto another computer.

## Add images or videos

1. Copy the media into the relevant project directory under `major-builds/` or
   `quick-builds/`. Keep media directly beside that project's `build.json` or
   `project.json`; do not create or edit a `thumbs/` directory.
2. Use `.jpg`, `.jpeg`, `.png`, or `.webp` for images and `.mp4`, `.mov`, or
   `.webm` for videos.
3. Update the project's JSON when changing its cover image, hero video, text, or
   metadata.
4. Stage and commit normally:

   ```bash
   git add major-builds/claw-machine
   git commit -m "Add claw machine media"
   git push origin master
   ```

Before the commit is created, `.githooks/pre-commit` examines only newly staged
project media. It strips JPEG EXIF metadata, reduces images above 2560 pixels or
2.5 MB, and re-encodes videos above 25 MB for the web. Any changed media is
automatically re-staged. It does not generate HTML, thumbnails, or posters.
The pull-request build independently validates changed project media against
those same requirements, so a skipped or interrupted local hook cannot merge
unoptimized files.

### Add a description to a gallery item

In a project's `build.json` (or `project.json`), add a `media_descriptions`
object keyed by the media filename. Each value can be one comment or a list of
comments. They appear in the full-screen gallery viewer; the speech-bubble
marker on a thumbnail shows that extra story context is available.

```json
"media_descriptions": {
  "PXL_20260226_150354165.jpg": [
    "The early control system was spread across several breadboards before the custom PCB brought everything together.",
    "This was the point where I knew I needed to design a custom PCB."
  ],
  "demo.mp4": "The first successful end-to-end test."
}
```

After a push to `master`, GitHub Actions builds an isolated `_site/` directory.
It generates thumbnails and WebP companions, extracts video posters, generates
the HTML, sitemap, and robots file, runs the tests, and deploys the result to
GitHub Pages. The generated artifact exists only for deployment.

## Preview locally

Build and serve an isolated copy:

```bash
python3 scripts/build_site.py --output _site
python3 -m http.server 8000 --directory _site
```

Then open <http://127.0.0.1:8000/>. `_site/` is disposable and ignored by Git.
Delete it whenever you finish testing.

For a watched preview that rebuilds when source files change, run:

```bash
python3 dev_server.py
```

The VS Code tasks provide the same isolated build and preview workflow. Do not
run `generate_site.py` directly from the repository root: that generator is
intended to run inside the isolated build and can rewrite source media in place.

## Responsibilities at a glance

- **Source repository:** project JSON, templates, CSS, JavaScript, and source media.
- **Pre-commit hook:** optimizes only newly staged source images and videos.
- **GitHub Actions:** generates, tests, and deploys the complete website.
- **Generated `_site/`:** temporary local or CI output; never commit it.
