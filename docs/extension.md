# Extension : Fraîcheur des données · niveau 2 (★★)

## La question

Comment détecter, mesurer en continu et diagnostiquer immédiatement l'obsolescence des données d'entrée dans le pipeline Vélo'v, afin de garantir qu'une défaillance amont ne laisse pas l'API servir des prédictions sur des données gelées sans qu'une alerte d'exploitation explicite ne soit levée ?

L'extension permet de distinguer formellement :
1. Une API de prédiction saine (HTTP 200 en sortie).
2. Un flux de données amont frais vs corrompu / arrêté.

---

## La mesure

### 1. Métrique et SLO
- **SLI** : `velov_data_freshness_seconds` (temps écoulé en secondes entre l'horodatage courant et l'observation la plus récente stockée en base).
- **SLO** : 99 % du temps sur 24 heures glissantes, la fraîcheur des données reste inférieure à **15 minutes**.

### 2. Référence et calibration du seuil
- Analyse de l'historique des collectes de la session 3 (`data/velov_history.csv` / table DuckDB) pour mesurer la distribution réelle des délais entre deux observations.
- Le seuil d'alerte (15 min) est calibré sur le **percentile 99** de l'intervalle réel de mise à jour (habituellement 5 min $\pm$ 2 min de gigue réseau), garantissant un seuil sans faux positifs intempestifs.

### 3. Trois causes de panne distinctes
Le système d'observation qualifie et isole trois modes d'échec :
1. **Cause 1 - Source externe indisponible** : L'API Grand Lyon / JCDecaux renvoie un code 5xx, un timeout ou est inaccessible.
2. **Cause 2 - Panne du pipeline local** : Le script de collecte plante (erreur de dépendance, réseau local, ou arrêt de la base PostgreSQL).
3. **Cause 3 - Données gelées / Stagnation** : Le scraper s'exécute avec succès (code 200), mais renvoie 0 nouvelles lignes ou un payload dont le timestamp ne progresse plus.

---

## Où ça tourne

- **En local** :
  - Calibration du seuil sur l'historique de données avec un script d'analyse.
  - Tests unitaires et d'intégration simulant les trois causes de panne (mocks HTTP, données figées, base coupée).
- **Sur la VM (en S7 / S8)** :
  - Pipeline de collecte automatisé (cron ou conteneur de scraping).
  - Exporteur de la métrique vers Prometheus (`:9090`).
  - Alertes dans `alerts.yml` (`DonneesObsoletes`, `SourceExterneInjoignable`, `DonneesGelees`).
  - Panneau de fraîcheur dédié sur le tableau de bord Grafana.

---

## Qui fait quoi

- **Membre A (Nolan)** :
  - Analyse statistique de l'historique (S3) et calibration du seuil de fraîcheur.
  - Définition des règles d'alerte PromQL dans `alerts.yml` et configuration du panneau Grafana associé.
  - Documentation de la procédure de diagnostic dans le runbook.
- **Membre B** :
  - Instrumenter le script de collecte/scraping pour distinguer et journaliser les trois causes de panne.
  - Création du scénario de test provoquant chaque panne et vérification de la remontée des alertes.
  - Rédaction de la fiche d'architecture (ADR).

---

## Si ça ne marche pas

- **Périmètre réduit garanti** :
  - Exposition de la métrique unique de fraîcheur (`velov_data_freshness_seconds`) calculée par une requête SQL périodique sur la table des prédictions.
  - Déclenchement d'une alerte Prometheus binaire si la fraîcheur dépasse le seuil critique de 15 minutes.
  - Le diagnostic précis de la cause parmi les 3 se fera via la consultation des logs Uvicorn/collecte documentée dans le runbook.
