# Handoff: steps 3 and 4 of the Basin-scale plan

> Scope update (24 October 2026): Basin-wide downloads and inter-system connections are deferred. The current task is a local-runoff Victorian pilot: Victorian Murray (SS2), Goulburn (SS6) and Broken (SS5). See `plans/victoria_pilot.md`. The remainder below records the earlier Basin-scale proposal, not the current implementation scope.

Read `README.md` first. The model runs daily NARCliM2.0 climate through GR4J and Muskingum routing for MDBA surface
water SDL resource units, stores everything in `data/results.db` keyed by SDL unit, and publishes the River Pulse
page in `docs/` (GitHub Pages, from `main`). Today it has 5 units in 4 river systems (`SYSTEMS` in
`1_masking/config.py`): murrumbidgee (SS15 + SS1, the ACT), lachlan (SS16), lower_darling (SS18), nsw_murray (SS14).
The goal is all 29 units. Steps 1 and 2 (the small demo bundle and per-system detail on the page) are done.

## Ground rules from the owner

- Never overwrite stored results without a backup. Rows keyed `CEWO-MBG` (the old CEWO-outline Murrumbidgee runs)
  must stay untouched.
- Everything stored or published stays keyed by SDL unit (`sdl_unit` column in every `results.db` table).
- Push to `main` (which redeploys the website) only when the owner asks. Push with
  `git -c http.postBuffer=524288000 push`, because the data files are large.
- Another session may be running `run_climates.py`, which spawns `main.py` per climate run and imports whatever
  code is on disk. Work in a scratch copy or a worktree, test against a copy of `results.db`, and copy the changes in
  at once (see "How to work safely" below).
- Keep the code style: short docstrings, comments only where the why isn't obvious, settings in `config.py`.

## How the pipeline runs today

- `main.py` without `SYSTEM` spawns `main.py` once per system in `DISPLAY_SYSTEMS`, with `SYSTEM=<id>` set. Config
  values are module-level per process: `SYSTEM`, `UNITS`, `NARCLIM_DIR`, `WATERWAYS_FILE`, `MAINSTEM` and so on.
  After all systems finish, it builds the page (`6_display/run_display.py`) for the default run.
- `1_masking/run_masking.py: run_masking()` runs these steps:
  1. `terrain_regions(units, HYBAS_FILE, n, min_network_km2)` returns `(subcatchments, basins)` for the system.
  2. For each unit, `load_climate(unit, RUN_KEY, its subcatchments, its basins)`.
  3. If any unit is missing, `_reduce_climate()` runs:
     - `download()` fetches 172 yearly files (`pr` and `evspsblpot`, 2015–2100) for the system's bounding box into
       `data/input/narclim/<system>/<model>/<scenario>/<config>/`.
     - `load_narclim()` opens them (it also shifts `rlon` into the half-turned frame; see `ROTATED_POLE_CRS` in
       config).
     - It computes, per unit, `areal_average` (the unit mean) and `unit_averages` for reaches and basins, plus
       `evap_anomaly_grids` (the display's 4 km evaporation anomaly), then `save_climate(unit, ...)`.
     - It refuses to store all-NaN series, then deletes the raw files.
- `3_routing/muskingum.py: route()` routes the whole system network (`routing.route_network`, which supports splits)
  and calibrates one loss over the last `loss_regions` main-stem reaches to `target_outlet_m3s`. It returns
  `unit_flow` (`{unit: flow at the unit's outlet basin}`), `reach_flow`, `basin_flow`, `rivers` and `river_flow`.
- `docs/engine.js` is the browser twin of rainfall-runoff, routing and ecology, run per system from
  `docs/data/engine_<system>_<run>.json`. `python 6_display/engine_parity.py` must pass for every system and method
  pair after any change to routing. Bump `ENGINE_VERSION` in `6_display/template.html` when `engine.js` changes
  results.

## Step 3: one Basin-wide climate download per run

**Why.** Each climate run currently downloads and reduces once per system: 4 downloads of 172 files now, and about
15 at 29 units. One Basin-wide window per run, reduced for every unit in one pass, removes the repeated downloads
and keeps all units on the same grid window.

**What to build:**

1. **A Basin download.** It writes to `data/input/narclim/basin/<model>/<scenario>/<config>/`. The window covers the
   union of every unit in `SYSTEMS`, not just `DISPLAY_SYSTEMS`, so adding units later doesn't need a re-download.
   Alternatively use the whole MDB bounding box (lon 138.57–152.49, lat −37.68 to −24.59) plus `BBOX_MARGIN`. The
   NARCliM SEAus-04 domain (lon 134.3–160.9, lat −40.2 to −22.5) covers it. Reuse `download.index_box`, `url` and
   `_fetch` with a bounds argument instead of `load_catchment()`.
2. **A reduction step that loops over systems inside one process.** Right now system settings are module-level and
   depend on the `SYSTEM` environment variable. Add accessors such as `config.system(sid)` and
   `config.narclim_dir(...)`, and make `terrain_regions` calls, `waterways_file` and similar take the system
   explicitly. Keep the existing module constants working for the per-system `main.py` processes.
3. **A run-level pre-step in `main.py`'s parent branch, before spawning the systems.** For the run, find every unit
   whose climate row is missing, or whose columns don't match its current reaches and basins (the same check
   `load_climate` does). If any are missing: download the Basin window once, reduce for all missing units, store
   each unit's row, then delete the raw files. The per-system processes then always find their climate in the
   database. Keep the "no empty series" guard.
