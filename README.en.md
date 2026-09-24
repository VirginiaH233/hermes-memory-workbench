# Hermes Memory Workbench (hermes-memory-workbench)

[中文](README.md) | **English**

**A local web page to review, edit, approve, and undo your Hermes memory.**

Hermes ships a "ask me before writing memory" switch (`memory.write_approval`). With it on, the
agent stages every memory change into a pending queue instead of writing it — but natively you
only get two buttons: approve / reject. **What does the entry actually say? Can I fix a word?
What if I approve the wrong thing?**

That's the gap this tool fills.

- Runs as a **local web page** — double-click a script, nothing to install, nothing resident, no network
- **Never assembles memory files by hand**: every write goes through Hermes' own write path
  (equivalent to `/memory approve <id>`)
- See the full text, edit it, approve **one change at a time**, and undo any step
- Delete the folder and it's gone — Hermes is unaffected

> Built for Hermes users only. It manages the **built-in memory** (`MEMORY.md` / `USER.md`),
> not external memory providers (mem0, Supermemory, Hindsight, …).

> The UI is in Chinese. Commands and this README are in English.

---

## What it looks like

**Pending proposals** — when the agent wants to change your memory, it queues here and waits

![pending](docs/01-pending.png)

**All memory (the one editing surface)** — readable text on the left, the exact line that gets written on the right

![memory](docs/02-memory.png)

**Action log (undo any step)** — every write is recorded with its character-count change

![log](docs/03-log.png)

---

## 30-second start

Requirements: **Hermes** installed, and **Python 3.9+** (no Python packages needed).

1. Turn the gate on (replace `default` with the profile you want to manage):

   ```
   hermes -p default config set memory.write_approval true
   ```

   Note: without `-p`, this writes the *currently active* profile — a common trap.

2. Double-click `start.cmd` (Windows) or run `./start.sh` (mac / Linux).
   The browser opens `http://127.0.0.1:8787/` automatically.

3. Ask Hermes to remember something ("remember I'm allergic to peanuts"), refresh the page —
   your first pending proposal appears.

**Want to look around first? Demo mode** (a full set of fake data, your real memory untouched):

```
start.cmd --demo        (Windows)
./start.sh --demo       (mac / Linux)
python server.py --demo (any platform)
```

---

## Two languages

The page has a **中文 ⇄ English** switch in the top right. It follows your browser language on the
first visit and remembers what you pick.

- **Interface** (titles, hints, buttons, errors, console output) is fully translated. **Your own
  memory text is never translated** — it is shown exactly as stored.
- The demo profile ships both: the Chinese persona 「阿岸」 and the English **Alex**. Start it with
  `--demo`; the language follows your system.
- `i18ntest.py` is a mechanical check: it finds every hard-coded string in the page, verifies the
  dictionary covers it, and fails if any Chinese leaks into the English UI. Run it after editing text.

---

## The three views

**1. Pending proposals** — for each entry in the queue:

| Action | What it does |
|---|---|
| **Edit the text** | Left pane is human-readable and editable; the right pane shows the exact line that will be written and the character count. Pure formatting translation, no AI involved |
| **Approve one change** | One queued item can contain several changes; handle them separately — keep the first, drop the second |
| **Dry run** | Really runs it in a sandbox: tells you whether it will succeed and what the size will become. Writes nothing |
| **Approve / Discard** | Only Approve writes to memory; Discard just moves the item to the archive |
| **Undo** | Every write is undoable from the action log — memory goes back to how it was |

**2. All memory** — what's actually in memory right now (notes / user profile separately), searchable,
editable, and you can add entries. This is the only editing surface; saving takes effect immediately
and keeps a snapshot of the previous version.

**3. Action log** — every write, failure, and discard, each with an "undo this step" button.

A profile tab row lets one page cover all your profiles (each reads and writes its own memory only).
The row hides itself when you have a single profile.

---

## One Hermes quirk worth knowing: "replace" means the whole entry

