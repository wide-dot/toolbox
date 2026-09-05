/* -----------------------------------------------------------------------------
 * shim.c - couche mince au dessus d'emu2413, appelee depuis Python (ctypes).
 *
 * Le but est de ne faire QU'UN appel ctypes par rendu : appeler OPLL_calc()
 * echantillon par echantillon depuis Python coute ~100x le temps du rendu.
 * On passe donc un flux d'evenements (instant en echantillons, registre,
 * valeur) et on recupere le buffer complet.
 * -----------------------------------------------------------------------------
 */

#include <stdint.h>
#include <string.h>
#include "emu2413.h"

/* Rend nsamples echantillons mono 16 bits.
 *
 * ev_t/ev_r/ev_v : nev evenements TRIES par ev_t croissant.
 *                  ev_t est un instant en echantillons depuis le debut.
 * chip_type      : 0 = YM2413 (jeu de patchs ROM du YM2413)
 *
 * Retourne le nombre d'echantillons ecrits.
 */
int opll_render(uint32_t clk, uint32_t rate, int chip_type,
                const uint32_t *ev_t, const uint8_t *ev_r, const uint8_t *ev_v,
                int nev, int16_t *out, int nsamples) {
  OPLL *opll = OPLL_new(clk, rate);
  if (!opll) return 0;
  OPLL_setChipType(opll, (uint8_t)chip_type);
  OPLL_reset(opll);
  OPLL_setQuality(opll, 1);

  int ei = 0;
  for (int i = 0; i < nsamples; i++) {
    while (ei < nev && (int)ev_t[ei] <= i) {
      OPLL_writeReg(opll, ev_r[ei], ev_v[ei]);
      ei++;
    }
    out[i] = OPLL_calc(opll);
  }

  OPLL_delete(opll);
  return nsamples;
}

/* Recopie les 8 octets de "dump" d'un patch ROM (num 1..15) dans dump8.
 * C'est exactement le format attendu par la commande $FF du driver soundFX.
 */
void opll_default_patch_dump(int chip_type, int num, uint8_t *dump8) {
  OPLL_PATCH patch[2];
  uint8_t dump[8];
  memset(dump, 0, sizeof(dump));
  /* getDefaultPatch remplit 2 patchs (modulateur + porteuse) pour l'instrument */
  OPLL_getDefaultPatch(chip_type, num, patch);
  OPLL_patchToDump(patch, dump);
  memcpy(dump8, dump, 8);
}