4. **Memory: don't load the whole window.** The current code loads a system's full 86-year series into memory
   (about 2 GB for one system's PET; see the comment in `evap_grid.py`). The Basin window is roughly 7 times larger,
   about 14 GB per variable, so process it one year file at a time:
   - `unit_averages` is a matrix product per time step. Build each unit's cell-weight matrix once, run it over each
     year's array and concatenate. `areal_average` can use the same weights.
   - `evap_anomaly_grids` needs a rolling 30-day sum across year boundaries (carry the last 29 days into the next
     year), a day-of-year normal over the whole run (accumulate sums and counts in a first pass), and the anomaly
     stored every 15 days (a second pass over the files, or keep only the 15-day samples and the rolling state).
5. **Delete `data/input/narclim/<system>/…`** as a download location once nothing uses it, and update
   `run_climates.py` and the README. `run_climates.py` keeps its role: one `main.py` per climate run.

**How to check it:**
- For the default run (`ACCESS-ESM1-5/ssp245/WRF412R5`), reduce from the Basin window into a scratch copy of
  `results.db`, then compare each unit's stored frames and evaporation grid with the current rows. The values should
  match to rounding, because the cells and outlines are the same; only the window offset changes.
- Run `python main.py` against the scratch copy, then `engine_parity.py`.
- Time one full Basin download and report its size and duration.

## Step 4: pass flow between river systems

**Why.** Each system currently models local runoff only. The Murray, the Lower Darling, and eventually the whole
Basin depend on water arriving from upstream systems.

**What the HydroBASINS links show today.** I followed each system's outlet down `NEXT_DOWN` until it hits a basin in
another modelled system's network:
- **lachlan → murrumbidgee** (basin 5080594380). In reality the Lachlan ends in the Great Cumbung Swamp and only
  reaches the Murrumbidgee in big floods. Keep it terminal (`inflows` off), or add it as a split with a small
  fraction.
- **murrumbidgee → lower_darling** (basin 5080591050, near Wentworth). Between Balranald and Wentworth this path runs
  down the Murray channel's own basins, which belong to no modelled network.
- **nsw_murray → lower_darling** (5080591050), the same way.
- **lower_darling →** leaves the modelled area (on to SA).

**The key gap: the Murray channel is in nobody's network.** The channel is the NSW–Victoria border, so its HydroBASINS
basins sit mostly outside SS14 (`nsw_murray` reaches only cover NSW tributaries and the Edward–Wakool). Routing
upstream flow "into the NSW Murray" therefore has no channel to travel down. The clean fix is a single `murray` river
system that combines:
- the NSW Murray (SS14)
- the Victorian Murray (SS2)
- the SA Murray (SS11)
- the Lower Darling, if you want the confluence inside one network

With that, the channel basins fall inside one system. Agree this with the owner before building it. It overlaps step
5 (adding units) and changes the existing lower_darling and nsw_murray results.

**What to build:**

1. **Config.** Per system add `"inflows": [{"from": "<system>", "to": "auto" | "B<hybas id>"}]`. `"auto"` means:
   follow `NEXT_DOWN` from the upstream system's outlet basin (the first basin with `next_id == ""`) until it reaches
   a basin in this system's network. If none is reached, fail loudly.
2. **Order.** Topologically sort systems by `inflows` and refuse cycles. `main.py` must spawn systems in that order
   (not `DISPLAY_SYSTEMS` order), and `run_climates.py` keeps calling `main.py` per run.
3. **Python routing.** `route()` takes `inflows`: `{target basin: series in m³/s}`, added to that basin's lateral
   inflow before routing. Add it after `delivery`, which applies only to local runoff, and before calibration. The
   upstream series is the upstream system's flow at its outlet basin: `unit_flow` of the unit owning that basin,
   loaded from `results.db` for the same run and method pair.
   - Calibration: Murrumbidgee is calibrated at Balranald, its own outlet, so it is unaffected. A downstream system's
     calibration target must now include upstream water.
4. **Stored results depend on upstream results.** When an upstream system is rerun, rerun everything downstream of
   it. The simplest rule: `main.py` always runs the full chain for a run.
5. **Browser engine.** Each system's engine file gets
   `"inflows": [{"from": "<system>", "fromBasin": "B…", "to": "B…"}]`. In `template.html`, `recalc()` already runs
   systems one after another; make it go in topological order and pass each upstream `basinFlow[fromBasin]` into the
   next system's run. `engine.js run()` then accepts inflow arrays and adds them to `lateral` for the target basin. In
   `engine.js` flows are in ML/d after routing but m³/s inside the router, so convert carefully. Make
   `engine_parity.py` run systems in the same order, feeding upstream outflows, and keep parity within 1 ML/d.
6. **Display.** Nothing changes structurally, but the receiving reaches will show much larger flows. The demo
   bundle's `maxQ` (full-run peak flow for the colour scale) is computed in `run_display.py` and picks this up.

**How to check it:**
- **Mass balance:** the downstream outlet mean should equal its local-only mean plus the upstream outlet mean
  (routed), within the existing routing start-up error of about 0.1%.
- **Parity:** passes for all systems and method pairs.
- **Murrumbidgee unchanged:** its results stay identical (it has no inflows).

## How to work safely

- Copy the repo code (not `data/`) to a scratch folder, symlink `data/input` into it, copy `data/results.db` beside
  it, and test there.
- When copying files back, check that the live `results.db` hasn't been modified since your copy. If another
  session's job writes in the meantime, merge your rows (`INSERT OR REPLACE` from the scratch database for the units
  you produced) rather than replacing the file.
- Back up `data/results.db` before any migration (`data/*.db` is git-ignored).
- Keep the old per-system raw-file paths readable until no running job uses them.
