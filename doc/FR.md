# 🚩 Flagship (Documentation FR)

*Un nouveau CTF, et c'est reparti : créer les dossiers, télécharger les fichiers, suivre ce qui est
résolu, retrouver ses notes… Flagship automatise toute cette plomberie ; il ne reste plus qu'à
résoudre les challenges.*

Flagship est une interface en terminal (TUI) pour les CTF basés sur **CTFd**. L'outil synchronise
les challenges dans une arborescence de dossiers organisée et permet de les parcourir, de lire les
énoncés et de soumettre les flags sans quitter le terminal.

```
┌───────────────────────────────Flagship───────────────────────────────┐
│▣ ▢ files  ● ○ solved              │ # 2 - Return                     │
│filter: all  sort: points  search: │ ──────────INFO──────────         │
│Pwn (3/8)                          │ Category: Pwn · Points: 200 · ○  │
│ ▣ ●  0 - Overflow 100·12 solves   │ Connection: nc chal... 1389      │
│ ▣ ○  2 - Return   200·5 solves    │ ───────DESCRIPTION───────        │
│Crypto (5/9)                       │ Can you pwn this problem? ...    │
│ ▢ ●  First XOR    50·30 solves    ├──────────────────────────────────┤
│ ▢ ○  RSA          150·5 solves    │ 🚩                                │
└ d Download  D Sync all  w Folder  u Hint  / Search  f Filter  o Sort ─┘
```

> **Langue de l'interface** : l'interface de Flagship (libellés, notifications, messages d'erreur,
> boîtes de confirmation) est **en anglais**, de même que les fichiers générés (`desc.txt`,
> `downloads.txt`, `notes.md`, `PROGRESS_flagship.md`). Cette documentation française en reprend
> donc les libellés anglais tels qu'ils s'affichent à l'écran.

Les marqueurs de chaque ligne sont rappelés par une légende en haut de la colonne de gauche :
`▣`/`▢` pour les fichiers téléchargés, `●`/`○` pour l'état résolu, et `N pt · N solves` pour les
points et le nombre de solves. Deux formes distinctes (carré pour les fichiers, cercle pour le
statut) et une couleur rendent l'état lisible d'un coup d'œil, avec un alignement constant quelle
que soit la combinaison. Juste en dessous se trouve la ligne filtre/tri/recherche (voir plus bas).
L'icône de palette de commandes de l'en-tête est masquée (`⭘`, en haut à gauche dans une app Textual
standard) — elle n'est reliée à rien dans Flagship.

## Fonctionnalités

### Configuration par fichier

Un fichier `config.sh` contient l'URL du CTF et le token CTFd. Aucune autre configuration n'est
nécessaire pour démarrer.

### Listing léger par défaut (aucun téléchargement massif)

Au lancement, Flagship interroge l'API et liste les challenges disponibles avec leur statut. Rien
n'est créé sur le disque tant qu'un téléchargement n'est pas demandé. La liste se rafraîchit
automatiquement selon un intervalle configurable : un challenge nouvellement débloqué apparaît
seul, accompagné d'une notification.

### Téléchargement à la demande

Depuis la TUI :

- La touche `d` télécharge le challenge sélectionné. Elle crée
  `<base>/CHALLENGES/<Catégorie>/<Nom>/` contenant `desc.txt` et `downloads.txt`, et place les
  fichiers dans un sous-dossier `work/`. Les challenges sont regroupés sous `CHALLENGES/` ; la
  racine du CTF ne conserve que `config.sh`, `PROGRESS.md` et `.flagship/` (état et journal).
- La touche `D` déclenche « Tout synchroniser » (après confirmation) et télécharge l'ensemble des
  challenges.

L'opération est idempotente : rien n'est écrasé ni supprimé, et un fichier déjà présent n'est pas
re-téléchargé.

### Versionnage des énoncés

Pour un challenge déjà téléchargé, si la description ou les indices changent, l'ancien `desc.txt`
n'est pas écrasé : une nouvelle version `desc2.txt`, `desc3.txt`, etc. est créée, avec la date et
la nature du changement. Les indices sont suivis, gratuits comme payants : ajout d'un indice,
déblocage, ou modification de coût.

### Interface à quatre onglets

