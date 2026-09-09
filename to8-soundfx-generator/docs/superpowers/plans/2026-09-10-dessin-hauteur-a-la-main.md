# Dessin de la hauteur à la main — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre d'attraper une trame dans le graphique de hauteur et de la tirer vers le haut ou vers le bas, en correction par-dessus la courbe paramétrique.

**Architecture:** Un champ `pitch_draw` dans `SfxParams` — un écart en cents par trame — rangé hors de `BOUNDS` comme `arp_steps`, ce qui lui donne gratuitement son cycle de vie (effacé au tirage, conservé en mutation, aucun curseur généré). `render` l'ajoute à la hauteur en demi-tons après l'arpège et avant la conversion en hertz, pour que vibrato et jitter restent par-dessus. Le serveur envoie en plus la courbe paramétrique nue `freq_base`, jamais tracée, qui sert au navigateur à convertir la position du curseur en cents.

**Tech Stack:** Python 3.10+, numpy, HTML/JS sans dépendance (canvas 2D). Suite de tests maison lancée par `python3 -m tests` — pas de pytest.

**Spec:** `docs/superpowers/specs/2026-09-10-dessin-hauteur-a-la-main-design.md`

## Global Constraints

- **Répertoire de travail :** `toolbox/to8-soundfx-generator/`. Ne toucher à rien en dehors — ni au moteur, ni à `battlesquadron/`.
- **Lancement des tests :** `python3 -m tests` depuis la racine du projet. Il n'y a **pas de pytest** : `tests/__main__.py` importe chaque module et appelle toute fonction dont le nom commence par `test_`. Un test échoue par `AssertionError` ; tout autre exception fait planter la suite.
- **Un nouveau module de test doit être ajouté à la liste** en tête de `tests/__main__.py`, sinon il n'est jamais exécuté. Ce plan n'en crée aucun : tout va dans des fichiers déjà listés.
- **Chaque test imprime une ligne** de mesure ou de résumé (`print("  …")`), comme tous les tests existants. Un test muet est hors style.
- **Commentaires et docstrings du code Python : sans accents** (convention du dépôt). Les documents Markdown, eux, sont accentués.
- **Borne de la couche dessinée :** `PITCH_DRAW_MAX_CENTS = 2400.0`, soit ±2 octaves.
- **`pitch_draw` ne doit jamais entrer dans `BOUNDS` ni dans `INT_PARAMS`.** C'est ce placement qui porte tout le cycle de vie ; l'y ajouter casserait silencieusement les tâches 3 et 5.
- **Un test au moins doit être éprouvé** avant la fin du plan (voir tâche 5) : casser volontairement le code couvert, montrer la sortie de l'échec dans le rapport, puis remettre en l'état.

---

## Structure des fichiers

| Fichier | Responsabilité | Tâches |
|---|---|---|
| `to8sfx/design.py` | le champ, son nettoyage, son ré-échantillonnage, son application au rendu, la courbe de référence | 1, 2 |
| `tests/test_design.py` | modèle et rendu de la couche dessinée, cycle de vie tirage/mutation | 1, 2, 3 |
| `tests/test_bank.py` | aller-retour JSON de la banque | 3 |
| `to8sfx/server.py` | `freq_base` dans la réponse de `_render_design` | 4 |
| `tests/test_server_design.py` | présence et appariement de `freq_base` | 4 |
| `static/index.html` | géométrie du tracé exposée, gestes souris, bouton d'effacement | 5 |

Aucun fichier créé. `to8sfx/bank.py`, `to8sfx/codegen.py` et `cli.py` ne sont pas modifiés : `pitch_draw` les traverse par `to_dict`/`from_dict`, et la tâche 3 le vérifie plutôt que de le supposer.

---

### Task 1: Le champ `pitch_draw` et son ré-échantillonnage

**Files:**
- Modify: `to8sfx/design.py` (dataclass `SfxParams` ~ligne 30-100, `to_dict`, `from_dict`, et une constante + deux fonctions près de `ARP_STEP_MIN`)
- Test: `tests/test_design.py`

**Interfaces:**
- Consumes: rien (première tâche).
- Produces:
  - `design.PITCH_DRAW_MAX_CENTS: float` = `2400.0`
  - `SfxParams.pitch_draw: tuple[float, ...]`, défaut `()`
  - `design._clean_draw(values) -> tuple[float, ...]` — filtre et borne
  - `design._resample_draw(values, n: int) -> np.ndarray` — cents étirés sur `n` trames

- [ ] **Step 1: Écrire les trois tests qui échouent**

Ajouter à la fin de `tests/test_design.py` :

