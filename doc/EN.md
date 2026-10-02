# 🚩 Flagship (Documentation EN)

*A new CTF, and it all starts over: creating folders, downloading files, tracking what is solved,
keeping notes… Flagship automates all this plumbing, leaving just one thing to do: solve the
challenges.*

Flagship is a terminal user interface (TUI) for **CTFd**-based CTFs. It syncs challenges into a
clean folder tree and lets users browse them, read the briefs and submit flags without leaving the
terminal.

```
┌──────────────────────────────Flagship──────────────────────────────┐
│▣ ▢ files  ● ○ solved              │ # 2 - Return                   │
│filter: all  sort: points  search: │ ──────────INFO──────────       │
│Pwn (3/8)                          │ Category: Pwn · Points: 200 · ○│
│ ▣ ●  0 - Overflow 100·12 solves   │ Connection: nc chal... 1389    │
│ ▣ ○  2 - Return   200·5 solves    │ ───────DESCRIPTION───────      │
│Crypto (5/9)                       │ Can you pwn this problem? ...  │
│ ▢ ●  First XOR    50·30 solves    ├────────────────────────────────┤
│ ▢ ○  RSA          150·5 solves    │ 🚩                              │
└ d Dl  D Sync  w Folder  u Hint  / Search  f Filter  o Sort  q Quit ─┘
```

> **Interface language**: the whole Flagship interface (labels, notifications, error messages,
> confirmation dialogs) is in **English**, as are the generated files (`desc.txt`, `downloads.txt`,
> `notes.md`, `PROGRESS_flagship.md`).

A legend at the top of the left column recalls each line's markers: `▣`/`▢` for downloaded files,
`●`/`○` for solved state, and `N pt · N solves` for points and solve count. Two distinct shapes
(square for files, circle for status) plus colour make the state readable at a glance, with
consistent alignment regardless of the combination. Right below it sits the filter/sort/search row
(see below). The header's command-palette icon is hidden (`⭘`, top-left in a stock Textual app) —
it isn't wired to anything in Flagship.

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

### Four-tab interface

**Challenges** tab: browsing by category; for each challenge, display of the download state
(`▣`/`▢`), the status (`●`/`○`), the points and the solve count. The detail panel is split into three
sections by a centered `────TITLE────` divider sized to the pane's current width: **INFO** (first
blood, connection, **prerequisites** — challenges to solve first, with their state and a
locked/unlocked indicator —, folder, files, external links), **DESCRIPTION**, and **HINT(S)** (shown
last, and only when the challenge has hints). The description is viewable without downloading, and
the dividers re-center after a pane resize (see "Resizable panes" below).
The interface provides a search (`/`: lives inline on the filter/sort row itself, never costing
  any extra terminal height, focused or not), filters (`f`: all, unsolved, solved; always starts on "all"), a sort (`o`: category, points, solves, fewest solves, name A→Z, CTFd id, downloaded first, unsolved first),
flag submission (writing `flag.txt` if the flag is correct), download or update
(`d`), download of a whole **category** (`C`), full synchronization (`D`, parallel, with a progress
bar), hint unlock (`u`), connection copy (`c`), open folder (`w`), notes editing (`e`, `notes.md`)
and export to `PROGRESS_flagship.md` (`p`, without ever touching the user's `PROGRESS.md`). The header
just shows the centered app name — score, rank, solved/downloaded counts and the active
filter/sort are deliberately kept out of it, since they're already shown right below (the
filter/sort row) and in the **Stats** tab, and repeating them on the title bar was just noise.

On submission, **incorrect** flags already tried are remembered: resubmitting an identical flag is
blocked (with a warning) so a submission attempt is not wasted. Every attempt is also logged to
`attempts.log` at the root of the challenge folder (handy for a writeup).

**Resizable panes**: a vertical bar `┃` separates the challenge list (left) from the detail
panel (right). Dragging it with the mouse widens or narrows either pane (minimum widths are
enforced); a double-click restores the default width (42%). The chosen width is remembered (as a
percentage) in `.flagship/state.json` (`tree_width`).

**Scoreboard** tab: ranking with position, team or player, and score. The user's row is highlighted
and the cursor jumps to it.

