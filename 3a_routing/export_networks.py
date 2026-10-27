"""Write each river system's current network to river_systems/<system>-network.json (the format the routing editor exports).

A system that already has a network file keeps it unless --force is given. Run from the repository root:
python 3a_routing/export_networks.py [--force] [system ...]
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for folder in ("1_masking", "2a_rainfall_runoff", "3a_routing", "5_outputs"):
    sys.path.insert(0, str(ROOT / folder))


def export(force):
    """Write the network of the system this process models (config is per system: SYSTEM)."""
    from config import HYBAS_FILE, N_SUBCATCHMENTS, SYSTEM, SYSTEM_ID
    from run_masking import load_units, terrain_regions
    from nodes import build_nodes, network_file, network_json
    path = network_file(SYSTEM_ID)
    if path.exists() and not force:
        print(f"{path.name}: kept (use --force to rewrite it)")
        return
    path.unlink(missing_ok=True)  # build_nodes applies an existing file: --force rebuilds without it
    _, basins = terrain_regions(load_units(), HYBAS_FILE, n=N_SUBCATCHMENTS, min_network_km2=SYSTEM.get("min_network_km2"), joins=SYSTEM.get("joins"))
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(network_json(build_nodes(basins, SYSTEM_ID), SYSTEM_ID), separators=(",", ":")))
    print(f"{path.name}: written")


if __name__ == "__main__":
    force, systems = "--force" in sys.argv, [a for a in sys.argv[1:] if a != "--force"]
    if "SYSTEM" in os.environ:
        export(force)
    else:
        from config import DISPLAY_SYSTEMS
        for system in systems or DISPLAY_SYSTEMS:  # each system in its own process, as main.py runs them
            subprocess.run([sys.executable, __file__, *(["--force"] if force else [])], env={**os.environ, "SYSTEM": system}, check=True)
