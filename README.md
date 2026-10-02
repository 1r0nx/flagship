# 🚩 Flagship

*Nouveau CTF, même routine : dossiers, téléchargements, suivi des résolus, notes à garder.
Flagship s'en charge, toi tu résous les challenges.*
*New CTF, same routine: folders, downloads, tracking what's solved, keeping notes. Flagship
handles all that, you just solve challenges.*

Une **TUI** pour n'importe quel CTF sous **CTFd** : synchronise les challenges en dossiers,
et permet de **parcourir, lire et soumettre les flags** depuis le terminal.
*A **TUI** for any **CTFd** CTF: it syncs challenges into folders and lets users **browse, read and
submit flags** from the terminal.*

## 📖 Documentation

- 🇫🇷 **[Français → `doc/FR.md`](doc/FR.md)**
- 🇬🇧 **[English → `doc/EN.md`](doc/EN.md)**

## ⚡ Démarrage rapide / Quick start

```bash
cd /workspace/flagship
pip install -e .                     # deps + commande `flagship` (ou: pip install -r requirements.txt)
cp config.sh.example config.sh       # renseigner URL + token / set URL + token
flagship config.sh                   # (ou ./flagship.sh config.sh)
```

Par défaut, le lancement **liste** seulement les challenges (aucun téléchargement). / By default,
launch just **lists** challenges (no download).

Raccourcis / Shortcuts : `↑↓`·Enter · `d` download · `D` sync all · `/` search (inline, no extra
height) · `r` refresh · `f` filter · `o` sort · `s` flag · `u` hint · `c` copy · `w` folder ·
`e` notes · `p` progress · `q` quit · drag `┃` to resize panes.
Interface language: English. / Interface en anglais.
Onglets / Tabs : Challenges · Scoreboard · Stats · Notifications.

> Le fichier `config.sh` contient le token : il est git-ignoré. / holds the token: git-ignored.

---

*Flagship a été conçu et développé avec [Claude Code](https://claude.com/claude-code).*
*Flagship was designed and built with [Claude Code](https://claude.com/claude-code).*
