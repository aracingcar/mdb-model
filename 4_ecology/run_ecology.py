import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for sub in ("", "fish", "waterbirds", "river_red_gum"):
    sys.path.insert(0, str(HERE / sub))

from breeding_trigger import breeding_trigger
from condition import red_gum_condition
from ctf_stress import ctf_stress


def run_ecology(flow):
    """Return (fish, waterbirds, river_red_gum) metric tables per water year from daily flow (ML/d)."""
    if flow is None:
        print("4_ecology: no flow series (needs steps 2-3), skipped")
        return None, None, None
    return ctf_stress(flow), breeding_trigger(flow), red_gum_condition(flow)
