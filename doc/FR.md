# 🚩 Flagship — Documentation (FR)

Une **TUI** (interface terminal) pour n'importe quel CTF sous **CTFd**.
Elle **synchronise** les challenges dans une arborescence de dossiers propre, et te laisse
**parcourir, lire et soumettre les flags** sans quitter le terminal.

```
┌ Flagship — MonCTF — score 8270 (#3) ── 12/40 résolus · 8 téléch. · tri : catégorie ┐
│ Pwn (3/8)                │  # 2 - Return                              │
│  ✔✓ 0 - Overflow 100·12✓ │  Catégorie : Pwn · Points : 200 · ○        │
│  ○⬇ 2 - Return   200·5✓  │  🩸 First blood : team_x                    │
│ Crypto (5/9)             │  Connexion : nc chal... 1389               │
│  ✔✓ First XOR    50·30✓  │  --- Can you pwn this problem? ...          │
│  ○⬇ RSA          150·5✓  ├────────────────────────────────────────────┤
│                          │ 🚩 Flag (Entrée = soumettre)…              │
└ d Télécharger  D Tout sync  / Rechercher  f Filtre  o Tri  q Quitter ──┘
```
Marqueurs : `✔`/`○` résolu · `✓`/`⬇` téléchargé · `pt · N✓` points et nb de solves.

## Ce que ça fait

1. **Configuration** — tu remplis un `config.sh` avec l'URL du CTF et ton token CTFd.
2. **Listing léger (par défaut, AUCUN téléchargement massif)** — au lancement, Flagship
   interroge l'API et **liste** les challenges dispo avec leur statut. Il ne crée **rien** sur
   le disque tant que tu ne le demandes pas. La liste se rafraîchit **toute seule** (intervalle
   configurable) : un nouveau challenge débloqué apparaît automatiquement (notification 🆕).
3. **Téléchargement à la demande** — dans la TUI :
   - **`d`** télécharge **le challenge sélectionné** → crée `<base>/CHALLENGES/<Catégorie>/<Nom>/`
     avec `desc.txt` et `downloads.txt`, et les **fichiers rangés dans `work/`**. Les challenges
     sont regroupés sous **`CHALLENGES/`** ; la racine du CTF ne garde que `config.sh`,
     `PROGRESS.md`, `.flagship/` (état/journal).
   - **`D`** = **« Tout synchroniser »** (avec confirmation) → télécharge **tous** les challenges.
   C'est **idempotent** : rien n'est écrasé ni supprimé ; un fichier déjà présent n'est pas
   re-téléchargé.
4. **Versionnage des énoncés** — pour les challenges **déjà téléchargés**, si la **description**
   ou les **indices** changent, l'ancien `desc.txt` **n'est pas écrasé** : une nouvelle version
   `desc2.txt`, `desc3.txt`… est créée (avec date + ce qui a changé). Les **indices** sont suivis
   (gratuits comme payants) : nouvel indice, indice débloqué, changement de coût.
5. **TUI** — deux onglets :
   - **Challenges** : navigation par catégorie ; par challenge : statut (✔/○), **état de
     téléchargement** (✓/⬇), **points** et **nombre de solves** ; détail avec **first blood**,
     connexion, fichiers, indices ; description consultable **sans** télécharger ; **recherche**
     (`/`), **filtres** (`f` : tous/non résolus/résolus), **tri** (`o` : catégorie/points/solves) ;
     **soumission** (`flag.txt` écrit si validé), **téléchargement**/retry (`d`), **« Tout
     synchroniser »** (`D`, parallèle + barre de progression), **déblocage d'indice** (`u`),
     **copier la connexion** (`c`), **notes** (`e`, `notes.md`), **export PROGRESS.md** (`p`).
     L'en-tête affiche **ton score et ton rang**.
   - **Scoreboard** : classement (position, équipe/joueur, score) ; **ta ligne est surlignée** et
     le curseur s'y positionne.
   - **Thèmes** : plusieurs thèmes de couleurs (clair/sombre : nord, gruvbox, dracula…), `t` pour
     cycler, mémorisés. **Mode hors-ligne** : si l'API est injoignable, la dernière liste
     synchronisée (cache) est affichée.
