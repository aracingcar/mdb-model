import os
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
INPUT = DATA / "input"
OUTPUT_ROOT = DATA / "output"
DB_FILE = DATA / "results.db"  # reduced climate series and model results, one row per run

GLOBAL_MODEL = os.environ.get("GLOBAL_MODEL", "ACCESS-ESM1-5")
SCENARIO = os.environ.get("SCENARIO", "ssp245")
KEEP_RAW = bool(os.environ.get("KEEP_RAW"))  # keep the raw NARCliM files after they are reduced into the database
REGIONAL_CONFIG = os.environ.get("REGIONAL_CONFIG", "WRF412R5")
OUTPUT = OUTPUT_ROOT / GLOBAL_MODEL / SCENARIO / REGIONAL_CONFIG
NARCLIM_ROOT = INPUT / "narclim"
NARCLIM_DIR = NARCLIM_ROOT / GLOBAL_MODEL / SCENARIO / REGIONAL_CONFIG
NARCLIM_GLOB = str(NARCLIM_DIR / "*.nc")
RLON_CORRECTION_FILE = NARCLIM_DIR / "rlon_correction.txt"
CATCHMENT_FILE = INPUT / "catchment" / "CEWO_MDB_Valleys.shp"
OUTPUT_FILE = OUTPUT / "murrumbidgee_daily_P_PET.csv"
SUBCATCHMENT_FORCING_FILE = OUTPUT / "murrumbidgee_subcatchment_forcing.csv"
SUBCATCHMENT_FILE = OUTPUT / "murrumbidgee_subcatchments.gpkg"
HYBAS_FILE = INPUT / "hydrobasins" / "hybas_au_lev08_v1c.shp"
N_SUBCATCHMENTS = 11  # terrain regions; a 12th lowland unit holds the rest of the valley
VALLEY_NAME = "Murrumbidgee"

# NARCliM2.0 4 km (SEAus-04), ACCESS-ESM1-5, SSP2-4.5, daily. Remote subsets come from NCI THREDDS (zz63).
THREDDS_DODS = "https://thredds.nci.org.au/thredds/dodsC/zz63/NARCliM2-0/output-CMIP6/DD"
RUN = f"NARCliM2-0-SEAus-04/NSW-Government/{GLOBAL_MODEL}/{SCENARIO}/r6i1p1f1/NARCliM2-0-{REGIONAL_CONFIG}/v1-r1/day"
RUN_TAG = f"NARCliM2-0-SEAus-04_{GLOBAL_MODEL}_{SCENARIO}_r6i1p1f1_NSW-Government_NARCliM2-0-{REGIONAL_CONFIG}_v1-r1_day"
YEARS = range(2015, 2101)
BBOX_MARGIN = 0.2  # degrees around the catchment

# NARCliM variable names -> output names. Fluxes are kg m-2 s-1; x86400 gives mm/day.
VARIABLES = {"pr": "P", "evspsblpot": "PET"}
SECONDS_PER_DAY = 86400

# Rotated-pole grid of the SEAus-04 domain (stored rlon is wrong; see RLON_CORRECTION_FILE).
ROTATED_POLE_CRS = (
    "+proj=ob_tran +o_proj=longlat +o_lon_p=0 +o_lat_p=60.31 +lon_0=321.38 "
    "+R=6370000 +to_meter=0.017453292519943295 +no_defs"
)
