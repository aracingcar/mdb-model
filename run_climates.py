"""Fill the database with climate runs: python run_climates.py [model[/scenario[/config]] ...]  (default: every known run).

Each missing run is downloaded (in parallel), reduced into data/results.db, run through the model with the default
methods, and its raw files are deleted. Runs already in the database for every displayed SDL unit are skipped.
"""
import itertools
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
for folder in ("1_masking", "5_outputs"):
    sys.path.insert(0, str(ROOT / folder))

from config import DISPLAY_SYSTEMS, MEMBERS, SYSTEMS
from results_db import stored_runs

UNITS = [u for s in DISPLAY_SYSTEMS for u in SYSTEMS[s]["units"]]

SCENARIOS = ("ssp126", "ssp245", "ssp370")
CONFIGS = ("WRF412R3", "WRF412R5")


def main(selectors):
    runs = list(itertools.product(MEMBERS, SCENARIOS, CONFIGS))
    if selectors:
        runs = [r for r in runs if any(r[: len(s)] == tuple(s) for s in (x.split("/") for x in selectors))]
    todo = [r for r in runs if r not in stored_runs(UNITS)]
    print(f"{len(todo)} of {len(runs)} runs to do", flush=True)
    for i, (model, scenario, config) in enumerate(todo, 1):
        t = time.time()
        env = {**os.environ, "GLOBAL_MODEL": model, "SCENARIO": scenario, "REGIONAL_CONFIG": config}
        done = subprocess.run([sys.executable, str(ROOT / "main.py")], env=env).returncode == 0
        print(f"[{i}/{len(todo)}] {model}/{scenario}/{config}: {'done' if done else 'FAILED'} in {(time.time() - t) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
