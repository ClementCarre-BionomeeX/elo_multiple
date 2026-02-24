# Elo multi-jeux (équipes variables) — Spécification + plan de réalisation (Python Dashboard)

Objectif : construire une application Python (dashboard) qui gère un groupe de joueurs, permet de saisir des résultats au fil des parties (équipes fixes ou variables), et met à jour un score de type Elo par jeu (et/ou global). Le moteur doit être générique, extensible à plusieurs jeux (belote, tarot…), et 100% couvert par des tests unitaires.

Ce document sert de brief “vibe coding” pour Codex : architecture, modèles, algorithmes, API internes, persistance, UI, et plan de tests.

---

## 1) Périmètre (MVP puis extensions)

### MVP
- Gestion des entités :
  - Joueurs
    - Groupes (un groupe = un ensemble de joueurs)
      - Jeux (belote, tarot…) avec un ruleset simple
        - Sessions (une “soirée” / match) contenant des rounds (manches/donnes)
        - Saisie :
          - Belote : 2v2, victoire/défaite, marge optionnelle
            - Tarot : camp Attaque (preneur + éventuel partenaire) vs camp Défense (restants), réussite/échec, marge optionnelle
            - Calcul Elo :
              - Équipe = “strength-sum” (recommandé) ou moyenne (configurable)
                - Mise à jour Elo à chaque round
                  - Historique d’événements de rating (rejouable/recalculable)
                  - Dashboard :
                    - Classement actuel par jeu
                      - Historique (courbe Elo par joueur)
                        - Liste des sessions + détails des rounds
                        - Qualité :
                          - Tests unitaires 100% coverage
                            - Lint + format + CI local (prévu)

### Non-MVP (mais prévu par l’architecture)
- Multi-camps (3+ équipes) via Elo pairwise
- Pondération “W” plus riche (contrats, bonus, points)
- K dynamique (débutants / expérience / tournois)
- Édition/suppression de rounds avec recalcul partiel
- Multi-utilisateur / authentification (hors scope)

---

## 2) Principes de conception

1. Séparer strictement :
   - Domaine (entités + règles)
      - Application (cas d’usage / orchestration)
         - Infra (DB, repo)
            - UI (Streamlit/Dash/Textual)

            2. Le moteur Elo ne connaît aucun jeu.
               - Il reçoit des “matchups” génériques (camp A vs camp B, S, W, K optionnel, distribution).
                  - Les règles du jeu traduisent la saisie en matchups.

                  3. Le système doit être “rejouable”.
                     - On stocke chaque Round (entrée) et chaque RatingEvent (sortie: deltas).
                        - On peut reconstruire l’état des ratings en rejouant les événements.

                        ---

## 3) Modèle Elo (générique)

### 3.1 Rating d’équipe (TeamRatingPolicy)

Deux politiques :
- `mean` : `R_team = average(R_i)`
- `strength_sum` (recommandé) :
  - force individuelle : `q_i = 10^(R_i/400)`
    - force d’équipe : `Q = Σ q_i`
      - rating équivalent : `R_team = 400 * log10(Q)`

### 3.2 Score attendu (2 camps)
`E_A = 1 / (1 + 10^((R_B - R_A)/400))`

### 3.3 Mise à jour
`Δ_A = K * W * (S_A - E_A)`
`Δ_B = -Δ_A`

- `S_A` ∈ [0, 1] : score réel (1 victoire, 0 défaite, 0.5 nul)
- `W` ≥ 1 : poids (optionnel, ex marge)
- `K` : facteur d’ajustement (configurable par jeu)

### 3.4 Répartition Δ équipe → joueurs (DeltaDistributionPolicy)
- `equal` : chaque joueur reçoit `Δ_team / n`
- `proportional` (optionnel) : proportionnel à la force `q_i / Σq`

---

## 4) Tarot et belote : conversion “saisie” → matchups

