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
| `s2-end` | Image Docker multi-stage, compose API + PostgreSQL, journalisation des prédictions |
| `s3-end` | Pipeline : collecte bronze, dbt silver et gold sur DuckDB, contrat Pandera, flow Prefect |
| `s4-end` | Suivi MLflow, registre (alias champion / challenger), promotion, export, CI GitHub Actions |

```bash
git checkout s1-end          # récupérer l'état de fin de S1
git checkout -b mon-binome   # travailler sur sa propre branche
```

## Démarrage rapide

Prérequis : Python 3.11+ (3.12 recommandé), git, Docker Desktop ou Docker Engine.

```bash
python -m venv .venv
source .venv/bin/activate            # Windows : .venv\Scripts\activate
pip install -r requirements-dev.txt
pip install -e .                     # rend le package velov importable

python -m velov.data                 # génère data/velov_history.csv (simulateur, seed fixe)
python -m velov.train                # entraîne et écrit models/model.joblib + models/metadata.json
python -m velov.train --mlflow       # idem + run tracé dans MLflow (voir « MLflow (S4) »)
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

## Docker (S2)

```bash
python -m velov.data && python -m velov.train   # l'image embarque models/ : il doit exister
docker build -t velov-api:0.1.0 .
docker run --rm -p 8000:8000 velov-api:0.1.0

cp .env.example .env                            # puis changer POSTGRES_PASSWORD
docker compose up --build -d
docker compose logs -f api
docker compose down                             # -v pour supprimer aussi le volume Postgres
```

## Pipeline de données (S3)

```bash
python -m velov.ingest --replay data/fixtures     # bronze de démonstration (48 h, 20 stations)
python -m velov.ingest                            # ou un instantané du vrai flux de la Métropole
cd velov_dbt && dbt build --profiles-dir . && cd ..   # silver et gold, tests et contrat
python -m velov.contract                          # contrat Pandera sur la table gold
python -m velov.train --data data/velov.duckdb --test-days 1
python -m velov.flow                              # les trois étapes orchestrées par Prefect
```

dbt est le seul écrivain de `data/velov.duckdb` : le reste ouvre la base en lecture seule.
Collecte continue sur la VM : voir l'en-tête de `src/velov/ingest.py` (crontab, toutes les 5 minutes).

## MLflow (S4)

```bash
# même PostgreSQL que l'API (service db), base dédiée "mlflow" ; aucun nouveau secret
docker compose -f compose.yaml -f compose.mlflow.yaml up -d --build  # http://<ip-vm>:5000
export MLFLOW_TRACKING_URI=http://127.0.0.1:5000    # sans serveur : sqlite:///mlflow.db

python -m velov.train --version 0.1.0 --register    # run tracé + version "challenger"
python -m velov.promote                             # décision, sans rien changer
python -m velov.promote --apply                     # déplace l'alias "champion" si la règle est remplie
python -m velov.export --alias champion --out models/
./scripts/release.sh                                # sur la VM : export, build, redémarrage de l'API
```

La règle de promotion et la livraison du modèle sont justifiées dans `src/velov/promote.py`
et `docs/adr/0002-livraison-du-modele.md`. La CI est dans `.github/workflows/ci.yml`.

## Test de charge (S5)

Fournis pour le TP5 : `loadtest/` (scénario Locust, paliers, résumé) et les fichiers `requirements-*.txt`.

```bash
# depuis le POSTE, vers l'API sur la VM (jamais depuis la machine qui sert l'API)
pip install -r requirements-loadtest.txt
./loadtest/paliers.sh http://<ip-vm>:8000 w1      # échauffement, puis 10, 25, 50, 100, 150 usagers
python loadtest/summary.py results/w1 --markdown  # p50, p95, p99, débit, erreurs, capacité sous le SLO
```

### Performance & Protocole de mesure (Étape 1 - Mesure locale)

- **Mode de mesure** : Mesure locale (API et Locust sur le même poste, VM indisponible).
- **Isolation CPU** : API bornée strictement à 1 cœur CPU (`docker update --cpus 1 nofah-api-1`), Locust tourne sur les autres cœurs du poste pour éviter la contention.
- **Machine hôte** : 8 cœurs CPU (`os.cpu_count() = 8`).
- **Services locaux** : MLflow et tout service inutile arrêtés. Seule l'API (`velov-api:dev`) et la base Postgres tournent.
- **Versions** : Locust 2.47.0, Python 3.12.10, image API basée sur `python:3.12-slim`.
- **Commit testé** : `00a0568` (branche `tp5`).
- **Date & Heure** : 17 novembre 2026 à 12:04.

#### Validation du premier essai (10 usagers, 1 minute)

| Endpoint | Nb requêtes | Échecs | Débit (req/s) | p50 (ms) | p95 (ms) | p99 (ms) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `POST /v1/predict` | 514 | 0 (0.00 %) | 8.63 | 69 ms | 130 ms | 460 ms |
| `GET /health` | 45 | 0 (0.00 %) | 0.76 | 6 ms | 23 ms | 32 ms |
| **Total / Agrégé** | **559** | **0 (0.00 %)** | **9.39** | **68 ms** | **120 ms** | **460 ms** |

### Courbe de saturation (Étape 2 - 1 worker sur 1 cœur CPU)

Mesure effectuée via `loadtest/run_paliers.py http://localhost:8000 w1` (1 min échauffement, puis 2 min par palier) :