6. **Notifications** — chaque changement (nouveau challenge dispo, description modifiée, indice
   nouveau/débloqué, flag validé, téléchargement) déclenche un **toast** et est **journalisé**
   (`.flagship/notifications.log`). Touche `n` pour revoir l'historique.

## Installation

```bash
cd /workspace/flagship
pip install -r requirements.txt     # textual + requests (+ gdown pour Google Drive)
```

Ou, mieux, en **paquet installable** (crée la commande `flagship` disponible partout) :
```bash
cd /workspace/flagship
pip install -e .            # installe Flagship + dépendances -> commande `flagship`
# ensuite, de n'importe où :  flagship chemin/config.sh
```
> ⚠️ Si tu **déplaces le dossier** après un `pip install -e .`, relance `pip install -e .` depuis
> le nouvel emplacement (l'install *editable* pointe vers l'ancien chemin). `./flagship.sh` et
> `python -m flagship`, eux, fonctionnent depuis n'importe où sans réinstaller.

## Configuration

Copie l'exemple et édite-le :

```bash
cp config.sh.example config.sh
$EDITOR config.sh
```

```sh
URL=https://ctf.example.com          # URL du CTFd
CTFD_TOKEN=ctfd_xxxxxxxxxxxxxxxxxxx  # token (CTFd > Settings > Access Tokens)

# optionnel
CTF_NAME=MonCTF            # nom affiché + dossier par défaut
BASE_DIR=./MonCTF          # racine des dossiers générés (relatif au config.sh)
POLL_INTERVAL=60           # synchro auto toutes les N s (0 = désactivée)
WRITE_FLAG_ON_SOLVE=true   # écrire flag.txt quand un flag est validé
WATCH_CHANGES=true         # suivre les changements desc/indices (desc2.txt...) ; false = + léger
AUTO_UNLOCK_FREE_HINTS=false # débloquer automatiquement les indices gratuits (coût 0)
DOWNLOAD_WORKERS=6         # téléchargements en parallèle pour « Tout synchroniser »
THEME=textual-dark         # thème de départ (nord, gruvbox, dracula, tokyo-night… ; `t` pour cycler)
```

- Le **token n'est jamais affiché ni journalisé**. Le nom de la variable peut aussi être
  `TOKEN` ou n'importe quel `*_TOKEN` (ex. `PWNY_CTFD_TOKEN`) — Flagship le détecte.
- `config.sh` est ignoré par git (voir `.gitignore`) : ne le partage pas, il contient ton token.

## Lancement

```bash
./flagship.sh                 # utilise ./config.sh
./flagship.sh chemin/config.sh
# ou :
python3 -m flagship [config.sh]
```

Le launcher `flagship.sh` **résout le chemin du `config.sh` en absolu** puis se place dans le
dossier de l'outil (pour que `python -m flagship` trouve le package) → tu peux le lancer depuis
n'importe où avec n'importe quel `config.sh`.

## Workflow multi-CTF (cloner une seule fois)

Flagship est **l'outil** ; l'arborescence d'un CTF est séparée (c'est `BASE_DIR`). Pas besoin de
re-cloner à chaque CTF.

**1. Une seule fois — installer l'outil :**
```bash
git clone <ton-repo>/flagship ~/ctfs/flagship
cd ~/ctfs/flagship
pip install -r requirements.txt      # textual + requests + gdown
```

**2. Pour chaque nouveau CTF (ex. HeroCTF) — un dossier + un config :**
```bash
mkdir ~/ctfs/HeroCTF
cp ~/ctfs/flagship/config.sh.example ~/ctfs/HeroCTF/config.sh
$EDITOR ~/ctfs/HeroCTF/config.sh     # -> URL, CTFD_TOKEN, BASE_DIR=.
```
```
~/ctfs/
├── flagship/          ← cloné UNE fois (l'outil)
└── HeroCTF/           ← créé par CTF ; l'arbre se génère ici
    └── config.sh      ← URL + token + BASE_DIR=.
```
> `BASE_DIR` est résolu **par rapport au dossier du `config.sh`**. `BASE_DIR=.` → les challenges
> apparaissent dans `HeroCTF/<Catégorie>/<Challenge>/`.

