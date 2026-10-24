# Murrumbidgee model

Daily climate-to-ecology chain for the Murrumbidgee valley, run with `python main.py`.

1. `1_masking`: NARCliM2.0 4 km P and PET (ACCESS-ESM1-5, SSP2-4.5) area-weighted over terrain-derived subcatchments (HydroBASINS).
2. `2_rainfall_runoff`: GR4J per subcatchment (uncalibrated).
3. `3_routing`: Muskingum routing with a calibrated reach loss.
4. `4_ecology`: fish cease-to-flow refuge survival, colonial waterbird breeding trigger, river red gum condition.
5. `5_outputs`: stores geometry and results in `data/results.db` (SQLite, git-ignored), one row per climate run and method pair.
6. `6_display`: builds the River Pulse page, published at `docs/index.html`.

The MDB Model driving controls live in `6_display/car/`. Their browser-ready files are copied to `docs/car/` by `python 6_display/car/build.py` and whenever the display build runs.

The model is uncalibrated and indicative only.

Climate runs are stored once, reduced, in `data/results.db` (`climate` table: valley, subcatchment and basin P/PET series plus the display's 4 km evaporation anomaly field). If a run is not in the database, `main.py` downloads its NARCliM subsets to `data/input/narclim/<global_model>/<scenario>/<regional_config>/`, reduces them, stores the result and deletes the raw `.nc` files (set `KEEP_RAW=1` to keep them). Choose the run with the `GLOBAL_MODEL`, `SCENARIO` and `REGIONAL_CONFIG` environment variables (defaults `ACCESS-ESM1-5`, `ssp245`, `WRF412R5`). Later runs read straight from the database, so a full run takes seconds.
Rainfall-runoff and routing methods are modules in `2_rainfall_runoff/` and `3_routing/`; add a module name to `AVAILABLE_MODELS` in the matching `run_*.py` to offer it.
The display's Climate model panel offers only the dataset embedded in the build, with its identity supplied by `1_masking/config.py`.
Other global models require their own source member identifiers before downloading; changing the model name alone is insufficient.
Running `python main.py` rebuilds `docs/index.html`.
Data: NARCliM2.0 (CC BY 4.0), HydroBASINS, OpenStreetMap contributors (ODbL), CEWO MDB valleys (CC BY-SA 4.0).
