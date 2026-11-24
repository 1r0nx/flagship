# 🚩 Flagship (Documentation EN)

New CTF, same routine: create folders, download files, track what's solved, keep
per-challenge notes. Flagship does all of it for you.

## Preview

![Flagship screenshot](img/screenshot.png)

> The interface and the generated files (`<nom-du-challenge>.txt`, `<nom-du-challenge>.md`…) are in English.

## Screens

**Scoreboard**

![Scoreboard](img/scoreboard.png)

**Stats (solo CTF)**

![Stats (solo)](img/stats-solo-ctf.png)

**Stats (team CTF)**

![Stats (team)](img/stats-team-ctf.png)

**Flags**

![Flags](img/flags.png)

## Features

- Lists challenges
- Downloads challenges: one, a whole category, or all of them
- Tracks what's solved; writes `flag.txt` when a flag is accepted
- Detects description/hint changes (`<nom-du-challenge>-v2.txt`, `<nom-du-challenge>-v3.txt`…)
- Submits flags
- Remembers rejected flags so they're never resent
- Limited-attempts challenge: a confirmation window before submitting
- Unlocks hints (confirmation for paid ones)
- Search, filter (all / unsolved / solved / bookmarked) and sort
- Bookmarks to pin a challenge
- Per-challenge notes (`<nom-du-challenge>.md`) in the editor of your choice
- Full scoreboard; double-click a row (or Enter) shows the solve history of a user or team
- "Gap" column: each row's point gap vs you (green = you lead, red = they lead you)
- Stats: score, rank, solved, points, first bloods (per-member in team mode; click a member's card
  for their solve history: challenge, category, points and date, most recent first)
- Everything cached locally: browsable offline and after the CTF
- Resizable panes, colour themes, Markdown export
- Export all written notes at once, in one zip organised by category (`N`)
- Six tabs: Challenges, Scoreboard, Stats, Flags, Notifications (platform
  announcements), Log (internal journal)

## Install

```bash
cd /workspace/flagship
pip install -e .            # installs Flagship + deps, adds the `flagship` command
```

## Configure

```bash
cp config.sh.example config.sh
$EDITOR config.sh
```

```sh
URL=https://ctf.example.com          # CTFd URL
CTFD_TOKEN=ctfd_xxxxxxxxxxxxxxxxxxx  # token (CTFd > Settings > Access Tokens)

# optional
CTF_NAME=MyCTF               # displayed name and default folder
BASE_DIR=./                  # root of generated folders (relative to config.sh)
POLL_INTERVAL=60             # auto-sync every N seconds (0 = disabled)
WRITE_FLAG_ON_SOLVE=true     # write flag.txt when a flag is accepted
WATCH_CHANGES=true           # track desc/hint changes (false = lighter sync)
WATCH_INTERVAL=300           # min seconds between two full watch passes (0 = every poll)
AUTO_UNLOCK_FREE_HINTS=true # auto-unlock free (cost 0) hints
AUTO_NOTES=true             # create <nom-du-challenge>.md notes automatically (never overwritten)
DOWNLOAD_WORKERS=6           # parallel downloads for "Sync all"
THEME=ansi-dark           # start theme (`t` to cycle)
EDITOR=code                  # editor for notes (e.g. vim, subl, code)
```

## Run

```bash
./flagship.sh                 # uses ./config.sh
./flagship.sh path/config.sh
./flagship.sh --offline       # offline: local data only (see below)
# or: python3 -m flagship [--offline] [config.sh]
```

One clone handles many CTFs: each CTF gets its own `config.sh` (with its own `BASE_DIR`),
passed as an argument. An alias saves retyping the path:

```bash
alias flagship='~/ctfs/flagship/flagship.sh'
flagship ~/ctfs/HeroCTF/config.sh
```

### Offline mode (`--offline`)

`--offline` **never** calls the CTFd API: Flagship only shows what was cached during the last
syncs (`BASE_DIR/.flagship/`) and what is already on disk.

- **Shown**: the challenge list, scoreboard, stats, flags, notifications, first bloods, solve
  histories already opened, and each challenge's description read from its `<nom-du-challenge>.txt`.
- **Disabled** (a notification says so): refresh (`r`), download (`d`, category, sync all), flag
  submission, hint unlocking, caching solve histories.
- **No automatic update**: no polling, and the cache is not rewritten.
- The status bar shows `⚠ Offline (--offline) · sync DD/MM HH:MM`: the date is the last successful sync.

