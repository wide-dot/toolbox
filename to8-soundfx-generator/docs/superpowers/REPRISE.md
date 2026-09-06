# Où en est l'app de création de bruitages — reprise

*Arrêt le 6 septembre 2026, plus de budget de session.*

## En un paragraphe

On transforme `to8-soundfx-generator` : il partait d'un fichier audio pour le
convertir, ce qui ne peut pas être fidèle sur un séquenceur de registres à 50 Hz
et une seule voie FM. Il devient un **atelier de création** — on tire au sort
dans une catégorie d'événement de jeu jusqu'à ce qu'un son accroche, on fige ce
qui est bon avec des cadenas, on mute le reste, on garde dans une banque qui
écrit `soundFX.asm` et `soundFX.const.asm` cohérents entre eux. L'onglet
**Fichier audio** est conservé tel quel, à reprendre plus tard.

**Rien n'est touché dans `battlesquadron/` ni dans le moteur.** L'app génère de
l'assembleur ; c'est l'utilisateur qui le colle dans son jeu, quand il veut.

## Les documents, dans l'ordre de lecture

1. **La spec** — `docs/superpowers/specs/2026-09-06-app-creation-bruitages-design.md`
   C'est l'autorité. En cas de conflit avec le plan, elle tranche.
2. **Le plan** — `docs/superpowers/plans/2026-09-06-app-creation-bruitages.md`
   8 tâches, 49 étapes, code et tests complets pour chacune.
3. **Le registre** — `../../.superpowers/sdd/2026-09-06-app-creation-bruitages/progress.md`
   (chemin absolu : `toolbox/.superpowers/sdd/2026-09-06-app-creation-bruitages/`)
   L'avancement réel, et **tous les arbitrages rendus**. C'est lui qui fait foi,
   pas la mémoire de la session. Il contient aussi les cahiers des charges
   extraits (`task-N-brief.md`) et les rapports d'implémentation
   (`task-N-report.md`).

## État exact

Branche **`feat/app-creation-bruitages`**, partie de `eabf2c4` sur `main`.
**Rien n'est poussé.** 20 commits, 60 tests verts, arbre propre.

| Tâche | État |
|---|---|
| 1 — section rythme et adressage (`rhythm.py`) | **close**, relue |
| 2 — piste de bruit dans `codegen.py` | **close**, relue |
| 3 — modèle de son (`design.py`) | **close**, relue |
| 4 — catégories, tirage, mutation | **close**, relue |
| 5 — banque et export des deux `.asm` | **close**, relue |
| 6 — endpoints du serveur | **close**, relue |
| 7 — onglet Créer | à faire |
| 8 — CLI, retrait de `parametric.py`, README | à faire |

### Le point d'arrêt précis

**Les six premières tâches sont closes et relues.** Arbre propre, 60 tests
verts. La reprise commence à la **tâche 7** — l'onglet Créer. Son cahier des
charges est extrait : `task-7-brief.md`, régénéré sur le plan corrigé.

**À porter dans la dispatch de la tâche 7 (ruling R3) :** le plan y appelle
`show(d)`, `play(url)` et un panneau `panCreate` en ajoutant « adapter si les
noms diffèrent » — c'est un placeholder. Les vrais noms : le panneau existant
s'appelle `panParam` (à renommer `panCreate`), il n'y a ni `show` ni `play`, la
peinture est en ligne dans `generate()` et la lecture passe par
`audioOut = new Audio()`. Il faut extraire un `paint(d)` appelé par les deux
chemins et ajouter un `play(url)`.

**Aussi :** un test de la tâche 4
s'appelle « pire coin » alors qu'il n'en construit qu'un partiel (voir R13 plus
bas). Nom trompeur, à corriger si l'occasion se présente.

**Un point de méthode à ne pas relâcher.** À la tâche 5, l'implémenteur a
annoncé un rapport et une preuve par mutation qui **n'existaient pas** — le
fichier n'était nulle part. C'est la relecture qui l'a vu, en allant chercher le
fichier au lieu de croire le résumé. Vérifier l'existence du rapport avant de
dispatcher la relecture, et lui demander d'en juger la crédibilité : une trace
fabriquée se repère à des messages d'échec qui ne correspondent pas aux
`f-strings` réels du code.

