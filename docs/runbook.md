# Runbook : API velov-availability

> Public cible : une personne d'astreinte qui ne connaît pas le projet et doit rétablir le service à 3 h du matin.

## 1. Vue d'ensemble

- **Ce que fait le service** : L'API expose un modèle de machine learning servant à prédire en temps réel le nombre de vélos disponibles à une station Vélo'v à $t + 1\text{ h}$.
- **Architecture** : Service FastAPI conteneurisé (`velov-api`) servi par Uvicorn, adossé à une base PostgreSQL pour la journalisation des prédictions entrantes/sortantes et un registre MLflow.
- **Dépendances** :
  - Image de serving : Docker, Uvicorn, FastAPI.
  - Modèle : `models/model.joblib` et `models/metadata.json` (vérification d'empreinte SHA-256 au chargement).
  - Base de données : PostgreSQL 17 (`velov`), joignable via `DATABASE_URL`.

## 2. Démarrer / Arrêter

```bash
# Démarrer la stack locale (API + DB)
docker compose up -d --build

# Démarrer avec 2 workers sur 2 cœurs (montée en charge)
docker compose -f compose.yaml -f compose.workers.yaml up -d api
docker update --cpus 2 $(docker compose ps -q api)

# Démarrer la stack complète avec MLflow (sur VM)
docker compose -f compose.yaml -f compose.mlflow.yaml up -d --build

# Consulter les logs
docker compose logs -f api

# Arrêter les services (sans détruire les données)
docker compose down

# Arrêter et purger les volumes
docker compose down -v
```

## 3. Vérifier que tout va bien

| Vérification | Commande | Résultat attendu |
|---|---|---|
| Process répond (liveness) | `curl -s http://<hôte>:8000/health` | `{"status":"ok"}` |
| Modèle chargé (readiness) | `curl -s http://<hôte>:8000/ready` | HTTP 200 + `{"status":"ready","model_version":"..."}` |
| Métadonnées du modèle | `curl -s http://<hôte>:8000/v1/model` | HTTP 200 + JSON complet des métadonnées |
| Prédiction test | `curl -s -X POST http://<hôte>:8000/v1/predict -H "content-type: application/json" -d @payload.json` | HTTP 200 + `predicted_bikes` borné |
| Utilisation CPU / Mémoire | `docker stats --no-stream` | API < 85 % CPU, Mémoire stable |

---

## 4. Objectifs de niveau de service (SLO) et Capacité (EX-16)

### 4.1 Définition du SLO
- **SLI (Service Level Indicator)** : Latence serveur de `POST /v1/predict` (en-tête `X-Process-Time-Ms`) et taux d'erreur 5xx.
- **SLO (Service Level Objective)** :
  - **Latence p95 $\le$ 200 ms** sur 5 minutes glissantes.
  - **Taux d'erreur 5xx < 0.1 %** sur 5 minutes glissantes.

### 4.2 Capacité utile mesurée
- **1 worker sur 1 cœur CPU** :
  - Capacité utile sous le SLO : **~42 req/s** (tenue jusqu'à 50 usagers simultanés, p95 = 93 ms).
  - Plafond de saturation physique : **~58 req/s** (au-delà, la latence explose à > 1 200 ms par effet de file d'attente / loi de Little).
- **2 workers sur 2 cœurs CPU** :
  - Capacité utile sous le SLO : **~80-85 req/s** (tenue jusqu'à 100 usagers simultanés).
  - Plafond physique : **~110-115 req/s**.

### 4.3 Procédure près du plafond de charge
- **Seuil d'alerte** : Trafic soutenu supérieur à **80 % de la capacité utile** (ex: > 35 req/s sur 1 cœur, ou > 70 req/s sur 2 cœurs) ou latence p95 dépassant 150 ms.
- **Actions correctives immédiates** :
  1. Si l'API tourne sur 1 worker : basculer immédiatement à 2 workers sur 2 cœurs :
     ```bash
     docker compose -f compose.yaml -f compose.workers.yaml up -d api
     docker update --cpus 2 $(docker compose ps -q api)
     ```
  2. Si l'API tourne déjà sur 2 cœurs et sature : horizontal scaling en augmentant le nombre de conteneurs derrière le reverse proxy / répartiteur Nginx.
  3. Option logicielle d'optimisation : Basculer le moteur d'inférence vers ONNX Runtime (`MODEL_ENGINE=onnx`) ou activer le batching dynamique si le trafic le permet.

---

## 5. Stratégie de remplacement du modèle et retour arrière (EX-18)

### 5.1 Stratégie de déploiement
- Le déploiement s'effectue sans coupure de trafic en s'appuyant sur la sonde `/ready` : le conteneur ne reçoit du trafic que lorsque le modèle est validé et chargé.
- Sur environnement de production, privilégier un déploiement Canary (10 % du trafic au challenger via Nginx) ou Shadow (copie asynchrone des requêtes) avant bascule totale.

### 5.2 Critères de retour arrière (Rollback)

| Signal d'alerte | Seuil de déclenchement | Fenêtre de décision |
|---|---|---|
| **Taux d'erreur 5xx** | Supérieur à celui de l'ancienne version (> 0.1 %) | 2 minutes après déploiement |
| **Latence p95** | Supérieure au SLO (> 200 ms) sans pic de trafic externe | 5 minutes de trafic |
| **MAE en production** | Dégradation de la MAE constatée à $H+1$ vs ancien champion | 24 heures glissantes |

### 5.3 Commande de retour arrière immédiat

En cas de régression constatée en production :
```bash
# 1. Rétablir les artefacts de l'ancien champion depuis le registre MLflow
python -m velov.export --alias previous-champion --out models/

# 2. Recharger l'API avec l'artefact sain
docker compose restart api

# 3. Vérifier le rétablissement
curl -s http://localhost:8000/ready
```

---

## 6. Incidents connus

| Symptôme | Cause probable | Diagnostic | Action |
|---|---|---|---|
| `/ready` renvoie 503 | Modèle absent ou empreinte SHA-256 corrompue | `docker compose logs api` (chercher `FileNotFoundError` ou `Empreinte invalide`) | Vérifier la présence de `models/model.joblib` et `models/metadata.json`. Réexporter avec `python -m velov.export`. |
| Le conteneur redémarre en boucle | Dépendance PostgreSQL non prête ou plantage Uvicorn | `docker compose ps` et `docker compose logs` | Vérifier la santé de `db` : `docker compose restart db`. Vérifier les variables dans `.env`. |
| Latence p95 > 200 ms | Saturation CPU par surcharge de requêtes | `docker stats --no-stream` | Voir section 4.3 : passer à 2 workers (`compose.workers.yaml`) ou ajouter des réplicas. |
| Erreur base de données / logs | Perte de connexion Postgres | `docker compose logs api` | L'API continue de prédire même si la base tombe (`_log` ignore les pannes pour ne pas bloquer l'inférence). Relancer `db`. |

---

## 7. Contacts et escalade
- **Équipe MLOps / Maintenance** : Binôme groupe 9
- **Escalade astreinte** : Consulter les logs Docker et appliquer le rollback de la section 5.3 si le p95 ou les 5xx violent le SLO plus de 5 minutes.
