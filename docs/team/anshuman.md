# Anshuman — scenario, data, demo and submission (`scenarios/`, `docs/DEMO.md`, `docs/QA.md`, Devpost)

Paste this file into your Claude session (or: "read docs/team/anshuman.md and follow it"). Your lane is JSON, markdown, facts, the demo script and the write-up. No engine code, no UI code, and your Claude will do the heavy lifting on the JSON.

## Context in five lines
- EMBER: disaster coordination for an urban flood in one district around the David Rubenstein Treehouse (the hackathon venue). One shared state, an allocator + simulator that produce one coordinated plan and a personal instruction per household, people in the loop over Photon (iMessage), robustness on Daytona, sustainability = m³ of untreated wastewater kept out of the Charles River. Spec: `docs/TECHNICAL.md` (read §0, §2, §6, §8–§11).
- You own the *scenario* (the concrete flood, facilities, resources and households the whole demo runs on), the *facts* that make it credible, the *demo script*, and the *submission* (Devpost, video, README, ASUS content post). The others cannot demo anything until your `scenario.json` validates.
- The world already exists: `data/town.json` has real roads, buildings, households, hospitals, substations, pumping stations around the venue. You pick ~40 households and the facilities from it, and you write the flood timeline.
- Everything assumed (a pumping station's storage, a hospital's backup hours, how many vans) must be written down with a reason in `assumptions.md`. Everything real (flood layers, MWRA outfalls, Sandy sewage releases, NIST timestamps) goes in `sources.md` with a link. Judges reward honesty here.
- The judge plays a resident whose needs start *unknown*; your scenario must make their reply matter (an accessible vehicle is scarce, and their pickup road closes in the timeline).

## Setup (once)
```bash
git clone https://github.com/soham-k-sinha/Ember.git && cd Ember
git checkout main && git pull && git checkout -b anshuman/<topic>
cd engine && uv sync --extra dev && cd ..
uv run --project engine ember render --plain      # writes data/town.png: open it, that's your map
uv run --project engine ember validate-scenario scenarios/allston_flood_v1/scenario.json   # once Aryaman ships it
```
If `data/town.json` is missing: `uv run --project engine ember build`.

## Tasks, in order (acceptance in brackets)
1. **Pick the district and the facilities** [open `data/town.png` and `data/town.json`; choose a district polygon inside the box that contains the venue, the riverfront roads and at least one bridge; list the real facility candidates from `town.json` `assets` (hospital/clinic, substation, pumping station) with their ids; if a facility type is missing in OSM, place a clearly labeled synthetic one at a plausible node and say so in `assumptions.md`].
2. **Flood timeline** [3–5 keyframes over 3 hours: t=0 dry; t≈60 min river edge paths; t≈90 min Soldiers Field Rd / Storrow / Memorial Dr; t≈150 min low streets and one bridge approach; t=180 crest. Trace polygons as lon/lat rings (geojson.io is fine) informed by public flood layers: FEMA National Flood Hazard Layer via MassGIS, Boston Climate Ready flood maps. Save as `scenarios/allston_flood_v1/keyframes.geojson` and reference them in `scenario.json`].
3. **`scenario.json` v1** against `contracts/scenario.schema.json` [district, hazard keyframes, facilities with parameters (see §2 of TECHNICAL.md for fields), resources: 3 vans (1 accessible, capacity 6), 1 truck, 1 crew, 2 generators (one compatible with the pumping station, one not), fuel; ~40 assisted households from `town.json` ids (mix of sizes; 6 mobility; 4 unknown incl. `judge: true`); reserve rule; deadline margin 900 s. `ember validate-scenario` passes].
4. **`assumptions.md` + `sources.md`** [one row per assumed value: value, why, what would change it; one row per real fact: claim, link, date accessed].
5. **`docs/DEMO.md`** [six beats with timings (see plan doc §7 and TECHNICAL.md §0), who holds which phone, the exact sentence for the Daytona judge ("hundreds of plan evaluations in parallel sandboxes…"), the Photon judge ("two threads, context persists across versions…"), the sustainability judge ("overflow m³ is inside the objective…"), fallbacks if Wi-Fi or Photon fails].
6. **`docs/QA.md`** [a judge-rehearsal checklist: every click and message in the demo, expected result, who fixes it if it fails; run it with the team at each integration window and tick boxes].
7. **Submission** [Devpost text ≥ 900 words with sections from plan doc §12; ≥ 8 screenshots (ask Soham for exports); video < 3 min recorded Saturday night; README polish; ASUS content-challenge post (tags and hashtags in plan doc §3.2) and the proof-of-content form].
8. Saturday afternoon: play the judge against the real system twice; file every confusing message or screen as a line in `docs/QA.md` for its owner.

## Interfaces you consume / produce
Produce: `scenarios/allston_flood_v1/{scenario.json, keyframes.geojson, assumptions.md, sources.md}`, `docs/DEMO.md`, `docs/QA.md`, Devpost text. Consume: `contracts/scenario.schema.json` and `ember validate-scenario` (Aryaman), `data/town.json`.

## Git and logging (non-negotiable)
Branch per feature from `main`; `git add scenarios docs/DEMO.md docs/QA.md docs/log/anshuman.md`; rebase on `origin/main` before every push; PR; self-merge when only your files changed and `validate-scenario` passes. After every feature: append to `docs/log/anshuman.md` (template in `docs/log/README.md`). At session start: read `docs/log/*.md` and `docs/DECISIONS.md`. Never edit `engine/`, `web/`, `residents/`, or `contracts/`.

## Your Claude's opening prompt
```
Read CLAUDE.md, docs/TECHNICAL.md (§0, §2, §6, §8–§11), docs/team/anshuman.md, docs/DECISIONS.md and all of docs/log/*.md. You own scenarios/, docs/DEMO.md, docs/QA.md and the Devpost text only. Work through docs/team/anshuman.md tasks in order. Build scenario.json from real ids in data/town.json and validate it with `uv run --project engine ember validate-scenario`. Every assumed number goes in assumptions.md with a reason; every real fact in sources.md with a link. After each task: append an entry to docs/log/anshuman.md, commit, rebase on origin/main, push, open a PR. Ask in chat if the schema is missing a field you need; never edit contracts/ yourself.
```

## Cut lines
Households → 20. Keyframes → 3. Video → screen recording with voice-over, no editing.