**Stats** tab: a summary table (name, score and rank, solved, points earned, downloaded, and
**first bloods**), then a per-category table and per-category progress bars. It updates
automatically. First bloods are counted by fetching, in the background, the first solver of every
challenge you've solved (one API call per challenge, the first time only — a first blood never
changes once set, so the result is cached forever in `.flagship/fb_cache.json`, confirmed against
CTFd's own source: `get_solves_for_challenge_id()` always returns the account's permanent, final
solve order); while that backlog is still being checked, the row shows `· checking N more…` next to
a provisional count. Solo example:

| Stat | Value |
|------|-------|
| Player | retro_pw |
| Score | 4210  ·  Rank #7th |
| Solved | 63 / 180 |
| Points earned | 4210 / 11200 |
| Downloaded | 58 / 180 |
| First bloods | 9 / 63 |

In **team mode**, the same table uses the team's name and score, the label becomes
"Team first bloods" (this is CTFd's own behaviour, not a Flagship choice: in team mode the
`/challenges/<id>/solves` endpoint reports the solving **team**'s name, never the individual member
who actually typed the flag — confirmed in CTFd's `get_solves_for_challenge_id()`, which looks up
`Model.name` where `Model` is the Teams model), and a **"Team members"** section is added below it:

| Stat | Value |
|------|-------|
| Team | NightOwls |
| Score (team) | 15420  ·  Rank #1st |
| Solved | 60 / 120 |
| Points earned | 15420 / 29800 |
| Downloaded | 45 / 120 |
| Team first bloods | 18 / 60 |

*Your individual rank: #5 · your score: 5400*

| Member | Solved | Points |
|--------|--------|--------|
| **Alice (you)** | **22** | **5400** |
| Carol | 19 | 5320 |
| Bob | 19 | 4700 |

