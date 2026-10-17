# allston_flood_v1 — sources

Real facts the scenario and the pitch rely on. One row per claim: the claim, where it comes from, when we accessed it. Anything not here is in `assumptions.md`.

## Map and facilities (OpenStreetMap via `ember build`)

| Claim | Source | Accessed |
|---|---|---|
| Roads, bridges and the Treehouse footprint (way 1338781017, 20 Western Ave) | OpenStreetMap through OSMnx; venue pin in `docs/DECISIONS.md` D13; address from https://rubensteintreehouse.harvard.edu | 2026-10-16 |
| Cottage Farm Combined Sewer Overflow Facility exists at the BU Bridge, on the Charles | OSM way/29585603 (`town.json` asset 0) | 2026-10-16 |
| Putnam Avenue Substation (Cambridge Riverside) | OSM way/382345594 (`town.json` asset 7) | 2026-10-16 |
| Mount Auburn Hospital | OSM way/589640526 (`town.json` asset 8) | 2026-10-16 |
| Boston EMS Station 14 (Allston) | OSM node/10180871934 (`town.json` asset 5) | 2026-10-16 |
| `town.json` assets came from the osmnx-cache fallback, so some assets may be missing | `docs/DECISIONS.md` D26 | 2026-10-16 |

## Wastewater (the sustainability metric)

| Claim | Source | Accessed |
|---|---|---|
| MWRA's permitted CSO outfalls on the Lower Charles are MWR010, MWR018, MWR019, MWR020, MWR201 (Cottage Farm CSO Treatment Facility) and MWR023 | MWRA, *2024 Annual CSO Discharge Report* (first report under the 2024 Charles River variance), Table 2-1. https://www.mwra.com/media/file/2024-cso-annual-report | 2026-10-16 |
| Cottage Farm (MWR201) discharged 5 times in 2024, 43.00 MG in total; the largest was 21.33 MG on 2024-01-10 (Allston gauge: 13.0 h, 2.71 in, peak 0.80 in/h) | Same report, Table 2-2 | 2026-10-16 |
| In 2024, MWR018/019/020 each discharged twice (0.47, 0.25, 0.28 MG), on 2024-01-10 and 2024-06-26 (a 5-year, 1-hour intensity of 1.43 in/h at Ward St) | Same report, Table 2-2 and §2.1 | 2026-10-16 |
| CSO activations must be publicly notified within 2 hours, with volumes estimated within 5 business days (314 CMR 16.00) | Same report, §2.2 | 2026-10-16 |
| Average annual Charles River Basin CSO volume is down about 99.3% from 1988 | MWRA joint press release, *Charles River Basin Combined Sewer Overflow Control*. https://www.mwra.com/node/6538 (search-result summary; confirm on the page before quoting on stage) | 2026-10-16 |
| Hurricane Sandy (2012) sent ~11 billion gallons of untreated and partially treated sewage into waterways, mostly in NY and NJ and mostly because storm surge flooded treatment plants | Climate Central, *Sewage Overflows From Hurricane Sandy* (2013-04-30). https://www.climatecentral.org/news/11-billion-gallons-of-sewage-overflow-from-hurricane-sandy-15924 | 2026-10-16 |

## Flood exposure (what the keyframes are shaped by)

| Claim | Source | Accessed |
|---|---|---|
| Allston/Brighton are among the "Charles River neighborhoods" expected to be exposed to flooding if the Charles River Dam is overtopped or flanked | Climate Ready Boston, *Focus Areas: Charles River Neighborhoods* (2016). https://www.boston.gov/sites/default/files/document-file-12-2016/climate_ready_boston_digital_focus_areas-charles_river_neighborhoods.pdf | 2026-10-16 |
| Low-lying parts of Cambridge Riverside can flood when high Charles River tailwater backs up the stormwater pipes; Charles-linked low areas face rising risk after 2030 | City of Cambridge, *Sea Level Rise and Storm Surge Vulnerability Assessment* (2017-04-26). https://www.cambridgema.gov/-/media/Files/CDD/Climate/vulnerabilityassessment/newdocumentsapril2017/sealevelriseandstormsurgevulnerabilityassessment_20170426.pdf | 2026-10-16 |
| FEMA's National Flood Hazard Layer for Massachusetts is distributed by MassGIS | MassGIS, *FEMA National Flood Hazard Layer*. https://www.mass.gov/info-details/massgis-data-fema-national-flood-hazard-layer | 2026-10-16 |
| The New Charles River Dam pumps basin water to the harbor with six diesel-driven pumps (~3.7 million gal/min combined); the pumps handle rain-driven flooding, not a surge that flanks the dam | Wikipedia, *Charles River Dam*. https://en.wikipedia.org/wiki/Charles_River_Dam | 2026-10-16 |

The keyframe polygons themselves are **not** traced from these layers: they are synthetic extents drawn on the OSM road network inside the areas these sources mark as exposed. `assumptions.md` says so per keyframe.

## The generic "warning → road closure" story (prior work, not this scenario)

| Claim | Source | Accessed |
|---|---|---|
| Camp Fire, Paradise CA: evacuation orders for all of Paradise at 08:03; "Traffic backups and road closures on Skyway restricted evacuation to the south by 10:45" | NIST TN 2252 (2023), doi:10.6028/NIST.TN.2252 (quotes verified in `docs/EMBER-hackharvard-2026-plan.md` §6.3) | 2026-10-16 |
