# Detector M --- Documentation technique

## 1. Objectif

Detector M est le composant de détection basé sur l'apprentissage
automatique du projet SensorGuard. Il vise à repérer des comportements
anormaux dans les mesures météorologiques des stations AZMET, FAWN et
Kansas, notamment dans le contexte des attaques False Data Injection.

L'approche retenue est une détection **One-Class** : le modèle apprend
le comportement normal à partir de fenêtres propres. Les scénarios
d'attaque servent à évaluer le détecteur et ne sont pas utilisés pour
entraîner LOF.

## 2. Données et caractéristiques

Les variables météorologiques utilisées comprennent :

-   `temp_c` : température ;
-   `rh_pct` : humidité relative ;
-   `wind_ms` : vitesse du vent ;
-   `precip_mm` : précipitations ;
-   `solar_mj_m2` : rayonnement solaire.

Les données de référence NASA POWER sont utilisées dans la préparation
et la construction de caractéristiques comparatives.

La matrice utilisée pour l'entraînement LOF contient **3 285 fenêtres
propres et 142 caractéristiques**, soit une forme `(3285, 142)`. Le
scaler est ajusté sur les fenêtres propres d'entraînement, puis appliqué
à ces mêmes données.

Selon la séparation temporelle du projet, les données propres des années
2021 à 2023 sont utilisées pour l'entraînement et les données propres de
2024 pour la validation et la calibration des seuils.

## 3. Pipeline One-Class

Le fonctionnement général est le suivant :

1.  préparer les données des stations et les références ;
2.  construire les fenêtres et les caractéristiques ;
3.  séparer les données propres d'entraînement et de validation ;
4.  ajuster le scaler sur les fenêtres propres d'entraînement ;
5.  entraîner les modèles candidats uniquement sur les fenêtres propres
    ;
6.  calculer les scores sur les données propres de validation et les
    scénarios d'attaque ;
7.  déterminer les seuils à partir des scores propres de validation ;
8.  produire les scores et les prédictions d'anomalie.

Les **129 scénarios d'attaque** sont évalués séparément. Ils ne sont pas
inclus dans la matrice d'entraînement de LOF.

## 4. Comparaison des modèles

Les candidats comparés sont :

-   Isolation Forest (IF) ;
-   ECOD ;
-   COPOD ;
-   HBOS ;
-   KNN ;
-   LOF, ajouté lors de l'amélioration.

Les métriques utilisées sont :

  -----------------------------------------------------------------------
  Métrique                            Description
  ----------------------------------- -----------------------------------
  ROC-AUC                             Capacité à distinguer les
                                      observations normales et anormales
                                      selon les scores

  AP                                  Average Precision, qualité du
                                      classement des anomalies

  Precision                           Part des détections positives qui
                                      sont réellement anormales

  Recall                              Part des anomalies réelles
                                      détectées

  F1-score                            Équilibre entre précision et rappel

  FPR                                 Part des observations propres
                                      classées à tort comme anomalies
  -----------------------------------------------------------------------

### Baseline KNN avec seuil global

  Métrique              Résultat
  ------------------- ----------
  ROC-AUC                 0,7066
  AP                      0,4175
  Precision               0,1912
  Recall                  0,1605
  F1-score                0,1545
  FPR propre pooled       1,00 %

KNN était le meilleur candidat de la comparaison initiale, mais son
rappel était faible. Le seuil global produisait également des
différences de faux positifs selon les stations et les saisons.

## 5. Améliorations apportées

### 5.1. Ajout de LOF

LOF (*Local Outlier Factor*) a été ajouté aux modèles candidats. Il
évalue le caractère atypique d'une observation en comparant sa densité
locale à celle de ses voisins.

Dans l'expérimentation réalisée, la nouvelle configuration LOF avec
seuils saisonniers obtient les meilleurs résultats parmi les
configurations comparées.

### 5.2. Seuils par site et par saison

Le mode de seuil saisonnier est activé dans la configuration avec :

``` yaml
threshold_mode: "season"
```

Au lieu d'utiliser un seul seuil global, le système utilise des seuils
adaptés au site et à la saison. Ces seuils sont calculés à partir des
scores des données propres de validation 2024 ; les scénarios d'attaque
ne participent pas à leur calcul.

Les seuils sont sauvegardés dans :

``` text
results/models_detector_m/thresholds_m.pkl
```

Le mécanisme de fallback est le suivant :

-   seuil site/saison disponible : utilisation de ce seuil ;
-   seuil saisonnier manquant : retour au seuil du site ;
-   fichier `thresholds_m.pkl` absent : utilisation du seuil global
    `threshold_m.pkl`, s'il est disponible.

## 6. Résultats avant et après

  Métrique              KNN global   LOF saisonnier
  ------------------- ------------ ----------------
  ROC-AUC                   0,7066       **0,7293**
  AP                        0,4175       **0,4467**
  Precision                 0,1912       **0,5160**
  Recall                    0,1605       **0,3152**
  F1-score                  0,1545       **0,3134**
  FPR propre pooled         1,00 %           1,09 %

