# Contributing

Thanks for taking an interest in this portfolio and its static-site generator.
Small, focused pull requests are easiest to review and keep the generated site
reproducible.

## Development setup

```bash
brew install ffmpeg
python3 -m pip install -r requirements-test.txt
npm ci
git config core.hooksPath .githooks
python3 dev_server.py
```

The development server builds an isolated `_site/` directory, watches `src/`,
and serves the result at `http://127.0.0.1:8000/`.

## Content and media

- Keep project content in `src/major-builds/` or `src/quick-builds/`.
- Put source photos and videos in that project's `media/` directory; use
  `build.json` for titles, stories, cover media, tags, and gallery comments.
- `story` is trusted HTML and is rendered as-is. Do not submit unreviewed HTML;
  all other `build.json` fields are validated by the build.
- Do not commit generated `_site/` output or thumbnail directories.
- The tracked pre-commit hook optimizes newly staged media and removes EXIF
  metadata. Let it finish and review the resulting staged files.
- Keep source media that is needed to reproduce the site, but never commit raw
  footage, generated derivatives, or duplicate exports. The full policy is in
  [repository maintenance](docs/repository-maintenance.md).
- Do not add credentials, private keys, personal addresses, or location data.

## Verification

Run the same checks used in CI before opening a pull request:

```bash
python3 -m ruff check .
npm run lint:js
npm run lint:css
python3 scripts/validate_project_media.py
python3 scripts/build_site.py --output _site
SITE_ROOT=_site npm run lint:html
SITE_ROOT=_site python3 tests/test_browser.py
```

If a deliberate UI change updates a visual test, follow the screenshot
baseline instructions in the README and include the reviewed PNGs in the same
pull request.

## Pull requests

Explain the user-facing effect, note any media or configuration changes, and
include verification results. Keep generated output out of the diff. CI builds
the site twice on pull requests and verifies that the output is reproducible.
