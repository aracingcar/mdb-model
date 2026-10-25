import os
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
INPUT = DATA / "input"
OUTPUT_ROOT = DATA / "output"
DB_FILE = DATA / "results.db"  # reduced climate series and model results, one row per SDL unit and run

# River channels (HydroBASINS network, OSM waterways) are kept within this distance of the exterior border of the SDL
# unit outlines (the union of a system's units; internal unit borders are untouched), so a river running along or just
# across the border is not cut off at it. The buffer is measured in OUTLINE_BUFFER_CRS (metres), never in degrees.
OUTLINE_BUFFER_KM = 3
OUTLINE_BUFFER_CRS = "EPSG:3577"  # Australian Albers

# Surface water SDL resource units (Basin Plan 2012), outlines from the MDBA layer (1_masking/download_sdl_units.py).
# Everything stored in results.db is keyed by unit. ecology: flow thresholds (ML/d) for the indicators scored at the
# unit's outlet; leave an indicator out, or set ecology to None, to skip it.
SDL_FILE = INPUT / "sdl" / "Surface Water SDL Resource Units.shp"
SDL_UNITS = {
    "SS15": {
        "name": "Murrumbidgee", "system": "murrumbidgee",
        # MDBA py-ewr parameter sheet: CF1 (Murrumbidgee LTWP), W-LF4_S (Lowbidgee, gauge 410021), OB-S2 (gauge 410040)
        "ecology": {"fish": {"ctf_flow": 1.0},
                    "waterbirds": {"trigger_flow": 15500, "trigger_days": 9},
                    "river_red_gum": {"flood_flow": 15000, "flood_days": 11}},
    },
    "SS1": {"name": "ACT", "system": "murrumbidgee", "ecology": None},
    "SS16": {"name": "Lachlan", "system": "lachlan", "ecology": None},
    "SS18": {"name": "Lower Darling", "system": "lower_darling", "ecology": None},
    "SS14": {"name": "NSW Murray", "system": "murray", "ecology": None},
    "SS2": {"name": "Victorian Murray", "system": "murray", "ecology": None},
    "SS6": {"name": "Goulburn", "system": "goulburn_broken", "ecology": None},
    "SS5": {"name": "Broken", "system": "goulburn_broken", "ecology": None},
    "SS3": {"name": "Kiewa", "system": "murray", "ecology": None},
    "SS4": {"name": "Ovens", "system": "murray", "ecology": None},
}