A challenge that was never downloaded has no `<nom-du-challenge>.txt`, so its description is not available offline.

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `↑`/`↓`, Enter | navigate, open a challenge |
| click tabs | switch tab |
| `d` / `D` / `C` | download: the challenge / all / the category |
| `/` | search |
| `r` | refresh now |
| `f` / `o` | cycle filter / sort |
| `b` | toggle bookmark |
| `x` | fold/unfold categories |
| `t` | cycle theme |
| `l` | Log tab: toggle last 500 ↔ full history |
| `s` | focus the flag field |
| `u` | unlock a hint |
| `c` / `w` | copy connection / open folder |
| `e` | edit notes (`<nom-du-challenge>.md`) |
| `p` / `P` | export progress / the Flags tab |
| `N` | export written notes to one zip (`notes-export-*.zip`): asks all notes or solved only |
| `A` | cache the whole scoreboard's solve history |
| `Esc` | leave the active field |
| drag `┃` | resize the panes (double-click: reset) |
| `q` | quit |

## Themes

- **Dark (15):** `ansi-dark`, `atom-one-dark`, `catppuccin-frappe`, `catppuccin-macchiato`,
  `catppuccin-mocha`, `dracula`, `flexoki`, `gruvbox`, `monokai`, `nord`, `rose-pine`,
  `rose-pine-moon`, `solarized-dark`, `textual-dark`, `tokyo-night`
- **Light (6):** `ansi-light`, `atom-one-light`, `catppuccin-latte`, `rose-pine-dawn`,
  `solarized-light`, `textual-light`

## Architecture

| File | Role |
|------|------|
| `config.py` | Reads `config.sh` (no shell involved) |
| `ctfd.py` | CTFd API client |
| `store.py` | Folders, `<nom-du-challenge>.txt`, `flag.txt`, downloads, cache |
| `app.py` | The Textual TUI |
| `__main__.py` | Entry point |

## Downloads

Files go into `work/`. A file larger than **2 GB is not downloaded** automatically (to
avoid filling the disk): it's marked `manual` and its link stays in `<nom-du-challenge>.txt` for manual
retrieval.

Each challenge gets a `downloads.txt` report where every line carries a status:

| Status   | Meaning                                                              |
| -------- | ------------------------------------------------------------------- |
| `ok`     | file downloaded into `work/`                                        |
| `skip`   | already present, not overwritten                                    |
| `page`   | a web page (not a file): kept in `<nom-du-challenge>.txt`, not downloaded          |
| `manual` | fetch it by hand (link in `<nom-du-challenge>.txt`): > 2 GB, private Drive, MEGA… |
| `error`  | the download failed                                                 |

## File tree

Example layout of the generated files:

```
MyCTF/                               # your CTF root (BASE_DIR)
├── config.sh                        # URL + token (never displayed)
├── PROGRESS_flagship.md             # generated progress table (press p)
├── FLAGS_flagship.md                # generated flags export (press P)
├── notes-export-*.zip               # all written notes, by category (press N)
├── .flagship/                       # internal cache & state (leave it)
└── CHALLENGES/
    ├── Crypto/
    │   ├── crypto1/
    │   │   ├── <nom-du-challenge>.txt             # challenge statement
    │   │   ├── work/                # downloaded files
    │   │   ├── <nom-du-challenge>.md             # your notes (press e)
    │   │   └── flag.txt             # written when the flag is accepted
    │   └── crypto2/
    │       ├── <nom-du-challenge>.txt
    │       └── work/
    └── Forensics/
        ├── forensics1/
        │   ├── <nom-du-challenge>.txt
        │   ├── work/
        │   └── flag.txt
        └── forensics2/
            ├── <nom-du-challenge>.txt
            └── work/
```

`<nom-du-challenge>.txt` = statement · `work/` = downloaded files · `<nom-du-challenge>.md` = your notes · `flag.txt` = appears once the flag is accepted.

## Tests

```bash
pip install -e ".[test]"
python -m pytest                    # unit + TUI tests, against an in-process fake CTFd (no network)
```

Live tests run against a **local, fictional** CTFd lab (never a real CTF). Clone the official
CTFd repository, install its requirements, then seed a lab and point the tests at it:

```bash
git clone --depth 1 https://github.com/CTFd/CTFd.git /path/to/CTFd
python tests/lab/seed_ctfd.py /path/to/CTFd /path/to/lab/ctfd.db 8101 users /path/to/lab/token
FLAGSHIP_LIVE_URL=http://127.0.0.1:8101 FLAGSHIP_LIVE_MODE=solo \
  FLAGSHIP_LIVE_TOKEN="$(cat /path/to/lab/token_player)" FLAGSHIP_LIVE_ADMIN_TOKEN="$(cat /path/to/lab/token)" \
  python -m pytest tests/test_live_ctfd.py tests/test_live_tui.py
```

The seed script writes the tokens to files (never printed). Use `users` or `teams` as the mode.

## Notes

- Solo or team is auto-detected.
- CTF over or offline: Flagship shows the last cached sync.
- Built for CTFd; other platforms aren't supported.
