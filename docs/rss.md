# RSS project feed

`/feed.xml` contains one RSS 2.0 entry per major or quick build, newest publication
first. Each entry has the title, subtitle (or description when no subtitle is
set), a cover image and a link to the project. The homepage footer links to it;
all project pages advertise it to feed readers.

Every project needs `published_date` in its `build.json`, formatted `YYYY-MM-DD`.
The existing projects were added to RSS on 2026-10-23, so they share that date;
this is their feed publication date, not when they were built or photographed.
New projects should use their actual publication date. Equal dates are sorted
by project type and directory name.

The feed is generated during every build. Item IDs depend on the project type
and directory name, so editing a title, summary, photos, comments or publication
date does not create a new item. Keep project directory names stable. Readers
may refresh existing content differently, but ordinary edits should not be
expected to trigger a new unread item or notification.

## Try it locally with NetNewsWire

From the repository root, run:

```sh
python3 dev_server.py
```

If an older development server is already running, stop it with Ctrl-C and
restart it on this branch. Open http://127.0.0.1:8000/ to preview the site.
The feed is http://127.0.0.1:8000/feed.xml. Seeing XML in a browser is normal.
The development server automatically makes feed links and images point at this
local server. Production builds use `SITE_URL` as usual.

1. Open NetNewsWire on this same Mac.
2. Choose **File → New Feed** (Command-N).
3. Paste `http://127.0.0.1:8000/feed.xml`.
4. Choose the **On My Mac** account, then add the feed. If that account is
   disabled, enable it in NetNewsWire's account settings first.
5. Open an entry to see its cover photo and summary. “View the build” opens the
   local project page.

[NetNewsWire's feed subscription instructions](https://netnewswire.com/help/mac/5.1/en/adding-feeds.html)
explain the New Feed dialog and account selection.

Use a local account for this experiment: a cloud reader's servers cannot fetch
`127.0.0.1` on your Mac. Likewise, this local URL will not work on your phone.
Keep the development server running while testing. Use the reader's refresh
control after a change; automatic refresh can take a while. The first
subscription imports the existing entries, usually as unread. Desktop alerts
are controlled by the reader and macOS, not by the feed.

## Watch a new entry arrive

Mark the existing entries as read in NetNewsWire. Then, in a second terminal at
the repository root, create a temporary demo project with one existing photo:

```sh
python3 - <<'PY'
import json
import shutil
from datetime import date
from pathlib import Path

source = Path('src/major-builds/claw-machine')
cover = json.loads((source / 'build.json').read_text())['cover_image']
demo = Path('src/quick-builds/rss-demo')
if demo.exists():
    raise SystemExit('rss-demo already exists; refusing to overwrite it')
(demo / 'media').mkdir(parents=True)
shutil.copy2(source / 'media' / cover, demo / 'media' / cover)
(demo / 'build.json').write_text(json.dumps({
    'title': 'RSS Test Project',
    'subtitle': 'A temporary project to see a new RSS entry arrive.',
    'published_date': date.today().isoformat(),
    'cover_image': cover,
}, indent=2) + '\n')
PY
```

Wait for the server to finish its incremental build, then refresh NetNewsWire.
“RSS Test Project” should arrive as a new unread entry. Open it to inspect the
image and follow its link. Edit its subtitle in `build.json`, wait for the
server to regenerate `feed.xml`, and refresh again: the ID stays the same, so
it remains the same entry. Some readers cache existing article contents.

Remove the temporary project afterward:

```sh
python3 - <<'PY'
import shutil
shutil.rmtree('src/quick-builds/rss-demo')
PY
```

The watcher rebuilds the feed and homepage after project additions/removals.
Readers may retain entries they have already downloaded even after removal
from the feed. To repeat the new-entry experiment, choose another demo directory
name or remove and re-add the local subscription. Do not commit the demo project.

## Build and verify

```sh
SITE_URL=https://cathalcoffey.com python3 scripts/build_site.py --incremental
npm run lint:html
```

A manual build uses production URLs in the feed. To build a local-feed preview
without the watched development server, add `FEED_BASE_URL=http://127.0.0.1:8000`
to that command and serve `_site` with `python3 -m http.server 8000 --directory _site`.
`FEED_BASE_URL` is a preview override; leave it unset for deployment.

After deployment, subscribe to `https://cathalcoffey.com/feed.xml` for real updates.
The preview and public feeds are separate subscriptions even though their item
IDs match.
