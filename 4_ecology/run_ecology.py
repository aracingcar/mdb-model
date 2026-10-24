import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for sub in ("", "fish", "waterbirds", "river_red_gum"):
    sys.path.insert(0, str(HERE / sub))

from breeding_trigger import breeding_trigger
from condition import red_gum_condition
from ctf_stress import ctf_stress

INDICATORS = {"fish": ctf_stress, "waterbirds": breeding_trigger, "river_red_gum": red_gum_condition}


def run_ecology(flow, thresholds):
    """Return (fish, waterbirds, river_red_gum) metric tables per water year from daily flow (ML/d).

    ``thresholds`` maps an indicator to its flow thresholds (an SDL unit's, see config.SDL_UNITS); an indicator
    without them is None.
    """
    if flow is None:
        print("4_ecology: no flow series (needs steps 2-3), skipped")
        return None, None, None
    thresholds = thresholds or {}
    skipped = [k for k in INDICATORS if k not in thresholds]
    if skipped:
        print(f"4_ecology: no thresholds for {', '.join(skipped)}, skipped")
    return tuple(f(flow, **thresholds[k]) if k in thresholds else None for k, f in INDICATORS.items())
