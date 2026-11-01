RAPPORT FINAL - PREPARATION (residus)

CE QUE FAIT LA PREPARATION
- Sur 2021-2023, on apprend l'ecart normal entre la station et NASA POWER,
  saison par saison.
- Pour chaque jour, on enleve cet ecart et on divise par la dispersion
  habituelle : c'est le residu.
- On controle sur 2024 (jamais vue a l'apprentissage) que le residu est centre
  sur 0 et sans memoire.

CE QUI A ETE CORRIGE
- Pluie : les jours secs des deux cotes ne donnent plus de residu (NaN).
- Vent et pluie : transformation logarithmique dans le modele temporel.
- Controles : les valeurs de pluie et de vent nulles ne comptent plus comme
  jours extremes ; une valeur non calculable est NA et non FAIL.
- Entrainement elargi de 1 an a 3 ans.

COMPTES (2024, entrainement complet, residu de reference)
Site     PASS  WARN  FAIL
azmet     41    20     4
fawn      32    13    20
kansas    44    16     5
Les FAIL restants sont des decalages de niveau (26, moyenne ou mediane) et de
l'autocorrelation (3). Aucun ne concerne la largeur du residu. 
Les seuils PASS/WARN/FAIL sont des choix de depart, pas des verites.

STATUT PAR SITE
- azmet : bien centre, 4 FAIL.
- fawn : plus fragile, 20 FAIL.
- kansas : bien centre, 5 FAIL.

LIMITES CONNUES
- Pluie : pas de residu temporel (non previsible par les jours precedents).
- Demarrage rapide : ne couvre que l'hiver et le debut du printemps.
- Une seule annee de validation (2024). Test annee par annee : 2024 n'est pas
  plus mauvaise que 2021-2023 (29 FAIL pour les 3 sites ensemble, contre 28 a
  34 les autres annees). Le detail par site n'a pas ete calcule.
- Un biais de 12 % est bien visible sur la temperature de FAWN (3,19) et le
  solaire d'AZMET (3,00), peu visible sur la pluie (environ 0,07). Les autres
  variables : voir results/analysis_2021_2024 (tache 4).
- Autocorrelation du residu : a relire dans results/analysis_2021_2024 avant
  de choisir les seuils du detecteur.

CE QU'HERITE LE DETECTEUR S
- Des residus par site, variable et saison, avec NaN conserves.
- Des decalages naturels entre annees : seuils assez larges necessaires.
- Les limites ci-dessus.