```python
def test_drawn_layer_is_untouched_when_lengths_match():
    """Longueur egale = identite. C'est le cas courant, tant que la duree ne
    bouge pas, et le geste doit y etre rendu au cent pres, sans lissage."""
    dessin = [0.0, 150.0, -300.0, 25.0]
    out = list(design._resample_draw(dessin, 4))
    assert out == dessin, f"{out} != {dessin}"
    print(f"  identite sur {len(dessin)} trames")


def test_drawn_layer_stretches_in_proportion():
    """Une correction posee au tiers du son reste au tiers apres allongement.

    C'est le comportement choisi : le dessin s'etire avec le son, comme
    l'enveloppe le fait deja sous le curseur de duree totale.
    """
    dessin = [0.0] * 9
    dessin[3] = 600.0                      # 3/8 du parcours, sur 9 valeurs
    out = list(design._resample_draw(dessin, 33))
    pic = out.index(max(out))
    assert abs(pic / 32 - 3 / 8) < 0.05, f"pic a {pic}/32, attendu vers 0.375"
    print(f"  pic 3/8 -> {pic}/32")


def test_drawn_layer_is_clamped_and_cleaned_on_the_way_in():
    """Une valeur hors bornes venue d'un JSON edite a la main est RAMENEE, pas
    refusee : la banque d'un utilisateur ne doit pas devenir illisible pour un
    cent de trop. Ce qui n'est pas un nombre est simplement ecarte."""
    p = design.SfxParams.from_dict(
        {"pitch_draw": [9000.0, -9000.0, "x", None, 100.0]})
    assert p.pitch_draw == (2400.0, -2400.0, 100.0), p.pitch_draw
    print(f"  {p.pitch_draw}")
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd toolbox/to8-soundfx-generator && python3 -m tests 2>&1 | grep -E "drawn_layer|FAIL"`

Expected: la suite plante sur `AttributeError: module 'to8sfx.design' has no attribute '_resample_draw'`. C'est l'échec attendu — le lanceur ne rattrape que les `AssertionError`, donc la première erreur d'attribut interrompt la suite. C'est normal à ce stade.

- [ ] **Step 3: Ajouter le champ au dataclass**

Dans `to8sfx/design.py`, dans `SfxParams`, juste après le bloc `# --- modulations ---` (après `jitter_cents`) :

```python
    # --- correction dessinee a la main ---
    # Un ecart en cents par trame, ajoute a la hauteur parametrique. Range
    # HORS de BOUNDS, comme arp_steps : ce n'est pas un scalaire. C'est ce
    # placement qui donne tout le cycle de vie sans une ligne de plus —
    # randomize() boucle sur BOUNDS donc un tirage repart de (), mutate()
    # recopie puis ne touche que BOUNDS donc le dessin survit, et
    # buildSliders() itere sur BOUNDS donc aucun curseur n'est genere.
    # La longueur est libre : render() la ramene a la duree courante.
    pitch_draw: tuple[float, ...] = ()
```

- [ ] **Step 4: Faire passer le champ dans la sérialisation**

Toujours dans `design.py`, dans `to_dict`, à côté des deux lignes existantes :

```python
        d["pitch_draw"] = list(self.pitch_draw)
```

Et dans `from_dict`, à côté des conversions de `arp_steps` et `inst_steps` :

```python
        if "pitch_draw" in out:
            out["pitch_draw"] = _clean_draw(out["pitch_draw"])
```

- [ ] **Step 5: Écrire la constante et les deux fonctions**

Dans `design.py`, juste après le bloc `ARP_STEP_MIN, ARP_STEP_MAX = -24, 24` :

```python
# La couche dessinee a la main est bornee comme l'arpege l'est, et pour la
# meme raison : sans borne, une valeur aberrante venue d'un JSON edite a la
# main enverrait la hauteur hors du domaine de la puce. Deux octaves de part
# et d'autre couvrent largement une correction de bruitage.
PITCH_DRAW_MAX_CENTS = 2400.0


def _clean_draw(values) -> tuple[float, ...]:
    """Rend une couche dessinee saine : que des nombres finis, tous bornes.

    Une valeur hors bornes est RAMENEE, pas refusee : la banque d'un
    utilisateur ne doit pas devenir illisible pour un cent de trop.
    """
    out = []
    for v in values or ():
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f != f or f in (float("inf"), float("-inf")):
            continue
        out.append(max(-PITCH_DRAW_MAX_CENTS, min(PITCH_DRAW_MAX_CENTS, f)))
    return tuple(out)


def _resample_draw(values, n: int) -> np.ndarray:
    """Etire la couche dessinee sur n trames. Le resultat est en cents.

    Longueur egale : l'identite, au cent pres. C'est le cas courant tant que
    la duree ne bouge pas, et le geste doit y etre rendu tel qu'il a ete fait.
    Longueur differente : interpolation lineaire sur un axe normalise [0, 1],
    pour que la forme dessinee garde sa place relative dans le son.
    """
    if n <= 0:
        return np.zeros(0)
    L = len(values)
    if L == 0:
        return np.zeros(n)
    src = np.asarray(values, dtype=float)
    if L == n:
        return src
    if L == 1:
        return np.full(n, src[0])
    return np.interp(np.linspace(0.0, 1.0, n), np.linspace(0.0, 1.0, L), src)
```

- [ ] **Step 6: Lancer les tests pour vérifier qu'ils passent**

Run: `cd toolbox/to8-soundfx-generator && python3 -m tests`

Expected: `OK test_drawn_layer_is_untouched_when_lengths_match`, `OK test_drawn_layer_stretches_in_proportion`, `OK test_drawn_layer_is_clamped_and_cleaned_on_the_way_in`, et **aucune régression** parmi les tests existants. Sortie finale sans une seule ligne `FAIL`.

- [ ] **Step 7: Commit**

