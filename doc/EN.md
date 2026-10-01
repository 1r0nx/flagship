# 🚩 Flagship — Documentation (EN)

A **TUI** (terminal interface) for any **CTFd**-based CTF.
It **syncs** the challenges into a clean folder tree and lets you **browse, read and submit
flags** without leaving the terminal.

```
┌ Flagship — MyCTF — score 8270 (#3) ──── 12/40 solved · 8 dl · sort: category ┐
│ Pwn (3/8)                │  # 2 - Return                              │
│  ✔✓ 0 - Overflow 100·12✓ │  Category: Pwn · Points: 200 · ○           │
│  ○⬇ 2 - Return   200·5✓  │  🩸 First blood: team_x                     │
│ Crypto (5/9)             │  Connection: nc chal... 1389               │
│  ✔✓ First XOR    50·30✓  │  --- Can you pwn this problem? ...          │
│  ○⬇ RSA          150·5✓  ├────────────────────────────────────────────┤
│                          │ 🚩 Flag (Enter = submit)…                  │
└ d Download  D Sync all  / Search  f Filter  o Sort  q Quit ────────────┘
```
Markers: `✔`/`○` solved · `✓`/`⬇` downloaded · `pt · N✓` points and solve count.

## What it does

1. **Configuration** — you fill a `config.sh` with the CTF URL and your CTFd token.
2. **Light listing (default, NO mass download)** — on launch, Flagship queries the API and
   **lists** the available challenges with their status. It creates **nothing** on disk until you
   ask. The list refreshes **on its own** (configurable interval): a newly unlocked challenge
   shows up automatically (🆕 notification).
3. **On-demand download** — in the TUI:
   - **`d`** downloads the **selected challenge** → creates `<base>/CHALLENGES/<Category>/<Name>/`
     with `desc.txt` and `downloads.txt`, and the **files placed in `work/`**. Challenges live
     under **`CHALLENGES/`**; the CTF root only keeps `config.sh`, `PROGRESS.md`, `.flagship/`
     (state/log).
   - **`D`** = **"Sync all"** (with confirmation) → downloads **all** challenges.
   It is **idempotent**: nothing is overwritten or deleted; an already-present file is not
   re-downloaded.
4. **Brief versioning** — for **already-downloaded** challenges, if the **description** or the
   **hints** change, the old `desc.txt` is **not overwritten**: a new version `desc2.txt`,
   `desc3.txt`… is written (with date + what changed). **Hints** are tracked (free or paid): new
   hint, hint unlocked, cost change.
5. **TUI** — two tabs:
   - **Challenges**: browse by category; per challenge: status (✔/○), **download state** (✓/⬇),
     **points** and **solve count**; detail with **first blood**, connection, files, hints;
     description viewable **without** downloading; **search** (`/`), **filters** (`f`:
     all/unsolved/solved), **sort** (`o`: category/points/solves); **submission** (`flag.txt`
     written if correct), **download / update** (`d`), **"Sync all"** (`D`, parallel + progress bar),
     **hint unlock** (`u`), **copy connection** (`c`), **notes** (`e`, `notes.md`),
     **export `PROGRESS_flagship.md`** (`p`, never overwrites your PROGRESS.md). The header shows **your score and rank**.
   - **Scoreboard**: ranking (position, team/player, score); **your row is highlighted** and the
     cursor jumps to it.
   - **Themes**: several color themes (light/dark: nord, gruvbox, dracula…), `t` to cycle,
     remembered. **Offline mode**: if the API is unreachable, the last synced list (cache) is shown.
6. **Notifications** — every change (new challenge available, description modified, new/unlocked
   hint, correct flag, download) triggers a **toast** and is **logged**
   (`.flagship/notifications.log`). Press `n` to review the history.

## Installation

```bash
cd /workspace/flagship
pip install -r requirements.txt     # textual + requests (+ gdown for Google Drive)
```