# River systems: the units whose rivers form one network, routed together across unit borders (the upper
# Murrumbidgee flows into the ACT, SS1, and the ACT drains back into SS15). Per system:
# n_subcatchments: main-stem reaches asked for (large HydroBASINS basins can merge some); every place a river leaves
#   a unit also ends a reach, so reaches never cross unit borders.
# routing: miscellaneous loss/km at basin outlets in the last loss_regions main-stem reaches, calibrated so
#   the mean outlet flow matches target_outlet_m3s after channel fluxes. Both None: provisional losses, no fitting.
# splits: {basin: {to: fraction}} sends that share of a basin's routed outflow to another basin, or out of the river
#   with to = '' (e.g. into a terminal wetland); the rest goes on to its downstream basin.
# split_rivers (optional): {basin: river name} the river a split to '' runs down, so the editor can draw it.
# storages (optional): {name: {lon, lat, max_release_ML_d}} dams, each placed on the routing node containing it. A storage
#   releases up to max_release_ML_d a day (less if it holds less), keeps the rest and never spills (no capacity limit).
#   The release caps are indicative placeholders, not operating rules.
# other_rivers (optional): rivers of other systems that run through this one; they are not given this system's flow.
# min_network_km2 (optional): also give reaches to every other drainage network at least this big that leaves the
#   system elsewhere (by default only the main network gets reaches and the rest joins the lowland).
SYSTEMS = {
    "murrumbidgee": {
        "units": ("SS15", "SS1"), "n_subcatchments": 11, "mainstem": "Murrumbidgee River",
        "routing": {"loss_regions": 3, "target_outlet_m3s": 27.0},  # recorded mean at Balranald, ~27 m3/s (Wikipedia, "Murrumbidgee River")
        # Yanco Creek leaves the river at Narrandera and runs out to the Billabong and Edward systems, outside this system: an
        # indicative ~8% of the flow there (not a measured allocation)
        "splits": {"B5080595380": {"": 0.08}},
        "split_rivers": {"B5080595380": "Yanco Creek"},
        "storages": {"Burrinjuck Dam": {"lon": 148.58, "lat": -35.00, "max_release_ML_d": 8000},
                     "Blowering Dam": {"lon": 148.26, "lat": -35.41, "max_release_ML_d": 12000}},
    },
    "lachlan": {
        "units": ("SS16",), "n_subcatchments": 11, "mainstem": "Lachlan River",
        "routing": {"loss_regions": None, "target_outlet_m3s": None},  # terminal river: no calibration gauge chosen yet
        "splits": {},
        "storages": {"Wyangala Dam": {"lon": 148.97, "lat": -33.97, "max_release_ML_d": 6000}},
    },
    # Local runoff only: the Darling's inflow from the Barwon-Darling (SS19) and the northern Basin is not modelled.
    "lower_darling": {
        "units": ("SS18",), "n_subcatchments": 11, "mainstem": "Darling River", "other_rivers": ("Murray River",),
        "routing": {"loss_regions": None, "target_outlet_m3s": None},  # no calibration gauge chosen yet
        "splits": {},
    },
    # The Murray with its Victorian tributaries the Kiewa and Ovens, routed into it through HydroBASINS' downstream links.
    # Local runoff only: the Murrumbidgee and Darling, Snowy releases and regulation are not routed in, so the flows are
    # uncalibrated. The Goulburn-Broken is its own system (below) that drains into the Murray; its outflow is not added
    # to the Murray's flow here.
    "murray": {
        "units": ("SS14", "SS2", "SS3", "SS4"), "n_subcatchments": 14, "mainstem": "Murray River", "min_network_km2": 500,
        "other_rivers": ("Murrumbidgee River", "Darling River", "Goulburn River"),
        "routing": {"loss_regions": None, "target_outlet_m3s": None},
        "splits": {},
        "storages": {"Hume Dam": {"lon": 147.03, "lat": -36.10, "max_release_ML_d": 25000},
                     "Dartmouth Dam": {"lon": 147.52, "lat": -36.55, "max_release_ML_d": 12000}},
    },
    # Goulburn (SS6) and Broken (SS5): the Broken flows into the Goulburn, and the Goulburn drains into the Murray.
    "goulburn_broken": {
        "units": ("SS6", "SS5"), "n_subcatchments": 12, "mainstem": "Goulburn River", "min_network_km2": 500,
        "other_rivers": ("Murray River",),
        "routing": {"loss_regions": None, "target_outlet_m3s": None},
        "splits": {},
        "storages": {"Eildon Dam": {"lon": 145.92, "lat": -37.22, "max_release_ML_d": 10000},
                     "Lake Nillahcootie": {"lon": 146.01, "lat": -36.89, "max_release_ML_d": 1000}},
    },
}
DISPLAY_SYSTEMS = ("murrumbidgee", "lachlan", "lower_darling", "murray", "goulburn_broken")  # drawn together on docs/index.html
SYSTEM_ID = os.environ.get("SYSTEM", DISPLAY_SYSTEMS[0])  # the system this process models (main.py sets it per system)
SYSTEM = SYSTEMS[SYSTEM_ID]
UNITS = SYSTEM["units"]
N_SUBCATCHMENTS = SYSTEM["n_subcatchments"]
MAINSTEM = SYSTEM["mainstem"]


def waterways_file(system):
    return INPUT / "routing" / f"osm_{system}_waterways.geojson"


WATERWAYS_FILE = waterways_file(SYSTEM_ID)

