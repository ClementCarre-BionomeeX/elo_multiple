 # Elo multi-jeux (belote, tarot)

Dashboard Python pour gérer des groupes de joueurs, saisir des rounds (équipes fixes ou variables) et calculer des ratings de type Elo par jeu.

## Lancer l'app

```bash
pip install -e .[dev]
streamlit run elo_app/ui/streamlit_app.py
```

## Tests et qualité

```bash
ruff check .
black --check .
PYTHONPATH=. pytest
```

Objectif de couverture : 100% (`--cov-fail-under=100`).

Notes :
- la base SQLite locale par défaut est `elo_app.db` (créée au lancement du dashboard).
- les rulesets belote/tarot sont pré-enregistrés dans l’UI Streamlit.

## Architecture (résumé)

- `elo_app/domain`: entités, règles Elo, règles de jeu.
- `elo_app/application`: services orchestrant rounds et ratings.
- `elo_app/infrastructure`: persistance SQLite, repos.
- `elo_app/ui`: Streamlit.
- `tests`: couverture unitaire complète.

UI Streamlit :
- onglet *Gestion* pour créer joueurs/groupes/jeux
- onglet *Rounds* pour lancer des sessions et saisir les manches (belote avec boutons rapides A/B/nul)
- onglet *Admin* pour recalculer ou supprimer un round erroné (recalcul automatique des ratings).

Le document `spec.md` détaille les conventions et le plan complet.
