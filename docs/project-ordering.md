# Reorder projects locally

Start the watched development server from the repository root:

```sh
python3 dev_server.py
```

Open http://127.0.0.1:8000/. Each project section displays a local editing hint.
Drag a card to its new position within Major Builds or Quick Builds. The status
changes from “Saving…” to “Saved locally”. You can also focus a project link
with Tab and use Alt + an arrow key to move it one position.

The server saves both sections' sequences under `project_order` in `src/site.json`.
The homepage and all navigation menus use that sequence. Reloading the page or
restarting the server preserves it. Commit `src/site.json` to publish a new
sequence; individual projects' `build.json` files do not need ordering fields.
The existing project sequence is migrated without changing the intended order.

New projects automatically appear before the saved projects. If several new
projects are added at once, their directory names determine their initial
order. Drag them into place when ready; there is no need to add them manually
to the sequence. Deleted project names in the saved sequence are ignored and
are removed from that section the next time its order is saved.

Projects stay within their existing section. Moving between Major Builds and
Quick Builds changes a project's type and is not part of reordering. If a
project is added or removed while a page is open, reload before saving another
order. The server rejects outdated sequences, and a failed save restores the
previous card positions and displays the error.

The public site displays the saved sequence without editing controls. Plain
`python3 -m http.server` previews also lack the admin endpoints: use
`dev_server.py` to reorder projects. The editing script is served from a local
admin endpoint and is not included in the published site assets.
