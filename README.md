# 🚩 Flagship

## 📖 Documentation

- 🇫🇷 **[Français](doc/FR.md)**
- 🇬🇧 **[English](doc/EN.md)**

## ⚡ Démarrage rapide / Quick start

```bash
cd /workspace/flagship
pip install -e .                     # deps + commande `flagship` (ou: pip install -r requirements.txt)
cp config.sh.example config.sh       # renseigner URL + token / set URL + token
flagship config.sh                   # (ou ./flagship.sh config.sh)
flagship --offline config.sh         # hors ligne : cache local seulement, aucun appel à l'API
```

## 🖱️ Souris dans tmux / Mouse in tmux

- FR : avec `tmux-mighty-scroll`, ajouter `set -g @mighty-scroll-fallback-mode 'pass-through'` **avant** sa ligne `@plugin`, sinon la molette ne défile pas dans Flagship.
- EN : with `tmux-mighty-scroll`, add `set -g @mighty-scroll-fallback-mode 'pass-through'` **before** its `@plugin` line, otherwise the wheel does not scroll Flagship.

---