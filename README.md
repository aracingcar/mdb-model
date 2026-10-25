# MDB model

Daily climate-to-ecology chain for Murray–Darling Basin surface water SDL resource units, currently the Murrumbidgee (SS15), ACT (SS1), Lachlan (SS16), Lower Darling (SS18), NSW Murray (SS14), Victorian Murray (SS2), Goulburn (SS6) and Broken (SS5), run with `python main.py`.

1. `1_masking`: NARCliM2.0 4 km P and PET (ACCESS-ESM1-5, SSP2-4.5) area-weighted over terrain-derived reaches (HydroBASINS) inside the MDBA SDL unit outlines.
2. `2_rainfall_runoff`: GR4J per basin (uncalibrated).
3. `3_routing`: Muskingum routing with channel rainfall, evaporation, seepage, miscellaneous losses and optional flow splits.
4. `4_ecology`: fish cease-to-flow refuge survival, colonial waterbird breeding trigger, river red gum condition, at each unit's outlet.
5. `5_outputs`: stores geometry and results in `data/results.db` (SQLite, git-ignored), one row per SDL unit, climate run and method pair.
6. `6_display`: builds the River Pulse page, published at `docs/index.html`, with every unit's reaches and SDL boundary on one map.

SDL units that share a river network are modelled together as a river system (`SYSTEMS` in `1_masking/config.py`): the upper Murrumbidgee flows into the ACT and the ACT drains back into SS15, so both are routed as one network, and every place a river crosses a unit border ends a reach. Each basin belongs to the unit holding most of its area. Per system the config sets the main-stem reach count, routing calibration (`loss_regions`, `target_outlet_m3s`; `None` leaves flow uncalibrated) and flow splits (a share of a basin's outflow sent to another basin or out of the river); per unit (`SDL_UNITS`) it sets the ecology thresholds (`None`, or a missing indicator, skips it). `main.py` runs each system in its own process (`SYSTEM=lachlan python main.py` runs one) and then builds the page from the database. Rows from before the SDL outlines, built on the CEWO Murrumbidgee valley, are kept under the key `CEWO-MBG`.

Rivers that leave one system and enter another are joined by `LINKS` in `1_masking/config.py` (from HydroBASINS' downstream links, each annotated with its landmark): the Goulburn, the Murray stub at its mouth and the Campaspe enter the Murray at Echuca, upstream of Torrumbarry Weir; the Murray (at Tooleybuc, with the Edward–Wakool) and the Murrumbidgee (at Balranald, near Boundary Bend) enter the Lower Darling system's Murray reach, upstream of Wentworth; the Lachlan spills into the Murrumbidgee at the Lowbidgee only above `spill_above_ML_d`, otherwise it ends in the Great Cumbung swamp. A link adds the routed outflow of its source basin to the outlet node of the target basin, so systems run in `RUN_ORDER` (a system after those feeding it; a loop is refused), each source's flow is kept in the `link_flows` table of `results.db`, and `docs/engine.js` and the page apply the links the same way. A downstream system fails with a clear message if the upstream system has no stored flow for the run, so run a climate run through `main.py` (all systems, in order) rather than one system alone. `joins` and `keep_links` in a system's config bridge a river that runs through basins outside the system, and keep a main-stem link whose mapped channel has gaps. Offtakes in the Murray are `splits` of indicative shares of the flow: Mulwala Canal 13% (drains to the Edward River) and Yarrawonga Main Channel 4% (drains by Broken Creek to Barmah) at Lake Mulwala, from Goulburn-Murray Water's ~1,900 GL a year (17%) split by offtake capacity, and the National Channel 6% (~500 GL a year, leaves the system) at Torrumbarry; they are not allocation data. Not modelled: Lake Mulwala and the weirs as storages, the Billabong Creek – Edward River network (Yanco Creek's share still leaves the Murrumbidgee system) and the Darling Anabranch, which need NARCliM climate for their basins.

The MDB Model driving controls live in `6_display/car/`. Their browser-ready files are copied to `docs/car/` by `python 6_display/car/build.py` and whenever the display build runs.

The model is uncalibrated and indicative only. The Lachlan has no calibration gauge yet, so its losses use provisional defaults and terminal-river flow remains unvalidated. The Lower Darling carries its own local runoff plus the Murray and Murrumbidgee flowing in (see below), but not the Darling's inflow from the Barwon–Darling and the northern Basin, which is not modelled. The Murray's main terrain network (and so its calibration outlet) is the Barmah reach; the Edward–Wakool and the NSW catchments that drain straight into the Murray (such as the upper Murray) are reaches of their own (`min_network_km2`), and the Snowy releases and regulation are not routed in.

The Victorian pilot adds `vic_murray` (SS2) and `goulburn_broken` (SS6 + SS5), using the same MDBA outlines, HydroBASINS terrain and NARCliM climate sources. Goulburn and Broken route together across their unit boundaries; the Goulburn-Broken passes its outflow into the Murray (see below). Victorian Murray retains secondary networks of at least 500 km², so its selected unit outlet is not the sum of all drainage outlets or the full Murray discharge. Both systems are uncalibrated, with ecology indicators disabled pending appropriate local thresholds. No NSW/Victorian Murray network merger or Basin-wide climate download is included. The default pilot run remains ACCESS-ESM1-5/ssp245/WRF412R5; `run_climates.py` without selectors will request all known runs for the expanded set, so use an explicit selector when testing.

To run only the new systems (after fetching their waterways), use `SYSTEM=vic_murray python main.py` and `SYSTEM=goulburn_broken python main.py`, then `python 6_display/run_display.py`. Validate their stored inputs and routing with `SYSTEM=vic_murray python validate_victoria.py` and `SYSTEM=goulburn_broken python validate_victoria.py`; run `python 6_display/engine_parity.py` after building the display. See `plans/victoria_pilot.md` for validation findings and limitations.

Climate runs are stored once per SDL unit, reduced, in `data/results.db` (`climate` table: unit, reach and basin P/PET series plus the display's 4 km evaporation anomaly field). If a run is not in the database, `main.py` downloads its NARCliM subsets to `data/input/narclim/<system>/<global_model>/<scenario>/<regional_config>/`, reduces them, stores the result and deletes the raw `.nc` files (set `KEEP_RAW=1` to keep them). Choose the run with the `GLOBAL_MODEL`, `SCENARIO` and `REGIONAL_CONFIG` environment variables (defaults `ACCESS-ESM1-5`, `ssp245`, `WRF412R5`). Later runs read straight from the database, so a full run takes seconds.
Inputs fetched by scripts: SDL unit outlines (`python 1_masking/download_sdl_units.py`), OpenStreetMap waterways per system (`SYSTEM=<system> python 3_routing/download_osm_waterways.py`) and display roads (`python 6_display/fetch_roads.py`).
Rainfall-runoff and routing methods are modules in `2_rainfall_runoff/` and `3_routing/`; add a module name to `AVAILABLE_MODELS` in the matching `run_*.py` to offer it.
The display's Climate model panel offers only the dataset embedded in the build, with its identity supplied by `1_masking/config.py`.
Other global models require their own source member identifiers before downloading; changing the model name alone is insufficient.
Running `python main.py` (or `python 6_display/run_display.py` alone) rebuilds `docs/index.html` and `docs/data/`. The page opens on a small demo bundle (`docs/data/demo/`: 2027–2036 only, 2 km terrain, each basin's main channel and full-run evaporation normals, about 8 MB compressed). Zooming in on a river system, or picking one of its units, fetches its detail (`docs/data/demo/detail_<system>.json`: 1 km terrain and its other rivers, about 0.1–0.2 MB compressed), and the page rebuilds the terrain on a 1 km grid, interpolating the systems not yet loaded. Choosing other years or another method reloads it with `?data=full` on the full 2015–2100 series (`docs/data/full/`, 1 km terrain, about 60 MB compressed); the basin forcing the browser engine needs (`docs/data/engine_*.json`) and the roads (`docs/data/roads.json`) are fetched only when needed. Set the demo years with `DEMO_YEARS` in `6_display/run_display.py`. View it with `python -m http.server --directory docs`.
Only the default method pair is precomputed. Choosing another pair in the page re-runs the hydrology in the browser (`docs/engine.js`, in a Web Worker, one river system at a time) and saves the result in IndexedDB. `engine.js` implements the `gr4j` and `muskingum` algorithms; a method that only changes parameters needs no JavaScript, because its `ALGORITHM` and `PARAMS` are shipped to the page. A method with a new algorithm needs a JavaScript implementation in `engine.js` too. Bump `ENGINE_VERSION` in `6_display/template.html` when `engine.js` changes results. `python 6_display/engine_parity.py` checks that the engine matches the Python for every method pair and river system.
Data: NARCliM2.0 (CC BY 4.0), MDBA surface water SDL resource units (CC BY 4.0), HydroBASINS, OpenStreetMap contributors (ODbL). `data/input/catchment/` holds the CEWO MDB valleys (CC BY-SA 4.0) used before the SDL outlines.

### Channel water balance (provisional)

Routing now requires the same daily basin P/PET forcing as rainfall-runoff (`basin_forcing=`).
Each physical node uses its channel length and a **10 m fixed width** to estimate surface area,
capped at its allocated catchment area. The channel footprint is excluded proportionally from
GR4J runoff before delivery is applied, avoiding duplication when direct channel rainfall is added.
Synthetic LOWLAND runoff sources have no modelled channel footprint or channel losses.

Parameters in `3_routing/muskingum.py` (shared by the alternate method) are initial guesses:

- `channel_width_m = 10`: representative fixed width, not surveyed geometry.
- `pet_factor = 1`: evaporation depth = PET times this factor; not an established conversion
  of NARCliM potential evaporation or AWO reference PET to open-water evaporation.
- `seepage_ML_day_km = 0.02`: potential losing-channel seepage per kilometre per day.
- `misc_loss_per_km = 0.001`: residual loss coefficient; fraction removed is
  `1 - exp(-coefficient * length_km)`, about 9.5% over 100 km.

After Muskingum routing, add rainfall (`P_mm * surface_km2` ML/day), then remove evaporation
(`PET_mm * pet_factor * surface_km2` ML/day) and seepage. If their combined demand exceeds
available routed water plus rain, reduce both proportionally. Apply miscellaneous loss to the
remainder, then operate the reservoir release cap, then split downstream flows. Rain can rewet
an otherwise dry channel; no evaporation or seepage occurs without available water.
These are daily outlet adjustments, not an explicit channel depth/storage or aquifer model:
they do not withdraw water from implicit routing storage or reservoir storage. Fixed width,
no floodplain/reservoir evaporation, no groundwater gains or bank-storage returns are limitations.

Where a mean outlet target exists, fit the miscellaneous coefficient in [0, 1]/km at the existing
selected basin outlet nodes after explicit fluxes; other nodes retain the provisional default.
If a target is outside the attainable range, warn and use the corresponding bound. A loss cannot
raise flow to a target. This residual fit can still compensate for runoff/input errors and is not
observational calibration of physical seepage, evaporation or routing parameters. Without a target,
all physical reaches use the default miscellaneous coefficient. Existing runoff delivery remains separate.

`basin_flow.attrs['channel_budget_ML']` contains per-node simulation totals for routed water,
rainfall, actual evaporation, actual seepage, miscellaneous loss and after-flux volumes in ML.
Reservoir storage/release is reported separately in `attrs['storages']`. Budgets are in-memory
diagnostics, not persisted in results.db; each pipeline run prints system totals. For small diagnostic
runs, `route_network(record_budget=True)` returns daily per-node budgets; the main pipeline uses
`record_budget="totals"` to avoid large memory costs. The browser routing API can return daily budgets
with its optional `recordBudget=true` argument. The worker omits these large diagnostics.

Fast full-record routing parity (all systems and method pairs):
`.venv/bin/python 3_routing/check_flux_parity.py` uses the exported network and P/PET.

Validation: `.venv/bin/python -m unittest discover -s 3_routing -p 'test_*.py'` and
`.venv/bin/python 6_display/engine_parity.py`. Re-run `main.py` to refresh stored results and the page.

### Interactive network editing

Open **Routing → Edit** in the display and select a river node. Use **Move node** followed by a map click to move it, **Add tributary** followed by a map click to create an upstream branch, or **Reconnect downstream** followed by a node click to change its destination. New tributaries take the chosen percentage (25% by default) of the selected node's existing catchment area and runoff share, using the same basin rainfall/PET. They do not delineate a new catchment or introduce additional water. Changed connections use the length of their drawn path for the existing routing calculations.

**Join channel** fixes a branch whose runoff enters the river too far downstream: a new junction appears just below the selected node; drag it onto the channel it should join (it snaps to the nearest line). That channel's reach is split at the junction, keeping its length, and the junction takes the share of the reach's local runoff above it. Nodes left below with no inflow are deleted.

Nodes show their role on the river (runoff entry, reach, junction); a basin outlet looks like any other node and its status line names the basin whose flow it reports. **System link** marks where another river system's water enters or leaves. **Delete node** bypasses a node: its runoff share goes to the node below within the same basin, or else joins that node directly as a watershed of its own basin, so every basin's runoff total is kept. Deleting a basin outlet moves that basin's flow reporting to the node below. System links, dams, calibration nodes and diversion endpoints cannot be deleted or reconnected, preserving river-system connections, calibration and operating rules. Connections that create loops are refused. **Undo** reverses edits during the editing session; **Reset network** restores the selected system and can itself be undone.

Edits are saved locally per system and engine-data version. **Apply & recalculate flows** runs all systems in dependency order through the unchanged browser hydrology functions, including their existing calibration procedure. The quick demo first loads the full climate record for correct forcing and model initialisation. The flow series and ecological indicators update; existing mapped river geometry is retained underneath the editable network overlay. **Export draft** downloads the edited graph and catchment shares as JSON. Edits do not overwrite Python inputs, calibration settings, published data or the result cache for the original network.

Run the network editor checks with `node 6_display/network-editor.test.cjs`. These include runoff-share conservation, protected nodes, cycle rejection, joining a channel, deleting basin outlets, persistence, undo and integration calculations with the unchanged hydrology engine.
