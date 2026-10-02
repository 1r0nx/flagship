# 🚩 Flagship (Documentation EN)

Flagship is a terminal user interface (TUI) for **CTFd**-based CTFs. It syncs challenges into a
clean folder tree and lets users browse them, read the briefs and submit flags without leaving the
terminal.

```
┌ Flagship · MyCTF · score 8270 (#3) ···· 12/40 solved · 8 dl · sort: category ┐
│ ▣ ▢ files  ● ○ solved    │  # 2 - Return                              │
│ Pwn (3/8)                │  Category: Pwn · Points: 200 · ○           │
│  ▣ ●  0 - Overflow 100·12 solves │  🩸 First blood: team_x             │
│  ▣ ○  2 - Return   200·5 solves  │  Connection: nc chal... 1389       │
│ Crypto (5/9)             │  --- Can you pwn this problem? ...          │
│  ▢ ●  First XOR    50·30 solves ├─────────────────────────────────────┤
│  ▢ ○  RSA          150·5 solves │ 🚩                                   │
└ d Download  D Sync all  / Search  f Filter  o Sort  q Quit ────────────┘
```

A legend at the top of the left column recalls each line's markers: `▣`/`▢` for downloaded files,
`●`/`○` for solved state, and `N pt · N solves` for points and solve count. Two distinct shapes
(square for files, circle for status) plus colour make the state readable at a glance, with
consistent alignment regardless of the combination.

## Features

### File-based configuration

A `config.sh` file holds the CTF URL and the CTFd token. No further configuration is required to
get started.

### Light listing by default (no mass download)

On launch, Flagship queries the API and lists the available challenges with their status. Nothing
is created on disk until a download is requested. The list refreshes on its own at a configurable
interval: a newly unlocked challenge appears automatically, along with a notification.

### On-demand download

From the TUI:

- The `d` key downloads the selected challenge. It creates
  `<base>/CHALLENGES/<Category>/<Name>/` with `desc.txt` and `downloads.txt`, and places the files
  in a `work/` subfolder. Challenges live under `CHALLENGES/`; the CTF root only keeps `config.sh`,
  `PROGRESS.md` and `.flagship/` (state and log).
- The `D` key triggers "Sync all" (after confirmation) and downloads every challenge.

The operation is idempotent: nothing is overwritten or deleted, and an already-present file is not
re-downloaded.

### Brief versioning

For an already-downloaded challenge, if the description or the hints change, the old `desc.txt` is
not overwritten: a new version `desc2.txt`, `desc3.txt`, and so on is written, with the date and
the nature of the change. Hints are tracked, free and paid alike: a new hint, an unlock, or a cost
change.

### Two-tab interface