| usagers | requêtes | erreurs % | débit req/s | p50 ms | p95 ms | p99 ms | SLO p95 (<= 200 ms) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 10 | 1 029 | 0.0 % | 8.7 | 53 | 60 | 76 | **ok** |
| 25 | 2 496 | 0.0 % | 21.0 | 53 | 68 | 90 | **ok** |
| 50 | 5 016 | 0.0 % | 42.2 | 56 | 93 | 160 | **ok** |
| 100 | 6 941 | 0.0 % | 58.5 | 620 | 1 200 | 1 500 | **KO** |
| 150 | 6 902 | 0.0 % | 58.1 | 1 400 | 2 500 | 3 100 | **KO** |

#### Analyse et conclusion :
- **Capacité sous le SLO (p95 <= 200 ms)** : **~42 req/s** (atteinte à 50 usagers).
- **Point de bascule (coude de saturation)** : Le système sature entre 50 et 100 usagers. Le débit maximal plafonne à **~58 req/s**.
- **Effet de file d'attente (Loi de Little $L = \lambda \times W$)** : Au-delà de la capacité maximale du cœur (58 req/s), le débit ne progresse plus mais les requêtes s'accumulent dans la file d'attente Uvicorn. La latence au p95 explose alors de 93 ms à 1 200 ms (puis 2 500 ms à 150 usagers), avec 0 % d'erreurs HTTP mais un non-respect total du SLO.
- **Ressources mesurées** : L'API plafonne à 100 % d'un cœur CPU lors des paliers 100 et 150 usagers, tandis que Locust reste sous 25 % d'utilisation CPU sur les cœurs restants de l'hôte.

```
Débit (req/s) & Latence p95 (ms) selon les usagers :
Débit (req/s)                                  p95 (ms)
  60 |                                [58.5]--[58.1]       3000 |                              [2500]
  50 |                         [42.2]/                      2000 |
  40 |                                                     1000 |                      [1200]
  30 |                  [21.0]/                              500 |
  20 |           [8.7]/                                      200 |---------------------------- Ligne SLO (200 ms)
  10 |                                                       100 |         [60]---[68]---[93]
   0 +------------+-------+-------+-------+--------            0 +-----------+------+------+------+------
     0           10      25      50      100      150 usagers    0          10     25     50    100    150 usagers
```

### Profilage interne et goulot d'étranglement (Étape 3 - scripts/bench_predict.py)

#### 1. Temps passé dans l'API (`X-Process-Time-Ms`)
Mesuré via `curl` sur `POST /v1/predict` (avec `payload.json`) :
- **En régime établi** : `X-Process-Time-Ms` oscille entre **8.7 ms et 10.1 ms**.
- **Écart avec Locust** : À 10 usagers, Locust mesure un p50 de ~53 à 68 ms. L'écart (~43 à 58 ms) provient du protocole HTTP/TCP complet (RTT aller-retour réseau/sockets, pool de workers et boucle événementielle d'Uvicorn).

#### 2. Décomposition des 4 étapes de `_predict()` (500 itérations sans réseau)
Chronométrage isolé avec `python scripts/bench_predict.py --n 500` (chargement du modèle et échauffement exclus) :

