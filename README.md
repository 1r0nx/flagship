# 🚩 Flagship

Une **TUI** pour n'importe quel CTF sous **CTFd** : synchronise les challenges en dossiers,
et permet de **parcourir, lire et soumettre les flags** depuis le terminal.
*A **TUI** for any **CTFd** CTF: syncs challenges into folders, lets you **browse, read and
submit flags** from the terminal.*

## 📖 Documentation

- 🇫🇷 **[Français → `doc/FR.md`](doc/FR.md)**
- 🇬🇧 **[English → `doc/EN.md`](doc/EN.md)**

## ⚡ Démarrage rapide / Quick start

```bash
cd /workspace/flagship
pip install -e .                     # deps + commande `flagship` (ou: pip install -r requirements.txt)
cp config.sh.example config.sh       # -> mets URL + token / set URL + token
flagship config.sh                   # (ou ./flagship.sh config.sh)
```

Par défaut, le lancement **liste** juste les challenges (aucun téléchargement). / By default,
launch just **lists** challenges (no download).

Raccourcis / Shortcuts : `↑↓`·Enter · `d` télécharger/download · `D` tout sync/sync all ·
`/` search · `r` refresh · `f` filtre · `o` tri/sort · `s` flag · `u` indice/hint ·
`c` copier/copy · `e` notes · `p` progress · `n` notifs · `q` quit.

> `config.sh` contient ton token → il est git-ignoré. / holds your token → git-ignored.
