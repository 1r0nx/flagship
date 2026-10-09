# 🚩 Flagship (Documentation FR)

Nouveau CTF, même routine : créer des dossiers, télécharger les fichiers, suivre les
résolutions, tenir des notes par challenge. Flagship fait tout ça pour toi.

## Preview

![Capture d'écran de Flagship](img/screenshot.png)

> L'interface de Flagship et les fichiers générés (`desc.txt`, `notes.md`…) sont en anglais.

## Aperçus

**Scoreboard** 

![Scoreboard](img/scoreboard.png)

**Stats**

![Stats](img/stats.png)

**Flags**

![Flags](img/flags.png)

## Fonctionnalités

- Liste les challenges
- Télécharge les challenges : un seul, une catégorie entière, ou tous les challenges
- Suit les résolutions, écrit `flag.txt` quand un flag est validé
- Détecte les changements de description/indices (`desc2.txt`, `desc3.txt`…)
- Soumet les flags 
- Mémorise les flags refusés pour ne pas les renvoyer
- Challenge à essais limités: fenêtre de confirmation avant de soumettre.
- Débloque les indices (pop-up de confirmation pour les payants)
- Recherche, filtre (tous / non résolus / résolus / favoris) et tri
- Épingler un challenge en favori
- Notes par challenge (`notes.md`) dans l'éditeur de ton choix
- Scoreboard complet, double-clic (ou Entrée) pour voir l'historique de solves
- Colonne « Gap » : écart de points par rapport à toi (vert = tu mènes, rouge = on te devance)
- Stats : score, rang, résolus, points, first bloods (détail par membre en équipe)
- Tout mis en cache local: consultable hors-ligne et après le CTF
- Panneaux redimensionnables, thèmes de couleur
- Export Markdown des flags et de la progression
- Six onglets : Challenges, Scoreboard, Stats, Flags, Notifications (annonces de la
  plateforme), Log (journal interne)

## Installation

```bash
cd /workspace/flagship
pip install -e .            # installe Flagship + dépendances, ajoute la commande `flagship`
```

## Configuration

```bash
cp config.sh.example config.sh
$EDITOR config.sh
```

```sh
URL=https://ctf.example.com          # URL du CTFd
CTFD_TOKEN=ctfd_xxxxxxxxxxxxxxxxxxx  # token (CTFd > Settings > Access Tokens)

# optionnel
CTF_NAME=MonCTF              # nom affiché et dossier par défaut
BASE_DIR=./                  # racine des dossiers générés (relatif au config.sh)
POLL_INTERVAL=60             # synchro auto toutes les N secondes (0 = désactivée)
WRITE_FLAG_ON_SOLVE=true     # écrire flag.txt quand un flag est validé
WATCH_CHANGES=true           # suivre les changements desc/indices (false = synchro plus légère)
AUTO_UNLOCK_FREE_HINTS=false # débloquer automatiquement les indices gratuits
DOWNLOAD_WORKERS=6           # téléchargements en parallèle pour "Sync all"
THEME=textual-dark           # thème de départ (`t` pour cycler)
EDITOR=nano                  # éditeur pour les notes (ex. vim, subl, code)
```

## Lancement

```bash
./flagship.sh                 # utilise ./config.sh
./flagship.sh chemin/config.sh
# ou : python3 -m flagship [config.sh]
```

Une seule installation suffit pour plusieurs CTF : chaque CTF a son propre `config.sh` (avec son
`BASE_DIR`), passé en argument. Un alias évite de retaper le chemin :

```bash
alias flagship='~/ctfs/flagship/flagship.sh'
flagship ~/ctfs/HeroCTF/config.sh
```

## Raccourcis clavier

| Touche               | Action                                                       |
| -------------------- | ------------------------------------------------------------ |
| `↑`/`↓`, Entrée      | naviguer, ouvrir un challenge                                |
| clic sur les onglets | changer d'onglet                                             |
| `d` / `D` / `C`      | télécharger : le challenge / tout / la catégorie             |
| `/`                  | rechercher                                                   |
| `r`                  | rafraîchir                                                   |
| `f` / `o`            | changer de filtre / de tri                                   |
| `b`                  | favori on/off                                                |
| `x`                  | replier/déplier les catégories                               |
| `t`                  | changer de thème                                             |
| `l`                  | onglet Log : basculer 500 dernières ↔ historique complet     |
| `s`                  | focus sur le champ de flag                                   |
| `u`                  | débloquer un indice                                          |
| `c` / `w`            | copier la connexion / ouvrir le dossier                      |
| `e`                  | éditer les notes (`notes.md`)                                |
| `p` / `P`            | exporter la progression / l'onglet Flags                     |
| `A`                  | mettre en cache l'historique de solves de tout le scoreboard |
| `Échap`              | quitter le champ actif                                       |
| glisser `┃`          | redimensionner les panneaux (double-clic : réinitialiser)    |
| `q`                  | quitter                                                      |

## Thèmes


- **Sombres (15) :** `ansi-dark`, `atom-one-dark`, `catppuccin-frappe`, `catppuccin-macchiato`,
  `catppuccin-mocha`, `dracula`, `flexoki`, `gruvbox`, `monokai`, `nord`, `rose-pine`,
  `rose-pine-moon`, `solarized-dark`, `textual-dark`, `tokyo-night`
- **Clairs (6) :** `ansi-light`, `atom-one-light`, `catppuccin-latte`, `rose-pine-dawn`,
  `solarized-light`, `textual-light`

## Architecture

| Fichier       | Rôle                                                     |
| ------------- | -------------------------------------------------------- |
| `config.py`   | Lit `config.sh` (sans passer par un shell)               |
| `ctfd.py`     | Client de l'API CTFd                                     |
| `store.py`    | crée les dossiers, fichiers, téléchargements et le cache |
| `app.py`      | L'interface TUI (Textual)                                |
| `__main__.py` | Point d'entrée                                           |

## Téléchargements

Les fichiers vont dans `work/`. Un fichier de plus de **2 Go n'est pas téléchargé**
automatiquement (pour ne pas saturer le disque) : il est marqué `manual` et son lien
reste dans `desc.txt` pour une récupération à la main.

Chaque challenge reçoit un rapport `downloads.txt` où chaque ligne porte une indication :

| Indication | Signification                                                              |
| ---------- | -------------------------------------------------------------------------- |
| `ok`       | fichier téléchargé dans `work/`                                            |
| `skip`     | déjà présent, non écrasé                                                   |
| `manual`   | à récupérer à la main (lien dans `desc.txt`) : > 2 Go, Drive privé, MEGA…  |
| `error`    | le téléchargement a échoué                                                 |

## Arborescence

Exemple d'organisation des fichiers générés:

```
MonCTF/                             # racine de ton CTF (BASE_DIR)
├── config.sh                       # URL + token (jamais affiché)
├── PROGRESS_flagship.md            # tableau de progression généré (touche p)
├── FLAGS_flagship.md               # export des flags généré (touche P)
├── .flagship/                      # cache & état interne (ne pas toucher)
└── CHALLENGES/
    ├── Crypto/
    │   ├── crypto1/
    │   │   ├── desc.txt            # énoncé du challenge
    │   │   ├── work/               # fichiers téléchargés
    │   │   ├── notes.md            # tes notes (touche e)
    │   │   └── flag.txt            # écrit quand le flag est validé
    │   └── crypto2/
    │       ├── desc.txt
    │       └── work/
    └── Forensics/
        ├── forensics1/
        │   ├── desc.txt
        │   ├── work/
        │   └── flag.txt
        └── forensics2/
            ├── desc.txt
            └── work/
```

`desc.txt` = énoncé · `work/` = fichiers téléchargés · `notes.md` = tes notes · `flag.txt` = apparaît une fois le flag validé.

## À noter

- Solo ou équipe est détecté automatiquement
- CTF fini ou hors-ligne : Flagship réaffiche la dernière synchro en cache.
- Conçu pour CTFd ; les autres plateformes ne sont pas prises en charge.
