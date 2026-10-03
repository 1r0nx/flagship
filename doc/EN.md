# 🚩 Flagship (Documentation EN)

New CTF, same routine: folders, downloads, tracking what's solved, keeping notes. Flagship
handles all that, you just solve challenges.

A terminal app for CTFd. Lists challenges, downloads files, tracks what you solved, lets you
submit flags. No browser needed.

![Flagship screenshot](img/screenshot.png)

> The interface is in **English** (labels, toasts, errors), same for generated files
> (`desc.txt`, `downloads.txt`, `notes.md`, `PROGRESS_flagship.md`).

## What it does

- Lists every challenge on launch. Nothing downloads until you ask.
- `d` downloads one challenge, `D` downloads all of them, `C` a whole category.
- Description or hints changed later? Old `desc.txt` stays, a new `desc2.txt` is saved next to
  it, with what changed.
- Five tabs: Challenges, Scoreboard, Stats, Flags, Notifications.
- Search (`/`, lives on the filter/sort line, costs no extra height) matches name, category,
  and the description if it's already cached. Filter (`f`): all, unsolved, solved, bookmarked.
  Sort (`o`, 8 ways: points, solves, name, id...).
- Bookmark a challenge with `b` to pin it for later, shows as a `★` in the list.
- Submit flags from the terminal. A flag already tried and rejected is never resent.
- Unlock hints on demand, with confirmation for paid ones.
- Resizable panes: drag `┃` between the list and the detail, double-click resets it.
- Detail panel split into INFO / DESCRIPTION / HINT(S), with centered dividers.
- Stats tab: score, rank, solved, points, downloaded, first bloods. Team mode adds a
  per-member breakdown, click a name for their stats, and the detail panel shows who on the
  team actually solved each one.
- Click "N solves" on a challenge to see who solved it: players in solo mode, teams in team
  mode (your own team starred, with the teammate who solved it). CTFd never exposes which
  member of another team solved, only its name: that's a platform limit, not Flagship's.
- Dynamic-value challenges show their point range (initial → minimum). Limited-attempt ones
  show how many you have left. Flags you already tried and got rejected stay listed, so you
  never retype one by mistake.
- Flags tab: every validated flag so far (category, challenge, points), as long as `flag.txt`
  was written for it. `P` exports the list to `FLAGS_flagship.md`.
- Works solo or in a team, same keys either way.
- CTF over or offline? Shows your last synced data, nothing lost.

## Install

```bash
cd /workspace/flagship
pip install -e .            # installs Flagship + deps, adds the `flagship` command
# or: pip install -r requirements.txt
```

> If you move the folder after `pip install -e .`, run it again from the new location.
> `./flagship.sh` and `python -m flagship` work from anywhere without reinstalling.

## Configure

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
WATCH_CHANGES=true         # track desc/hint changes ; false = lighter sync
AUTO_UNLOCK_FREE_HINTS=false # auto-unlock free (cost 0) hints
DOWNLOAD_WORKERS=6         # parallel downloads for "Sync all"
THEME=textual-dark         # start theme (nord, gruvbox, dracula... ; `t` to cycle)
```

Token variable can also be named `TOKEN` or anything ending in `_TOKEN`. `config.sh` is
git-ignored: never share it, it holds the token.

## Run

```bash
./flagship.sh                 # uses ./config.sh
./flagship.sh path/config.sh
# or: python3 -m flagship [config.sh]
```

`flagship.sh` resolves the config path first, then moves into its own folder. Works from
anywhere, with any `config.sh`.

## One tool, many CTFs

Clone Flagship once. Each CTF gets its own folder and `config.sh`, pointed at with `BASE_DIR`.

```
~/ctfs/
├── flagship/          # cloned once
└── HeroCTF/
    └── config.sh      # URL + token + BASE_DIR=.
