# CLAUDE.md — Flagship (tests et vérification)

Ce fichier s'applique au repo `flagship/`. Il précise comment tester l'application. Les règles
générales de `/workspace/CLAUDE.md` restent valables (jamais de token affiché, pas de soumission de flag,
propriété des fichiers `chown 1000:rvm` après chaque modification sous `/workspace`).

## 1. Préparer l'environnement

```bash
cd /workspace/flagship
python3 -m venv .venv                       # .venv/ est ignoré par git
.venv/bin/pip install -e ".[test]"          # textual, requests, gdown, pytest, ruff
.venv/bin/pip install pexpect               # requis par tests/test_quit.py (sinon ce test est sauté)
```

## 2. Lancer la batterie complète (obligatoire avant de dire « c'est bon »)

```bash
.venv/bin/python -m pytest tests/ -q        # attendu : tout passe, 10 tests « live » sautés sans lab
.venv/bin/ruff check flagship tests --select F,E,W,B,UP --ignore E501,UP031   # attendu : All checks passed!
.venv/bin/python -m pyflakes flagship tests                                    # attendu : aucune sortie
```

Un test qui échoue n'est pas « un problème de l'environnement » tant qu'il n'est pas expliqué.
Ne jamais modifier un test pour le faire passer sans avoir compris pourquoi il échoue.

## 3. Ce que couvrent les tests

| Fichier | Couvre |
|---|---|
| `test_config.py` | lecture de `config.sh`, valeurs par défaut, guillemets, commentaires, BOM |
| `test_ctfd_client.py` | client CTFd contre le faux serveur : erreurs HTTP, mode équipe, solves |
| `test_store_unit.py` | nommage, migration `desc.txt`, notes, tentatives, exports, téléchargements |
| `test_store_sync.py` | synchro, versions de description, indices, téléchargements complets |
| `test_app_helpers.py` | fonctions pures de l'interface (formatage, classement, historique membre) |
| `test_app_tui.py` | l'application réelle en mode headless : touches, actions, fenêtres |
| `test_notes_export.py` | export des notes (zip, fenêtre de choix, annulation) |
| `test_docs_consistency.py` | touches, configuration, thèmes et structure EN/FR identiques au code |
| `test_quit.py` | `q` ne doit pas attendre les requêtes en vol (pseudo-terminal, serveur lent) |
| `test_live_ctfd.py`, `test_live_tui.py` | CTFd réel (lab local), voir la section 4 |

Le faux serveur (`tests/fake_ctfd.py`) est déterministe : il sert à tout ce qui concerne les cas
d'erreur, les délais et les données précises. Les tests live servent à vérifier le comportement
réel de CTFd (prérequis, dates, mode équipe).

## 4. Tests live contre un lab CTFd local (fictif)

Ne jamais pointer ces tests vers une vraie plateforme de CTF.

1. Cloner le dépôt officiel : `git clone --depth 1 https://github.com/CTFd/CTFd.git <dossier>`,
   puis installer ses dépendances dans un venv séparé (`pip install -r requirements.txt`).
2. Amorcer un lab (une instance par mode) : `python tests/lab/seed_ctfd.py <dossier CTFd> <base.db> <port> users|teams <fichier_token>`.
   Le script lance le serveur lui-même ; il écrit le token admin dans `<fichier_token>` et le token
   joueur dans `<fichier_token>_player`. Ne jamais afficher ces fichiers.
3. Lancer les tests avec les variables d'environnement :
   ```bash
   FLAGSHIP_LIVE_URL=http://127.0.0.1:8101 FLAGSHIP_LIVE_MODE=solo \
     FLAGSHIP_LIVE_TOKEN="$(cat <fichier_token>_player)" FLAGSHIP_LIVE_ADMIN_TOKEN="$(cat <fichier_token>)" \
     .venv/bin/python -m pytest tests/test_live_ctfd.py tests/test_live_tui.py -q
   ```
   Pour le mode équipe : port 8102, `FLAGSHIP_LIVE_MODE=team`, et les tokens de l'instance équipe.
4. Après un redémarrage de la machine, les labs ne tournent plus : les relancer avant les tests live
   (sur les bases existantes, sans les supprimer).
5. Les tests live passent deux fois de suite sur le même lab : ils créent leurs propres challenges.

Attendu : solo 9 passent + 1 sauté, équipe 10 passent.

## 5. Vérifier une modification de l'interface

En plus de la batterie, pour toute modification de `app.py` :

- **Ajouter ou modifier une touche** : la mettre dans `BINDINGS` ET dans les deux tableaux de touches de
  `doc/EN.md` et `doc/FR.md`. `test_docs_consistency.py` échoue sinon. Ajouter un test pilote
  (`pilot.press(...)`) qui vérifie l'effet réel de la touche.
- **Nouvelle fenêtre** : un test qui l'ouvre, interagit avec elle (flèches, Entrée, Échap) et vérifie le
  résultat sur disque ou à l'écran.
- **Texte visible** : en anglais uniquement (`test_user_facing_strings_are_english` le vérifie).
- **Performance d'affichage** : sur un volume de 500 challenges, reconstruire l'arbre doit rester sous
  ~150 ms (mesure avec un script jetable dans le scratchpad, jamais dans le repo).

Vérification visuelle optionnelle : `app.save_screenshot(...)` dans un test jetable, puis contrôler
les dimensions des widgets (`widget.size`), pas seulement leur présence.

## 6. Règles de sécurité pour les tests

- Ne jamais utiliser `tmux kill-server` sans `-L <socket privé>` : cela fermerait les sessions de
  l'utilisateur. Pour tester tmux, utiliser un serveur dédié (`tmux -L flagship-test ...`) et le
  terminer avec `tmux -L flagship-test kill-server`.
- Ne jamais lancer Flagship contre les dossiers réels d'un CTF : utiliser une copie des fichiers texte
  (`CHALLENGES/**/*.txt|*.md|.flagship.json`) dans le scratchpad, avec une copie de `config.sh` pointant
  vers cette copie.
- Ne jamais écrire de token dans le repo, un test, un log ou une réponse.
- `tests/conftest.py` réinitialise le drapeau d'arrêt (`shutdown.reset()`) avant chaque test. Un test qui
  appelle `action_quit` doit rester isolé.

## 7. Avant de rendre un travail

- Batterie complète verte (section 2), tests live verts sur les deux labs si le lab tourne.
- Propriété des fichiers modifiés remise à `1000:rvm`.
- Rien n'est commité sauf demande explicite.