Onglet **Challenges** : navigation par catégorie ; pour chaque challenge, affichage de l'état de
téléchargement (`▣`/`▢`), du statut (`●`/`○`), des points et du nombre de solves. Le panneau de
détail est découpé en trois sections par un séparateur centré `────TITRE────`, dimensionné à la
largeur actuelle du panneau : **INFO** (first blood, connexion, **prérequis** — challenges à
résoudre avant, avec leur état et un indicateur verrouillé/déverrouillé —, dossier, fichiers, liens
externes), **DESCRIPTION**, puis **HINT(S)** (affichée en dernier, uniquement si le challenge a des
indices). La description est consultable sans téléchargement, et les séparateurs se recentrent après
un redimensionnement du panneau (voir « Panneaux redimensionnables » ci-dessous).
L'interface offre une recherche (`/` : intégrée directement sur la ligne filtre/tri, sans jamais
  coûter de hauteur de terminal supplémentaire, qu'elle soit active ou non), des filtres (`f` : tous (valeur au démarrage),
non résolus, résolus), un tri (`o` : catégorie, points, solves, moins de solves, nom A→Z, id CTFd, téléchargés d'abord, non résolus d'abord), la soumission de flag (avec
écriture de `flag.txt` si le flag est correct), le téléchargement ou la mise à jour (`d`), le
téléchargement de toute une **catégorie** (`C`), la synchronisation complète (`D`, parallèle, avec
barre de progression), le déblocage d'indice (`u`), la copie de la connexion (`c`), l'ouverture du
dossier (`w`), l'édition des notes (`e`, `notes.md`) et l'export vers `PROGRESS_flagship.md` (`p`,
sans jamais toucher au `PROGRESS.md` de l'utilisateur). L'en-tête affiche juste le nom de l'app,
centré — score, rang, résolus/téléchargés et le filtre/tri actifs sont volontairement absents,
puisqu'ils sont déjà visibles juste en dessous (la ligne filtre/tri) et dans l'onglet **Stats** ;
les répéter sur la barre de titre n'ajoutait que du bruit.

À la soumission, les flags **incorrects** déjà tentés sont mémorisés : resoumettre un flag identique
est bloqué (avec un avertissement) afin de ne pas gaspiller de tentative. Chaque tentative est aussi
journalisée dans `attempts.log` à la racine du dossier du challenge (utile pour un writeup).

**Panneaux redimensionnables** : une barre verticale `┃` sépare la liste des challenges (à
gauche) du détail (à droite). Un glisser à la souris la déplace pour élargir l'un ou l'autre
panneau (largeurs minimales respectées) ; un double-clic restaure la largeur par défaut (42 %). La
largeur choisie est mémorisée (en pourcentage) dans `.flagship/state.json` (`tree_width`).

Onglet **Scoreboard** : classement avec position, équipe ou joueur, et score. La ligne de
l'utilisateur est surlignée et le curseur s'y positionne.

Onglet **Stats** : un tableau récapitulatif (nom, score et rang, résolus, points gagnés,
téléchargés, et **first bloods**), puis un tableau par catégorie et des barres de progression par
catégorie. Il se met à jour automatiquement. Les first bloods sont comptés en récupérant, en
arrière-plan, le premier solveur de chaque challenge que tu as résolu (un appel API par challenge,
une seule fois — un first blood ne change jamais une fois fixé, le résultat est donc mis en cache
définitivement dans `.flagship/fb_cache.json`, vérifié dans le code source de CTFd :
`get_solves_for_challenge_id()` renvoie toujours l'ordre de résolution définitif et permanent du
compte) ; pendant ce rattrapage, la ligne affiche `· checking N more…` à côté d'un compte
provisoire. Exemple en solo :

| Stat | Value |
|------|-------|
| Player | retro_pw |
| Score | 4210  ·  Rank #7th |
| Solved | 63 / 180 |
| Points earned | 4210 / 11200 |
| Downloaded | 58 / 180 |
| First bloods | 9 / 63 |

En **mode équipe**, le même tableau utilise le nom et le score de l'équipe, le libellé devient
« Team first bloods » (c'est un comportement propre à CTFd, pas un choix de Flagship : en mode
équipe, l'endpoint `/challenges/<id>/solves` renvoie le nom de l'**équipe** qui a résolu, jamais
celui du membre qui a réellement tapé le flag — vérifié dans `get_solves_for_challenge_id()` de
CTFd, qui interroge `Model.name` où `Model` est le modèle Teams), et une section
**« Team members »** s'ajoute en dessous :

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

trié par points, ta propre ligne étant surlignée et marquée « (you) » — ces chiffres viennent de
`/teams/me/solves`, qui (vérifié dans le `SubmissionSchema` de CTFd) attribue bien chaque solve au
membre individuel via un objet imbriqué `user: {id, name}`, contrairement à la liste de solves au
niveau challenge ci-dessus. Chaque **pseudo est cliquable** : un clic ouvre une fenêtre détaillant
les stats propres de ce membre — résolus, points, et **son propre nombre de first bloods** (un
challenge compte pour un membre quand c'est un first blood de l'équipe ET que c'est lui qui l'a
personnellement soumis) :

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

Onglet **Notifications** : l'historique des notifications (les plus récentes en haut), mis à jour en
direct. Chaque événement y apparaît en plus du toast éphémère.

**Thèmes** : plusieurs thèmes de couleurs clairs et sombres (nord, gruvbox, dracula, etc.) ; la
touche `t` fait défiler les thèmes, et le choix est mémorisé. En **mode hors-ligne** (ou **après la
fin du CTF**, quand l'API masque les challenges), Flagship réaffiche la **dernière synchronisation
mise en cache** : liste des challenges, statuts et points, ton score/rang et le scoreboard restent
visibles. Tout est stocké dans `<dossier-du-ctf>/.flagship/` (`challenges_cache.json`,
`me_cache.json`, `scoreboard_cache.json`).

Dans les champs de saisie (recherche et flag), le curseur est affiché sous forme de barre verticale
`▏` (style « I-beam ») plutôt que de bloc inversé. Comme Textual masque le curseur du terminal et
dessine le sien dans une cellule, cette barre est une approximation ; en cas d'incompatibilité, le
rendu revient automatiquement au curseur standard.

### Notifications

Chaque changement (nouveau challenge disponible, description modifiée, indice nouveau ou débloqué,
flag validé, téléchargement) déclenche un toast et est journalisé dans
`.flagship/notifications.log`. L'onglet **Notifications** affiche l'historique (plus récentes en haut).

## Installation

```bash
cd /workspace/flagship
pip install -r requirements.txt     # textual + requests (+ gdown pour Google Drive)
```

Installation recommandée en paquet, qui crée la commande `flagship` disponible partout :

```bash
cd /workspace/flagship
pip install -e .            # installe Flagship et ses dépendances, puis la commande `flagship`
# ensuite, depuis n'importe où :  flagship chemin/config.sh
```

> Remarque : après un déplacement du dossier suivant un `pip install -e .`, relancer
> `pip install -e .` depuis le nouvel emplacement, car l'installation *editable* pointe vers
> l'ancien chemin. Les lanceurs `./flagship.sh` et `python -m flagship` fonctionnent depuis
> n'importe où sans réinstallation.

## Configuration

Copier l'exemple puis l'éditer :

```bash
cp config.sh.example config.sh
$EDITOR config.sh
```

```sh
URL=https://ctf.example.com          # URL du CTFd
CTFD_TOKEN=ctfd_xxxxxxxxxxxxxxxxxxx  # token (CTFd > Settings > Access Tokens)

# optionnel
CTF_NAME=MonCTF            # nom affiché et dossier par défaut
BASE_DIR=./MonCTF          # racine des dossiers générés (relatif au config.sh)
POLL_INTERVAL=60           # synchro auto toutes les N secondes (0 = désactivée)
WRITE_FLAG_ON_SOLVE=true   # écrire flag.txt quand un flag est validé
WATCH_CHANGES=true         # suivre les changements desc/indices (desc2.txt...) ; false = plus léger
AUTO_UNLOCK_FREE_HINTS=false # débloquer automatiquement les indices gratuits (coût 0)
DOWNLOAD_WORKERS=6         # téléchargements en parallèle pour « Tout synchroniser »
THEME=textual-dark         # thème de départ (nord, gruvbox, dracula, tokyo-night ; `t` pour cycler)
```

Le token n'est jamais affiché ni journalisé. Le nom de la variable peut aussi être `TOKEN` ou tout
nom se terminant par `_TOKEN` (par exemple `PWNY_CTFD_TOKEN`), que Flagship détecte automatiquement.
Le fichier `config.sh` est ignoré par git (voir `.gitignore`) : il ne doit pas être partagé, car il
contient le token.

## Exécution

```bash
./flagship.sh                 # utilise ./config.sh
./flagship.sh chemin/config.sh
# ou :
python3 -m flagship [config.sh]
```

Le lanceur `flagship.sh` résout le chemin du `config.sh` en absolu, puis se place dans le dossier
de l'outil pour que `python -m flagship` trouve le paquet. L'outil peut donc être lancé depuis
n'importe où avec n'importe quel `config.sh`.

## Workflow multi-CTF (cloner une seule fois)

Flagship est l'outil ; l'arborescence d'un CTF est séparée (définie par `BASE_DIR`). Il n'est pas
nécessaire de re-cloner le dépôt pour chaque CTF.

**1. Une seule fois, installer l'outil :**

```bash
git clone <depot>/flagship ~/ctfs/flagship
cd ~/ctfs/flagship
pip install -r requirements.txt      # textual + requests + gdown
```

**2. Pour chaque nouveau CTF (par exemple HeroCTF), un dossier et un config :**

```bash
mkdir ~/ctfs/HeroCTF
cp ~/ctfs/flagship/config.sh.example ~/ctfs/HeroCTF/config.sh
$EDITOR ~/ctfs/HeroCTF/config.sh     # renseigner URL, CTFD_TOKEN, BASE_DIR=.
```

```
~/ctfs/
├── flagship/          # cloné une seule fois (l'outil)
└── HeroCTF/           # créé par CTF ; l'arborescence est générée ici
    └── config.sh      # URL + token + BASE_DIR=.
```

> `BASE_DIR` est résolu par rapport au dossier du `config.sh`. Avec `BASE_DIR=.`, les challenges
> apparaissent dans `HeroCTF/<Catégorie>/<Challenge>/`.

**3. Démarrer, depuis n'importe où :**

```bash
~/ctfs/flagship/flagship.sh ~/ctfs/HeroCTF/config.sh
# équivalent :
cd ~/ctfs/flagship && python3 -m flagship ~/ctfs/HeroCTF/config.sh
```

Un alias évite de retaper le chemin (dans `~/.zshrc` ou `~/.bashrc`) :

```bash
alias flagship='~/ctfs/flagship/flagship.sh'
# puis :  flagship ~/ctfs/HeroCTF/config.sh
```

Variante : cloner Flagship à l'intérieur du dossier du CTF (`HeroCTF/flagship/`) fonctionne
également ; il faut alors renseigner `BASE_DIR=..` dans son `config.sh` pour générer l'arborescence
dans `HeroCTF/`. Cette variante impose de re-cloner l'outil à chaque fois, ce qui est moins pratique.

Le fichier `config.sh`, qui contient le token, est ignoré par git. Sur une nouvelle machine, il
doit être recréé à partir de `config.sh.example`.

## Raccourcis clavier

| Touche | Action |
|--------|--------|
| `↑`/`↓`, Entrée | naviguer et ouvrir un challenge (affiche l'énoncé, sans télécharger) |
| clic sur les onglets | basculer entre Challenges, Scoreboard, Stats et Notifications |
| `d` | télécharger ou mettre à jour le challenge sélectionné (recrée `desc.txt` si manquant, complète les fichiers manquants dans `work/`) |
| `D` | tout synchroniser (parallèle, barre de progression, confirmation) |
| `C` | télécharger tous les challenges de la catégorie sous le curseur (confirmation) |
| `/` | mettre le focus sur le champ de recherche en ligne (sur la ligne filtre/tri ; la saisie filtre l'arbre en direct) |
| `r` | actualiser la liste immédiatement (plus scoreboard et rang) |
| `f` | changer de filtre (all, unsolved, solved) |
| `o` | changer le tri : catégorie (points ↑), points (↓), solves (↓), moins de solves, nom A→Z, id CTFd, téléchargés d'abord, non résolus d'abord |
| `t` | changer de thème de couleurs (cycle, persisté) |
| `s` | aller au champ de soumission du flag |
| `u` | débloquer un indice (confirmation) |
| `c` | copier la connexion du challenge (`nc …` ou URL) |
| `w` | ouvrir le dossier du challenge dans le gestionnaire de fichiers |
| `e` | éditer les notes du challenge (`notes.md`, via `$EDITOR`) |
| `p` | exporter un récapitulatif dans `PROGRESS_flagship.md` (sans toucher à `PROGRESS.md`) |
| `Échap` | quitter un champ de saisie (recherche ou flag) et revenir sur la liste |
| souris : glisser `┃` | redimensionner la liste / le détail (double-clic : largeur par défaut) |
| `Tab` / `Maj+Tab` | déplacer le focus vers l'élément suivant ou précédent |
| `q` | quitter |

Pour soumettre un flag : sélectionner un challenge, appuyer sur `s`, saisir le flag, puis `Entrée`.
Pour rechercher : appuyer sur `/` et saisir une partie du nom (l'arbre se filtre en direct). Le champ
de recherche fait partie intégrante de la ligne filtre/tri au-dessus de la liste : il n'agrandit
jamais la mise en page ni ne prend de ligne à part, qu'il soit actif, en cours de saisie ou
simplement vide. `Entrée` ou un clic ailleurs laisse le filtre actif ; `Échap` l'annule en plus
(efface le texte, retrouve tous les challenges). Pour
débloquer un indice : appuyer sur `u` puis confirmer (le moins cher est proposé). Un indice payant
réduit le score, d'où la confirmation.

## Architecture

```
flagship/
├── config.py   # lit config.sh (CLE=valeur), sans exécuter de shell
├── ctfd.py     # client API CTFd : challenges, détail, solves, submit, unlock, download
├── store.py    # arborescence + desc.txt + flag.txt + slugify + téléchargements
├── app.py      # la TUI Textual (onglets, détail, soumission, poll auto, notifications)
└── __main__.py # point d'entrée (python -m flagship)
```

`config.py` analyse `config.sh` ligne par ligne, en tolérant `export`, les guillemets et les
commentaires. Aucun `source` shell n'est exécuté, ce qui évite tout effet de bord.

`ctfd.py` encapsule l'API :

- `GET /api/v1/challenges` (liste) et `GET /api/v1/challenges/<id>` (détail, dont les prérequis) ;
- `GET /api/v1/users/me` ou `/api/v1/teams/me` selon le **mode détecté** (solo ou équipe), avec
  le `/…/solves` correspondant (résolus), et `GET /api/v1/scoreboard` (classement) ;
- en mode équipe, `GET /api/v1/teams/me/solves` fournit aussi la contribution de chaque membre
  (chaque solve porte le membre qui l'a résolu) ;
- `GET /api/v1/challenges/<id>/solves` donne le first blood (onglet Stats) ;
- `POST /api/v1/challenges/attempt` (soumission) et `POST /api/v1/unlocks` (déblocage d'indice) ;
- téléchargement des fichiers listés.

Les erreurs (CTF fermé, réseau indisponible, etc.) remontent proprement et s'affichent dans la TUI
sans interrompre l'application.

`store.py` :

- `slugify()` applique le nommage : espaces remplacés par `-`, jamais de tirets consécutifs
  (`0 - Overflow` devient `0-Overflow`, `Bruh 0: Exif` devient `Bruh-0:-Exif`), `/` et `\`
  remplacés par `-`.
- `list_state()` (comportement par défaut) liste les challenges avec leur statut et leur état de
  téléchargement, sans rien créer ; `download_one()` télécharge un challenge ; `download_subset()`
  télécharge une catégorie ; `sync()` (« Tout synchroniser ») télécharge l'ensemble. Ces fonctions
  renvoient les événements (descriptions et indices modifiés sur les challenges suivis).
- Versionnage : un état caché `.flagship.json` par challenge mémorise les empreintes SHA-256 de la
  description et des indices. En cas de changement, un `descN.txt` est créé, sans écrasement. Avec
  `WATCH_CHANGES=false`, le détail n'est récupéré que pour les nouveaux challenges, ce qui allège
  la synchronisation mais supprime la détection de changement.
- Tentatives de flag : les flags **incorrects** sont mémorisés dans `.flagship/attempts.json`
  (anti-resoumission) et chaque tentative est journalisée dans `attempts.log` du challenge.
- `write_flag()` écrit `flag.txt`, jamais par-dessus un fichier existant.

Les toasts de notification sont aussi écrits dans `<base>/.flagship/notifications.log`, et consultables
dans l'onglet **Notifications**. L'état d'interface (tri, catégories pliées ou dépliées, dernière sélection, largeur des panneaux) est
conservé dans `<base>/.flagship/state.json`, puis restauré aux reconstructions de l'arbre
(téléchargement, rafraîchissement) et à la réouverture de la TUI.

`app.py` (Textual) :

- Les appels réseau bloquants s'exécutent dans des workers threadés (`@work(thread=True)`), et
  l'interface est mise à jour via `call_from_thread`, de sorte qu'elle ne gèle jamais.
- `on_mount` lance une première synchronisation puis programme le poll (`set_interval`).
- Le détail d'un challenge est chargé à la sélection, puis mis en cache.

## Téléchargements

Les téléchargements n'ont lieu qu'à la demande (`d` sur un challenge, ou `D` pour tout). Lorsqu'un
challenge est téléchargé, Flagship range ses fichiers dans `work/` et écrit un rapport
`downloads.txt` (valeurs `ok`, `skip`, `manual`, `error`) à la racine du challenge. Dans tous les
cas, les liens figurent dans `desc.txt` (section « Files (platform) » avec l'URL complète, et
section « External links »).

| Source | Comportement |
|--------|--------------|
| Fichier hébergé par le CTFd | téléchargé (authentifié), garde-fou 2 Go |
| Lien http(s) direct | téléchargé sans envoi du token, garde-fou 2 Go |
| Dropbox | réécrit en lien direct (`?dl=1`) puis téléchargé |
| Google Drive (fichier) | via `gdown` si public ; sinon marqué `manual` (lien conservé) |
| Google Drive (dossier) | via `gdown.download_folder` |
| MEGA | via `megatools`/`megadl` si installé ; sinon marqué `manual` (lien conservé) |
| Fichier supérieur à 2 Go | non téléchargé, marqué `manual` (récupération manuelle) |

« Tout synchroniser » (`D`) télécharge en parallèle (`DOWNLOAD_WORKERS`), avec une barre de
progression. La touche `d` est auto-réparatrice : elle recrée `desc.txt` s'il manque (par exemple
après un dossier vidé) et complète les fichiers manquants ou en échec dans `work/`, de manière
idempotente (les fichiers déjà présents sont sautés). Un `work/` ou un `downloads.txt` ne sont
jamais créés sans `desc.txt`. Le token CTFd n'est jamais envoyé à un hôte tiers (Drive, MEGA, etc.).
Le garde-fou Drive est vérifié a posteriori, car `gdown` ne connaît pas la taille à l'avance.

## Notes et limites

- **Solo ou équipe** : Flagship détecte automatiquement le mode du CTF. En **mode équipe**, le
  score, le rang et le nom affichés (en-tête, stats, surlignage du scoreboard) sont ceux de
  **l'équipe**, et un challenge résolu par n'importe quel coéquipier apparaît comme résolu. En mode
  solo, ce sont les informations individuelles. Aucune configuration n'est requise.
- Le statut résolu provient de l'API (solves de l'équipe en mode équipe, sinon les siens) et, à
  défaut, de la présence d'un `flag.txt` local.
- Les indices sont affichés avec leur coût et leur état (verrouillé ou débloqué). Le déblocage se
  fait à la demande (touche `u`) avec confirmation, jamais automatiquement, car il coûte des points.
- Si le CTF est terminé ou fermé, l'API renvoie souvent un 403 : Flagship l'indique clairement
  (token OK vs refusé) et réaffiche la dernière synchronisation en cache (challenges, points, score,
  scoreboard), en plus de conserver l'arborescence déjà téléchargée.
- L'outil est conçu pour CTFd (auto-hébergé ou de type sigpwny). Les autres plateformes ne sont pas
  prises en charge.