```

```bash
mkdir ~/ctfs/HeroCTF
cp ~/ctfs/flagship/config.sh.example ~/ctfs/HeroCTF/config.sh
$EDITOR ~/ctfs/HeroCTF/config.sh
~/ctfs/flagship/flagship.sh ~/ctfs/HeroCTF/config.sh
```

An alias saves retyping the path:

```bash
alias flagship='~/ctfs/flagship/flagship.sh'
flagship ~/ctfs/HeroCTF/config.sh
```

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `↑`/`↓`, Enter | navigate, open a challenge (shows the brief, no download) |
| click tabs | switch between Challenges, Scoreboard, Stats, Flags, Notifications |
| `d` | download/update the selected challenge |
| `D` | sync all (parallel, progress bar, confirmation) |
| `C` | download the category under the cursor (confirmation) |
| `/` | focus the inline search field, filters live as you type |
| `r` | refresh now (list, scoreboard, rank) |
| `f` | cycle filter: all, unsolved, solved, bookmarked |
| `b` | toggle bookmark on the selected challenge |
| `x` | fold all categories, or unfold them all back |
| `o` | cycle sort: category, points, solves, fewest solves, name, id, downloaded first, unsolved first |
| `t` | cycle colour theme (remembered) |
| `s` | focus the flag field |
| `u` | unlock a hint (confirmation) |
| `c` | copy the challenge's connection string |
| `w` | open the challenge folder |
| `e` | edit challenge notes (`notes.md`) |
| `p` | export to `PROGRESS_flagship.md` |
| `P` | export the Flags tab to `FLAGS_flagship.md` |
| `Esc` | leave the field you're in; on search, also clears it |
| drag `┃` | resize list/detail panes (double-click: reset) |
| `Tab` / `Shift+Tab` | move focus |
| `q` | quit |

## Architecture

```
flagship/
├── config.py   # reads config.sh, no shell involved
├── ctfd.py     # CTFd API client
├── store.py    # folder tree, desc.txt, flag.txt, downloads
├── app.py      # the Textual TUI
└── __main__.py # entry point
```

`ctfd.py` calls: `GET /challenges`, `/challenges/<id>` (detail + prerequisites),
`/users/me` or `/teams/me` (detected mode), `/…/solves`, `/scoreboard`,
`/challenges/<id>/solves` (first blood), `POST /challenges/attempt` (submit),
`POST /unlocks` (hints). Errors show up in the TUI, they never crash it.

`store.py`: `slugify()` turns a name into a folder name. Spaces become `-`, no doubled dashes,
and shell-special characters (`` ' " ` $ ! ; & | ( ) < > { } [ ] * ? ~ # = % ``) are dropped
outright rather than replaced, so `"Anakin's PC"` becomes `Anakins-PC`, not `Anakin's-PC`.
`list_state()` just lists; `download_one()`, `download_subset()`, `sync()` download.
A hidden `.flagship.json` per challenge tracks whether desc/hints changed, so `descN.txt`
only gets written when something actually did. Incorrect flags are remembered in
`.flagship/attempts.json` so they're never resent.

`app.py`: network calls run in threaded workers, UI stays responsive. A challenge's detail
loads on selection, then stays cached.

## Downloads

Only on demand (`d`, `D`, or `C`). Each challenge gets a `downloads.txt` report
(`ok`/`skip`/`manual`/`error`). Links always end up in `desc.txt` either way.

| Source | Behaviour |
|--------|-----------|
| CTFd-hosted file | downloaded (authenticated), 2 GB guard |
| Direct http(s) link | downloaded, no token sent, 2 GB guard |
| Dropbox | rewritten to a direct link, then downloaded |
| Google Drive | via `gdown`, or `manual` if private |
| MEGA | via `megatools` if installed, else `manual` |
| Over 2 GB | not downloaded, marked `manual` |

`d` is self-healing: recreates `desc.txt` if missing, completes whatever's missing in
`work/`. The CTFd token never goes to a third-party host.

## Notes

- Solo or team is auto-detected. In team mode, score/rank/solved shown are the **team's**.
- Solved status comes from the API, or a local `flag.txt` as fallback.
- Paid hints always ask for confirmation first.
- CTF over or API down: Flagship shows the last cached sync instead of an empty screen.
- Built for CTFd. Other platforms aren't supported.
