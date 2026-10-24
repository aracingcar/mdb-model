# Murrumbidgee model

Daily climate-to-ecology chain for the Murrumbidgee valley, run with `python main.py`.

1. `1_masking`: NARCliM2.0 4 km P and PET (ACCESS-ESM1-5, SSP2-4.5) area-weighted over terrain-derived subcatchments (HydroBASINS).
2. `2_rainfall_runoff`: GR4J per subcatchment (uncalibrated).
3. `3_routing`: Muskingum routing with a calibrated reach loss.
4. `4_ecology`: fish cease-to-flow refuge survival, colonial waterbird breeding trigger, river red gum condition.
5. `5_outputs`: writes results to `data/output/<global_model>/<scenario>/<regional_config>/`.
6. `6_display`: builds the River Pulse page, published at `docs/index.html`.

The MDB Model driving controls live in `6_display/car/`. Their browser-ready files are copied to `docs/car/` by `python 6_display/car/build.py` and whenever the display build runs.

The model is uncalibrated and indicative only. NARCliM subsets are not in the repo; fetch them with `1_masking/download.py`.
Climate inputs now live in `data/input/narclim/<global_model>/<scenario>/<regional_config>/`.
The current dataset is `ACCESS-ESM1-5/ssp245/WRF412R3` (daily, 4 km, 2015–2034).
The other 29 combination directories are empty local placeholders; Git does not preserve empty directories.
Outputs mirror those 30 combination directories, including the local River Pulse HTML and all CSV/GeoPackage results. `docs/index.html` remains the preview of the most recently built combination.
The display's Climate model panel offers only the dataset embedded in the build, with its identity supplied by `1_masking/config.py`.
Other global models require their own source member identifiers before downloading; changing the model name alone is insufficient.
Running `python main.py` rebuilds both the local output page and `docs/index.html`.
Data: NARCliM2.0 (CC BY 4.0), HydroBASINS, OpenStreetMap contributors (ODbL), CEWO MDB valleys (CC BY-SA 4.0).