La nouvelle configuration améliore les cinq métriques de détection. La
précision passe de 0,1912 à 0,5160 et le rappel de 0,1605 à 0,3152.

Le FPR propre pooled passe de 1,00 % à 1,09 %. Le pic de FPR AZMET en
été diminue de 11,96 % à environ 1,09 %. Les combinaisons site/saison
vérifiées sont également proches de 1,09 %.

## 7. Prédictions par station

Les prédictions exécutées donnent les nombres d'anomalies suivants :

  Station     Observations   Anomalies détectées
  --------- -------------- ---------------------
  AZMET              1 461                    29
  FAWN               1 461                    25
  Kansas             1 461                    21

Une prédiction d'anomalie signale une observation à examiner ; elle ne
prouve pas à elle seule qu'une attaque réelle a eu lieu.

## 8. Vérifications effectuées

### 8.1. Entraînement propre uniquement

La vérification a confirmé un seul appel à `fit` pour LOF, sur une
matrice `(3285, 142)` identique à la sortie du scaler ajusté sur les 3
285 fenêtres propres d'entraînement. Les 129 scénarios d'attaque sont
traités séparément.

### 8.2. Seuils sans étiquettes d'attaque

Les seuils ont été recalculés uniquement à partir des scores propres de
validation 2024. L'écart maximal avec `thresholds_m.pkl` est de **0,0**.
Les blocs `clean_scores_for_model` et `thresholds_for_model` ne
référencent pas les attaques.

### 8.3. Comparaison équitable

Les versions avant et après utilisent les mêmes 129 scénarios, les mêmes
répartitions par site et type d'attaque et les mêmes colonnes de
métriques. Les moyennes recalculées correspondent exactement aux résumés
enregistrés.

### 8.4. Prédictions et fallback

Les prédictions recalculées à partir de `thresholds_m.pkl` correspondent
aux valeurs `is_anomaly` et `anomaly_score` enregistrées. Les
vérifications confirment également le fallback global si le fichier
saisonnier est absent et le retour au seuil du site lorsqu'une saison
manque.

Le journal de preuve de cette ancienne version n'est pas inclus (il contenait des chemins
locaux). La version actuelle de Detector M est décrite dans le rapport, section 5.2.

## 9. Tests logiciels

La suite de tests exécutée après les modifications a donné :

``` text
120 passed
16 warnings
```

Les 120 tests ont réussi. Les 16 avertissements sont à examiner
séparément si nécessaire.

## 10. Limites restantes

-   Le Recall de 0,3152 reste modéré : une partie importante des
    anomalies n'est pas détectée.
-   Certains scénarios Drift de FAWN conservent une ROC-AUC inférieure à
    0,5. Exemple : `solar std -1`, avec une AUC de 0,388.
-   L'analyse indique que certaines attaques déplacent la série vers une
    zone déjà considérée comme normale par le modèle One-Class. Ces
    scénarios nécessitent une analyse complémentaire des
    caractéristiques, des scores et de la génération des attaques.
-   Les anomalies signalées doivent être examinées à l'aide du contexte
    des mesures et de références indépendantes.

## 11. Artefacts principaux

  ------------------------------------------------------------------------------------------------------
  Fichier                                                            Rôle
  ------------------------------------------------------------------ -----------------------------------
  `src/sensorguard/detect/learned.py`                                Logique du détecteur appris,
                                                                     candidats et seuils

  `config/config_m.yaml`                                             Configuration de Detector M, dont
                                                                     le mode de seuil

  `results/models_detector_m/model_comparison.csv`                   Comparaison des modèles

  `results/models_detector_m/attack_scenario_metrics.csv`            Métriques détaillées par scénario

  `results/models_detector_m/thresholds_m.pkl`                       Seuils saisonniers

  `results/models_detector_m/best_model_m.pkl`                       Modèle sélectionné

  `results/models_detector_m/scaler_m.pkl`                           Scaler

  `results/models_detector_m/features_m.pkl`                         Informations sur les
                                                                     caractéristiques

  `results/models_detector_m_analysis/baseline_vs_new_summary.csv`   Comparaison baseline/nouvelle
                                                                     version

  ------------------------------------------------------------------------------------------------------

## 12. Conclusion

Detector M a été amélioré par l'ajout de LOF et de seuils adaptés au
site et à la saison. La nouvelle configuration obtient de meilleurs
résultats que la baseline KNN globale sur ROC-AUC, AP, Precision, Recall
et F1-score.

Les vérifications confirment que LOF est ajusté sur les fenêtres
propres, que les seuils saisonniers sont calculés à partir des scores
propres de validation, que la comparaison utilise les mêmes scénarios et
que les prédictions sont reproductibles avec les seuils sauvegardés.

Cette configuration constitue une meilleure version de référence pour
Detector M, mais elle ne doit pas encore être considérée comme
définitive : le rappel reste modéré et certains scénarios Drift de FAWN
restent difficiles à détecter.

Les changements décrits concernent Detector M. **Detector S et le
système de fusion n'ont pas été modifiés** dans le cadre de ces
améliorations.
