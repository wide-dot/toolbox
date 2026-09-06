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
**Rien n'est poussé.** 25 commits, 60 tests verts, arbre propre sur `fe44bb0`.

| Tâche | État |
|---|---|
| 1 — section rythme et adressage (`rhythm.py`) | **close**, relue |
| 2 — piste de bruit dans `codegen.py` | **close**, relue |
| 3 — modèle de son (`design.py`) | **close**, relue |
| 4 — catégories, tirage, mutation | **close**, relue |
| 5 — banque et export des deux `.asm` | **close**, relue |
| 6 — endpoints du serveur | **close**, relue |
| 7 — onglet Créer | **close**, relue — *non observée en navigateur* |
| 8 — CLI, retrait de `parametric.py`, README | **close**, relue |

### Le point d'arrêt précis

**Les huit tâches sont closes et relues.** 25 commits, 60 tests verts, arbre
propre sur `fe44bb0`. Puis la **relecture finale de branche** a rendu son
verdict : **non fusionnable en l'état**. Sa vague de correction a été lancée et
tuée par la limite de session avant d'écrire quoi que ce soit — rien à démêler,
tout est à faire.

## Vague de correction finale — à faire en reprenant

Huit constats, par ordre d'importance. C'est la relecture d'assemblage qui les a
vus : chaque tâche était propre isolément, aucune ne pouvait les voir.

**C1 — CRITIQUE. La banque est un cul-de-sac : rien n'en sort.**
`Bank.to_json` n'est appelé nulle part hors tests. `_bank_view` renvoie pourtant
`build.asm` et `build.const`, mais `refreshBank()` ne lit que `per_sound`,
`bytes` et `warnings` : **les deux fichiers assembleur ne sont jamais affichés
ni copiables**, et aucun endpoint n'exporte le JSON. On garde douze sons, on
redémarre, tout est perdu — et `cli.py bank` exige un JSON que rien ne produit.
C'est le deuxième livrable de tête de la spec, sans sortie.
*Correction :* un `GET /api/bank/export.json`, et trois zones de texte en
lecture seule dans le panneau Banque (`soundFX.asm`, `soundFX.const.asm`, JSON),
chacune avec un bouton Copier reprenant le mécanisme existant.

**I1 — La voie YM2413 n'est validée nulle part côté Python.** Reproduit :
`channel: 42` écrit `; voie YM2413 42` dans le `.asm` sans un mot, et le driver
ajoutera 42 aux numéros de registres. Le seul garde-fou est un `max="8"` HTML,
que le navigateur n'impose pas à la saisie clavier.
*Correction :* `CHANNEL_MIN, CHANNEL_MAX = 0, 8` et `check_any_channel()` dans
`rhythm.py`, appelée depuis `bank._validate`, `server._render_design`,
`server._variants` et `cli.py`. `check_channel` doit l'appeler en premier.

**I2 — Trois panneaux déclenchent une erreur 400 en mode Créer.** Les
`fieldset` **Instrument**, **Mélodique** et **Sortie** sont hors des deux blocs
`panCreate`/`panWav`, donc visibles partout, et câblés sur `generate()` qui
poste `mode: 'create'` — refusé par le serveur. Toucher un contrôle affiche un
bandeau rouge. *Correction :* les déplacer dans `panWav`, puis refaire l'audit
croisé des `$('id')`.

**I3 — La spec se contredit.** Sa section *Tests* dit encore « refusée au-delà
de la voie **6** », sa section *Garde-fous* dit 5. Le commit `b07cfa6` a
rectifié l'une et oublié l'autre.

**I4 — `rhythm.py` dément son propre en-tête**, affirmant encore qu'« une
explosion enregistrée ne se convertit pas ». Chiffres périmés aussi (0,26 et
0,12 dans le README). Et « retombe **sous** `$0F` » : à la voie 7 il retombe
**sur** `$0F`.

