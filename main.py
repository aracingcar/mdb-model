import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
for folder in ("1_masking", "2_rainfall_runoff", "3_routing", "4_ecology", "5_outputs", "6_display"):
    sys.path.insert(0, str(ROOT / folder))

from config import DEFAULT_RUN, DISPLAY_SYSTEMS, RUN_KEY, SDL_UNITS, UNITS
from outputs_io import write_data
from run_display import run_display
from run_ecology import run_ecology
from run_masking import run_masking
from run_rainfall_runoff import RAINFALL_RUNOFF_MODEL, run_rainfall_runoff
from run_routing import ROUTING_MODEL, run_routing


def run_system():
    """Model the river system named by SYSTEM and store each of its SDL units' geometry and results."""
    units, subcatchments, basins, basin_forcing = run_masking()
    runoff = run_rainfall_runoff(basin_forcing, basins)
    unit_flow, reach_flow, basin_flow, rivers, river_flow = run_routing(runoff, basins, subcatchments)
    for u in UNITS:
        of = lambda frame: frame[frame["sdl_unit"] == u]
        regions, unit_rivers = of(subcatchments), of(rivers)
        fish, waterbirds, river_red_gum = run_ecology(unit_flow[u], SDL_UNITS[u]["ecology"])
        write_data(u, units.loc[[u]].reset_index(), regions, of(basins), unit_flow[u], reach_flow[list(regions["subcatchment"])],
                   unit_rivers, river_flow[list(unit_rivers["river_id"])], fish, waterbirds, river_red_gum, (RAINFALL_RUNOFF_MODEL, ROUTING_MODEL))


if __name__ == "__main__":
    if "SYSTEM" in os.environ:
        run_system()
    else:  # each system in its own process (config is per system), then the page shows them all
        for system in DISPLAY_SYSTEMS:
            subprocess.run([sys.executable, __file__], env={**os.environ, "SYSTEM": system}, check=True)
        if RUN_KEY == DEFAULT_RUN:  # docs/ shows the default run only
            run_display()
