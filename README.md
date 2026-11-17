# velov-mlops

Projet fil rouge du cours **Industrialisation de l'IA dans le Cloud** (M2 Data Engineering / IA).

Objectif métier : prédire, pour chaque station Vélo'v, le nombre de vélos disponibles **dans une heure**,
et servir cette prédiction via une API fiable, conteneurisée, puis déployée (on-premise et cloud).

## Progression par session

Chaque étape du cours correspond à un tag git. Absent ou bloqué : repartez du tag de fin de la session précédente.

| Tag | Contenu |
|---|---|
| `s1-start` | Données simulées, features, entraînement. API à compléter (TP1) |
| `s1-end` | Modèle v0 servi par FastAPI, tests pytest |

```bash
git checkout s1-end          # récupérer l'état de fin de S1
git checkout -b mon-binome   # travailler sur sa propre branche
```

## Démarrage rapide

Prérequis : Python 3.11+ (3.12 recommandé), git. Docker sera nécessaire en S2.

```bash
python -m venv .venv
source .venv/bin/activate            # Windows : .venv\Scripts\activate
pip install -r requirements-dev.txt
pip install -e .                     # rend le package velov importable

python -m velov.data                 # génère data/velov_history.csv (simulateur, seed fixe)
python -m velov.train                # entraîne et écrit models/model.joblib + models/metadata.json
python -m velov.train --mlflow       # idem + journalisation MLflow (puis : mlflow ui)
pytest                               # tests
uvicorn velov.api.main:app --reload  # API sur http://127.0.0.1:8000/docs (--reload : en dev uniquement)
```

Exemple d'appel :

```bash
curl -X POST http://127.0.0.1:8000/v1/predict \
  -H "Content-Type: application/json" \
  -d '{"station_id": 3, "timestamp": "2026-10-06T08:00:00+02:00", "capacity": 20,
       "bikes_available": 12, "temperature": 14.5, "is_raining": false}'
```

Le `timestamp` doit porter un fuseau (`+02:00`, `Z`...) : sans fuseau, l'API répond 422.
Les instants sont renvoyés et journalisés en UTC (`"target_timestamp": "2026-10-06T07:00:00Z"`).

## Exigences du projet

Le service doit respecter les exigences de [docs/exigences.md](docs/exigences.md), de S1 à S9.
Chaque rendu indique celles qu'il couvre et comment le vérifier.


## Structure

```
src/velov/
  data.py          simulateur de données (remplacé par l'open data en S3, même schéma)
  features.py      features partagées entraînement / API (anti training-serving skew)
  train.py         entraînement, baseline, artefact + metadata.json, option MLflow
  api/main.py      FastAPI : /health, /ready, /v1/model, /v1/predict, /v1/predict/batch
  api/schemas.py   contrat d'entrée / sortie (Pydantic)
tests/             pytest (features, API)
docs/              templates : model card, runbook, ADR
exercices/         démo pickle (S1)
```

## Usage de l'IA générative

Chaque activité indique son mode : **sans IA**, **IA déclarée** ou **IA imposée**.
En mode IA déclarée, ajoutez dans la description de vos commits ou de votre rendu :
outil utilisé, ce que vous lui avez demandé, ce que vous avez vérifié ou corrigé.

## Usage d'une prédiction TP2

Pour le tp 2, nous avons besoin de tester l'API avec une prédiction. Pour cela, nous allons utiliser la commande curl.

```bash
curl -X POST http://[IP_ADDRESS]/v1/predict \ 
  -H "Content-Type: application/json" \
  -d '{"station_id": 1, "timestamp": "2026-10-06T08:00:00+02:00", "capacity": 20, "bikes_available": 12, "temperature": 14.5, "is_raining": false}'
  ```

Ensuite pour lire la base de données, nous allons utiliser la commande docker exec. 
```bash
docker exec nofah-db-1 psql -U velov_user -d velov -c "SELECT * FROM predictions;"
```
### Étape 2 : Tracer chaque entraînement

Les runs sont tracés dans MLflow via `velov.tracking` (`velov.train --mlflow`) :

| Catégorie | Contenu tracé |
|---|---|
| **Paramètres** | `seed`, `learning_rate`, `max_iter`, `test_days` |
| **Métriques** | `mae_model`, `mae_baseline_persistence`, `mae_model_peak_hours` |
| **Tags** | `git_commit`, `git_dirty`, `data_sha256` (empreinte triée), `data_period` (début/fin UTC) |
| **Artefacts** | Modèle MLflow avec signature (format skops) + paquet `model.joblib` et `metadata.json` |

```bash
export MLFLOW_TRACKING_URI=http://127.0.0.1:5000
python -m velov.data
python -m velov.train --mlflow --seed 42
python -m velov.train --mlflow --seed 7
```

**Écart de MAE entre les seeds 42 et 7 :**
- **Seed 42 :** MAE modèle = **1.339** vélos (pointes = 1.430 vélos)
- **Seed 7 :** MAE modèle = **1.345** vélos (pointes = 1.445 vélos)
- **Écart :** `0.006` vélo (~0.45%). Comme expliqué en cours (slide 12), une variation de l'ordre de 1 à 2 % entre différentes graines est purement attribuable au hasard/bruit statistique. Cela justifie la règle de promotion (étape 3) exigeant un gain minimal de 2 % pour qu'un modèle soit promu champion.

### Étape 3 : Registre et promotion (`velov.promote`)

Le registre MLflow gère les versions du modèle via les alias `@champion`, `@challenger` et `@previous-champion` (exigence EX-14 / ADR 0002).

**Règle de promotion en 3 conditions :**
1. **Même fenêtre :** Challenger et champion évalués sur le même historique récent.
2. **Battre la persistance :** Le challenger doit obligatoirement avoir `mae_model < mae_baseline_persistence` (EX-05).
3. **Battre le champion de 2 % :** `mae_model <= mae_champion * (1 - 0.02)` pour s'affranchir du bruit statistique lié à la graine aléatoire.

```bash
# Simuler la décision de promotion
python -m velov.promote

# Appliquer la promotion (déplace @champion et archive l'ancien sous @previous-champion)
python -m velov.promote --apply

# Exécuter les tests de la règle de promotion
pytest tests/test_promote.py
```

### Étape 4 : Intégration continue (Workflow CI GitHub Actions)

Le workflow `.github/workflows/ci.yml` s'exécute à chaque `push` et `pull_request` :

1. **`lint`** : Vérifie la qualité et le formatage du code avec `ruff check .` et `ruff format --check .`.
2. **`tests`** : Exécute l'ensemble de la suite de tests avec `pytest` :
   - Contrat d'API et features (`tests/test_api.py`, `tests/test_features.py`)
   - Test de modèle (`tests/test_model_quality.py`) : vérifie que le modèle bat la baseline de persistance et qu'une même seed produit un artefact reproductible au SHA-256 près.
   - Règle de promotion du registre (`tests/test_promote.py`)
3. **`secrets`** : Analyse l'historique complet git avec `gitleaks` (avec `.gitleaksignore` pour les faux secrets pédagogiques).
4. **Actions épinglées** : Toutes les actions GitHub (`checkout`, `setup-python`, `gitleaks-action`) sont épinglées par leur hash de commit SHA complet pour garantir l'intégrité de la supply chain.