Hermes' `replace` is a **whole-entry** replacement, not a substring edit
(see `tools/memory_tool_store.py`: *replace the WHOLE entry with new_content — old_text only
locates the entry*). `old_text` merely finds which entry you mean; that entire entry is then
overwritten.

This page tells you exactly that — "this whole entry will be overwritten" — and shows you the
original text, so you don't lose half an entry thinking you changed one word. Undo restores the
**complete** entry (older action-log records are repaired from the snapshot taken at the time).

---

## Safety

- **Local only**: binds `127.0.0.1`, no outbound network, nothing uploaded
- **Only requests from its own page are accepted**: origin check + JSON-only + a token that only
  the served page knows — other pages on your machine can't call it (no token → 403, foreign
  origin → 403)
- **Writes go through Hermes' own entry point**: locking, re-read, drift detection, atomic write
  and size checks are all inherited. It deliberately does **not** parse and write memory files
  itself (some projects do; with two writers, one silently overwrites the other)
- **Snapshot before, undo after**: every write is preceded by a snapshot and can be undone in one click
- **Demo mode is fully isolated**: `--demo` uses fake data under `demo-home/`, with its own action
  log and snapshots. Click anything; your real memory is untouched
- **Uninstall is deleting the folder** (see below)

## Boundaries

- **Built-in memory only.** External memory providers are out of scope — they don't go through this
  queue and aren't gated by `write_approval`
- **Doesn't change memory limits**: set `memory.memory_char_limit` etc. with `hermes config set`
- **Nothing resident**: it runs only while you have it open. Hermes still notifies you on its own
  when it wants to write memory
- **macOS / Linux scripts are untested** (`start.sh` / `start.command`); Windows is the tested platform

## FAQ

**The queue stays empty.**
Two things must both be true: the agent wants to write memory, and `write_approval` is on. The
empty state tells you the status of both.

**Approving failed.**
Usually the referenced old text is no longer in the file (it was changed by a later write). Such
items are flagged *before* you click, with the approve button disabled and the reason shown. Fix it
by picking a line that still exists in the "All memory" view.

**Will it survive Hermes updates?**
Hit "self-check" (also runs automatically at startup): it verifies reading memory, reading the queue,
the sandbox dry-run path, and that its own directory is writable. If Hermes renames something
internally, only the write step breaks — with a clear error, and without writing anything partial.

**Does it conflict with other memory plugins?**
No. It doesn't register a plugin and doesn't modify Hermes; it's a small standalone program plus a page.

## Uninstall (1 minute)

1. Delete this folder
2. Optionally turn the gate back off: `hermes -p default config set memory.write_approval false`
3. Nothing else is left behind (no service, no scheduled task, no plugin)

## Tests (if you want proof it doesn't touch your memory)

```bash
python selftest.py          # end-to-end: real write → undo → byte-exact memory restore (23 checks)
python sectest.py           # security: path traversal / cross-page calls / origin checks (32 checks)
python demotest.py          # demo mode: fake data works, real memory byte-identical (33 checks)
python profcheck.py         # multi-profile: writing another profile never bleeds (needs 2 profiles)
node test_js_roundtrip.js   # formatting round-trip is lossless
```

All of them clean up after themselves.

---

## Related projects

The ecosystem already has good tools; this one doesn't redo them:

- **[xraysight/hermes-memory-ui](https://github.com/xraysight/hermes-memory-ui)** — read-only memory
  browser across many backends. Its README states the same writing principle this project follows:
  writes should go through Hermes' own tools so locking and mirroring are preserved
- **`hermes-memory-wiki`** (official) — read-only audit panel plus a session-history wiki
- **`memory-review`** (community plugin) / **`hermes-memory-approval`** — tick-box approve/reject
  for pending proposals

They cover "view" and "approve". This project covers **view · edit · approve · undo** together, as a
standalone tool that doesn't touch Hermes and doesn't break when it updates.

## Design decisions

Why this is a standalone tool instead of a plugin, why it never assembles memory files itself, and
what it deliberately doesn't do — see [`DECISIONS.md`](DECISIONS.md).

## License

MIT — see `LICENSE`.