| Étape de calcul | p50 (ms) | p95 (ms) | Part du temps |
| :--- | :--- | :--- | :--- |
| **Validation Pydantic** | 0.007 ms | 0.016 ms | 0.1 % |
| **DataFrame + add_features** | 2.146 ms | 2.825 ms | 40.5 % |
| **model.predict, 1 ligne** | 3.136 ms | 4.093 ms | 59.1 % |
| **Bornage et réponse** | 0.016 ms | 0.026 ms | 0.3 % |
| **Total calcul interne** | **5.305 ms** | **-** | **100 %** |

#### 3. Inférence par lots (`model.predict` avec `--batch 1 100 1000`)

| Taille du lot (lignes) | Temps du lot p50 (ms) | Temps du lot p95 (ms) | Temps par prédiction unitaire |
| :---: | :---: | :---: | :---: |
| **1** | 3.19 ms | 4.33 ms | 3.19 ms |
| **100** | 3.51 ms | 4.67 ms | 35.1 µs |
| **1000** | 6.88 ms | 8.86 ms | 6.9 µs |

*Constat : Le coût fixe de l'inférence est largement amorti par le traitement par lots (divisé par près de 460 à 1000 lignes).*

#### 4. Conclusion sur le goulot d'étranglement
> **Preuve et identification du goulot :**
> Le goulot d'étranglement de l'API est constitué à **99.6 %** par l'exécution CPU synchrone en Python : **59.1 % du temps dans l'inférence scikit-learn (`model.predict`, ~3.14 ms)** et **40.5 % dans la préparation des features pandas (`add_features`, ~2.15 ms)**. À l'inverse, la validation contractuelle Pydantic et l'assemblage de la réponse sont virtuellement instantanés (< 0.4 % du temps).

### Comparaison d'optimisation (Étape 4 - w1 contre w2)

La question : *Un worker et un cœur de plus, le débit double-t-il ?* (S5 · 12, règle 6).

- **w1** : 1 worker Uvicorn, bridé à 1 cœur CPU (`docker update --cpus 1`).
- **w2** : 2 workers Uvicorn (`compose.workers.yaml`), bridé à 2 cœurs CPU (`docker update --cpus 2`).
- Machine : même hôte (8 cœurs, Locust sur les cœurs restants).

#### 1. Tableaux comparatifs côte à côte (`results/w1/` vs `results/w2/`)

| Usagers | Débit w1 (req/s) | p95 w1 (ms) | SLO w1 | Débit w2 (req/s) | p95 w2 (ms) | SLO w2 | Gain débit | Évolution latence p95 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **10** | 8.7 | 60 ms | ok | 8.8 | 64 ms | ok | +1 % | stable |
| **25** | 21.0 | 68 ms | ok | 21.2 | 64 ms | ok | +1 % | -6 % |
| **50** | 42.2 | 93 ms | ok | 42.5 | 89 ms | ok | +1 % | -4 % |
| **100** | 58.5 | 1 200 ms | KO | **73.9** | **670 ms** | KO | **+26.3 %** | **-44.2 %** |
| **150** | 58.1 | 2 500 ms | KO | **63.0** | **1 700 ms** | KO | **+8.4 %** | **-32.0 %** |

#### 2. Mémoire consommée (`docker stats --no-stream`)
- **1 worker (`w1`)** : **168 Mo**
- **2 workers (`w2`)** : **315 Mo** ($\times 1.88$)
*Chaque worker chargeant son propre modèle en mémoire dans son processus Python, l'empreinte mémoire double quasiment.*

#### 3. Conclusion chiffrée : le débit double-t-il ?
> **Non, le débit ne double pas.**
> - Le débit maximal progresse de **58.5 req/s à 73.9 req/s (+26.3 %)** à 100 usagers, loin d'un doublement linéaire ($\times 2$ nécessiterait ~117 req/s).
> - **Cause** : Même avec 2 workers CPU indépendants, la journalisation en base PostgreSQL (`storage.py`) crée un goulot d'I/O partagé, et le multiplexage des sockets limite le gain linéaire pur.
> - **En revanche, le gain majeur réside dans la réduction massive de la latence sous saturation** : le temps de réponse au p95 est divisé par près de deux à 100 usagers (**670 ms contre 1 200 ms**, soit **-44.2 %**), réduisant nettement l'accumulation dans la file d'attente.

