# 🚩 Flagship

*Un nouveau CTF, et c'est reparti : créer les dossiers, télécharger les fichiers, suivre ce qui est
résolu, retrouver ses notes… Flagship automatise toute cette plomberie ; il ne reste plus qu'à
résoudre les challenges.*
*A new CTF, and it all starts over: creating folders, downloading files, tracking solves, keeping
notes… Flagship automates all this plumbing, leaving just one thing to do: solve the challenges.*

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

Raccourcis / Shortcuts : `↑↓`·Enter · `d` télécharger/download · `D` tout sync/sync all ·
`/` search · `r` refresh · `f` filter · `o` sort · `s` flag · `u` hint ·
`c` copy · `w` folder · `e` notes · `p` progress · `q` quit · drag `┃` to resize panes.
Interface language: English. / Interface en anglais.
Onglets / Tabs : Challenges · Scoreboard · Stats · Notifications.

> Le fichier `config.sh` contient le token : il est git-ignoré. / holds the token: git-ignored.

---

*Flagship a été conçu et développé avec [Claude Code](https://claude.com/claude-code).*
*Flagship was designed and built with [Claude Code](https://claude.com/claude-code).*