**3. Démarrer (depuis n'importe où) :**
```bash
~/ctfs/flagship/flagship.sh ~/ctfs/HeroCTF/config.sh
# équivalent :
cd ~/ctfs/flagship && python3 -m flagship ~/ctfs/HeroCTF/config.sh
```

**Astuce — un alias pour ne plus retaper le chemin** (dans `~/.zshrc` / `~/.bashrc`) :
```bash
alias flagship='~/ctfs/flagship/flagship.sh'
# puis :  flagship ~/ctfs/HeroCTF/config.sh
```

**Variante** : cloner Flagship *dans* le dossier du CTF (`HeroCTF/flagship/`) fonctionne aussi —
mets alors `BASE_DIR=..` dans son `config.sh` pour générer l'arbre dans `HeroCTF/`. Mais tu clones
l'outil à chaque fois (moins pratique).

> Sécurité : `config.sh` (avec ton token) est **git-ignoré**. Sur une nouvelle machine, recrée-le
> à partir de `config.sh.example`.

### Raccourcis clavier

| Touche | Action |
|--------|--------|
| `↑`/`↓`, Entrée | naviguer / ouvrir un challenge (affiche l'énoncé, sans télécharger) |
| clic sur les onglets | basculer Challenges ↔ Scoreboard |
| `d` | **télécharger** le sélectionné (ou **re-télécharger/retry** s'il est déjà là) |
| `D` | **Tout synchroniser** (parallèle + barre de progression, confirmation) |
| `/` | aller à la barre de recherche |
| `r` | actualiser la liste maintenant (+ scoreboard + rang) |
| `f` | changer de filtre (tous → non résolus → résolus) |
| `o` | changer le tri (catégorie → points → solves) |
| `t` | changer de thème de couleurs (cycle, persisté) |
| `s` | aller au champ de soumission du flag |
| `u` | débloquer un indice (confirmation) |
| `c` | copier la connexion (`nc …`/URL) du challenge |
| `e` | éditer les **notes** du challenge (`notes.md`, éditeur `$EDITOR`) |
| `p` | exporter un récap **PROGRESS.md** |
| `n` | afficher l'historique des notifications |
| `Échap` | quitter un champ de saisie (recherche/flag) → focus sur la liste |
| `Tab` / `Maj+Tab` | passer d'un élément à l'autre (focus suivant/précédent) |
| `q` | quitter |

- **Soumettre** : sélectionne un challenge, `s`, tape le flag, **Entrée** → `✔ Correct` / `✘`.
- **Rechercher** : `/`, tape une partie du nom (l'arbre se filtre en direct).
- **Débloquer un indice** : `u` → confirme (le moins cher est proposé). ⚠️ un indice payant
  réduit ton score, d'où la confirmation.

## Comment ça marche (architecture)

```
flagship/
├── config.py   # lit config.sh (CLE=valeur), sans exécuter de shell
├── ctfd.py     # client API CTFd : challenges, détail, solves, submit, unlock, download
├── store.py    # arborescence + desc.txt + flag.txt + slugify + téléchargements
├── app.py      # la TUI Textual (onglets, détail, soumission, poll auto, notifs)
└── __main__.py # point d'entrée (python -m flagship)
```

- **`config.py`** parse `config.sh` ligne par ligne (`export`/guillemets/commentaires tolérés).
  Aucun `source` shell n'est exécuté → pas d'effet de bord.
- **`ctfd.py`** encapsule l'API :
  - `GET /api/v1/challenges` (liste), `GET /api/v1/challenges/<id>` (détail),
  - `GET /api/v1/users/me/solves` (résolus), `GET /api/v1/scoreboard` (classement),
  - `POST /api/v1/challenges/attempt` (soumission), `POST /api/v1/unlocks` (déblocage d'indice),
  - téléchargement des fichiers listés. Les erreurs (CTF fermé, réseau…) remontent proprement
    et s'affichent dans la TUI sans planter.
- **`store.py`** :
  - `slugify()` applique le nommage : espaces → `-`, **jamais de tirets consécutifs**
    (`0 - Overflow` → `0-Overflow`, `Bruh 0: Exif` → `Bruh-0:-Exif`), `/` et `\` → `-`.
  - `list_state()` (défaut) liste les challenges + statut + **état de téléchargement**, sans rien
    créer ; `download_one()` télécharge un challenge ; `sync()` (« Tout synchroniser ») télécharge
    tout. Elles renvoient les **événements** (desc/indices modifiés sur les challenges suivis).
  - **Versionnage** : un état caché `.flagship.json` par challenge mémorise les empreintes
    (SHA-256) de la description et des indices. Si ça change → `descN.txt` (jamais d'écrasement).
    Quand `WATCH_CHANGES=false`, le détail n'est récupéré que pour les nouveaux challenges
    (synchro plus légère, mais pas de détection de changement).
  - `write_flag()` écrit `flag.txt` (jamais par-dessus un existant).
- **Notifications** : les toasts sont aussi écrits dans `<base>/.flagship/notifications.log`
  (historique consultable avec `n`).
- **État d'interface persistant** : le filtre, le tri, les **catégories pliées/dépliées** et la
  dernière sélection sont mémorisés dans `<base>/.flagship/state.json` → conservés aux rebuilds
  (download/refresh) **et** restaurés à la réouverture de la TUI.
- **`app.py`** (Textual) :
  - Les appels réseau (bloquants) tournent dans des **workers threadés** (`@work(thread=True)`) ;
    l'UI est mise à jour via `call_from_thread` → l'interface ne gèle jamais.
  - `on_mount` lance une première synchro puis programme le **poll** (`set_interval`).
  - Le **détail** d'un challenge est chargé à la sélection et **mis en cache**.

## Téléchargements

Les téléchargements n'ont lieu **qu'à la demande** (`d` sur un challenge, ou `D` pour tout).
Quand un challenge est téléchargé, Flagship range ses fichiers dans **`work/`** et écrit un rapport
`downloads.txt` (`ok` / `manual` / `error`) à la racine du challenge. Dans **tous** les cas, les
**liens** sont présents dans `desc.txt` (section *Fichiers (plateforme)* avec URL complète, et
*Liens externes*).

| Source | Comportement |
|--------|--------------|
| Fichier hébergé par le CTFd | téléchargé (authentifié), garde-fou **2 Go** |
| Lien **http(s)** direct | téléchargé **sans** envoyer ton token, garde-fou 2 Go |
| **Dropbox** | réécrit en lien direct (`?dl=1`) puis téléchargé |
| **Google Drive** (fichier) | via `gdown` si public ; sinon → `manual` (lien conservé) |
| **Google Drive** (dossier) | via `gdown.download_folder` |
| **MEGA** | via `megatools`/`megadl` **si installé** ; sinon → `manual` (lien conservé) |
| Fichier **> 2 Go** | non téléchargé → `manual` (à toi de le récupérer) |

- **« Tout synchroniser »** (`D`) télécharge **en parallèle** (`DOWNLOAD_WORKERS`) avec une
  **barre de progression**.
- **`d` sur un challenge déjà téléchargé** = **retry** : retente uniquement les fichiers
  manquants/en échec (voir `downloads.txt`).
- Ton **token CTFd n'est jamais envoyé à un hôte tiers** (Drive, MEGA…). Le garde-fou Drive est
  vérifié *a posteriori* (gdown ne connaît pas la taille à l'avance).

## Notes / limites

- Le **statut résolu** vient de l'API (`/users/me/solves`) et, à défaut, de la présence d'un
  `flag.txt` local.
- Les **indices** sont affichés (coût + verrouillé/débloqué). Le déblocage se fait **à la
  demande** (touche `u`) avec **confirmation** — jamais automatiquement, car ça coûte des points.
- Si le CTF est **terminé/fermé**, l'API renvoie un message d'erreur : Flagship l'affiche et
  garde l'arborescence déjà synchronisée.
- Pensé pour CTFd (self-hosted ou sigpwny-like). D'autres plateformes ne sont pas gérées.