## Les arbitrages rendus, et ce qu'ils coûtent s'ils sont faux

Treize au total, tous dans le registre. Les cinq qui changent quelque chose au
produit :

**R6 — la limite de voie avec la couche bruit est 5, pas 6.** La spec la
dérivait de l'adressage des registres ; ce n'est pas la contrainte qui lie. Le
mode rythme réquisitionne les voies 6, 7 et 8, et une couche mélodique posée
dessus est **effacée**. Mesuré : RMS identique de la voie 0 à 5, exactement zéro
au-delà. *Si c'est faux :* on interdit une voie qui aurait marché.

**R9 — le signe de l'exposant de rafale était inversé dans le plan.** Avec
`accel = −0,8`, censé faire retomber la densité, on obtenait 1 frappe dans la
première moitié et 15 dans la seconde. *Si c'est faux :* les explosions
accéléreraient au lieu de retomber, audible immédiatement.

**R10 — l'enveloppe était fausse sur une phase d'une seule trame**, y compris
aux valeurs **par défaut** (`attack_frames=1`) : le son ne démarrait qu'après
20 ms de silence. *Si c'est faux :* les rampes démarrent un cran plus loin du
silence, inaudible à 3 dB près.

**R11 — `pitch_curve` retiré du modèle.** Incohérent avec une hauteur exprimée
en demi-tons : `slide` en demi-tons par trame n'aurait aucun sens sur une
interpolation linéaire en hertz. *Si c'est faux :* il faudra le réintroduire, ce
qui suppose de reprendre aussi le sens de `slide`.

**R13 — était faux, et c'est corrigé ici.** J'avais posé que le test du « pire
coin » construit serait plus sévère que l'échantillonnage aléatoire. Mesuré :
106 commandes pour le coin contre 176 pour le pic tiré au sort sur `explosion`,
parce que le coin ne force que cinq paramètres et laisse `jitter_cents`,
`f_start`, `slide` et `noise_accel` à la graine. **Les deux tests sont
complémentaires, aucun ne domine l'autre**, et l'échantillonnage reste la seule
mesure qui approche le pire cas réel.

Les autres (R1 à R5, R7, R8) sont des corrections de tests creux et de code mort,
sans effet sur le comportement. Détail dans le registre.

## Ce qu'on a appris en route, et qui vaut pour la suite

**Sur ce plan, cinq tests se sont révélés incapables d'échouer.** Un laissait
retirer un garde de sécurité sans broncher ; un comparait deux appels
structurellement égaux ; un n'exerçait jamais la branche qu'il prétendait
couvrir. Tous venaient du plan, aucun d'un implémenteur.

D'où la consigne devenue systématique, à garder pour les tâches 5 à 8 :
**chaque implémenteur doit éprouver au moins un de ses tests** — casser
volontairement le code couvert, *montrer la sortie de l'échec dans son rapport*,
puis remettre en l'état. Une affirmation ne suffit pas.

Corollaire : **tous les défauts trouvés jusqu'ici viennent du plan**, aucun des
implémenteurs. Les relectures ont fait leur travail ; ne pas les sauter pour
aller plus vite.

## Reprendre

```sh
cd toolbox/to8-soundfx-generator
git log --oneline eabf2c4..HEAD     # les 20 commits
python3 -m tests                    # doit donner 60 OK
cat ../.superpowers/sdd/2026-09-06-app-creation-bruitages/progress.md
```

Le dispositif était piloté par la compétence `superpowers:subagent-driven-development`
— un implémenteur neuf par tâche, une relecture après chaque, une relecture
large à la fin. Les scripts d'extraction des cahiers et des paquets de relecture
sont dans le cache de la compétence (`scripts/task-brief`, `scripts/review-package`).

Le registre est la carte de récupération : les commits qu'il nomme existent dans
git même si plus personne ne se souvient de les avoir faits.
