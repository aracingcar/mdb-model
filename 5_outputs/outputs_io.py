import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "1_masking"))

from config import OUTPUT, OUTPUT_FILE, SUBCATCHMENT_FILE, SUBCATCHMENT_FORCING_FILE

FLOW_FILE = OUTPUT / "murrumbidgee_flow.csv"
BASINS_FILE = OUTPUT / "murrumbidgee_basins.gpkg"
RIVERS_FILE = OUTPUT / "murrumbidgee_rivers.gpkg"
RIVER_FLOW_FILE = OUTPUT / "murrumbidgee_river_flow.csv"
REACH_FLOW_FILE = OUTPUT / "murrumbidgee_reach_flow.csv"
FISH_FILE = OUTPUT / "fish_ctf_stress.csv"
WATERBIRD_FILE = OUTPUT / "waterbird_breeding_trigger.csv"
RED_GUM_FILE = OUTPUT / "river_red_gum_condition.csv"


def write_data(forcing, subcatchments, subcatchment_forcing, basins, flow, reach_flow, rivers, river_flow, fish, waterbirds, river_red_gum):
    """Write every available result to data/output/ and print what was written. None results are skipped."""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    forcing.to_csv(OUTPUT_FILE)
    subcatchments.to_file(SUBCATCHMENT_FILE, layer="subcatchments", driver="GPKG")
    subcatchment_forcing.to_csv(SUBCATCHMENT_FORCING_FILE)
    basins.to_file(BASINS_FILE, layer="basins", driver="GPKG")
    print(f"Wrote valley-average forcing ({len(forcing)} days): {OUTPUT_FILE}")
    print(f"Wrote {len(subcatchments)} subcatchment polygons: {SUBCATCHMENT_FILE}")
    print(f"Wrote {len(basins)} network basins: {BASINS_FILE}")
    print(f"Wrote {len(subcatchment_forcing)} days of unit forcing: {SUBCATCHMENT_FORCING_FILE}")

    if flow is not None:
        flow.rename("flow_ML_d").rename_axis("date").to_csv(FLOW_FILE)
        print(f"Wrote flow ({len(flow)} days): {FLOW_FILE}")
        reach_flow.rename_axis("date").to_csv(REACH_FLOW_FILE)
        print(f"Wrote flow at {reach_flow.shape[1]} reach outlets: {REACH_FLOW_FILE}")
        rivers.to_file(RIVERS_FILE, layer="rivers", driver="GPKG")
        river_flow.rename_axis("date").to_csv(RIVER_FLOW_FILE)
        print(f"Wrote {len(rivers)} river segments and their daily flow: {RIVER_FLOW_FILE}")
    for table, path in ((fish, FISH_FILE), (waterbirds, WATERBIRD_FILE), (river_red_gum, RED_GUM_FILE)):
        if table is not None:
            table.to_csv(path)
            print(f"Wrote {len(table)} water years: {path}")