### Belote (2v2)
- Camps : Team A vs Team B (2 joueurs chacun)
- S :
  - 1 si A gagne
    - 0 si A perd
      - 0.5 si nul (rare, mais possible si tu veux le supporter)
      - W (optionnel) :
        - basé sur marge : `W = 1 + c * clamp(|margin| / M, 0, 1)`
          - sinon W = 1

### Tarot (équipes variables)
On saisit par donne (Round) :
- Camp ATT : preneur (+ partenaire si appelé)
- Camp DEF : tous les autres
- S :
  - 1 si contrat réussi
    - 0 sinon
    - W (optionnel) :
      - basé sur marge (diff entre points faits et points requis)
        - ou basé sur type de contrat (garde, garde sans…) + marge

        ---

## 5) Architecture Python (packages)

Proposition de structure :

elo_app/
domain/
models.py
matchup.py
policies.py
elo_engine.py
rules/
base.py
belote.py
tarot.py
application/
services.py
dtos.py
errors.py
infrastructure/
db.py
repos.py
migrations.py (optionnel, si SQLAlchemy/Alembic)
ui/
streamlit_app.py
tests/
unit/
test_elo_engine.py
test_policies.py
test_rules_belote.py
test_rules_tarot.py
test_service_flow.py
helpers.py
pyproject.toml
README.md


---

## 6) Domaine : classes et contrats

### 6.1 Entités (domain/models.py)

- `Player(id: str, name: str)`
- `Group(id: str, name: str, member_ids: list[str])`
- `Game(id: str, name: str, ruleset_id: str, config: dict)`
- `Match(id: str, group_id: str, game_id: str, participant_ids: list[str], started_at, ended_at?)`
- `Team(side_id: str, player_ids: list[str], role: str = "")`
- `Outcome(type: str, data: dict)`
- `Round(id: str, match_id: str, index: int, teams: list[Team], outcome: Outcome, created_at)`
- `RatingEvent(id: str, group_id: str, game_id: str, round_id: str, deltas: dict[player_id->float], meta: dict, created_at)`

### 6.2 Matchup (domain/matchup.py)
- `Matchup(sideA: list[str], sideB: list[str], S: float, W: float = 1.0, k_override: float|None = None, distribution: str = "equal")`

### 6.3 Interfaces règles (domain/rules/base.py)
- `class GameRules(Protocol):`
  - `to_matchups(round: Round) -> list[Matchup]`

### 6.4 EloEngine (domain/elo_engine.py)
Fonctions pures (testables) :
- `team_rating(ratings_by_player, player_ids, policy) -> float`
- `expected(rA, rB) -> float`
- `apply_matchup(ratings_by_player, matchup, K, team_policy, distribution_policy) -> deltas_by_player`

### 6.5 Policies (domain/policies.py)
- `TeamRatingPolicy: "mean" | "strength_sum"`
- `DeltaDistributionPolicy: "equal" | "proportional"`
- `WeightPolicy` (optionnel, sinon dans les règles de jeu)
- `KFactorPolicy` (optionnel, sinon constant par jeu)

---

## 7) Couche application : services (application/services.py)

### 7.1 RatingService (orchestrateur)
Responsabilités :
- Ajouter un round
- Calculer les deltas via rules + EloEngine
- Persister Round + RatingEvent(s)
- Mettre à jour le cache “ratings_current” (optionnel)
- Recalculer un match si round modifié/supprimé

API interne proposée :
- `create_player(name) -> player_id`
- `create_group(name, member_ids) -> group_id`
- `create_game(id, name, ruleset_id, config) -> game_id`
- `create_match(group_id, game_id, participant_ids) -> match_id`
- `add_round(match_id, teams, outcome) -> round_id`
  - retourne aussi le `RatingEvent`
  - `get_ratings(group_id, game_id) -> list[(player, rating)]`
  - `get_rating_history(group_id, game_id, player_id) -> list[(timestamp, rating)]`
  - `list_matches(group_id, game_id?) -> list[Match]`
  - `get_match_details(match_id) -> Match + rounds + events`

