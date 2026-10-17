# Anshuman — scenario & story log (`scenarios/`, `docs/DEMO.md`, `docs/QA.md`, Devpost)

(no entries yet — first entry should be `scenarios/allston_flood_v1/scenario.json` v0 with facilities, resources and assisted households drafted from the rendered map)

## 2026-10-16 23:30 · allston_flood_v1 scenario v1 · branch anshuman/scenario-v1 · commit (this PR)
What: the flood scenario the demo runs on. 4 keyframes (60/90/150/180 min) in the Anderson → River St reach: paths only → Soldiers Field Rd + Memorial Dr → Riverside low streets + Western Ave bridge approach + Putnam Ave substation → crest with the River St bridge approach (N Harvard St stays open). Facilities: Cottage Farm CSO (pumping station + wastewater), Putnam Ave substation (down at 7200), Mount Auburn (critical, 9 h backup), outfall MWR201, EMS 14 base, Treehouse shelter. Fleet: 2 vans, 1 accessible van, truck, crew, gen-1 (fits Cottage Farm and the hospital), gen-2 (fits neither). 40 assisted households / 78 known people, 6 mobility, 4 unknown incl. judge #10296 at River St × Memorial Dr, which is on the generator truck's route to Cottage Farm. 3 scripted need reports. assumptions.md + sources.md (MWRA 2024 CSO report numbers, Climate Ready Boston, Cambridge 2017 VA, Sandy).
Files: scenarios/allston_flood_v1/{scenario.json, keyframes.geojson, assumptions.md, sources.md}
Run: uv run --project engine ember validate-scenario scenarios/allston_flood_v1/scenario.json --town contracts/fixtures/town.fixture.json --deadlines   → OK (deadlines 75/135/165 min; 136/1196 edges under water at crest)
Interfaces: consumes scenario v0.1 (D28), town ids. No contract changes.
  - Aryaman: `load_scenario` inlines `keyframes` but keeps `keyframes_file`, so the hazard then has both and fails the schema's `oneOf`. Any scenario using `keyframes_file` fails. Workaround here: keyframes are inline in scenario.json (keyframes.geojson is the same data for geojson.io).
  - Aryaman: validated against `contracts/fixtures/town.fixture.json` because Overpass is still down and I can't build data/town.json. The ids are every-12th households of the seed-7 build, the same ones the scenario fixture uses. Please run validate-scenario against your data/town.json, or share it, before this merges.
  - Generator story: overflow ≈ 9,600 m³ with no generator, 0 if gen-1 is connected by t=9000, ≈100 at t=10800, ≈4,850 at t=12600 (my stand-in integration of the §3.3 formula, not the engine's).
Status: partial. Validated against the fixture town, not yet against data/town.json. Not merged.
Next: Sat 09–12 re-validate on the real town.json and tune keyframes with Aryaman's deadlines → I1 @12:00. DEMO.md v1 after I2 (needs Soham's message copy and Arnav's controls), QA.md at I2/I3, Devpost Sat night.
