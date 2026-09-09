# Dessin de la hauteur à la main — design

*10 septembre 2026*

## Le problème

La courbe de hauteur est aujourd'hui un **rendu pur** : `design.render(p)`
fabrique les trames à partir des seuls paramètres — `f_start`, `slide`,
`slide_delta`, arpège, vibrato, jitter. Le graphique l'affiche, on ne peut pas
la toucher.

Ces paramètres décrivent une famille de courbes lisses : un départ, une pente,
une inflexion. Ils ne savent pas exprimer « cette trame-là, un demi-ton plus
haut ». Pour un réglage fin et maîtrisé, il manque le geste direct : attraper
une trame dans le graphique et la tirer vers le haut ou vers le bas.

**Ce document ajoute une couche de correction dessinée à la main, par-dessus la
courbe paramétrique.** Les curseurs ne sont pas remplacés — ils restent le
moyen de poser la forme d'ensemble, et le dessin vient l'affiner.

## Le geste, et ce qu'on voit

Le graphique dessine déjà, sur la piste de hauteur, **une bande verticale par
trame**, colorée selon l'instrument de cette trame et posée à 35 % d'opacité
derrière la courbe. Ce sont ces bandes-là qu'on attrape : rien de neuf à
dessiner, elles deviennent les cibles du geste.

Appui dans la piste de hauteur, puis glissement. Chaque trame que le curseur
traverse prend la hauteur qui se trouve sous lui. Un balayage rapide dessine une
forme d'un trait ; un passage lent sur une seule bande la règle finement. Le
même geste sert au grand mouvement et au détail.

**Le seul retour visuel est la courbe verte qui suit la main.** Décision
explicite : la couleur des bandes reste celle de l'instrument, et une trame
retouchée ne se signale par aucune teinte particulière. On voit ce qu'on fait
parce que la courbe monte ou descend, pas parce que le fond change de couleur.

## Le modèle : un champ, pas une couche à part

Dans `SfxParams` :

```python
pitch_draw: tuple[float, ...] = ()   # ecart en cents, une valeur par trame
```

Il se range exactement comme `arp_steps` et `inst_steps` : **hors de `BOUNDS`**,
avec une ligne dans `to_dict` et une dans `from_dict`. Ce placement n'est pas un
détail de rangement, c'est lui qui donne gratuitement les deux règles de cycle
de vie voulues :

| Action | Comportement obtenu | Pourquoi, sans code ajouté |
|---|---|---|
| **Tirer au sort** | le dessin est effacé | `roll` reconstruit un `SfxParams` neuf en bouclant sur `BOUNDS` ; le champ reprend son défaut `()` |
| **Muter** | le dessin est conservé intact | `mutate` recopie par `from_dict(to_dict())` puis ne touche que les clés de `BOUNDS`, plus `arp_steps` et `inst_steps` nommément |
| **Curseurs** | aucun curseur généré | `buildSliders` itère sur `INIT.bounds` |
| **Banque, rechargement, CLI** | aller-retour complet | tout passe par `to_dict`/`from_dict` |

Un tirage repart donc d'une page blanche — c'est un son neuf — tandis qu'une
mutation cherche autour du son courant en respectant les retouches.

### Longueur libre, et ré-échantillonnage

La longueur `L` du tuple est libre et n'a pas à valoir `n`. À chaque rendu,
`render` ré-échantillonne de `L` vers `n` par interpolation linéaire sur un axe
normalisé `[0, 1]`.

Quand `L == n` — le cas courant, tant que la durée ne bouge pas — le
ré-échantillonnage est **l'identité** : le geste est rendu au cent près, sans
lissage. La perte de précision n'arrive que le jour où le son est réellement
étiré, et c'est le comportement voulu : le dessin s'étire en proportion, comme
l'enveloppe le fait déjà sous le curseur de durée totale.

Chaque valeur est bornée à ±2400 cents (`PITCH_DRAW_MAX_CENTS = 2400.0`), soit
deux octaves de part et d'autre. La fréquence finale reste par ailleurs bornée à
20–8000 Hz par le `np.clip` déjà présent dans `render`.