```bash
git add to8sfx/design.py tests/test_design.py
git commit -m "feat(dessin): champ pitch_draw, borne et etire sur la duree du son

Un ecart en cents par trame, range hors de BOUNDS comme arp_steps. Ce
placement n'est pas cosmetique : c'est lui qui donne le cycle de vie
voulu sans une ligne de plus, et la tache 3 le verrouille par des tests.

La longueur du tuple est libre. Quand elle vaut la duree, le
re-echantillonnage est l'identite et le geste est rendu au cent pres ;
c'est le cas courant. Il ne devient une interpolation que le jour ou le
son est reellement etire."
```

---

### Task 2: L'application au rendu, et la courbe de référence

**Files:**
- Modify: `to8sfx/design.py` — fonction `render`, découpée ; ajout de `_local_index`, `_pitch_semitones` et `base_pitch`
- Test: `tests/test_design.py`

**Interfaces:**
- Consumes: `design._resample_draw`, `design.PITCH_DRAW_MAX_CENTS`, `SfxParams.pitch_draw` (tâche 1).
- Produces:
  - `design._local_index(p: SfxParams, n: int) -> np.ndarray`
  - `design._pitch_semitones(p: SfxParams, n: int, local: np.ndarray) -> tuple[np.ndarray, np.ndarray]` — rend `(midi, attack_flags)`, **sans** la couche dessinée
  - `design.base_pitch(p: SfxParams) -> list[float]` — la courbe paramétrique nue en Hz, arrondie à 2 décimales, de longueur `p.duration_frames`
  - `design.render(p)` : signature **inchangée**, `(list[Frame], list[int] | None)`

- [ ] **Step 1: Ajouter le helper de test des fréquences**

Dans `tests/test_design.py`, juste après le helper `_midis` existant :

```python
def _freqs(frames):
    return [opll.fnum_block_to_freq(f.fnum, f.block) for f in frames if f.voiced]
```

- [ ] **Step 2: Écrire les trois tests qui échouent**

À la fin de `tests/test_design.py` :

```python
def test_drawn_layer_shifts_the_pitch_in_cents():
    """+1200 cents dessines sur toute la duree, c'est une octave : le double.

    Modulations coupees, sinon le jitter brouille la mesure.
    """
    p = design.SfxParams(slide=0.0, slide_delta=0.0,
                         vibrato_cents=0.0, jitter_cents=0.0)
    nu = _freqs(design.render(p)[0])
    p2 = design.SfxParams.from_dict(
        {**p.to_dict(), "pitch_draw": [1200.0] * p.duration_frames})
    dessine = _freqs(design.render(p2)[0])
    assert len(nu) == len(dessine) and nu
    for a, b in zip(nu, dessine):
        assert abs(b / a - 2.0) < 0.02, f"{a:.1f} Hz -> {b:.1f} Hz"
    print(f"  {nu[0]:.0f} Hz -> {dessine[0]:.0f} Hz")


def test_drawn_layer_composes_with_the_slide():
    """Le dessin s'AJOUTE au glissement, il ne le remplace pas.

    C'est tout l'interet du choix « correction relative » : les curseurs
    continuent de porter la forme d'ensemble sous les retouches.
    """
    base = design.SfxParams(slide=-1.0, slide_delta=0.0, vibrato_cents=0.0,
                            jitter_cents=0.0, attack_frames=1, hold_frames=0,
                            decay_frames=9)
    n = base.duration_frames
    p = design.SfxParams.from_dict(
        {**base.to_dict(), "pitch_draw": [0.0] * (n - 1) + [1200.0]})
    sans = _midis(design.render(base)[0])
    avec = _midis(design.render(p)[0])
    assert avec[:-1] == sans[:-1], f"trames non dessinees deplacees\n{sans}\n{avec}"
    assert avec[-1] - sans[-1] == 12, f"{sans[-1]} -> {avec[-1]}, attendu +12"
    print(f"  glissement conserve, derniere trame {sans[-1]} -> {avec[-1]}")


def test_base_pitch_ignores_modulations_and_the_drawing():
    """base_pitch est la reference contre laquelle pitch_draw est un ecart.

    Si elle suivait le dessin, l'interface mesurerait le geste contre une
    courbe qui a deja bouge, et le deplacement serait double a chaque passage.
    Si elle suivait le jitter, celui-ci se figerait dans la couche dessinee.
    """
    p = design.SfxParams(vibrato_hz=6.0, vibrato_cents=200.0,
                         jitter_cents=300.0, seed=7)
    nu = design.base_pitch(p)
    p2 = design.SfxParams.from_dict(
        {**p.to_dict(), "pitch_draw": [900.0] * p.duration_frames})
    assert design.base_pitch(p2) == nu, "base_pitch a suivi le dessin"
    assert len(nu) == p.duration_frames, f"{len(nu)} vs {p.duration_frames}"
    print(f"  {len(nu)} trames, {nu[0]:.0f} Hz -> {nu[-1]:.0f} Hz")
```