Or, better, as an **installable package** (creates the `flagship` command available anywhere):
```bash
cd /workspace/flagship
pip install -e .            # installs Flagship + deps -> `flagship` command
# then, from anywhere:  flagship path/config.sh
```
> ⚠️ If you **move the folder** after `pip install -e .`, re-run `pip install -e .` from the new
> location (the editable install points to the old path). `./flagship.sh` and `python -m flagship`
> work from anywhere without reinstalling.

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
CTF_NAME=MyCTF             # displayed name + default folder
BASE_DIR=./MyCTF           # root of generated folders (relative to config.sh)
POLL_INTERVAL=60           # auto-sync every N s (0 = disabled)
WRITE_FLAG_ON_SOLVE=true   # write flag.txt when a flag is accepted
WATCH_CHANGES=true         # track desc/hint changes (desc2.txt...) ; false = lighter
AUTO_UNLOCK_FREE_HINTS=false # auto-unlock free (cost 0) hints
DOWNLOAD_WORKERS=6         # parallel downloads for "Sync all"
THEME=textual-dark         # start theme (nord, gruvbox, dracula, tokyo-night… ; `t` to cycle)
```

- The **token is never printed or logged**. The variable name can also be `TOKEN` or any
  `*_TOKEN` (e.g. `PWNY_CTFD_TOKEN`) — Flagship detects it.
- `config.sh` is git-ignored (see `.gitignore`): don't share it, it holds your token.

## Running

```bash
./flagship.sh                 # uses ./config.sh
./flagship.sh path/config.sh
# or:
python3 -m flagship [config.sh]
```

The `flagship.sh` launcher **resolves the `config.sh` path to an absolute one**, then changes
into the tool's directory (so `python -m flagship` finds the package) → you can run it from
anywhere with any `config.sh`.

## Multi-CTF workflow (clone once)

Flagship is **the tool**; a CTF's folder tree is separate (that's `BASE_DIR`). No need to
re-clone for each CTF.

**1. Once — install the tool:**
```bash
git clone <your-repo>/flagship ~/ctfs/flagship
cd ~/ctfs/flagship
pip install -r requirements.txt      # textual + requests + gdown
```

**2. For each new CTF (e.g. HeroCTF) — one folder + one config:**
```bash
mkdir ~/ctfs/HeroCTF
cp ~/ctfs/flagship/config.sh.example ~/ctfs/HeroCTF/config.sh
$EDITOR ~/ctfs/HeroCTF/config.sh     # -> URL, CTFD_TOKEN, BASE_DIR=.
```
```
~/ctfs/
├── flagship/          ← cloned ONCE (the tool)
└── HeroCTF/           ← created per CTF; the tree is generated here
    └── config.sh      ← URL + token + BASE_DIR=.