sorted by points, with your own row highlighted and marked "(you)" — figures come from
`/teams/me/solves`, which (confirmed against CTFd's `SubmissionSchema`) really does attribute each
solve to the individual member via a nested `user: {id, name}`, unlike the challenge-level solves
list above. Each **name is clickable**: a click opens a window detailing that member's own stats —
solved, points, and **their personal first-blood count** (a challenge counts for a member when it's
one of the team's first bloods AND they personally are the one who submitted it):

```
# Bob
**Solved**: 19  ·  **Points**: 4700  ·  **First bloods**: 6

## By category (ranked by points)

| Category | Solved | Points |
|----------|--------|--------|
| Pwn      | 8/10   | 2400/2800 |
| Web      | 11/14  | 2300/3100 |

## Progress by category

Pwn   ██████████░░  8/10
Web   █████████░░░  11/14
```

**Notifications** tab: the notification history (most recent on top), updated live. Every event also
appears here in addition to the transient toast.

**Themes**: several light and dark colour themes (nord, gruvbox, dracula, and more); the `t` key
cycles through them, and the choice is remembered. In **offline mode** (or **after the CTF ends**,
when the API hides the challenges), Flagship shows the **last cached synchronization**: challenge
list, statuses and points, your score/rank and the scoreboard all remain visible. Everything is
stored under `<ctf-folder>/.flagship/` (`challenges_cache.json`, `me_cache.json`,
`scoreboard_cache.json`).

In the input fields (search and flag), the cursor is drawn as a vertical bar `▏` ("I-beam" style)
rather than a reversed block. Since Textual hides the terminal cursor and draws its own within a
cell, this bar is an approximation; on any incompatibility, rendering falls back automatically to
the standard cursor.

### Notifications

Every change (new challenge available, modified description, new or unlocked hint, accepted flag,
download) triggers a toast and is logged to `.flagship/notifications.log`. The **Notifications** tab
shows the history (most recent on top).

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
| click the tabs | switch between Challenges, Scoreboard, Stats and Notifications |
| `d` | download or update the selected challenge (recreates `desc.txt` if missing, completes missing files in `work/`) |
| `D` | sync all (parallel, progress bar, confirmation) |
| `C` | download every challenge in the category under the cursor (confirmation) |
| `/` | focus the inline search field (on the filter/sort row; typing filters the tree live) |
| `r` | refresh the list now (plus scoreboard and rank) |
| `f` | cycle filter (all, unsolved, solved) |
| `o` | cycle sort: category (points ↑), points (↓), solves (↓), fewest solves, name A→Z, CTFd id, downloaded first, unsolved first |
| `t` | change colour theme (cycles, persisted) |
| `s` | focus the flag submission field |
| `u` | unlock a hint (confirmation) |
| `c` | copy the challenge's connection (`nc …` or URL) |
| `w` | open the challenge folder in the file manager |
| `e` | edit the challenge notes (`notes.md`, via `$EDITOR`) |
| `p` | export a summary to `PROGRESS_flagship.md` (never touches `PROGRESS.md`) |
| `Esc` | leave an input field (search or flag) and return to the list |
| mouse: drag `┃` | resize the list / detail panes (double-click: default width) |
| `Tab` / `Shift+Tab` | move focus to the next or previous element |
| `q` | quit |

To submit a flag: select a challenge, press `s`, type the flag, then `Enter`. To search: press `/`
and type part of the name (the tree filters live). The search field is built right into the
filter/sort row above the list — it never grows the layout or steals a row, whether it's focused,
being typed into, or just sitting empty. `Enter` or clicking elsewhere leaves with the filter still
running ; `Esc` additionally CANCELS it (clears the text, shows every challenge again). To unlock a
hint: press `u` then confirm (the
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

- `GET /api/v1/challenges` (list) and `GET /api/v1/challenges/<id>` (detail, including prerequisites);
- `GET /api/v1/users/me` or `/api/v1/teams/me` depending on the **detected mode** (solo or team),
  with the matching `/…/solves` (solved), and `GET /api/v1/scoreboard` (ranking);
- in team mode, `GET /api/v1/teams/me/solves` also provides each member's contribution (every solve
  carries the member who solved it);
- `GET /api/v1/challenges/<id>/solves` gives the first blood (Stats tab);
- `POST /api/v1/challenges/attempt` (submission) and `POST /api/v1/unlocks` (hint unlock);
- download of listed files.

Errors (closed CTF, unreachable network, and so on) propagate cleanly and are shown in the TUI
without crashing the application.

`store.py`:

- `slugify()` applies the naming rule: spaces replaced by `-`, never consecutive dashes
  (`0 - Overflow` becomes `0-Overflow`, `Bruh 0: Exif` becomes `Bruh-0:-Exif`), `/` and `\`
  replaced by `-`.
- `list_state()` (default behaviour) lists challenges with their status and download state,
  creating nothing; `download_one()` downloads one challenge; `download_subset()` downloads a
  category; `sync()` ("Sync all") downloads everything. These functions return the events
  (descriptions and hints changed on tracked challenges).
- Versioning: a hidden `.flagship.json` per challenge stores SHA-256 fingerprints of the
  description and hints. On change, a `descN.txt` is written, never overwritten. With
  `WATCH_CHANGES=false`, the detail is fetched only for new challenges, which lightens the sync but
  removes change detection.
- Flag attempts: **incorrect** flags are remembered in `.flagship/attempts.json` (to block
  resubmission) and every attempt is logged to the challenge's `attempts.log`.
- `write_flag()` writes `flag.txt`, never over an existing one.

Notification toasts are also written to `<base>/.flagship/notifications.log`, viewable in the
**Notifications** tab. The
UI state (sort, collapsed or expanded categories, last selection, pane width) is kept in
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

- **Solo or team**: Flagship detects the CTF mode automatically. In **team mode**, the displayed
  score, rank and name (header, stats, scoreboard highlight) are the **team's**, and a challenge
  solved by any teammate shows as solved. In solo mode, individual information is used. No
  configuration required.
- The solved status comes from the API (the team's solves in team mode, otherwise one's own) and,
  failing that, from a local `flag.txt`.
- Hints are displayed with their cost and state (locked or unlocked). Unlocking is on demand (`u`
  key) with confirmation, never automatic, since it costs points.
- If the CTF is over or closed, the API often returns a 403: Flagship states it clearly (token OK vs
  refused) and shows the last cached synchronization (challenges, points, score, scoreboard), on top
  of keeping the already-downloaded tree.
- Built for CTFd (self-hosted or sigpwny-style). Other platforms are not supported.
