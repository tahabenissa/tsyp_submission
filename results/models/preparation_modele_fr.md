MODELE DE PREPARATION : CALIBRATION ET RESIDUS

But
===

Ce modele prepare les donnees avant toute decision. Il ne cherche pas a dire qu'une mesure est une attaque. Il ne contient donc ni detecteur, ni scenario d'attaque, ni apprentissage automatique.

Il compare chaque jour la mesure de la station avec NASA POWER, une source independante qui donne une estimation de la meteo pour la meme zone. Une station mesure un point precis et POWER represente une zone plus grande : un petit ecart habituel est normal.

1. Calibration
==============

La premiere annee sert uniquement a apprendre les ecarts habituels. Le calcul est fait separement pour DJF, MAM, JJA et SON, car la meteo change avec les saisons.

Pour la temperature, l'humidite et le soleil, le modele apprend l'ecart median station moins POWER. Pour le vent et la pluie, il apprend plutot un rapport en logarithme : cela est plus adapte aux valeurs positives et aux petites valeurs. Pour la pluie, les jours ou les deux sources sont presque seches ne dominent pas le calcul.

Le modele mesure aussi la dispersion habituelle avec une mesure robuste : la MAD. Cette mesure est moins influencee par une journee tres inhabituelle. Une valeur minimale evite toute division par zero.

2. Residus de reference
========================

Chaque jour, le modele retire l'ecart normal appris puis le divise par la dispersion habituelle. Le resultat est un residu standardise. Un residu proche de zero veut dire que la station est proche de son comportement habituel par rapport a POWER. Une valeur grande, positive ou negative, veut dire que leur ecart est inhabituel.

Une valeur manquante reste manquante. Le modele ne complete jamais les jours absents.

3. Residus temporels
====================

Le modele fait aussi une prediction a partir de la saison et des jours precedents de la station. La partie saison utilise des courbes simples pour representer le cycle annuel. La partie autoregressive utilise seulement le passe : elle ne regarde jamais le lendemain.

Le residu temporel est la mesure du jour moins cette prediction. Il aide a separer un changement inhabituel de la variation normale de la meteo.

4. Pourquoi verifier sur 2024
=============================

Les parametres sont ajustes seulement avec 2023, puis appliques sans les changer a 2024. Cette separation montre si le modele reste raisonnable sur des donnees qu'il n'a pas utilisees pour apprendre.

Les tableaux de controle regardent la moyenne, la mediane, la dispersion par saison, les jours ordinaires et les jours extremes. Ils regardent aussi si un residu ressemble trop a celui de la veille. Les figures montrent les residus dans le temps et leur repartition par saison.

Limite importante
=================

Une seule annee d'apprentissage voit chaque saison une seule fois. Les estimations saisonnieres sont donc utiles mais encore fragiles. Le mode de demarrage rapide utilise seulement les premiers jours disponibles ; quand une saison n'a pas encore ete vue, il utilise l'estimation globale et le signale dans ses parametres.
