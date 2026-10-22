# Murrumbidgee routing data

`gauges.csv` is a small station index assembled from publicly available gauge
listings. It is not a downloaded flow record and its locations do not define
reach topology. It is provided to identify observed series for later
calibration and validation.

## Public sources

- **Bureau of Meteorology Hydrologic Reference Stations (HRS):** daily
  streamflow series, station facts and station details, with coverage through
  February 2026 for most records. The source offers station-level downloads:
  <https://www.bom.gov.au/water/hrs/>. Station details CSV:
  <https://www.bom.gov.au/water/hrs/content/hrs_station_details.csv>.
- **Bureau of Meteorology Water Data Online:** historical discharge/level
  observations and SOS2 service documentation:
  <https://www.bom.gov.au/waterdata/> and
  <https://www.bom.gov.au/waterdata/wiski-web-public/faq.htm>.
- **Australian Hydrological Geospatial Fabric (Geofabric):** connected river
  network and gauging nodes; version 3 services are available through AWDS.
  Geofabric has CC BY 4.0 licensing. Start at
  <https://www.bom.gov.au/water/geofabric/>.
- **WaterNSW WaterInsights / Water Data API:** NSW gauge metadata and
  observations. API subscription is required for programmatic API access:
  <https://api-portal.waternsw.com.au/>. Daily river reports are also public:
  <https://realtimedata.waternsw.com.au/>.
- **NSW DCCEEW modelled without-development flows:** daily modelled ML/day
  series by gauge for historic conditions; useful as a comparison dataset,
  not as observed flow. Dataset landing page:
  <https://www.data.nsw.gov.au/data/dataset/water-modelling-modelled-data-without-development-murrumbidgee-valley>.

The station names and coordinates in `gauges.csv` were taken from the
Murrumbidgee Selected Area Monitoring, Evaluation and Research Plan (2019),
which cites WaterNSW, and from the MDBA/BOM Murrumbidgee basin gauge listing.
See the per-row `source` field. Station codes are agency-specific and should
be cross-checked against Water Data Online before joining timeseries.

## Modeling note

The current GR4J input is a single area-weighted daily series over the whole
Murrumbidgee valley. It cannot supply lateral inflows to separate river
reaches. `3_routing/routing.py` therefore offers a generic reach router and
does not hard-code gauge-to-gauge topology or uncalibrated Muskingum values.
Use network nodes/links from Geofabric and observed records at gauges to build
and calibrate that topology. The Murrumbidgee is regulated, so gauge flows can
also reflect dam releases, diversions, weirs and irrigation operations;
rainfall-runoff output alone will not reproduce all downstream observations.

## Initial model subdivision

`osm_murrumbidgee_waterways.geojson` contains OSM river, stream, canal, drain
and ditch ways clipped to the CEWO Murrumbidgee valley polygon. It was fetched
from Overpass and clipped locally. The source, query, timestamp and license are
recorded in `osm_murrumbidgee_waterways_metadata.json`. OSM data is ©
OpenStreetMap contributors and licensed under ODbL 1.0.

The model creates 12 contiguous regions by cutting the valley polygon across
the mainstem at selected mapped tributary junctions: Bredbo, Gudgenby, Cotter,
Molonglo, Yass, Goodradigbee, Jugiong, Tumut/Muttama, Hillas, Tarcutta/Kyeamba
and Old Man Creek. Regions are ordered upstream to downstream as SC01–SC12.
This makes separate area-weighted P/PET series at each longitudinal river
reach and gives a simple place to add lateral inflows before routing each
reach. These are routing-informed model regions, **not** true terrain-derived
watersheds; do not interpret their polygons as drainage divides.

The output polygons are written to
`data/output/murrumbidgee_subcatchments.gpkg`; one P/PET pair per unit is
written to `data/output/murrumbidgee_subcatchment_forcing.csv`.
