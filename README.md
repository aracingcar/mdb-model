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
Running `python main.py` rebuilds `docs/index.html` and `docs/data/` (geometry, climate series, results for the default methods, and the basin forcing the browser engine needs). View it with `python -m http.server --directory docs`.
Only the default method pair is precomputed. Choosing another pair in the page re-runs the hydrology in the browser (`docs/engine.js`, in a Web Worker) and saves the result in IndexedDB. `engine.js` implements the `gr4j` and `muskingum` algorithms; a method that only changes parameters needs no JavaScript, because its `ALGORITHM` and `PARAMS` are shipped to the page. A method with a new algorithm needs a JavaScript implementation in `engine.js` too. Bump `ENGINE_VERSION` in `6_display/template.html` when `engine.js` changes results. `python 6_display/engine_parity.py` checks that the engine matches the Python for every method pair.
Data: NARCliM2.0 (CC BY 4.0), HydroBASINS, OpenStreetMap contributors (ODbL), CEWO MDB valleys (CC BY-SA 4.0).