```
> `BASE_DIR` is resolved **relative to the `config.sh` folder**. `BASE_DIR=.` → challenges appear
> in `HeroCTF/<Category>/<Challenge>/`.

**3. Start (from anywhere):**
```bash
~/ctfs/flagship/flagship.sh ~/ctfs/HeroCTF/config.sh
# equivalent:
cd ~/ctfs/flagship && python3 -m flagship ~/ctfs/HeroCTF/config.sh
```

**Tip — an alias so you don't retype the path** (in `~/.zshrc` / `~/.bashrc`):
```bash
alias flagship='~/ctfs/flagship/flagship.sh'
# then:  flagship ~/ctfs/HeroCTF/config.sh
```

**Alternative**: cloning Flagship *inside* the CTF folder (`HeroCTF/flagship/`) also works — set
`BASE_DIR=..` in its `config.sh` to generate the tree into `HeroCTF/`. But then you re-clone the
tool every time (less convenient).

> Security: `config.sh` (with your token) is **git-ignored**. On a new machine, recreate it from
> `config.sh.example`.

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `↑`/`↓`, Enter | navigate / open a challenge (shows the brief, without downloading) |
| click the tabs | switch Challenges ↔ Scoreboard |
| `d` | **download / update** the selected one (recreates `desc.txt` if missing, completes missing files in `work/`) |
| `D` | **Sync all** (parallel + progress bar, confirmation) |
| `/` | focus the search bar |
| `r` | refresh the list now (+ scoreboard + rank) |
| `f` | cycle filter (all → unsolved → solved) |
| `o` | cycle sort (category → points → solves) |
| `t` | change color theme (cycles, persisted) |
| `s` | focus the flag submission field |
| `u` | unlock a hint (confirmation) |
| `c` | copy the challenge's connection (`nc …`/URL) |
| `e` | edit the challenge **notes** (`notes.md`, `$EDITOR`) |
| `p` | export a summary to **`PROGRESS_flagship.md`** (never touches your `PROGRESS.md`) |
| `n` | show the notifications history |
| `Esc` | leave an input field (search/flag) → focus back to the list |
| `Tab` / `Shift+Tab` | move focus to the next/previous element |
| `q` | quit |

- **Submit**: select a challenge, `s`, type the flag, **Enter** → `✔ Correct` / `✘`.
- **Search**: `/`, type part of the name (the tree filters live).
- **Unlock a hint**: `u` → confirm (the cheapest one is offered). ⚠️ a paid hint lowers your
  score, hence the confirmation.

## How it works (architecture)

```
flagship/
├── config.py   # reads config.sh (KEY=value), without running any shell
├── ctfd.py     # CTFd API client: challenges, detail, solves, submit, unlock, download
├── store.py    # folder tree + desc.txt + flag.txt + slugify + downloads
├── app.py      # the Textual TUI (tabs, detail, submission, auto-poll, notifs)
└── __main__.py # entry point (python -m flagship)
```

- **`config.py`** parses `config.sh` line by line (`export`/quotes/comments tolerated).
  No shell `source` is executed → no side effects.
- **`ctfd.py`** wraps the API:
  - `GET /api/v1/challenges` (list), `GET /api/v1/challenges/<id>` (detail),
  - `GET /api/v1/users/me/solves` (solved), `GET /api/v1/scoreboard` (ranking),
  - `POST /api/v1/challenges/attempt` (submission), `POST /api/v1/unlocks` (hint unlock),
  - download of listed files. Errors (closed CTF, network…) propagate cleanly and are shown in
    the TUI without crashing.
- **`store.py`**:
  - `slugify()` applies the naming rule: spaces → `-`, **never consecutive dashes**
    (`0 - Overflow` → `0-Overflow`, `Bruh 0: Exif` → `Bruh-0:-Exif`), `/` and `\` → `-`.
  - `list_state()` (default) lists challenges + status + **download state**, creating nothing;
    `download_one()` downloads one challenge; `sync()` ("Sync all") downloads everything. They
    return the **events** (desc/hints changed on tracked challenges).
  - **Versioning**: a hidden `.flagship.json` per challenge stores SHA-256 fingerprints of the
    description and hints. On change → `descN.txt` (never overwritten). With `WATCH_CHANGES=false`
    the detail is fetched only for new challenges (lighter sync, but no change detection).
  - `write_flag()` writes `flag.txt` (never over an existing one).
- **Notifications**: toasts are also written to `<base>/.flagship/notifications.log`
  (history viewable with `n`).
- **Persistent UI state**: the filter, sort, **collapsed/expanded categories** and last selection
  are saved in `<base>/.flagship/state.json` → kept across rebuilds (download/refresh) **and**
  restored when you reopen the TUI.
- **`app.py`** (Textual):
  - Blocking network calls run in **threaded workers** (`@work(thread=True)`); the UI is updated
    via `call_from_thread` → the interface never freezes.
  - `on_mount` runs a first sync then schedules the **poll** (`set_interval`).
  - A challenge's **detail** is loaded on selection and **cached**.

## Downloads

Downloads happen **on demand only** (`d` on a challenge, or `D` for everything). When a challenge
is downloaded, Flagship places its files in **`work/`** and writes a `downloads.txt` report
(`ok` / `manual` / `error`) at the challenge root. In **all** cases the **links** are present in
`desc.txt` (*Platform files* section with the full URL, and *External links*).

| Source | Behavior |
|--------|----------|
| File hosted by the CTFd | downloaded (authenticated), **2 GB** guard |
| Direct **http(s)** link | downloaded **without** sending your token, 2 GB guard |
| **Dropbox** | rewritten to a direct link (`?dl=1`) then downloaded |
| **Google Drive** (file) | via `gdown` if public; otherwise → `manual` (link kept) |
| **Google Drive** (folder) | via `gdown.download_folder` |
| **MEGA** | via `megatools`/`megadl` **if installed**; otherwise → `manual` (link kept) |
| File **> 2 GB** | not downloaded → `manual` (grab it yourself) |

- **"Sync all"** (`D`) downloads **in parallel** (`DOWNLOAD_WORKERS`) with a **progress bar**.
- **`d` is self-healing**: it **recreates `desc.txt`** if missing (e.g. emptied folder) and
  **completes missing/failed files** in `work/` (idempotent — files already there are skipped).
  Never `work/`/`downloads.txt` without `desc.txt`.
- Your **CTFd token is never sent to a third-party host** (Drive, MEGA…). The Drive guard is
  checked *after the fact* (gdown doesn't know the size upfront).

## Notes / limitations

- **Solved status** comes from the API (`/users/me/solves`) and, failing that, from a local
  `flag.txt`.
- **Hints** are displayed (cost + locked/unlocked). Unlocking is **on demand** (`u` key) with
  **confirmation** — never automatic, since it costs points.
- If the CTF is **over/closed**, the API returns an error message: Flagship shows it and keeps
  the already-synced tree.
- Built for CTFd (self-hosted or sigpwny-like). Other platforms are not supported.
