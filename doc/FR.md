# 🚩 Flagship (Documentation FR)

*Un nouveau CTF, et c'est reparti : créer les dossiers, télécharger les fichiers, suivre ce qui est
résolu, retrouver ses notes… Flagship automatise toute cette plomberie ; il ne reste plus qu'à
résoudre les challenges.*

Flagship est une interface en terminal (TUI) pour les CTF basés sur **CTFd**. L'outil synchronise
les challenges dans une arborescence de dossiers organisée et permet de les parcourir, de lire les
énoncés et de soumettre les flags sans quitter le terminal.

```
┌ Flagship · MonCTF · score 8270 (#3) · ⏳ fin 2h11 · 12/40 résolus ────────┐
│▣ ▢ fichiers  ● ○ résolu        │ # 2 - Return                             │
│Pwn (3/8)                       │ Catégorie : Pwn · Points : 200 · ○       │
│ ▣ ●  0 - Overflow 100·12 solves│ Prérequis (déverrouillé) : ✔ 0 - Overflow│
│ ▣ ○  2 - Return   200·5 solves │ Connexion : nc chal... 1389              │
│Crypto (5/9)                    │ Can you pwn this problem? ...            │
│ ▢ ●  First XOR    50·30 solves ├──────────────────────────────────────────┤
│ ▢ ○  RSA          150·5 solves │ 🚩                                       │
└ d Dl  D Sync  w Dossier  u Indice  / Rech.  f Filtre  o Tri  q Quit ──────┘
```

Les marqueurs de chaque ligne sont rappelés par une légende en haut de la colonne de gauche :
`▣`/`▢` pour les fichiers téléchargés, `●`/`○` pour l'état résolu, et `N pt · N solves` pour les
points et le nombre de solves. Deux formes distinctes (carré pour les fichiers, cercle pour le
statut) et une couleur rendent l'état lisible d'un coup d'œil, avec un alignement constant quelle
que soit la combinaison.

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
détail présente le first blood, la connexion, les **prérequis** (challenges à résoudre avant, avec
leur état et un indicateur verrouillé/déverrouillé), les fichiers et les indices. La description est
consultable sans téléchargement. L'interface offre une recherche (`/`), des filtres (`f` : tous,
non résolus, résolus), un tri (`o` : catégorie, points, solves), la soumission de flag (avec
écriture de `flag.txt` si le flag est correct), le téléchargement ou la mise à jour (`d`), le
téléchargement de toute une **catégorie** (`C`), la synchronisation complète (`D`, parallèle, avec
barre de progression), le déblocage d'indice (`u`), la copie de la connexion (`c`), l'ouverture du
dossier (`w`), l'édition des notes (`e`, `notes.md`) et l'export vers `PROGRESS_flagship.md` (`p`,
sans jamais toucher au `PROGRESS.md` de l'utilisateur). L'en-tête affiche le score, le rang et un
**compte à rebours** jusqu'à la fin du CTF.

À la soumission, les flags **incorrects** déjà tentés sont mémorisés : resoumettre un flag identique
est bloqué (avec un avertissement) afin de ne pas gaspiller de tentative. Chaque tentative est aussi
journalisée dans `attempts.log` à la racine du dossier du challenge (utile pour un writeup).

Onglet **Scoreboard** : classement avec position, équipe ou joueur, et score. La ligne de
l'utilisateur est surlignée et le curseur s'y positionne.

Onglet **Stats** : récapitulatif de la progression : score et rang, nombre de résolus et points
gagnés sur le total, challenges téléchargés, puis un tableau par catégorie (résolus, points,
téléchargés) et des barres de progression par catégorie. Il se met à jour automatiquement. En
**mode équipe**, une section **« Membres de l'équipe »** s'ajoute : ton rang et ton score
individuels, puis un **tableau de tous les membres** (résolus et points de chacun, calculés depuis
les solves de l'équipe), trié par points, ta ligne étant surlignée et marquée « (toi) ». Chaque
**pseudo est cliquable** : un clic ouvre une fenêtre détaillant les stats de ce membre, avec ses
sections « Par catégorie » et « Progression par catégorie » (classées par points) pour voir où
chacun a le plus contribué.

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
CTF_END=2026-10-05T18:00   # fin du CTF pour le compte à rebours (epoch ou ISO ; vide = auto via API)
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
| clic sur les onglets | basculer entre Challenges et Scoreboard |
| `d` | télécharger ou mettre à jour le challenge sélectionné (recrée `desc.txt` si manquant, complète les fichiers manquants dans `work/`) |
| `D` | tout synchroniser (parallèle, barre de progression, confirmation) |
| `C` | télécharger tous les challenges de la catégorie sous le curseur (confirmation) |
| `/` | aller à la barre de recherche |
| `r` | actualiser la liste immédiatement (plus scoreboard et rang) |
| `f` | changer de filtre (tous, non résolus, résolus) |
| `o` | changer le tri (catégorie, points, solves) |
| `t` | changer de thème de couleurs (cycle, persisté) |
| `s` | aller au champ de soumission du flag |
| `u` | débloquer un indice (confirmation) |
| `c` | copier la connexion du challenge (`nc …` ou URL) |
| `w` | ouvrir le dossier du challenge dans le gestionnaire de fichiers |
| `e` | éditer les notes du challenge (`notes.md`, via `$EDITOR`) |
| `p` | exporter un récapitulatif dans `PROGRESS_flagship.md` (sans toucher à `PROGRESS.md`) |
| `Échap` | quitter un champ de saisie (recherche ou flag) et revenir sur la liste |
| `Tab` / `Maj+Tab` | déplacer le focus vers l'élément suivant ou précédent |
| `q` | quitter |

Pour soumettre un flag : sélectionner un challenge, appuyer sur `s`, saisir le flag, puis `Entrée`.
Pour rechercher : appuyer sur `/` et saisir une partie du nom (l'arbre se filtre en direct). Pour
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
- `GET /api/v1/configs` est tenté pour la date de fin (compte à rebours ; souvent réservé aux admins,
  d'où la possibilité de la fixer via `CTF_END`) ;
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
dans l'onglet **Notifications**. L'état d'interface (filtre, tri, catégories pliées ou dépliées, dernière sélection) est
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
cas, les liens figurent dans `desc.txt` (section « Fichiers (plateforme) » avec l'URL complète, et
section « Liens externes »).

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
