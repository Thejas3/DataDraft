"""Apply a league's scoring_settings to a projected stat line.

Sleeper projection stat keys (pass_yd, rec, bonus_rec_te, pts_allow_21_27, fgm_40_49, ...)
use the same names as scoring_settings, so league scoring is a key-by-key dot product.
Keys the league doesn't score (pts_ppr, adp_*, gp) contribute nothing."""


def score(stats: dict, scoring_settings: dict) -> float:
    total = 0.0
    for key, value in stats.items():
        weight = scoring_settings.get(key)
        if weight is not None and isinstance(value, (int, float)):
            total += value * weight
    return total