- [ ] **Step 3: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd toolbox/to8-soundfx-generator && python3 -m tests 2>&1 | tail -20`

Expected: la suite plante sur `AttributeError: module 'to8sfx.design' has no attribute 'base_pitch'`. `test_drawn_layer_shifts_the_pitch_in_cents` doit de son côté donner un `FAIL` avec un rapport de fréquences de 1.0 — le champ existe (tâche 1) mais `render` ne l'applique pas encore. **Vérifier que ce FAIL-là apparaît bien** : c'est lui qui prouve que le test mesure quelque chose.

- [ ] **Step 4: Extraire l'indice local et le calcul de hauteur**

Dans `to8sfx/design.py`, ajouter ces deux fonctions juste **avant** `def render(`:

```python
def _local_index(p: SfxParams, n: int) -> np.ndarray:
    """Indice de trame, remis a zero a chaque repetition du motif."""
    if p.repeat_frames and p.repeat_frames > 0:
        return np.arange(n) % p.repeat_frames
    return np.arange(n)


def _pitch_semitones(p: SfxParams, n: int, local: np.ndarray):
    """Hauteur parametrique en demi-tons, et les re-attaques posees par l'arpege.

    SANS la couche dessinee, sans vibrato ni jitter : c'est la courbe de
    reference contre laquelle pitch_draw est un ecart. render() lui ajoute le
    dessin ; base_pitch() la rend telle quelle a l'interface.
    """
    # Hauteur en demi-tons : depart + glissement + inflexion. L'inflexion est
    # la derivee seconde ; c'est elle qui donne le glissement qui ralentit.
    midi0 = freq_to_midi(max(p.f_start, 1.0))
    t = local.astype(float)
    midi = midi0 + p.slide * t + 0.5 * p.slide_delta * t * t

    # L'arpege s'ajoute en relatif : il se compose avec le glissement.
    attack_flags = np.zeros(n, dtype=bool)
    attack_flags[0] = True
    if p.arp_frames > 0 and p.arp_steps:
        step_idx = (local // p.arp_frames) % len(p.arp_steps)
        midi = midi + np.array([p.arp_steps[k] for k in step_idx], dtype=float)
        if p.arp_retrigger:
            changed = np.ones(n, dtype=bool)
            changed[1:] = step_idx[1:] != step_idx[:-1]
            attack_flags |= changed
    return midi, attack_flags
```

- [ ] **Step 5: Rebrancher `render` sur les deux helpers, et y appliquer le dessin**

Dans `render`, **remplacer** tout le bloc qui va de `# Indice local : la repetition relance le motif entier.` jusqu'à la ligne `attack_flags |= (local == 0)` incluse, par :

```python
    # Indice local : la repetition relance le motif entier.
    local = _local_index(p, n)
    midi, attack_flags = _pitch_semitones(p, n, local)

    # La correction dessinee s'ajoute ICI : apres l'arpege, avant la conversion
    # en hertz. Le vibrato et le jitter s'appliquent ensuite, donc ils restent
    # PAR-DESSUS — ce sont des modulations, pas la hauteur elle-meme. Une
    # retouche deplace la note ; le vibrato continue de la faire osciller
    # autour de sa nouvelle position.
    if p.pitch_draw:
        midi = midi + _resample_draw(p.pitch_draw, n) / 100.0

    if p.repeat_frames and p.repeat_frames > 0:
        attack_flags |= (local == 0)
```

La ligne `freq = np.array([midi_to_freq(float(m)) for m in midi])` qui suit ne bouge pas, ni rien après elle.

- [ ] **Step 6: Écrire `base_pitch`**

Dans `design.py`, juste **après** la fin de `render` (avant `def _noise_track`) :

```python
def base_pitch(p: SfxParams) -> list[float]:
    """Courbe parametrique nue, en Hz : sans vibrato, sans jitter, sans dessin.

    C'est la reference que l'interface utilise pour convertir la position du
    curseur en un ecart de cents. La prendre sur la courbe finale figerait le
    jitter de la trame dans la couche dessinee, et l'erreur s'accumulerait a
    chaque passage ; l'y inclure elle-meme doublerait chaque deplacement.
    Elle n'est jamais tracee.
    """
    n = p.duration_frames
    midi, _ = _pitch_semitones(p, n, _local_index(p, n))
    return [round(float(np.clip(midi_to_freq(float(m)), 20.0, 8000.0)), 2)
            for m in midi]
```

- [ ] **Step 7: Lancer toute la suite**

Run: `cd toolbox/to8-soundfx-generator && python3 -m tests`

Expected: les trois nouveaux tests en `OK`, et **aucune régression** — l'extraction de `_pitch_semitones` a déplacé du code de rendu existant, donc les tests d'arpège, de répétition et d'enveloppe sont le filet qui prouve que le déplacement est fidèle. Aucune ligne `FAIL`.

- [ ] **Step 8: Commit**

```bash
git add to8sfx/design.py tests/test_design.py
git commit -m "feat(dessin): appliquer la correction au rendu, et exposer la courbe nue

La correction s'ajoute apres l'arpege et avant la conversion en hertz :
vibrato et jitter restent par-dessus, ce sont des modulations et pas la
hauteur. Elle se compose donc avec le glissement au lieu de le remplacer,
ce qui est tout l'interet d'une correction relative.

base_pitch rend la meme courbe SANS le dessin ni les modulations. Les
deux exclusions comptent : y inclure le dessin doublerait chaque
deplacement du curseur, y inclure le jitter le figerait dans la couche
dessinee. Le calcul commun est extrait dans _pitch_semitones pour que les
deux ne puissent pas diverger."
```

---

### Task 3: Le cycle de vie et l'aller-retour banque, verrouillés par des tests

Cette tâche n'écrit **aucun code de production**. Le comportement voulu est déjà celui du code — c'est exactement pour ça qu'il faut le verrouiller : rien ne le signale à la lecture, et le jour où quelqu'un ajoutera `pitch_draw` à `BOUNDS` pour lui donner un curseur, les trois règles tomberont ensemble et en silence.

**Files:**
- Test: `tests/test_design.py`
- Test: `tests/test_bank.py`

**Interfaces:**
- Consumes: `SfxParams.pitch_draw` (tâche 1), `design.randomize`, `design.mutate`, `bank.Bank`, `bank.BankSound` (existants).
- Produces: rien pour les tâches suivantes.

- [ ] **Step 1: Écrire les deux tests de cycle de vie**

À la fin de `tests/test_design.py` :

```python
def test_mutation_never_touches_the_drawing():
    """Muter cherche AUTOUR du son courant : les retouches restent en place.

    Gratuit par construction — mutate recopie par from_dict(to_dict()) puis ne
    perturbe que les cles de BOUNDS, plus arp_steps et inst_steps nommement.
    Ce test est la pour que ca le reste.
    """
    p = design.randomize("tir", seed=3)
    p.pitch_draw = (0.0, 350.0, -120.0, 40.0)
    attendu = p.pitch_draw
    for k in range(20):
        p = design.mutate(p, amount=0.9, locked=(), seed=100 + k)
        assert p.pitch_draw == attendu, f"mutation {k} : {p.pitch_draw}"
    print("  20 mutations enchainees a 90 % : dessin intact")


def test_a_roll_starts_from_a_blank_page():
    """Tirer au sort, c'est un son NEUF : la main repart de zero.

    Gratuit aussi — randomize construit un SfxParams neuf en bouclant sur
    BOUNDS, ou pitch_draw n'est pas.
    """
    for cat in design.CATEGORIES:
        for seed in (0, 1, 999):
            p = design.randomize(cat, seed=seed)
            assert p.pitch_draw == (), f"{cat}/{seed} : {p.pitch_draw}"
    print(f"  {len(design.CATEGORIES)} categories x 3 graines : dessin vide")
```

- [ ] **Step 2: Écrire le test d'aller-retour de la banque**

À la fin de `tests/test_bank.py` :

```python
def test_the_drawing_survives_the_json_round_trip():
    """Un son garde avec un dessin doit le retrouver identique au rechargement.

    Sans ca, la banque perdrait silencieusement la moitie du travail : le
    parametrique reviendrait, les retouches non.
    """
    p = design.randomize("explosion", seed=8)
    p.pitch_draw = (0.0, 240.5, -1100.0, 12.25)
    b = bank.Bank(name="essai", default_channel=4)
    b.sounds.append(bank.BankSound(name="Boum", params=p,
                                   category="explosion", priority=1))
    revenu = bank.Bank.from_json(b.to_json()).sounds[0].params
    assert revenu.pitch_draw == p.pitch_draw, revenu.pitch_draw
    print(f"  {len(p.pitch_draw)} valeurs conservees : {revenu.pitch_draw}")
```

`tests/test_bank.py` importe déjà `design` (`from to8sfx import bank, codegen, design, importer`) : ne rien ajouter à ses imports.

- [ ] **Step 3: Lancer la suite**

Run: `cd toolbox/to8-soundfx-generator && python3 -m tests`

Expected: les trois tests en `OK` du premier coup — ils décrivent un comportement déjà acquis. Aucune ligne `FAIL`.

- [ ] **Step 4: Éprouver le test de mutation**

Un test qui passe du premier coup n'a rien prouvé tant qu'on ne l'a pas vu échouer. Ajouter temporairement `"pitch_draw": (0.0, 0.0)` à `BOUNDS` dans `design.py` :

```python
    "noise_vol": (0, 15),
    "pitch_draw": (0.0, 0.0),      # TEMPORAIRE — a retirer
}
```

Run: `cd toolbox/to8-soundfx-generator && python3 -m tests 2>&1 | tail -20`

Expected: la suite casse. **Copier la sortie exacte dans le rapport de tâche.** Puis retirer la ligne et relancer `python3 -m tests` pour confirmer le retour au vert.

- [ ] **Step 5: Commit**

```bash
git add tests/test_design.py tests/test_bank.py
git commit -m "test(dessin): verrouiller le cycle de vie et l'aller-retour banque

Efface au tirage, conserve en mutation, conserve par la banque : les trois
regles sont deja le comportement du code, obtenues en rangeant pitch_draw
hors de BOUNDS. C'est precisement pourquoi elles ont besoin de tests —
rien ne les signale a la lecture, et le jour ou quelqu'un ajoutera
pitch_draw a BOUNDS pour lui donner un curseur, elles tomberont ensemble
et sans un mot.

Eprouve : pitch_draw ajoute a BOUNDS fait bien tomber le test de mutation."
```

---

### Task 4: `freq_base` dans la réponse du serveur

**Files:**
- Modify: `to8sfx/server.py` — dictionnaire `curves` de `_render_design` (~ligne 288-296)
- Test: `tests/test_server_design.py`

**Interfaces:**
- Consumes: `design.base_pitch` (tâche 2).
- Produces: `_render_design(...)["curves"]["freq_base"]` — `list[float]` en Hz, **de la même longueur que `curves["freq"]`**. C'est sur cette clé que la tâche 5 s'appuie.

- [ ] **Step 1: Écrire les deux tests qui échouent**

À la fin de `tests/test_server_design.py` :

```python
def test_render_design_ships_the_reference_curve():
    """L'interface ne peut pas convertir un clic en cents sans cette courbe."""
    p = design.randomize("tir", seed=21)
    out = server._render_design({"params": p.to_dict(), "channel": 4,
                                 "name": "Laser", "priority": 1})
    c = out["curves"]
    assert "freq_base" in c, "freq_base absente de la reponse"
    assert c["freq_base"], "freq_base vide"
    print(f"  {len(c['freq_base'])} trames de reference")


def test_the_reference_curve_is_indexed_like_the_others():
    """Les deux courbes doivent s'indexer de la meme facon.

    fit_to_budget peut rendre moins de trames que la duree quand le son
    deborde des 255 commandes. Si freq_base gardait la duree pleine, un clic
    en fin de son se mesurerait contre la mauvaise trame — sans erreur, juste
    un resultat faux.
    """
    p = design.randomize("explosion", seed=5)
    p.attack_frames, p.hold_frames, p.decay_frames = 1, 0, 90
    p.jitter_cents = 1200.0                # la hauteur change a chaque trame
    p.arp_frames, p.arp_steps = 1, (0, 7, 12)
    out = server._render_design({"params": p.to_dict(), "channel": 4,
                                 "name": "Boum", "priority": 1})
    c = out["curves"]
    assert len(c["freq_base"]) == len(c["freq"]), \
        f"reference {len(c['freq_base'])} vs rendu {len(c['freq'])}"
    print(f"  duree {p.duration_frames}, rendu {len(c['freq'])} trames, "
          f"tronque={out['info']['truncated']}")
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd toolbox/to8-soundfx-generator && python3 -m tests 2>&1 | grep -A2 "reference_curve"`

Expected: deux `FAIL`, le premier sur `freq_base absente de la reponse`.

- [ ] **Step 3: Ajouter la clé**

Dans `to8sfx/server.py`, dans le dictionnaire `"curves"` retourné par `_render_design`, après la ligne `"instrument": [f.instrument for f in used],` :

```python
            # Courbe de reference du dessin a la main : la hauteur parametrique
            # nue, sans vibrato, sans jitter et sans la correction dessinee.
            # Elle n'est JAMAIS tracee — elle sert au navigateur a convertir la
            # position du curseur en un ecart de cents. Tronquee a la longueur
            # de `used` comme les autres courbes : fit_to_budget peut rendre
            # moins de trames que la duree quand le son deborde du budget, et
            # les deux courbes doivent s'indexer pareil.
            "freq_base": design.base_pitch(p)[:len(used)],
```

- [ ] **Step 4: Lancer la suite**

Run: `cd toolbox/to8-soundfx-generator && python3 -m tests`

Expected: les deux nouveaux tests en `OK`, aucune régression. `test_render_design_returns_everything_the_ui_needs` doit toujours passer.

- [ ] **Step 5: Commit**

```bash
git add to8sfx/server.py tests/test_server_design.py
git commit -m "feat(dessin): envoyer la courbe de reference au navigateur

freq_base est la hauteur parametrique nue. Elle n'est jamais tracee : le
graphique garde exactement les traces qu'il a. Elle sert uniquement a
convertir la position du curseur en cents, et elle est tronquee comme les
autres courbes pour que toutes s'indexent de la meme facon — un son
tronque par le budget rendrait sinon un clic de fin de son faux, sans la
moindre erreur pour le signaler."
```

---

### Task 5: Le geste dans le graphique

Pas de banc de test JS dans ce dépôt : cette tâche se vérifie **devant la page**. La liste de vérification de l'étape 8 fait partie de la tâche, pas de son épilogue.

**Files:**
- Modify: `static/index.html` — corps de `draw()` (~ligne 697-765), bloc HTML sous le canvas (~ligne 326-332), bascule d'onglets (~ligne 455-465), `paint()` (~ligne 1045)

**Interfaces:**
- Consumes: `curves.freq_base` (tâche 4), `CUR.pitch_draw` accepté par `/api/design/render` via `SfxParams.from_dict` (tâche 1).
- Produces: rien.

- [ ] **Step 1: Exposer la géométrie du tracé**

Dans `static/index.html`, juste **avant** `function draw(c, notes){` :

```javascript
// Geometrie du dernier trace, et courbes qui l'ont produit. Le gestionnaire de
// souris en a besoin pour inverser Y(f) et localiser la trame sous le curseur ;
// elles etaient locales a draw().
let GEO = null, BASE = [], LASTC = null, LASTNOTES = null;
```

Dans `draw()`, ajouter `GEO = null;` comme **toute première ligne** du corps (avant `const cv = $('cv')`), pour qu'un retour anticipé ne laisse pas une géométrie périmée. Puis, juste **après** la ligne `const Y = f => m.t + pitchH - ...`, ajouter :

```javascript
  GEO = {n, m, pw, pitchH, fmin, fmax};
```

- [ ] **Step 2: Mémoriser les courbes reçues**

Dans `paint(d)`, remplacer la ligne `draw(d.curves, d.notes);` par :

```javascript
  BASE = (d.curves && d.curves.freq_base) || [];
  LASTC = d.curves; LASTNOTES = d.notes;
  draw(d.curves, d.notes);
```

- [ ] **Step 3: Écrire les gestionnaires de souris**

Juste **après** la fonction `draw()` (après son accolade fermante) :

```javascript
// ---------- dessin de la hauteur a la main ----------
// Les bandes verticales colorees par instrument, deja tracees sur la piste de
// hauteur, SONT les cibles du geste : rien de neuf a dessiner. Elles gardent
// leur couleur — une trame retouchee ne se signale par aucune teinte. Le seul
// retour visuel est la courbe verte qui suit la main.
let pitchDrag = false;

function canvasPos(ev){
  const cv = $('cv'), r = cv.getBoundingClientRect();
  return {x: (ev.clientX - r.left) / r.width  * cv.width,
          y: (ev.clientY - r.top)  / r.height * cv.height};
}

// Inverse de Y(f) et de X(i), tels que draw() les a poses.
const freqAt  = y => GEO.fmin * Math.pow(2,
  (GEO.m.t + GEO.pitchH - y) / GEO.pitchH * Math.log2(GEO.fmax / GEO.fmin));
const frameAt = x => GEO.n > 1
  ? Math.max(0, Math.min(GEO.n - 1,
      Math.round((x - GEO.m.l) / GEO.pw * (GEO.n - 1))))
  : 0;

// Ramene pitch_draw a la duree courante avant d'y ecrire. Meme interpolation
// que _resample_draw cote Python : la duree a pu changer depuis le dessin.
function ensureDraw(n){
  const cur = CUR.pitch_draw || [];
  if (cur.length === n) return;
  const out = new Array(n).fill(0);
  if (cur.length === 1) out.fill(cur[0]);
  else if (cur.length > 1){
    for (let i = 0; i < n; i++){
      const u = (n > 1 ? i / (n - 1) : 0) * (cur.length - 1);
      const a = Math.floor(u), b = Math.min(cur.length - 1, a + 1);
      out[i] = cur[a] + (cur[b] - cur[a]) * (u - a);
    }
  }
  CUR.pitch_draw = out;
}

function drawAt(ev){
  if (!GEO || !BASE.length || !LASTC) return;
  const pos = canvasPos(ev);
  const i = frameAt(pos.x);
  if (i >= BASE.length || !(BASE[i] > 0)) return;
  const f = Math.max(20, Math.min(8000, freqAt(pos.y)));
  ensureDraw(GEO.n);
  // pitch_draw est un ecart contre la courbe NUE, donc une affectation
  // directe : le geste est idempotent, retirer deux fois la meme bande au
  // meme endroit donne la meme valeur, sans derive.
  CUR.pitch_draw[i] = Math.max(-2400, Math.min(2400,
    1200 * Math.log2(f / BASE[i])));
  // Par construction la trame vaut exactement f : rien d'autre a calculer
  // pour le trace provisoire. Elle perd son jitter jusqu'au rendu suivant.
  LASTC.freq[i] = f;
  draw(LASTC, LASTNOTES);
}

$('cv').addEventListener('mousedown', ev => {
  if (mode !== 'create' || !GEO || !BASE.length) return;
  const y = canvasPos(ev).y;
  if (y < GEO.m.t || y > GEO.m.t + GEO.pitchH) return;   // hors piste de hauteur
  pitchDrag = true; drawAt(ev); ev.preventDefault();
});
// Sur window, comme la selection de la forme d'onde : un glissement qui sort
// du canvas doit continuer d'etre suivi.
window.addEventListener('mousemove', ev => { if (pitchDrag) drawAt(ev); });
window.addEventListener('mouseup', () => {
  if (!pitchDrag) return;
  pitchDrag = false;
  // Un seul rendu au relachement. La garde renderBusy/renderAgain de render()
  // suffit, pas besoin de minuterie.
  render();
});
```

- [ ] **Step 4: Ajouter le bouton d'effacement sous le graphique**

Dans le HTML, juste **après** le bloc `<div class="legend">…</div>` qui suit `<canvas id="cv" …>` :

```html
  <div id="drawBox" style="display:flex;gap:8px;align-items:center;margin:-8px 2px 14px">
    <button class="ghost" id="clearDraw">effacer le dessin</button>
    <span class="hint">Glisser sur la courbe de hauteur corrige les trames
      travers&eacute;es. Les r&eacute;glages param&eacute;triques continuent de
      s'appliquer dessous&nbsp;: le dessin est un &eacute;cart, pas un
      remplacement. Un tirage l'efface, une mutation le garde.</span>
  </div>
```

Et son gestionnaire, à côté des autres boutons du mode Créer (près de `$('gen').onclick`) :

```javascript
$('clearDraw').onclick = () => { CUR.pitch_draw = []; render(); };
```

- [ ] **Step 5: N'ouvrir le geste que dans l'onglet Créer**

Le canvas est partagé par les deux onglets, mais `CUR` n'existe qu'en mode Créer. Dans la bascule d'onglets, ajouter le masquage du bloc :

```javascript
$('tabCreate').onclick = ()=>{ mode='create'; $('wavOnly').classList.add('hide');
  $('drawBox').classList.remove('hide');
```

```javascript
$('tabWav').onclick = ()=>{ mode='wav'; $('wavOnly').classList.remove('hide');
  $('drawBox').classList.add('hide');
```

Le garde `mode !== 'create'` du `mousedown` reste : il protège le geste, le masquage ne fait que retirer le bouton de la vue.

- [ ] **Step 6: Lancer la suite Python**

Run: `cd toolbox/to8-soundfx-generator && python3 -m tests`

Expected: aucune régression. Cette tâche ne touche pas Python, mais un `pitch_draw` mal formé envoyé par le navigateur remonterait ici.

- [ ] **Step 7: Ouvrir la page**

Run: `cd toolbox/to8-soundfx-generator && ./run.sh`

Ouvrir `http://127.0.0.1:8731/`. La console du navigateur doit être vierge au chargement.

- [ ] **Step 8: Vérifier le geste, point par point**

À faire dans cet ordre, chaque point étant à reporter dans le compte rendu :

1. **Tirer au sort**, puis glisser sur la courbe de hauteur : la courbe verte suit le curseur pendant tout le glissement, sans à-coup et sans appel réseau.
2. Au relâchement, **un seul** rendu part (onglet Réseau), et le son joué correspond à la courbe dessinée.
3. **Les bandes colorées ne changent pas de couleur** sur les trames retouchées. C'est la vérification centrale de cette tâche.
4. Repasser lentement **deux fois au même endroit** : la courbe ne dérive pas, elle se repose exactement au même niveau.
5. Bouger ensuite le curseur `slide` : **toute** la courbe glisse, retouches comprises, et la forme dessinée est conservée par-dessus.
6. Allonger `decay_frames` : le dessin s'étire en proportion au lieu de rester tassé au début.
7. **Tirer au sort** : le dessin disparaît. **Muter puis adopter une variante** : le dessin est toujours là.
8. **effacer le dessin** : retour à la courbe purement paramétrique.
9. Garder le son dans la banque, **recharger la banque** : le son revient avec son dessin.
10. Cliquer **sous** la piste de hauteur, dans la zone de volume : aucun effet, le volume reste non éditable.
11. Basculer sur l'onglet **Fichier audio** : le bloc *effacer le dessin* disparaît, et glisser sur le canvas n'a aucun effet. Charger un fichier, sélectionner, générer, écouter — **le mode fichier doit se comporter exactement comme avant**.
12. Avec du `jitter_cents` élevé, dessiner une trame : le tracé provisoire est lisse sur la trame touchée, et le rendu qui revient y remet du jitter. C'est attendu.
13. Dessiner une courbe très accidentée sur un son long : l'avertissement de simplification apparaît plus souvent. C'est attendu et documenté.

- [ ] **Step 9: Commit**

```bash
git add static/index.html
git commit -m "feat(dessin): tirer une trame de hauteur a la main dans le graphique

Les bandes verticales colorees par instrument, deja tracees sur la piste
de hauteur, deviennent les cibles du geste : rien de neuf a dessiner, et
elles GARDENT leur couleur. Une trame retouchee ne se signale par aucune
teinte — le seul retour visuel est la courbe verte qui suit la main.

L'ecart est mesure contre freq_base, la courbe parametrique nue, donc le
geste s'ecrit en affectation et non en accumulation : repasser au meme
endroit repose la courbe au meme niveau, sans derive. Pendant le
glissement rien ne part sur le reseau ; un seul rendu au relachement."
```

---

## Auto-relecture du plan

**Couverture de la spec, section par section :**

| Section de la spec | Tâche |
|---|---|
| Le geste, et ce qu'on voit (bandes comme cibles, pas de teinte) | 5, étapes 3 et 8.3 |
| Le modèle : champ hors `BOUNDS`, `to_dict`/`from_dict` | 1 |
| Longueur libre et ré-échantillonnage, borne ±2400 | 1 |
| Le rendu : addition après l'arpège, avant les hertz | 2 |
| `freq_base` nue, calculée mais jamais dessinée, `_pitch_semitones` | 2 et 4 |
| L'interface : géométrie hoistée, gestionnaires, retour immédiat, bouton | 5 |
| Le coût en commandes | 5, étape 8.13 — rien à coder, `fit_to_budget` avertit déjà |
| Garde-fous : bornes, `from_dict` tolérant, `n == 0`, mode Créer seul | 1 (étapes 3 et 5), 5 (étape 5) |
| Tests 1 à 10 de la spec | 1 (1-3), 2 (4, 5, 9), 3 (6, 7, 8), 4 (10) |
| Hors périmètre | aucune tâche n'y touche |

Les dix tests de la spec sont tous placés. La consigne « éprouver au moins un test » est la tâche 3, étape 4.

**Cohérence des noms entre tâches :** `_resample_draw`, `_clean_draw`, `PITCH_DRAW_MAX_CENTS`, `_local_index`, `_pitch_semitones`, `base_pitch`, `freq_base`, `pitch_draw`, `GEO`, `BASE`, `LASTC`, `LASTNOTES`, `ensureDraw`, `drawAt`, `canvasPos`, `freqAt`, `frameAt`, `drawBox`, `clearDraw` — chacun défini une fois et employé sous la même orthographe partout.

**Ordre des dépendances :** 1 → 2 (a besoin de `_resample_draw`), 2 → 4 (a besoin de `base_pitch`), 4 → 5 (a besoin de `freq_base`). La tâche 3 ne dépend que de la 1 et peut être menée à tout moment après elle.