GLOBAL_MODEL = os.environ.get("GLOBAL_MODEL", "ACCESS-ESM1-5")
SCENARIO = os.environ.get("SCENARIO", "ssp245")
KEEP_RAW = bool(os.environ.get("KEEP_RAW"))  # keep the raw NARCliM files after they are reduced into the database
REGIONAL_CONFIG = os.environ.get("REGIONAL_CONFIG", "WRF412R5")
OUTPUT = OUTPUT_ROOT / SYSTEM_ID / GLOBAL_MODEL / SCENARIO / REGIONAL_CONFIG
NARCLIM_ROOT = INPUT / "narclim"
NARCLIM_DIR = NARCLIM_ROOT / SYSTEM_ID / GLOBAL_MODEL / SCENARIO / REGIONAL_CONFIG  # subsets are cut to the system's bounds
NARCLIM_GLOB = str(NARCLIM_DIR / "*.nc")
RLON_CORRECTION_FILE = NARCLIM_ROOT / "rlon_correction.txt"  # one correction for the whole SEAus-04 domain
OUTPUT_FILE = OUTPUT / f"{SYSTEM_ID}_daily_P_PET.csv"
SUBCATCHMENT_FORCING_FILE = OUTPUT / f"{SYSTEM_ID}_subcatchment_forcing.csv"
SUBCATCHMENT_FILE = OUTPUT / f"{SYSTEM_ID}_subcatchments.gpkg"
HYBAS_FILE = INPUT / "hydrobasins" / "hybas_au_lev08_v1c.shp"  # basins: rainfall-runoff runs on these
HYBAS_NODE_FILE = INPUT / "hydrobasins" / "hybas_au_lev10_v1c.shp"  # routing nodes: the finer watersheds inside each basin

# NARCliM2.0 4 km (SEAus-04), ACCESS-ESM1-5, SSP2-4.5, daily. Remote subsets come from NCI THREDDS (zz63).
THREDDS_DODS = "https://thredds.nci.org.au/thredds/dodsC/zz63/NARCliM2-0/output-CMIP6/DD"
# Ensemble member NARCliM2.0 downloaded each global model's run from (checked against the THREDDS server; UKESM1-0-LL not found).
MEMBERS = {"ACCESS-ESM1-5": "r6i1p1f1", "EC-Earth3-Veg": "r1i1p1f1", "MPI-ESM1-2-HR": "r1i1p1f1", "NorESM2-MM": "r1i1p1f1"}
MEMBER = MEMBERS.get(GLOBAL_MODEL, "r1i1p1f1")
DEFAULT_RUN = ("ACCESS-ESM1-5", "ssp245", "WRF412R5")  # the run published in docs/
# The climate cases the display offers, best to worst. The middle one is the default run.
CLIMATE_CASES = (
    {"id": "best", "label": "Best case", "run": ("NorESM2-MM", "ssp126", "WRF412R3")},
    {"id": "median", "label": "Median", "run": DEFAULT_RUN},
    {"id": "worst", "label": "Worst case", "run": ("UKESM1-0-LL", "ssp370", "WRF412R5")},
)
RUN_KEY = (GLOBAL_MODEL, SCENARIO, REGIONAL_CONFIG)
DOWNLOAD_WORKERS = 4  # parallel processes; more than ~4 gave no further speed-up
RUN = f"NARCliM2-0-SEAus-04/NSW-Government/{GLOBAL_MODEL}/{SCENARIO}/{MEMBER}/NARCliM2-0-{REGIONAL_CONFIG}/v1-r1/day"
RUN_TAG = f"NARCliM2-0-SEAus-04_{GLOBAL_MODEL}_{SCENARIO}_{MEMBER}_NSW-Government_NARCliM2-0-{REGIONAL_CONFIG}_v1-r1_day"
YEARS = range(2015, 2101)
BBOX_MARGIN = 0.2  # degrees around the catchment

# NARCliM variable names -> output names. Fluxes are kg m-2 s-1; x86400 gives mm/day.
VARIABLES = {"pr": "P", "evspsblpot": "PET"}
SECONDS_PER_DAY = 86400

# Rotated-pole grid of the SEAus-04 domain (stored rlon is wrong; see RLON_CORRECTION_FILE). o_lon_p=180 turns the
# rotated longitudes half a circle, so the domain runs -6 to 17 degrees instead of crossing +-180 over the Lower Darling;
# load.py shifts the stored rlon to match.
ROTATED_POLE_CRS = (
    "+proj=ob_tran +o_proj=longlat +o_lon_p=180 +o_lat_p=60.31 +lon_0=321.38 "
    "+R=6370000 +to_meter=0.017453292519943295 +no_defs"
)