### 7.2 Registry de règles
- `RulesRegistry.get(game_id or ruleset_id) -> GameRules`

---

## 8) Persistance (SQLite)

### 8.1 Options
- Simple : `sqlite3` + JSON (teams/outcome/deltas stockés en JSON)
- Plus “propre” : SQLAlchemy (mais plus long)

Pour un MVP rapide : sqlite3 suffit.

### 8.2 Tables minimales
- `players(id TEXT PK, name TEXT)`
- `groups(id TEXT PK, name TEXT)`
- `group_members(group_id TEXT, player_id TEXT, PRIMARY KEY (group_id, player_id))`
- `games(id TEXT PK, name TEXT, ruleset_id TEXT, config_json TEXT)`
- `matches(id TEXT PK, group_id TEXT, game_id TEXT, participant_ids_json TEXT, started_at TEXT, ended_at TEXT NULL)`
- `rounds(id TEXT PK, match_id TEXT, idx INTEGER, teams_json TEXT, outcome_json TEXT, created_at TEXT)`
- `rating_events(id TEXT PK, group_id TEXT, game_id TEXT, round_id TEXT, deltas_json TEXT, meta_json TEXT, created_at TEXT)`
- (optionnel) `ratings_current(group_id TEXT, game_id TEXT, player_id TEXT, rating REAL, games_played INT, PRIMARY KEY(...))`

### 8.3 Recalcul (stratégie)
MVP : recalcul complet du match ou du jeu quand on modifie (acceptable si peu de données).  
Plus tard : recalcul à partir du round modifié.

---

## 9) UI (Streamlit recommandé pour démarrer)

Écrans :
1. Home
   - Choix du groupe
      - Choix du jeu
      2. Classement
         - Table des ratings actuels
            - Bouton “Nouvelle session”
            3. Session (Match)
               - Liste des rounds
                  - Formulaire “Ajouter round”
                  4. Graphiques
                     - Courbe Elo par joueur
                        - Comparaison de joueurs

                        Saisie belote :
                        - sélectionner 4 joueurs
                        - définir équipes A/B
                        - résultat : A gagne ? + marge optionnelle

                        Saisie tarot :
                        - sélectionner participants (4 ou 5)
                        - choisir preneur
                        - choisir partenaire optionnel
                        - DEF = restants
                        - résultat : success bool + marge optionnelle + type contrat optionnel

                        ---

## 10) Tests unitaires (objectif 100% coverage)

### 10.1 Outils
- `pytest`
- `pytest-cov` (couverture)
- `hypothesis` (optionnel, utile pour tests de propriétés)
- `ruff` (lint)
- `black` (format)
- `mypy` (optionnel)

### 10.2 Stratégie de test
On vise surtout du test “pur” :
- EloEngine : fonctions pures, beaucoup de cas
- Policies : strength_sum vs mean, distribution equal/proportional
- Rules : tarot/belote → matchups corrects
- Service flow : add_round persiste et met à jour correctement

### 10.3 Tests indispensables

#### A) EloEngine
1. expected symmetry :
   - si rA == rB : E == 0.5
   2. delta conservation :
      - somme des deltas joueurs == 0 (ou très proche, tolérance float)
      3. distribution equal :
         - deux joueurs dans A reçoivent le même delta
         4. distribution proportional :
            - joueur plus fort reçoit un delta légèrement différent (selon policy)
            5. team_rating mean :
               - moyenne simple
               6. team_rating strength_sum :
                  - Q = sum(q), rating = 400 log10(Q)
                  7. edge cases :
                     - team vide => deltas vides, pas de crash
                        - ratings manquants : décider une politique (ex default 1500) et tester

#### B) Rules Belote
- outcome winner A → S=1
- outcome winner B → S=0
- marge → W calculé dans les bornes [1, 1+c]
- matchups contient exactement 1 matchup A vs B