**Challenges** tab: browsing by category; for each challenge, display of the download state
(`▣`/`▢`), the status (`●`/`○`), the points and the solve count. The detail panel shows the first blood,
the connection, the **prerequisites** (challenges to solve first, with their state and a
locked/unlocked indicator), the files and the hints. The description is viewable without downloading.
The interface provides a search (`/`), filters (`f`: all, unsolved, solved), a sort (`o`: category,
points, solves), flag submission (writing `flag.txt` if the flag is correct), download or update
(`d`), full synchronization (`D`, parallel, with a progress bar), hint unlock (`u`), connection
copy (`c`), open folder (`w`), notes editing (`e`, `notes.md`) and export to `PROGRESS_flagship.md`
(`p`, without ever touching the user's `PROGRESS.md`). The header shows the current score, rank and a
**countdown** to the end of the CTF.

On submission, **incorrect** flags already tried are remembered: resubmitting an identical flag is
blocked (with a warning) so a submission attempt is not wasted. Every attempt is also logged to
`attempts.log` at the root of the challenge folder (handy for a writeup).

**Scoreboard** tab: ranking with position, team or player, and score. The user's row is highlighted
and the cursor jumps to it.

**Themes**: several light and dark colour themes (nord, gruvbox, dracula, and more); the `t` key
cycles through them, and the choice is remembered. In **offline mode**, when the API is unreachable,
the last synced list (cache) remains shown.

In the input fields (search and flag), the cursor is drawn as a vertical bar `▏` ("I-beam" style)
rather than a reversed block. Since Textual hides the terminal cursor and draws its own within a
cell, this bar is an approximation; on any incompatibility, rendering falls back automatically to
the standard cursor.

### Notifications

Every change (new challenge available, modified description, new or unlocked hint, accepted flag,
download) triggers a toast and is logged to `.flagship/notifications.log`. The `n` key shows the
history.

## Installation

```bash
cd /workspace/flagship
pip install -r requirements.txt     # textual + requests (+ gdown for Google Drive)
```

Recommended installation as a package, which creates the `flagship` command available anywhere:

```bash
cd /workspace/flagship
pip install -e .            # installs Flagship and its deps, then the `flagship` command
# then, from anywhere:  flagship path/config.sh
```

> Note: after moving the folder following a `pip install -e .`, re-run `pip install -e .` from the
> new location, because the editable install points to the old path. The `./flagship.sh` and
> `python -m flagship` launchers work from anywhere without reinstalling.

## Configuration

Copy the example and edit it:

```bash
cp config.sh.example config.sh
$EDITOR config.sh
```

```sh
URL=https://ctf.example.com          # CTFd URL
CTFD_TOKEN=ctfd_xxxxxxxxxxxxxxxxxxx  # token (CTFd > Settings > Access Tokens)

# optional
CTF_NAME=MyCTF             # displayed name and default folder
BASE_DIR=./MyCTF           # root of generated folders (relative to config.sh)
POLL_INTERVAL=60           # auto-sync every N seconds (0 = disabled)
WRITE_FLAG_ON_SOLVE=true   # write flag.txt when a flag is accepted
WATCH_CHANGES=true         # track desc/hint changes (desc2.txt...) ; false = lighter
AUTO_UNLOCK_FREE_HINTS=false # auto-unlock free (cost 0) hints
DOWNLOAD_WORKERS=6         # parallel downloads for "Sync all"
THEME=textual-dark         # start theme (nord, gruvbox, dracula, tokyo-night ; `t` to cycle)
CTF_END=2026-10-05T18:00   # CTF end for the countdown (epoch or ISO ; empty = auto via API)
```

The token is never printed or logged. The variable name can also be `TOKEN` or any name ending in
`_TOKEN` (for example `PWNY_CTFD_TOKEN`), which Flagship detects automatically. The `config.sh`
file is git-ignored (see `.gitignore`): it must not be shared, since it holds the token.

## Running

```bash
./flagship.sh                 # uses ./config.sh
./flagship.sh path/config.sh
# or:
python3 -m flagship [config.sh]
```

The `flagship.sh` launcher resolves the `config.sh` path to an absolute one, then changes into the
tool's directory so that `python -m flagship` finds the package. The tool can therefore be run from
anywhere with any `config.sh`.

## Multi-CTF workflow (clone once)

Flagship is the tool; a CTF's folder tree is separate (defined by `BASE_DIR`). Re-cloning the
repository for each CTF is not necessary.

**1. Once, install the tool:**

```bash
git clone <repo-url>/flagship ~/ctfs/flagship
cd ~/ctfs/flagship
pip install -r requirements.txt      # textual + requests + gdown
```

**2. For each new CTF (for example HeroCTF), one folder and one config:**

```bash
mkdir ~/ctfs/HeroCTF
cp ~/ctfs/flagship/config.sh.example ~/ctfs/HeroCTF/config.sh
$EDITOR ~/ctfs/HeroCTF/config.sh     # set URL, CTFD_TOKEN, BASE_DIR=.
```

```
~/ctfs/
├── flagship/          # cloned once (the tool)
└── HeroCTF/           # created per CTF; the tree is generated here
    └── config.sh      # URL + token + BASE_DIR=.
```

> `BASE_DIR` is resolved relative to the `config.sh` folder. With `BASE_DIR=.`, challenges appear
> in `HeroCTF/<Category>/<Challenge>/`.

**3. Start, from anywhere:**

```bash
~/ctfs/flagship/flagship.sh ~/ctfs/HeroCTF/config.sh
# equivalent:
cd ~/ctfs/flagship && python3 -m flagship ~/ctfs/HeroCTF/config.sh
```

An alias avoids retyping the path (in `~/.zshrc` or `~/.bashrc`):

```bash
alias flagship='~/ctfs/flagship/flagship.sh'
# then:  flagship ~/ctfs/HeroCTF/config.sh
```

Alternative: cloning Flagship inside the CTF folder (`HeroCTF/flagship/`) also works; in that case
set `BASE_DIR=..` in its `config.sh` to generate the tree into `HeroCTF/`. This variant requires
re-cloning the tool every time, which is less convenient.

The `config.sh` file, which holds the token, is git-ignored. On a new machine, it must be recreated
from `config.sh.example`.

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `↑`/`↓`, Enter | navigate and open a challenge (shows the brief, without downloading) |
| click the tabs | switch between Challenges and Scoreboard |
| `d` | download or update the selected challenge (recreates `desc.txt` if missing, completes missing files in `work/`) |
| `D` | sync all (parallel, progress bar, confirmation) |
| `/` | focus the search bar |
| `r` | refresh the list now (plus scoreboard and rank) |
| `f` | cycle filter (all, unsolved, solved) |
| `o` | cycle sort (category, points, solves) |
| `t` | change colour theme (cycles, persisted) |
| `s` | focus the flag submission field |
| `u` | unlock a hint (confirmation) |
| `c` | copy the challenge's connection (`nc …` or URL) |
| `w` | open the challenge folder in the file manager |
| `e` | edit the challenge notes (`notes.md`, via `$EDITOR`) |
| `p` | export a summary to `PROGRESS_flagship.md` (never touches `PROGRESS.md`) |
| `n` | show the notifications history |
| `Esc` | leave an input field (search or flag) and return to the list |
| `Tab` / `Shift+Tab` | move focus to the next or previous element |
| `q` | quit |

To submit a flag: select a challenge, press `s`, type the flag, then `Enter`. To search: press `/`
and type part of the name (the tree filters live). To unlock a hint: press `u` then confirm (the
cheapest one is offered). A paid hint lowers the score, hence the confirmation.

## Architecture

```
flagship/
├── config.py   # reads config.sh (KEY=value), without running any shell
├── ctfd.py     # CTFd API client: challenges, detail, solves, submit, unlock, download
├── store.py    # folder tree + desc.txt + flag.txt + slugify + downloads
├── app.py      # the Textual TUI (tabs, detail, submission, auto-poll, notifications)
└── __main__.py # entry point (python -m flagship)
```

`config.py` parses `config.sh` line by line, tolerating `export`, quotes and comments. No shell
`source` is executed, which avoids side effects.

`ctfd.py` wraps the API:

- `GET /api/v1/challenges` (list) and `GET /api/v1/challenges/<id>` (detail);
- `GET /api/v1/users/me/solves` (solved) and `GET /api/v1/scoreboard` (ranking);
- `POST /api/v1/challenges/attempt` (submission) and `POST /api/v1/unlocks` (hint unlock);
- download of listed files.

Errors (closed CTF, unreachable network, and so on) propagate cleanly and are shown in the TUI
without crashing the application.

`store.py`:

- `slugify()` applies the naming rule: spaces replaced by `-`, never consecutive dashes
  (`0 - Overflow` becomes `0-Overflow`, `Bruh 0: Exif` becomes `Bruh-0:-Exif`), `/` and `\`
  replaced by `-`.
- `list_state()` (default behaviour) lists challenges with their status and download state,
  creating nothing; `download_one()` downloads one challenge; `sync()` ("Sync all") downloads
  everything. These functions return the events (descriptions and hints changed on tracked
  challenges).
- Versioning: a hidden `.flagship.json` per challenge stores SHA-256 fingerprints of the
  description and hints. On change, a `descN.txt` is written, never overwritten. With
  `WATCH_CHANGES=false`, the detail is fetched only for new challenges, which lightens the sync but
  removes change detection.
- `write_flag()` writes `flag.txt`, never over an existing one.

Notification toasts are also written to `<base>/.flagship/notifications.log`, viewable with `n`. The
UI state (filter, sort, collapsed or expanded categories, last selection) is kept in
`<base>/.flagship/state.json`, then restored across tree rebuilds (download, refresh) and when the
TUI is reopened.

`app.py` (Textual):

- Blocking network calls run in threaded workers (`@work(thread=True)`), and the UI is updated via
  `call_from_thread`, so the interface never freezes.
- `on_mount` runs a first sync then schedules the poll (`set_interval`).
- A challenge's detail is loaded on selection, then cached.

## Downloads

Downloads happen on demand only (`d` on a challenge, or `D` for everything). When a challenge is
downloaded, Flagship places its files in `work/` and writes a `downloads.txt` report (values `ok`,
`skip`, `manual`, `error`) at the challenge root. In all cases the links are present in `desc.txt`
(the "Platform files" section with the full URL, and the "External links" section).

| Source | Behaviour |
|--------|-----------|
| File hosted by the CTFd | downloaded (authenticated), 2 GB guard |
| Direct http(s) link | downloaded without sending the token, 2 GB guard |
| Dropbox | rewritten to a direct link (`?dl=1`) then downloaded |
| Google Drive (file) | via `gdown` if public; otherwise marked `manual` (link kept) |
| Google Drive (folder) | via `gdown.download_folder` |
| MEGA | via `megatools`/`megadl` if installed; otherwise marked `manual` (link kept) |
| File larger than 2 GB | not downloaded, marked `manual` (manual retrieval) |

"Sync all" (`D`) downloads in parallel (`DOWNLOAD_WORKERS`), with a progress bar. The `d` key is
self-healing: it recreates `desc.txt` if missing (for example after an emptied folder) and completes
missing or failed files in `work/`, idempotently (files already present are skipped). A `work/` or a
`downloads.txt` is never created without `desc.txt`. The CTFd token is never sent to a third-party
host (Drive, MEGA, and so on). The Drive guard is checked after the fact, because `gdown` does not
know the size upfront.

## Notes and limitations

- The solved status comes from the API (`/users/me/solves`) and, failing that, from a local
  `flag.txt`.
- Hints are displayed with their cost and state (locked or unlocked). Unlocking is on demand (`u`
  key) with confirmation, never automatic, since it costs points.
- If the CTF is over or closed, the API returns an error message: Flagship shows it and keeps the
  already-synced tree.
- Built for CTFd (self-hosted or sigpwny-style). Other platforms are not supported.