## Le rendu : une addition, au bon endroit

Dans `render()`, **après l'arpège et avant la conversion en hertz** :

```python
if p.pitch_draw:
    midi = midi + _resample_draw(p.pitch_draw, n) / 100.0
```

Là et pas ailleurs. Le vibrato et le jitter s'appliquent ensuite, donc ils
restent **par-dessus** la correction : ce sont des modulations, pas la hauteur
elle-même. Une correction dessinée déplace la note ; le vibrato continue de la
faire osciller autour de sa nouvelle position.

### La courbe de référence, calculée mais jamais dessinée

Conséquence directe du placement ci-dessus : avec du jitter ou du vibrato
actif, la ligne verte affichée **n'est pas** la grandeur que le geste pilote.
Convertir la position du curseur en cents contre cette ligne bruitée figerait le
jitter de cette trame dans la couche dessinée, et l'erreur s'accumulerait à
chaque passage.

Le serveur renvoie donc, dans `curves`, une entrée de plus :

```
"freq_base": [...]   # la hauteur parametrique seule, en Hz
```

**`freq_base` est la courbe paramétrique nue : sans vibrato, sans jitter, et
sans la correction dessinée.** C'est la définition même du champ — `pitch_draw`
est un écart *par rapport à cette courbe-là*. Le geste peut donc s'écrire en
affectation directe plutôt qu'en accumulation, ce qui le rend idempotent :
retirer deux fois la même bande au même endroit donne exactement la même
valeur, sans dérive.

Elle sert **uniquement au calcul** de l'écart en cents côté navigateur. Elle
n'est pas tracée : le graphique garde exactement les tracés qu'il a aujourd'hui.