#### C) Rules Tarot
- ATT = preneur (+ partenaire) ; DEF = restants
- success True/False → S=1/0
- marge influence W correctement

#### D) Service / Repo (test d’intégration “unitaire” avec DB temporaire)
- Créer players/group/game/match
- Add round belote → 1 rating_event, ratings mis à jour
- Add round tarot → idem
- Rejouer historique → reconstruire mêmes ratings

### 10.4 Tests de propriétés (optionnel mais excellent)
- Pour tout matchup : somme des deltas == 0 (tolérance)
- Pour toute permutation des joueurs dans une équipe : mêmes deltas (equal distribution)
- Ratings finissent finies (pas NaN/inf)

---

## 11) Règles de qualité et CI local

### 11.1 pyproject.toml (idée)
- deps : pytest, pytest-cov, ruff, black
- commands :
  - `ruff check .`
    - `black --check .`
      - `pytest --cov=elo_app --cov-report=term-missing --cov-fail-under=100`

### 11.2 “Definition of Done”
- Tous les tests passent
- Coverage = 100%
- Lint/format ok
- README explique comment lancer l’app et les tests

---

## 12) Prompts “vibe coding” pour Codex

Tu peux donner à Codex des tâches séquentielles, chacune petite, avec validation tests.

### Prompt 1 — Bootstrap projet
- “Crée la structure de packages, pyproject.toml, configure pytest + pytest-cov 100%, ruff, black.”
- “Ajoute un README minimal et un script de lancement.”

### Prompt 2 — Domaine minimal + EloEngine
- “Implémente dataclasses : Player/Group/Game/Match/Round/Team/Outcome/RatingEvent + Matchup.”
- “Implémente EloEngine avec policies mean/strength_sum et distribution equal/proportional.”
- “Écris tests unitaires complets EloEngine/policies (100% coverage).”

### Prompt 3 — Rules belote + tests
- “Implémente BeloteRules.to_matchups, marge → W.”
- “Tests unitaires rules belote.”

### Prompt 4 — Rules tarot + tests
- “Implémente TarotRules.to_matchups selon convention side_id ATT/DEF.”
- “Tests unitaires rules tarot.”

### Prompt 5 — Infrastructure SQLite + repos + service
- “Implémente un repo sqlite3 minimal (create tables, CRUD basique).”
- “Implémente RatingService.add_round : read ratings, compute deltas, write round + event, update ratings_current.”
- “Tests avec DB temporaire (tmp_path) et parcours complet (create → add_round).”

### Prompt 6 — Dashboard Streamlit
- “Crée ui/streamlit_app.py : pages classement, session, ajout round belote/tarot, historique (simple line chart).”
- “Pas besoin de tests UI, mais le domaine et services doivent rester testés à 100%.”

---

## 13) Conventions de saisie (pour éviter le flou)

### Convention teams
Pour chaque Round :
- `teams` contient au minimum deux camps avec `side_id` stables :
  - belote : "A", "B"
    - tarot : "ATT", "DEF"

### Convention outcome
- Belote :
  - `Outcome(type="winloss", data={"winner": "A"|"B", "margin": int|float?})`
  - Tarot :
    - `Outcome(type="contract", data={"success": bool, "margin": int|float?, "contract": str?})`

    Le moteur Elo ne dépend pas du contenu exact, uniquement les Rules.

    ---

## 14) Décisions par défaut (recommandées)

- Rating initial : 1500
- team_rating_policy : strength_sum
- distribution : equal
- Belote : K=20
- Tarot : K=16
- Weight via marge : activable, sinon W=1

---

## 15) Livrables attendus

1. Moteur Elo générique (purement testable)
2. Rules belote + tarot
3. Persistance SQLite
4. RatingService + registry
5. Dashboard Streamlit
6. Tests unitaires 100% coverage (domaine + application + infra minimale)
7. Documentation README + ce plan

---
