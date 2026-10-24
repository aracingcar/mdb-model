# Victorian local-runoff pilot

Scope agreed on 24 October 2026: add Victorian Murray (SS2), Goulburn (SS6) and Broken (SS5), taking the pilot to eight SDL units. Defer the Basin-wide climate download, the NSW/Victorian Murray merger and all connections between river systems.

## Configuration

- `vic_murray`: SS2, Murray River main stem, secondary drainage networks retained at 500 km².
- `goulburn_broken`: SS6 and SS5 routed together, Goulburn River main stem, secondary networks retained at 500 km². Flow crosses the Broken/Goulburn boundary inside this system.
- Both use 11 requested main-stem reaches, no calibrated losses, no flow splits and no ecology thresholds. Existing lowland delivery assumptions remain in place.
- Only the default climate run is populated for the additions: ACCESS-ESM1-5 / ssp245 / WRF412R5, daily 2015–2100.
- Existing NSW/ACT systems and the historical CEWO-MBG rows retain their results.

## State and boundary findings

The existing MDBA shapefile already contains all three Victorian units, with `StateID=VIC`. It distinguishes Goulburn and Broken as separate SDL units. The same NARCliM SEAus-04 rotated grid, variable units, HydroBASINS source and OSM importer are used; no state-specific file format is introduced. New OSM extracts and elevation tiles are downloaded for the added coverage.

The first annual climate file covers every retained basin: the smallest polygon overlaps about 2.38 cell equivalents in Victorian Murray and 1.10 in Goulburn–Broken. This includes fractional cell coverage.

Victorian Murray has six retained drainage outlets. About 35.37% of its official area is represented as lowland; the existing model sends 5% of its generated runoff directly into the selected unit outlet (B5080603860). This is a coarse modelling assumption, not evidence that those plains actually drain there. The displayed outlet is one selected drainage outlet, not total discharge from the unit and not the Murray's actual discharge. No upstream Murray, Goulburn, NSW or other system inflow is supplied.

Goulburn–Broken has three retained system outlets and two links from Broken-owned basins into Goulburn-owned basins. A single displayed unit outlet does not sum all exits from that unit. Basin ownership is assigned by largest area overlap with an SDL unit, after clipping to the combined system outline; basins are not split at the internal SDL boundary. Consequently, the allocated Goulburn basin area is about 4.10% smaller than its official outline, and Broken's about 14.22% larger. These are allocation differences, not lost or duplicated water. The combined system also drops approximately 101 km² of residual area under the existing 1% per-unit lowland threshold.

All new outputs are uncalibrated local-runoff experiments. State-specific gauge comparisons, reservoir operations, diversions and ecological thresholds have not been added. The existing GR4J parameters and lowland delivery rule have not been validated for Victoria.

## Reproduction

Use the project Python environment. Fetch waterways with `SYSTEM=vic_murray python 3_routing/download_osm_waterways.py` and `SYSTEM=goulburn_broken python 3_routing/download_osm_waterways.py`.

Run each new system using `SYSTEM=vic_murray python main.py` and `SYSTEM=goulburn_broken python main.py`, then build the combined display with `python 6_display/run_display.py`. These system-specific runs do not recompute the existing systems.

Validate with `SYSTEM=vic_murray python validate_victoria.py`, `SYSTEM=goulburn_broken python validate_victoria.py`, and `python 6_display/engine_parity.py`. The validator checks the stored default run, complete daily coverage, finite non-negative forcing and flows, matching basin columns, river ownership, disabled ecology, reproducibility and volume conservation summed across all system outlets. This is implementation validation, not calibration against observations.

`run_climates.py` without selectors requests the entire available climate ensemble for all displayed units. It was not used for this pilot; use an explicit run selector if filling more data later.

## Fixes exposed by the pilot

River-flow shares were rounded to four decimals in stored geometry even though Python used the unrounded values. Goulburn–Broken exposed browser differences of several ML/d. `river_flows.py` now preserves the full share so new engine payloads use the same value as Python. The engine source and hydrological algorithms are unchanged; changed engine data automatically changes the browser cache hash.

Victorian Murray's lowland polygon contained fragments that collapsed during reprojection. `terrain_regions.py` now repairs invalid projected geometry and retains polygon components. Routing identifiers, areas and topology were compared with the previous implementation for all six systems and are unchanged.

## Validation results

Both new systems have all 31,411 daily records for 2015–2100, finite non-negative climate forcing and flows, matching basin/reach columns, valid output polygons, and no ecology values without local thresholds. Recomputed unit outlet flows match the stored values exactly.

| System | Basins | Reaches | River segments | Routed volume difference |
|---|---:|---:|---:|---:|
| Victorian Murray | 19 | 11 | 54 | 0.0506% |
| Goulburn–Broken | 28 | 13 | 63 | 0.0316% |

Volume differences are calculated across every system outlet against delivered local runoff over the full run; both are below the 0.1% tolerance.

Demo and full display payloads include all eight unit boundaries and all six systems, with engine and detail files for both additions.

Browser parity passed all 24 combinations (six systems × two rainfall-runoff methods × two routing methods). The new Victorian systems match exactly at the reported ML/d precision; existing systems remain within 1 ML/d.

Integration backs up the live database to `data/results_before_victoria_pilot_20261024.db`, inserts only the three new units, and verifies all pre-existing rows remain byte-for-byte unchanged.