Pour la produire sans dupliquer la formule, le calcul de la hauteur en demi-tons
(`midi0 + slide·t + ½·slide_delta·t²`, plus l'arpège) est extrait de `render`
dans une fonction `_pitch_semitones(p, n, local)`, à laquelle `render` ajoute
ensuite la correction dessinée. Une nouvelle fonction publique
`design.base_pitch(p) -> list[float]` appelle `_pitch_semitones` et rend des
hertz, sans jamais ajouter `pitch_draw`. La signature de `render` ne change
pas : ses appelants (`server`, `cli`, tests) ne sont pas touchés.

`freq_base` est tronquée à la longueur de `used` avant l'envoi, pour que les
deux courbes s'indexent de la même façon : `fit_to_budget` peut rendre moins de
trames que `n` quand le son est tronqué.

## L'interface

Dans `static/index.html`, quatre points.

**1. La géométrie sort de `draw()`.** `fmin`, `fmax`, les marges `m`, `pitchH`
et `n` sont aujourd'hui locaux à `draw()`. Le gestionnaire de souris doit
inverser `Y(f)` et localiser la trame sous le curseur : ces valeurs sont donc
rangées dans une variable de module au moment du tracé.

**2. Les gestionnaires.** `mousedown` sur `cv`, `mousemove` et `mouseup` sur
`window` — le même idiome que la sélection de la forme d'onde, qui gère déjà
correctement le glissement sorti du canvas. Les coordonnées se normalisent par
`getBoundingClientRect()`, le canvas étant affiché en `width:100%`. Le geste est
ignoré hors du mode **Créer** et hors de la bande verticale de la piste de
hauteur.

**3. Le retour immédiat.** Pendant le glissement, aucun appel serveur : les
trames touchées sont écrites dans une copie locale des courbes et `draw()` est
rappelée. La courbe verte suit donc le curseur exactement. Au relâchement, un
seul `render()` — sa garde `renderBusy`/`renderAgain` suffit, pas besoin de
minuterie. Le rendu qui revient peut différer de quelques cents du tracé
provisoire quand le jitter est actif : c'est lui qui fait foi.

Pour chaque trame `i` traversée :

```
CUR.pitch_draw[i] = clamp(1200 · log2(f_cible / freq_base[i]), ±2400)
```

`pitch_draw` est initialisée à un tableau de `n` zéros au premier geste, ou
ré-échantillonnée à `n` si elle existe déjà avec une autre longueur.

Le tracé provisoire ne demande aucun calcul : par construction la trame touchée
vaut exactement `f_cible`, donc le glissement écrit `f_cible` dans la copie
locale de `curves.freq`, et rien d'autre. Les trames non traversées gardent leur
valeur, jitter compris ; celles qu'on vient de tirer perdent provisoirement leur
jitter et le retrouvent au rendu suivant.

**4. Un bouton *effacer le dessin*** près du graphique : `CUR.pitch_draw = []`
puis `render()`. C'est la seule annulation prévue.

## Le coût en commandes, assumé

Une courbe dessinée fait bouger la hauteur sur des trames où la formule la
laissait tranquille, donc plus d'écritures dans les registres `$10` et `$20`.

Rien de nouveau à construire : `fit_to_budget` quantifie déjà la hauteur en
cents et le volume par paliers jusqu'à tenir dans les 255 commandes, et pose un
avertissement quand il a dû le faire. **Mais cet avertissement va se déclencher
bien plus souvent qu'aujourd'hui.** C'est le prix du dessin libre sur un budget
de 255 commandes, pas un défaut à corriger.

## Garde-fous

- Chaque valeur de `pitch_draw` est bornée à ±2400 cents à l'écriture comme à la
  lecture : une valeur hors bornes venue d'un JSON édité à la main est ramenée,
  pas refusée.
- `from_dict` convertit en `tuple(float)` et ignore les valeurs non numériques,
  comme il le fait déjà pour `arp_steps`.
- `n == 0` ou `L == 0` : le ré-échantillonnage rend un tableau de zéros, aucune
  division par zéro.
- Le geste n'est actif qu'en mode **Créer**. L'onglet **Fichier audio** n'est
  touché par rien de ce document.

## Tests

1. `_resample_draw` rend l'entrée à l'identique quand `L == n`.
2. `_resample_draw` étire en proportion quand `n` change : une correction posée
   au tiers du son reste au tiers après allongement.
3. Une valeur hors bornes est ramenée à ±2400 cents.
4. `render` applique bien la correction en cents : `pitch_draw = [1200]·n`
   double la fréquence de chaque trame par rapport au même son sans dessin.
5. La correction se compose avec l'arpège et le glissement, elle ne les
   remplace pas.
6. `mutate` laisse `pitch_draw` rigoureusement intact, cadenas ou pas.
7. `roll` rend toujours `pitch_draw == ()`.
8. Aller-retour JSON de la banque : un son gardé avec un dessin le retrouve
   identique après `to_json`/rechargement.
9. `base_pitch` ignore vibrato, jitter **et** la correction dessinée. Deux
    assertions distinctes, et la seconde doit pouvoir échouer : deux sons dont
    seul `pitch_draw` diffère ont la même `freq_base` ; et le **même** son
    modulations coupées a la même `freq_base` que modulations actives. Comparer
    deux sons qui portent tous deux les mêmes modulations ne prouve rien — le
    terme se simplifie des deux côtés de l'égalité, et une régression qui ferait
    entrer le jitter dans `base_pitch` passerait au vert.
10. `freq_base` a la même longueur que `curves.freq`, y compris sur un son
    tronqué par le budget.

Au moins un de ces tests doit être **éprouvé** : casser volontairement le code
qu'il couvre, montrer la sortie de l'échec, puis remettre en l'état. C'est la
consigne héritée du chantier précédent, où cinq tests venus du plan se sont
révélés incapables d'échouer.

## Hors périmètre

- **Le volume, le timbre et le bruit ne deviennent pas éditables.** Le volume
  est déjà en barres et le geste serait évident dessus, mais c'est une deuxième
  couche de correction, avec ses propres bornes sur 4 bits. Plus tard, et rien
  ici ne l'empêche.
- **Pas de pile d'annulation** au-delà du bouton *effacer le dessin*.
- **Pas de teinte sur les trames retouchées** : décision prise, pas un oubli.
- **Pas d'option de dessin en ligne de commande.** Le dessin est un geste
  d'interface ; la CLI se contente de relire un `pitch_draw` présent dans un
  JSON de banque.
- L'onglet **Fichier audio** n'est pas touché.