**Quatre mineurs jugés à traiter avant fusion :** la docstring du test « pire
coin » qui revendique une borne qu'il ne fournit pas ; `--category` inconnu qui
retombe en silence (nommer le repli `libre`, et avertir sur `stderr`) ;
`mode = params.get("mode", "param")` dont le défaut pointe un mode supprimé ;
`initCreate()` sans `.catch`.

## Écarts spec ↔ livraison, connus

1. **L'historique** des tirages : absent, rendu approximativement par la rangée
   de huit variantes.
2. **Le « tirage libre sur tout l'espace »** : le mécanisme existe mais n'a ni
   nom ni bouton — atteignable seulement par une faute de frappe.
3. **`arp_steps` n'est jamais tiré au sort.** L'arpège, que la spec décrit comme
   le geste le plus caractéristique du son de puce, n'est atteignable que par la
   catégorie « ramassage » ; le curseur `arp_frames` est inopérant dans sept
   catégories sur huit. **C'est une décision de conception, pas un bug** : il
   faut choisir quelles catégories doivent arpéger.
4. La courbe de bruit est calculée et renvoyée mais jamais dessinée, alors que
   la maquette de la spec montre une piste « bruit ».

## Ce que la relecture finale a confirmé comme sain

Le budget de 255 commandes tient sur tous les chemins (300 mutations enchaînées
plafonnent à 255 exactement). La limite de voie de la couche bruit est appliquée
à trois endroits indépendants et jamais écrite en dur. **L'ordre de la table et
celui des identifiants ne peuvent pas diverger** — un seul producteur, une seule
énumération, doublons interdits. Aucun test creux parmi les 60. Périmètre
respecté : pas une ligne hors de `to8-soundfx-generator/`.

## À essayer devant la page — personne ne l'a fait

Aucun agent n'avait de navigateur : l'interface a été vérifiée par les
extrémités (appels HTTP réels, audit statique du DOM et du JS), **jamais
observée**. Lance `./run.sh` et vérifie, dans cet ordre :

1. La page charge sans erreur console, **Créer** est l'onglet ouvert par défaut,
   les catégories et les kits sont peuplés.
2. **Tirer au sort** donne un son différent à chaque clic, et il se joue.
3. **Muter** affiche huit variantes ; un clic les écoute, un second l'adopte.
4. Un cadenas coché fige visuellement son curseur pendant une mutation.
5. **Garder dans la banque** ajoute une ligne avec sa voie et ses octets.
6. Cocher « Activer les percussions » avec une voie déjà à 7 : le champ doit se
   ramener à 5 au moment du cochage. Puis taper 7 au clavier alors que le bruit
   est actif : le champ reste à 7 (défaut mineur connu), mais le rendu suivant
   doit afficher **un message d'erreur lisible**, pas geler.
7. Glisser vite un curseur d'« Affiner » : un seul rendu à la fois, et c'est la
   position finale qui s'entend.
8. Cliquer dans la zone de l'assembleur et appuyer sur espace : ça doit insérer
   un espace, pas relancer un rendu.
9. **L'onglet Fichier audio doit se comporter exactement comme avant** — dépose
   d'un fichier, forme d'onde, sélection à la souris, génération, écoute.

C'est le point 9 qui compte le plus : c'est la seule contrainte de tout ce
chantier qu'aucun test ne rattrape.

**Note pour la tâche 8 :** un test de la tâche 4
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
git log --oneline eabf2c4..HEAD     # les 25 commits
python3 -m tests                    # doit donner 60 OK
cat ../.superpowers/sdd/2026-09-06-app-creation-bruitages/progress.md
```

Le dispositif était piloté par la compétence `superpowers:subagent-driven-development`
— un implémenteur neuf par tâche, une relecture après chaque, une relecture
large à la fin. Les scripts d'extraction des cahiers et des paquets de relecture
sont dans le cache de la compétence (`scripts/task-brief`, `scripts/review-package`).

Le registre est la carte de récupération : les commits qu'il nomme existent dans
git même si plus personne ne se souvient de les avoir faits.