### TP5a : DistilBERT en int8 (Triplet Taille, Latence, Précision)

Mesure du triplet d'optimisation via `python scripts/bench_quantization.py` :
- **Modèle** : `distilbert-base-uncased-finetuned-sst-2-english` (Hugging Face)
- **Données** : 872 phrases de validation du benchmark SST-2 (`nyu-mll/glue`)
- **Conditions de test** : 1 seul thread CPU (`torch.set_num_threads(1)`), phrase de 128 tokens, 50 répétitions.

#### 1. Tableau récapitulatif du triplet

| Variante | Taille (Mo) | p50 (ms) | p95 (ms) | Précision SST-2 | Accord float32 | Écart max logits |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **float32** (référence) | 255.4 Mo | 39.4 ms | 53.6 ms | 91.06 % | 100.00 % | 0.0000 |
| **int8 torch.ao** (`quantize_dynamic`) | **132.4 Mo** | **25.1 ms** | **32.8 ms** | 90.71 % | 98.74 % | 0.4497 |
| **int8 torchao** (`Int8Dynamic...`) | **132.8 Mo** | 42.1 ms | 58.7 ms | 90.71 % | 98.39 % | 0.4673 |

#### 2. Analyse et conclusion :
- **Taille mémoire (-48 %)** : La quantification divise par près de 2 la taille du modèle en mémoire et sur disque (de 255 Mo à 132 Mo), permettant d'embarquer le modèle sur des machines plus légères ou d'augmenter le nombre d'instances par nœud.
- **Latence (-36 % avec `torch.ao`)** : L'accélération atteint $\times 1.57$ (latence réduite de 39.4 ms à 25.1 ms au p50) grâce aux instructions vectorielles entières du CPU.
- **Précision préservée (90.71 % contre 91.06 %)** : La perte de performance est négligeable (-0.35 point de pourcentage), avec un accord de **98.74 %** sur les prédictions par rapport à la version float32 (seules 11 phrases sur 872 changent de classe).
- **Enseignement technique sur les bibliothèques** : `torch.ao.quantization` bien que dépréciée par PyTorch, bénéficie encore d'implémentations C++ plus véloces sur CPU x86 que `torchao` qui présente un léger surcoût d'ordonnancement en mode eager (42 ms contre 25 ms).

## Structure

```
src/velov/
  data.py          simulateur de données (remplacé par l'open data en S3, même schéma)
  features.py      features partagées entraînement / API (anti training-serving skew)
  ingest.py        collecte du flux GBFS vers data/bronze, idempotente (S3)
  contract.py      contrat Pandera de la table d'entraînement (S3)
  flow.py          flow Prefect : ingestion, dbt, contrat (S3)
  train.py         entraînement, baseline, paquet model.joblib + metadata.json
  tracking.py      run MLflow, registre, alias (S4)
  promote.py       règle de promotion challenger / champion (S4)
  export.py        version du registre -> models/ avant le build (S4)
  retrain.py       réentraînement : entraîner, enregistrer, décider (S4)
  api/main.py      FastAPI : /health, /ready, /v1/model, /v1/predict, /v1/predict/batch
  api/schemas.py   contrat d'entrée / sortie (Pydantic)
  api/storage.py   journalisation des prédictions (S2)
tests/             pytest (features, API, ingestion, contrat, qualité du modèle, registre)
.github/workflows/ CI : lint, tests, scan de secrets, build et /ready de l'image (S4)
docs/              templates : model card, runbook, ADR
velov_dbt/         projet dbt : silver (stg_*), gold (station_hourly), tests, contrat (S3)
data/fixtures/     bronze de démonstration, régénérable avec scripts/make_fixtures.py (S3)
exercices/         démo pickle (S1), audit, debug et conformité Docker (S2), audit SQL (S3)
```

## Usage de l'IA générative

Chaque activité indique son mode : **sans IA**, **IA déclarée** ou **IA imposée**.
En mode IA déclarée, ajoutez dans la description de vos commits ou de votre rendu :
outil utilisé, ce que vous lui avez demandé, ce que vous avez vérifié ou corrigé.
