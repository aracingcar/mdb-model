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
# The MDBA layer ends the NSW Murray (SS14) at Tooleybuc and gives the river below it to the Lower Darling (SS18) and the Mallee
# plain (SS9), but the NSW Murray runs to the South Australian border (NSW Murray and Lower Darling Water Resource Plan, status and
# issues paper, 2017). So the HydroBASINS basins ``basins`` of the Murray from Boundary Bend to the border move from the units in
# ``from`` into ``unit``, west of ``west_lon`` (the border) cut off.
MURRAY_CORRIDOR = {
    "unit": "SS14", "from": ("SS18", "SS9"), "west_lon": 141.0,
    "basins": (5080595640, 5080595260, 5080595320, 5080594890, 5080595020, 5080593440, 5080591050, 5080590940, 5080591290,
               5080590720, 5080590470, 5080589480),
}
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
# joins (optional): {basin: downstream basin} replaces a basin's HydroBASINS downstream link, for a river that runs on through
#   basins outside the system (or another system's stub) to a basin of this system. Applied after the reaches are grouped,
#   so reaches and the stored climate keyed by them do not change.
# keep_links (optional): basins whose outlet node keeps its straight-line link to the next river node even over the
#   MAX_GAP_KM (3_routing/nodes.py) where the mapped channel cannot be followed; for main-stem links the cut would strand.
SYSTEMS = {
    "murrumbidgee": {
        "units": ("SS15", "SS1"), "n_subcatchments": 11, "mainstem": "Murrumbidgee River",
        # no outlet target: Balranald's recorded mean is regulated flow (Snowy transfers in, irrigation out) that this model does not represent.
        "routing": {"loss_regions": None, "target_outlet_m3s": None},
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
    # Local runoff only: the Darling's inflow from the Barwon-Darling (SS19) and the northern Basin is not modelled. The Murray below
    # Tooleybuc is in the murray system (MURRAY_CORRIDOR), so the Darling ends at its junction and joins it through LINKS.
    "lower_darling": {
        "units": ("SS18",), "n_subcatchments": 11, "mainstem": "Darling River", "other_rivers": ("Murray River",),
        "routing": {"loss_regions": None, "target_outlet_m3s": None},  # no calibration gauge chosen yet
        # The Great Darling Anabranch leaves the Darling just below Menindee and runs south to the Murray near Wentworth, inside this
        # system's reach but outside what is routed: an indicative ~5% of the flow there leaves the river (not a measured allocation)
        "splits": {"B5080575770": {"": 0.05}},
        "split_rivers": {"B5080575770": "Great Darling Anabranch"},
    },
    # The Murray with its Victorian tributaries the Kiewa and Ovens, routed into it through HydroBASINS' downstream links, from
    # Hume to the South Australian border (the corridor below Tooleybuc is moved into SS14, see MURRAY_CORRIDOR). Local runoff
    # plus the Goulburn, Murrumbidgee and Lower Darling through LINKS: Snowy releases and regulation are not routed in, so the flows are
    # uncalibrated. The Goulburn-Broken is its own system (below) that drains into the Murray; its outflow is not added
    # to the Murray's flow here.
    "murray": {
        "units": ("SS14", "SS2", "SS3", "SS4"), "n_subcatchments": 14, "mainstem": "Murray River", "min_network_km2": 500,
        "other_rivers": ("Murrumbidgee River", "Darling River", "Goulburn River"),
        "routing": {"loss_regions": None, "target_outlet_m3s": None},
        # Offtakes, as indicative shares of the river's flow there. Yarrawonga Weir diverts ~1,900 GL a year, ~17% of the river's flow
        # (Goulburn-Murray Water), split by offtake capacity: Mulwala Canal (10,000 ML/d) ~13% and Yarrawonga Main Channel (3,100 ML/d)
        # ~4%. Mulwala Canal supplies Murray Irrigation and drains to the Edward River (Deniliquin, B5080599730); the Main Channel's
        # irrigation drains by Broken Creek back to the Murray at Barmah (B5080602310). Torrumbarry Weir's National Channel takes
        # ~500 GL a year (Goulburn-Murray Water), about 6% of the flow there, to the Torrumbarry irrigation area, outside this system.
        "splits": {"B5080603240": {"B5080599730": 0.13, "B5080602310": 0.04},  # Murray at Lake Mulwala, upstream of Yarrawonga Weir: Ovens already in
                   "B5080603590": {"": 0.06}},  # Murray at Echuca, upstream of Torrumbarry Weir: Goulburn and Campaspe already in
        # Barmah (B5080602660) drains past the Goulburn-Broken system's B5080603740, the Murray stub at the Goulburn mouth, so it
        # joins Echuca's B5080603920 directly (that stub's own runoff arrives through LINKS). The Edward-Wakool tributaries run
        # through two or more unmodelled basins into the Wakool B5080596500, which joins the Murray at Tooleybuc.
        "joins": {"B5080602660": "B5080603920", "B5080597940": "B5080596500", "B5080599730": "B5080596500"},
        # the Edward-Wakool links run over unmapped country to the Wakool
        "keep_links": ("B5080597940", "B5080599730"),
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

# Cross-system links, from HydroBASINS' downstream links where a system's river leaves it. Each system routes in its own
# process; a link adds the routed outflow of its basin ``basin`` in system ``from`` to the outlet node of basin ``into`` in
# system ``to`` (in 3_routing/muskingum.py, and in docs/engine.js for the browser), so the systems run in RUN_ORDER. Basins
# are HydroBASINS level-8 IDs. spill_above_ML_d (optional): only the flow above this goes on; the rest stays in the terminal
# wetland. The value is an indicative placeholder, not a measured spill threshold. A link may skip basins outside every system.
LINKS = (
    # Lachlan River, Great Cumbung Swamp: terminal, dissipating in the swamp; only a flood overtops it into the Murrumbidgee
    # at the Lowbidgee (Murrumbidgee at Oxley / Balranald).
    {"from": "lachlan", "basin": "B5080593360", "to": "murrumbidgee", "into": "B5080594380", "spill_above_ML_d": 10000},
    # Goulburn River at McCoys Bridge / Murchison joins the Murray just above Echuca, upstream of Torrumbarry Weir.
    {"from": "goulburn_broken", "basin": "B5080603790", "to": "murray", "into": "B5080603920"},
    # Murray stub from Barmah past the Goulburn mouth (its own runoff only; the Murray itself comes in through ``joins``).
    {"from": "goulburn_broken", "basin": "B5080603740", "to": "murray", "into": "B5080603920"},
    # Campaspe River at Echuca.
    {"from": "goulburn_broken", "basin": "B5080603970", "to": "murray", "into": "B5080603900"},
    # Lower Darling at Wentworth: the Darling's last basin joins the Murray just below the junction, inside the Murray corridor.
    {"from": "lower_darling", "basin": "B5080591010", "to": "murray", "into": "B5080590940"},
    # Murrumbidgee River at Balranald joins the Murray near Boundary Bend, inside the Murray corridor.
    {"from": "murrumbidgee", "basin": "B5080595630", "to": "murray", "into": "B5080595260"},
)


def run_order():
    """DISPLAY_SYSTEMS ordered so every system comes after the systems that feed it through LINKS."""
    feeders = {s: {l["from"] for l in LINKS if l["to"] == s} for s in DISPLAY_SYSTEMS}
    order = []
    while len(order) < len(DISPLAY_SYSTEMS):
        ready = [s for s in DISPLAY_SYSTEMS if s not in order and feeders[s] <= set(order)]
        if not ready:
            raise ValueError(f"LINKS make a loop through {[s for s in DISPLAY_SYSTEMS if s not in order]}")
        order.append(ready[0])
    return order


RUN_ORDER = run_order()
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
# Ensemble member NARCliM2.0 downloaded each global model's run from (checked against the THREDDS server).
MEMBERS = {"ACCESS-ESM1-5": "r6i1p1f1", "EC-Earth3-Veg": "r1i1p1f1", "MPI-ESM1-2-HR": "r1i1p1f1", "NorESM2-MM": "r1i1p1f1", "UKESM1-0-LL": "r1i1p1f2"}
MEMBER = MEMBERS.get(GLOBAL_MODEL, "r1i1p1f1")
YEAR_END = "1230" if GLOBAL_MODEL == "UKESM1-0-LL" else "1231"  # UKESM1-0-LL runs a 360-day calendar, so its yearly files end on 30 December
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
