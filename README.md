# Murrumbidgee model

Daily climate-to-ecology chain for the Murrumbidgee valley, run with `python main.py`.

1. `1_masking`: NARCliM2.0 4 km P and PET (ACCESS-ESM1-5, SSP2-4.5) area-weighted over terrain-derived subcatchments (HydroBASINS).
2. `2_rainfall_runoff`: GR4J per subcatchment (uncalibrated).
3. `3_routing`: Muskingum routing with a calibrated reach loss.
4. `4_ecology`: fish cease-to-flow refuge survival, colonial waterbird breeding trigger, river red gum condition.
5. `5_outputs`: writes everything to `data/output/`.
6. `6_display`: builds the River Pulse page, published at `docs/index.html`.

The MDB Model driving controls live in `6_display/car/`. Their browser-ready files are copied to `docs/car/` by `python 6_display/car/build.py` and whenever the display build runs.

The model is uncalibrated and indicative only. NARCliM subsets are not in the repo; fetch them with `1_masking/download.py`.
Data: NARCliM2.0 (CC BY 4.0), HydroBASINS, OpenStreetMap contributors (ODbL), CEWO MDB valleys (CC BY-SA 4.0).
