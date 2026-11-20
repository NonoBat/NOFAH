# Model card : velov-availability

> Template à compléter par le binôme. Mettez-la à jour à chaque nouvelle version du modèle.
> Inspirée de Mitchell et al., "Model Cards for Model Reporting" (2019).

## 1. Identité
- Nom / version :
- Date d'entraînement :
- Responsables (binôme) :
- Emplacement de l'artefact (fichier, registre, image) :

## 2. Usage prévu
- Ce que le modèle prédit :
- Utilisateurs et décisions alimentées :
- Usages hors périmètre (ce qu'il ne faut PAS faire avec ce modèle) :

## 3. Données
- Source, période couverte, volume :
- Découpage entraînement / test (et pourquoi temporel) :
- Limites connues (stations absentes, événements exceptionnels, météo...) :

## 4. Performance
| Métrique | Modèle | Baseline (persistance) | Seuil d'acceptation |
|---|---|---|---|
| MAE (vélos) | | | |

- Performance par segment (heure de pointe, week-end, station) :

## 5. Contrat d'entrée / sortie
- Champs d'entrée, types, bornes :
- Sortie et unité :
- Comportement sur entrée inconnue (nouvelle station...) :

## 6. Risques et limites
- Dérive attendue (saisonnalité, travaux, nouvelles stations) :
- Données personnelles : oui / non, justification :

## 7. Exploitation
- Latence cible : 200 ms (p95) sous 42 req/s (1 worker)
- Fréquence de réentraînement prévue : Hebdomadaire ou sur alerte de performance (ratio > 0.90)
- Lien vers le runbook : [runbook.md](runbook.md)

## 8. Monitoring et Surveillance du modèle (S6 - EX-21)

### 8.1 Résultats des semaines rejouées

| Semaine rejouée | Colonnes en dérive (score Wasserstein > 0.1) | MAE Modèle | MAE Persistance | Ratio | Statut / Alerte |
|---|---|---|---|---|---|
| **Semaine normale** | `temperature` (0.394) | 1.309 | 1.821 | **0.72** | ✅ Normal (conforme entraînement) |
| **Froid (-15 °C)** | `temperature` (4.460) | 1.420 | 1.821 | **0.78** | ✅ Acceptable (pas d'alerte) |
| **Déménagement** | `temperature` (0.394), `bikes_available` (0.252), `occupancy_rate` (0.301), `predicted_bikes` (0.264) | 1.580 | 1.821 | **0.87** | ⚠️ Dégradation critique par segment |

### 8.2 Réponses aux questions d'analyse

1. **Quelles colonnes dérivent, et pourquoi ?**
   - *Semaine normale* : seule la `temperature` dérive légèrement (score 0.39) en raison de la saisonnalité climatique fin août. Les prédictions et la disponibilité ne dérivent pas (scores < 0.05).
   - *Scénario Froid (-15 °C)* : la variable d'entrée `temperature` dérive massivement (score 4.46). En revanche, la distribution des sorties (`predicted_bikes`) dérive à peine (0.12) car l'arbre de décision n'utilise pas la température comme feature discriminante majeure.
   - *Scénario Déménagement* : dérive nette des entrées structurelles (`bikes_available` à 0.25, `occupancy_rate` à 0.30) et surtout de la sortie du modèle (`predicted_bikes` à 0.26). Le basculement des stations de bureaux en stations résidentielles déplace la distribution vers les stations pleines en soirée.

2. **Le ratio à la persistance, comparé à celui de l'entraînement :**
   - À l'entraînement (fenêtre de test S4), le ratio $\text{MAE}_{\text{modèle}} / \text{MAE}_{\text{persistance}}$ valait **0.71**.
   - En condition normale rejouée, le ratio est de **0.72** : le modèle conserve l'intégralité de sa valeur ajoutée (+28 % face à la persistance).
   - En conditions de grand froid, le ratio passe à **0.78** (+22 % face à la persistance).
   - En scénario déménagement, le ratio s'effondre à **0.87** (gain réduit à seulement 13 %).

3. **Les stations les plus mal prédites : un segment qui décroche ?**
   - Oui : la moyenne globale (0.87) masque un **décrochage sévère par segment**.
   - Sur les stations professionnelles modifiées (notamment les stations 14 et 17), le modèle obtient une MAE de 2.77 et 2.85 face à 2.74 et 2.79 pour la persistance (ratio > 1.0).
   - Sur ce cluster, le modèle fait **pire que de ne rien faire** (pire que la persistance).

4. **Décision de réentraînement et seuil d'alerte retenu :**
   - **Seuil d'alerte retenu** : Ratio global $\ge 0.90$ ou au moins 2 stations avec ratio $> 1.0$ persistant plus de 48 h.
   - **Décision** :
     - Semaines normale et froid : **Ne pas réentraîner**. Une dérive d'entrée (température) sans dégradation d'erreur ne justifie aucun réentraînement.
     - Déménagement : **Réentraînement indispensable**. Après 2 semaines d'accumulation de la nouvelle distribution, exécuter `python -m velov.retrain` puis `python -m velov.promote`.

