# EMBER — HackHarvard 2026 build plan (verified, 3-person team)

**One line:** Ember tells each household in a wildfire exactly when to leave and which road to take, by simulating the whole town's escape first, and updates that plan as residents reply "I can't."

**Tagline:** *Before disaster strikes, find where the evacuation plan breaks.*

How to read this: every technical claim below is marked **[VERIFIED]** (quoted from official docs on 2026-10-16, source in §13), **[DESIGN]** (our own engineering choice, not a doc claim), or **[UNVERIFIED]** (must be confirmed at a workshop or by a 10-minute test before we depend on it). Nothing in this file is a guess presented as fact.

---

## 1. Event facts (verbatim from hhuh.io and the HackHarvard handbook)

| Item | Fact |
|---|---|
| Dates | Oct 16–18, 2026, Harvard, "36 hours", undergraduates only, in person |
| Hacking starts | Fri after the 3–4 PM opening ceremony (site countdown is set to 5:00 PM ET) |
| **Submissions due** | **Sunday 8:00 AM on Devpost** |
| Judging | Sun 9:00–10:30 and 10:30–12:00 "Judging period 1/2", Canopy Hall. Handbook: "Expo judging ... Each team will be assigned a table and judges will come to their tables and ask them about their project." Some teams get panel judging; "Not getting selected for panel judging is NOT an indication of the team's score." |
| Judging criteria | "All projects will be judged based on four criteria. Each category is weighted the same, but a bias in the following listed order will be used to break ties. 1. Innovation, Creativity and Impact 2. Technical Complexity 3. Functionality and Usability 4. Teamwork and Collaboration and Learning" |
| Prize rule | "Prizes are awarded to each person on the team unless otherwise specified." |
| Workshops we must attend | **Fri 4–5 PM Photon workshop**; **Sat 1:30–2:30 SpaceXAI workshop**; **Sat 2:30–3:30 Daytona workshop**; Sat 10–12 sponsor fair |
| Accommodation | "HackHarvard cannot provide overnight accommodations this year." |

Tracks that exist on the site (only four): Reinvent Clinical Trials (Regeneron), Save the Earth (ASUS), Digital Trust (Fintech & Cybersecurity, Brick), Hardware for Good. There is **no** "Code for Care", "Money Moves" or "(De)-Cipher" this year.

---

## 2. The idea in one loop

```
   NASA FIRMS hotspots ──┐
   OSM roads + buildings ─┤
                          ▼
            ┌──────────────────────────┐
            │  ENGINE (our Python)      │  households → vehicles → queue model
            │  fire front cuts roads    │  metrics: exposed, clearance, vulnerable delay
            └────────────┬─────────────┘
                         │ 400 jobs (plan × scenario)
                         ▼
            ┌──────────────────────────┐
            │  DAYTONA sandbox pool     │  robust search: keep the plan whose
            │  (parallel evaluation)    │  WORST 20% of scenarios is best
            └────────────┬─────────────┘
                         │ plan.json (zone timing, routes, contraflow) or "NO STAGING: everyone now"
                         ▼
            ┌──────────────────────────┐      iMessage / voice
            │  RESIDENTS (Photon 2.0)  │◄────────────────────────► resident phone
            │  per-household thread    │◄────────────────────────► volunteer phone
            └────────────┬─────────────┘
                         │ "no car, mom in wheelchair" → structured need → re-plan → pickup assigned
                         ▼
            ┌──────────────────────────┐
            │  MAP (deck.gl)            │  live trips, fire polygon, scatter of runs,
            │  judge-facing dashboard   │  edge inspector, three message threads
            └──────────────────────────┘
```

The engine and planner are deterministic and inspectable. The only LLM job is turning a panicked free-text reply into a structured need (and a structured instruction into a sentence). Every zone, time, route and assignment in any message is computed by the engine.

---

## 3. Track and prize map (what we submit, verbatim briefs, how we earn it)

### 3.1 Grand prize (overall) — the real target
- **What the rubric rewards:** Innovation/Impact first on ties. Past HackHarvard 1st places: a sensor pillow ranking post-op patients for nurses (2025), an eco-scanner with a large AI stack (2024). TreeHacks/HackMIT grand prizes: self-steering LiDAR cane, FPGA GPU, robot-arm wheelchair, pill-authenticity device, "Physical Realities" (thousands of agents + custom engine + A/B scenarios).
- **How Ember matches:** custom engine below the API layer, a problem every judge has seen on the news, a calibration against a real disaster, and the judge changes the outcome with a phone in their hand.

### 3.2 Save the Earth (Sustainability, ASUS) — track anchor
- **Brief (verbatim):** "Create innovative solutions to real-world environmental challenges: rethink how we consume resources, build tools that promote sustainable habits, or find new ways to reduce environmental impact." Prizes: 1st ASUS motherboard, 2nd ZenScreen portable monitor, 3rd ROG keyboard. "Teams on this track can use select ASUS hardware, including desktop and portable monitors."
- **Honest fit:** climate *adaptation*, not mitigation. Say the word "adaptation" out loud. Supporting metric that we already compute: vehicle-hours in gridlock per plan (idling fuel proxy). Pre-season use: counties run Ember to find chokepoints before fire season (planning, not response).
- **Proof artifact:** metrics panel shows vehicle-hours; Devpost text has one paragraph on adaptation.
- **Bonus:** ASUS Content Challenge (prize announced at opening; public post on Instagram/TikTok/LinkedIn/YouTube tagging `@asususa & @hhuh.hackathon` (IG), `@ASUS Education` (LinkedIn), `@asuseducation` (TikTok), `@ASUSUSA` (YouTube); hashtags `#ASUSEducation #hackharvard2026 #agentcomputer`; submit the proof-of-content form). Cost: one 60-second phone video Saturday. Do it.

### 3.3 Best Use of Daytona ($5,000 credits, title sponsor) — structural
- **Brief (verbatim):** "Daytona provides fast, secure sandboxes for running code, built for the era of AI agents. Give an AI agent a safe place to write and run code, spin up isolated development environments on demand, or build tools that execute untrusted code at scale. Daytona must be a meaningful part of how your project works; the most creative and effective use wins."
- **How we use it:** the robust optimizer evaluates hundreds of (plan × scenario) simulations in parallel across a pool of Daytona sandboxes. Without it, the robust objective (worst-20%-of-scenarios) does not exist on one laptop in demo time. See §6.5 for the exact verified API and the tier limits that shape the design.
- **Proof artifact:** live scatter plot filling in as sandboxes return; sandbox count and job throughput on screen; README section "Why Daytona: the optimizer's compute".

### 3.4 Build a Messaging Agent with Photon 2.0 — structural
- **Brief (verbatim):** "Build an agent that lives where people already talk. With Photon 2.0, your agent gets a real phone number and a native presence across iMessage, SMS, RCS, WhatsApp, Telegram, email and phone calls. Build companions that understand social context, multi-agent systems that collaborate with humans, or voice agents that answer and place real calls. Projects must be built on Photon 2.0 and live on at least one Photon channel. Most creative and technically impressive agent wins."
- **Prizes:** Winner $400 cash + $300 credits + fast-track interview; Runner-up $200 + $100; **Best voice agent $300 + $100 "for the best voice agent on a Photon phone number."**
- **How we use it:** per-household iMessage thread with persistent state (address, vehicles, mobility, confirmation, assigned helper, plan version). Resident replies in free text → structured need → re-plan → volunteer gets a pickup request in *their* thread → accept/revoke flows back. Voice (stretch): residents call the Ember number and get a live route from the engine's current closure state.
- **Proof artifact:** two phones on the table; dashboard panel showing both threads side by side; the "revoke" moment.
- **Known constraints that shape the demo:** see §6.6 (opt-in first text, no group chat on shared lines, voice needs an SMS number + SIP vendor).

### 3.5 Make It Legendary (SpaceXAI) — conditional on voice
- **Brief (verbatim):** "Real space data goes in and a legendary project comes out. Your project must be built with Cursor (the more you use it, the better your odds) and must use the Grok Imagine or Voice API. Bonus points for using Grok Bot for project planning and team collaboration." Prize: Cursor mechanical keyboard per member; every entry in a raffle.
- **How we use it, honestly:** (1) *Real space data:* NASA FIRMS VIIRS hotspots seed the ignition and are the ground truth the fire model is scored against at each satellite overpass. (2) *Grok Voice API* is the speech-to-speech brain on the phone line (see §6.8). (3) One teammate builds in Cursor.
- **Rule:** if voice is cut for time, we do **not** bolt on Grok Imagine to qualify. Then we skip this challenge. The FIRMS integration stays regardless because the calibration needs it.

### 3.6 Not submitting, and why
| Challenge | Why not |
|---|---|
| Reinvent Clinical Trials (Regeneron) | Off-topic. |
| Digital Trust (Brick) | Off-topic. |
| Hardware for Good | Brief says "Arduinos, Raspberry Pis, microcontrollers ... build with your hands." Phones don't count. |
| Chalk ($1,500) | Only honest use is wrapping our own evaluation in their evals product. That is the bolt-on we said we won't do. Revisit only if a Chalk mentor shows a 30-minute path at the Sat sponsor fair. |
| Factory Droid SDK ($2,000) | Requires a coding agent doing real work inside the running product. Runtime-generated code in a safety-critical planner is a bad story. |
| Capital One Nessie | No banking in Ember. |

Net: **Overall + Save the Earth + Daytona + Photon (+ Photon voice) + SpaceXAI (if voice ships)**. Four to five submissions, each with a real role.

---

## 4. Essentiality audit (remove it and what breaks)

| Component | Why it is essential | If removed |
|---|---|---|
| OSM road graph + building footprints | Real town, real driveways. The calibration claim is impossible on a synthetic grid. | "SimCity" verdict. |
| FIRMS hotspots | Ignition location and the only observed fire truth to score the front against. Also the SpaceXAI "real space data" requirement. | Fire position is an assumption; no calibration. |
| NIST TN 2252 timestamps | Observed evacuation-order and road-closure times to compare against. | No "we reproduce the closure order" slide. |
| Queue-model engine (ours) | Produces different closure orders under different winds. The technical-complexity score. | A renderer with a story. |
| Fire front that cuts roads | What makes a route deadly over time; defines "exposed vehicles". | Just a traffic sim. |
| Daytona pool | Hundreds of evaluations in demo time → robust objective. | Optimizer degrades to ~10 runs; "robust" claim dies. |
| Robust search + "no staging" rule | The algorithmic contribution; the honesty moment. | "Staged always wins" is circular. |
| Photon threads (resident + volunteer) | The product acts in the real world; human constraints flow back into the plan. Photon's rubric verbatim. | A research tool nobody receives. |
| LLM need extraction | Free text under stress can't be a form. One narrow call. | Residents must type structured commands. |
| deck.gl map + scatter + edge inspector | Judge sees the jam, the search, and proof there is an engine. | Numbers in a terminal. |
| Voice line (stretch) | Elderly residents without smartphones (most Paradise deaths were older residents); Photon voice prize; SpaceXAI eligibility. | Lose two sponsor prizes, keep the core. |

Cut list (deliberately): "type your hometown" loader, commander copilot, Marshall Fire negative control, 3D rendering, Apple Watch/AirPods, Grok Imagine, group chats.

---

## 5. Architecture and contracts

### 5.1 Repo layout (one monorepo, three owned directories)
```
ember/
  contracts/        # JSON schemas + fixture files. Committed in HOUR 1. Everyone builds against fixtures.
    town.schema.json        town.fixture.json
    plan.schema.json        plan.fixture.json
    job.schema.json         metrics.schema.json   metrics.fixture.json
    trajectories.schema.json trajectories.fixture.json
    household.schema.json   need.schema.json      assignment.schema.json
  engine/           # P1. Python. osmnx build, queue model, fire, metrics, Daytona pool, optimizer.
  residents/        # P3. Python FastAPI. DB, Photon, need extraction, assignment state machine, voice.
  web/              # P2. React + deck.gl. Map, trips, fire, scatter, inspector, thread panels.
  data/             # downloaded OSM/FIRMS/NIST extracts (git-lfs or .gitignore + download script)
  docs/             # Devpost text, README, calibration slide
```

### 5.2 Contracts [DESIGN] (freeze by Fri 6 PM; change only by group agreement)
- **town.json:** `nodes[{id, lat, lon}]`, `edges[{id, u, v, length_m, lanes, speed_kph, capacity_vph, jam_density_vpkm, oneway, highway}]`, `households[{id, lat, lon, edge_id, zone, vehicles, size, flags:{no_car, mobility, elderly}}]`, `exits[node_id]`, `zones[{id, name, centroid}]`.
- **plan.json:** `{plan_id, mode:"staged"|"immediate", zone_offsets_s:{zone_id: int}, contraflow_edges:[edge_id], exit_assignment:{zone_id: node_id}}`.
- **job.json:** `{plan, scenario:{wind_deg, wind_mps, ignition:[lat,lon], compliance, extra_closures:[edge_id], seed}}`.
- **metrics.json:** `{exposed_vehicles, clearance_s_95, max_queue_veh, vulnerable_delay_s_mean, vehicle_hours, first_closure_s, closure_order:[[edge_id, t_s]]}`.
- **trajectories.json:** per vehicle `{id, path:[[lon,lat]...], t:[s...] }` with `t` as seconds since sim start (float32-safe; see §6.9).
- **DB (residents):** `households` (mirrors town.households + `phone_handle`, `space_id`, `status`), `needs` (`household_id, kind, text, extracted_json, created_at`), `assignments` (`helper_id, rider_id, status: proposed|accepted|revoked|done, pickup_edge, eta_s`), `plan_versions`, `messages` (every in/out message with `plan_version`).
- **Backend ↔ web:** FastAPI WebSocket `/ws` pushing `{type: "trajectories"|"fire"|"metrics"|"scatter_point"|"thread"|"assignment", payload}`; REST `POST /optimize`, `POST /replan/{household_id}`, `GET /state`.

### 5.3 Engine spec [DESIGN]
- **Graph:** OSMnx `graph_from_place("Paradise, Butte County, California, USA", network_type="drive")` + `add_edge_speeds` + `add_edge_travel_times`. Capacity per edge = `lanes × 1800 veh/h` (standard planning saturation flow; lanes imputed 1 when untagged, 2 for primary/secondary). Jam density = `150 veh/km/lane`.
- **Vehicles:** one per household with `vehicles ≥ 1` (households from building footprints, `building=*` features, residential tags; ~1 household per residential footprint; Paradise ≈ 26k people / ~11k households pre-fire). Departure time = `zone_offset + mobilization delay` (lognormal; parameters tuned once so the *immediate* plan qualitatively matches TN 2252's departure wave; stated as such).
- **Behavior knobs (scenario inputs, never hidden):** compliance `p` (fraction that follow staging; the rest depart at their own mobilization time), refusers `r` (leave only when the front is within 1 km), family-pickup `f` (route via another household first).
- **Queue model:** per-edge point queue with spillback, 10 s ticks. Enter if downstream storage `< jam_density × length × lanes`; traverse at free-flow `travel_time`; exit limited to `capacity × tick`; blocked edges have capacity 0.
- **Routing:** shortest travel-time path to assigned exit at departure; re-route when the next edge is closed or its queue exceeds a threshold (bounded re-routes per vehicle).
- **Fire:** front polygon from an ignition point (FIRMS high-FRP cluster at the first overpass) spreading as a wind-driven ellipse (rate scales with wind speed; length-to-breadth from wind). When the front intersects an edge, the edge closes at that tick. Vehicles on a closed edge at closure = **exposed**. At each satellite overpass time, compare the modeled front with the VIIRS hotspot cloud (centroid error, hotspot coverage).
- **Metrics:** as in `metrics.json`.
- **Plan space:** 8–12 zones (k-means on household coordinates, snapped to road clusters); `zone_offsets_s ∈ {0, 300, ..., 2400}`; contraflow candidates = the 6 highest-flow exit edges (reversal doubles outbound capacity); exit assignment per zone.
- **Robust search:** population of 20 plans × 20 scenarios (wind ±30°, speed ±30%, compliance 0.7–1.0, one random extra closure) = 400 jobs/generation, 3–5 generations, evolutionary (mutate offsets/contraflow/exits). Objective = mean of the worst 20% of `exposed_vehicles` across scenarios, tie-break `clearance_s_95`. The *immediate* plan is always in the population. **If no staged plan beats immediate under the worst-20% objective by a margin, output `mode:"immediate"` and the message "No time to stage: everyone leaves now."**
- **Re-plan on a need (local, sub-second):** recompute that household's route/exit; for a `no_car` need, pick the nearest household with spare seats whose detour to the rider's edge ≤ 4 min and whose pickup time precedes that edge's projected closure; propose; on accept → assignment; on revoke → next candidate or flag `needs_bus`.

Runtime estimate [DESIGN, must measure Fri night]: ~2k edges, ~10k vehicles, 1,080 ticks (3 h) → 2–5 s per run in numpy. If it's 20 s, cut ticks to 20 s and vehicles to 1 per 2 households and say so.

---

## 6. Technology verification (quotes are from official docs; URLs in §13)

### 6.1 OSMnx 2.1.1 [VERIFIED]
- `graph_from_place(query, *, network_type='all', simplify=True, retain_all=False, truncate_by_edge=False, which_result=None, custom_filter=None)`; `graph_from_bbox(bbox, ...)` with bbox "(left, bottom, right, top)". `network_type` includes `"drive"`.
- Edge attributes present only "when present in the data retrieved from OSM": default `useful_tags_way` includes `highway, lanes, maxspeed, oneway, ...`; `length` always present. So **lanes/maxspeed will be missing on many edges**: impute (engine does).
- `add_edge_speeds(G)`: "Add edge speeds (km per hour) to graph as new speed_kph edge attributes." `add_edge_travel_times(G)`: "Add edge travel time (seconds) to graph as new travel_time edge attributes."
- Buildings: `features_from_place(query, tags)`; "tags = {'building': True} would return all buildings in the area."
- `convert.graph_to_gdfs(G, ...)`: "gdf_edges is multi-indexed by (u, v, key)."
- Overpass: `max_query_area_size` default 2.5e9 m² (Paradise bbox ≈ 5.5e8 m² → one query); `overpass_rate_limit=True`; `requests_timeout=180`; `use_cache=True`. Nominatim resolves "Paradise, Butte County, California, USA" to an admin boundary, bbox 39.725–39.802 N, −121.656 to −121.564 E. Note the road network is today's OSM (roads still exist post-fire).

### 6.2 NASA FIRMS [VERIFIED]
- Area API: `/api/area/csv/[MAP_KEY]/[SOURCE]/[AREA_COORDINATES]/[DAY_RANGE]/[DATE]`; AREA = `west,south,east,north`; "DAY_RANGE: 1 .. 5"; "DATE: YYYY-MM-DD - [Optional] If not provided it will return the most recent data"; free MAP_KEY at `/api/map_key`.
- Sources: `MODIS_NRT, MODIS_SP, VIIRS_NOAA20_NRT, VIIRS_NOAA20_SP, VIIRS_NOAA21_NRT, VIIRS_SNPP_NRT, VIIRS_SNPP_SP, LANDSAT_NRT`. Archive availability: "VIIRS_SNPP_SP 2012-01-20" onward. **Camp Fire call:** `/api/area/csv/KEY/VIIRS_SNPP_SP/-121.75,39.65,-121.45,39.85/3/2018-11-08` (documented form; run it Friday to confirm it returns rows).
- Rate limit: "MAP_KEY limit is 5000 transactions / 10-minute interval."
- CSV columns: `latitude, longitude, bright_ti4, scan, track, acq_date, acq_time, satellite, instrument, confidence, version, bright_ti5, frp, daynight`. "FRP depicts the pixel-integrated fire radiative power in MW".
- Resolution/latency: "for VIIRS the pixel is approximately 375 m"; VIIRS passes "nominally at 01:30 and 13:30 local time"; NRT "within 3 hours of a satellite observation".
- **Implication:** a hotspot is "something in this ~375 m square is burning," not a flame outline. Between overpasses our spread model interpolates; say so.

### 6.3 NIST Camp Fire reports [VERIFIED]
- **TN 2135** "A Case Study of the Camp Fire - Fire Progression Timeline" (Feb 2021, doi 10.6028/NIST.TN.2135): "Over 2200 observations about fire spread and behavior were collected"; time-windowed fire maps.
- **TN 2252** "A Case Study of the Camp Fire - Notification, Evacuation, Traffic, and Temporary Refuge Areas (NETTRA)" (July 2023, doi 10.6028/NIST.TN.2252; appendices in TN 2252sup). Quotes we calibrate against: "The ECC issued evacuation orders for all of Paradise at 08:03"; "entire towns of Paradise and Magalia were under evacuation orders by 09:03"; "Traffic backups and road closures on Skyway restricted evacuation to the south by 10:45."; "southbound passage was blocked until 16:30".
- No public GIS/CSV of the 2,600-point database was found; the timestamps live in the PDFs. The 2020 Google Research Paradise SUMO pipeline exists (github.com/google-research/google-research/tree/master/simulation_research) but its Paradise data bucket is **not public** (AccessDenied). We rebuild from OSM; we cite the paper as prior work on the slide.
- **Calibration claim we can defend:** "With the real ignition, the 11/8 wind, and the 08:03 order, our immediate-plan run reproduces the *order* of exit closures and has Skyway impassable southbound within ±X min of 10:45. Inputs that are historical: ignition, wind, order time. Outputs compared: closure order, Skyway time." Never say "we found the jam ourselves."

### 6.4 Engine — our code [DESIGN]
Covered in §5.3. Python 3.12, numpy, networkx/osmnx for build only; the tick loop is pure numpy arrays (no networkx in the hot path).

### 6.5 Daytona Python SDK 0.224.1 [VERIFIED] — and the limits that decide the design
- Install/client: `pip install daytona`; `Daytona()` reads `DAYTONA_API_KEY`; `DaytonaConfig(api_key, api_url="https://app.daytona.io/api", target="us")`; **`AsyncDaytona`** exists (`async with AsyncDaytona() as daytona: sandbox = await daytona.create()`). `connection_pool_maxsize` "Defaults to 250. Set to `None` to remove the limit, which is recommended when running many concurrent long-lived operations".
- Sandbox resources: "Sandboxes have 1 vCPU, 1GB RAM, and 3GiB disk by default. Organizations get a maximum sandbox resource limit of 4 vCPUs, 8GB RAM, and 10GB disk."
- **Tier limits (the key fact):** "Tier 1 | 10 / 10GiB / 30GiB | Email verified"; "Tier 2 | 100 / 200GiB / 300GiB | Credit card linked, $25 top-up"; "Tier 3 | 250 / 500GiB / 2000GiB | $500 top-up". "Resources are shared across all running sandboxes." ⇒ **≈10 concurrent 1-vCPU sandboxes on Tier 1, ≈100 on Tier 2.** Rate limit Tier 1: 300 sandbox creations/min.
- **Networking:** "Tier 1 & Tier 2: Network access is restricted and cannot be overridden at the sandbox level ... Essential services remain reachable" (PyPI, GitHub, app.daytona.io). ⇒ **Sandboxes cannot POST results to our server. Results come back as the API return value.** FIRMS/OSM downloads happen on the laptop, not in sandboxes.
- Snapshots: `Image.debian_slim("3.12").pip_install("numpy").add_local_file(...).add_local_dir(...).workdir(...)`; `daytona.snapshot.create(CreateSnapshotParams(name, image, resources=Resources(cpu=1, memory=1, disk=2)), on_logs=print)`; then `daytona.create(CreateSandboxFromSnapshotParams(snapshot="evac-sim-v1", auto_stop_interval=0, ttl_minutes=360))`. "Declarative images are cached for 24 hours". Use snake_case names (one doc example shows camelCase; the reference is snake_case).
- Stateful execution (keeps the graph in RAM across jobs): `sandbox.code_interpreter.run_code(code, *, context=None, on_stdout=..., timeout=None)`; "By default, code runs in the default shared context which persists variables, imports, and functions across executions." Default timeout 10 min. `ExecutionResult` has `stdout, stderr, error`.
- `process.exec(command, cwd, env, timeout)`: "The default timeout is 10 seconds when not specified" → **always pass `timeout`**. `process.code_run` is stateless ("Each invocation starts from a clean interpreter").
- Files: `sandbox.fs.upload_file(local, remote)`; volumes exist but "Volumes are generally slower" → bake the 20 MB graph into the snapshot.
- Lifecycle: "By default, Daytona sandboxes auto-stop after 15 minutes of inactivity"; `auto_stop_interval=0` disables; `ttl_minutes` as billing backstop; delete when done ("Stopped container sandboxes occupy disk quota until archived"). Fork is VM-only ("Forking is not supported for container sandboxes"); warm pools need support enablement → **we use neither**.
- Pricing: vCPU $0.0504/h, GiB RAM $0.0162/h, storage $0.000108/GiB-h, "All billing is calculated per second", "$200 in free compute included". A 1 vCPU/1 GiB sandbox ≈ $0.07/h → 100 sandboxes × 48 h ≈ $320. Credits are not the bottleneck; **the tier vCPU pool is**.
- GitHub `daytonaio/daytona` README: "This repository is no longer maintained ... moved to a private codebase." Use daytona.io/docs as the authority.

**Architecture decision [DESIGN, grounded in the above]:** pool of N long-lived sandboxes (N = tier vCPU pool), each loads the graph once via `code_interpreter`, then pulls jobs from an asyncio queue and returns one JSON per job; the laptop/backend is the orchestrator. Throughput: Tier 1 → 400 jobs / 10 × ~4 s ≈ **3 min per generation**; Tier 2 → ≈ **20 s**.
**Action Friday night (P1):** link a card and top up $25 to reach Tier 2. At the Sat 2:30 Daytona workshop, ask for a hackathon tier bump and whether sponsor credits count as top-up (**[UNVERIFIED]**). Demo plan if stuck on Tier 1: generations 1–4 precomputed Saturday; generation 5 (or a 100-job slice) runs live on stage, and we say exactly that.

Sketch (API calls above only):
```python
from daytona import AsyncDaytona, DaytonaConfig, CreateSandboxFromSnapshotParams, DaytonaRateLimitError
PRELUDE = "import json,pickle,sys; sys.path.insert(0,'/home/daytona'); from sim import run_job; G=pickle.load(open('/home/daytona/town_graph.pkl','rb'))"
async def worker(sb, jobs, out):
    await sb.code_interpreter.run_code(PRELUDE, timeout=120)
    while (job := await jobs.get()) is not None:
        r = await sb.code_interpreter.run_code(f"print(json.dumps(run_job(G, {json.dumps(job)})))", timeout=60)
        out.put_nowait({"job": job, "error": r.error.value} if r.error else json.loads(r.stdout.strip().splitlines()[-1]))
```

### 6.6 Photon 2.0 [VERIFIED] — and the constraints that shape the demo
- **What it is:** blog "Introducing Photon 2.0" (Oct 15, 2026): "a new iMessage engine, a redesigned dashboard, and a unified API for iMessage, WhatsApp Business, Telegram, SMS, RCS, email, and voice"; "public beta, with $100 in free credit." Docs are split: **Stable = Spectrum** (`spectrum-ts`), **Beta = Photon platform = 2.0** at `https://api.photon.codes/v1`. The hackathon requires 2.0 → use Beta.
- **Clients:** `pip install photonhq-api` (import `photon_api`, Python ≥ 3.11) or `npm install @photon-ai/api`; both 0.5.0, published 2026-10-16 (brand new; fall back to raw HTTPS with `httpx` if the client misbehaves). Auth `Authorization: Bearer pho_sk_...`.
- **Core objects:** Users, Spaces, Messages. Outbound: `POST /users {platform:"imessage", handle:"+1415..."}` → `POST /spaces {platform, participantIds:[agentId, userId]}` → `POST /messages {spaceId, senderId, content:{type:"text", format:"plain", text}}` with an `Idempotency-Key`.
- **iMessage on the free tier = shared line with assignments:** "up to 25 shared iMessage assignments"; `POST /platforms/imessage/assignments {handle}` → `assignedPhoneNumber`; "Only messages from the assigned sender reach this" line. **Opt-in rule:** "a shared line cannot send an unsolicited first message" / sends "only to a peer with an active Assignment who has messaged it since that Assignment." **"A shared assignment supports direct conversations, not group chats."** "Shared lines cannot take calls."
- **Inbound (no public webhook needed):** Socket.IO at `/v1/projects/${projectId}/events/ws`, `subscribe {startSeq}`; events include `message.received`, `message.delivered`, `message.failed`, and "the same parsed public JSON object you receive from a webhook". Alternatives: polling `GET /messages?direction=received` (docs poll every 2 s) or `POST /webhooks/destinations` (needs public HTTPS). get-started: "You do not need a public webhook server or an AI model yet."
- **State:** message history is stored per Space (`GET /messages?spaceId=...`, "eventually consistent"); no cross-channel memory feature ("A User on one platform isn't automatically the same person on another"). Our DB holds the household state.
- **SMS:** `POST /platforms/sms/numbers {countryCode:"US"}` "Buys one US local number"; $2/number/month; "Add a payment method before using paid features." Outbound SMS to arbitrary numbers needs "campaign eligibility" (10DLC) → **we do not use SMS for texts**; iMessage only.
- **Voice:** phone calls "run on an SMS number, not on iMessage"; voice profile `PUT /voice/profiles/{id}/inbound {destinationUri}` points the number at a **SIP** vendor; cookbooks exist for Retell, ElevenLabs, LiveKit, Twilio. Photon provides no STT/TTS/LLM; the vendor runs the conversation. Outbound calls need a payment method. Voice $0.013/min US. Webhook events `call.started/ringing/answered/connected/ended/dtmf.received` exist in the spec.
- **Limits:** Beta rate numbers not published (429 `RATE_LIMITED` + `RateLimit` headers); Stable was 5 req/s/project; "50 new conversations per line per day"; "5,000 outbound messages per server per day"; iMessage Spaces 2–1000 participants (shared lines: direct only).

**Demo design forced by these facts [DESIGN]:**
1. **Testers must text first.** We pre-assign two team iPhones (Resident, Volunteer) and have them text "hi" to their assigned numbers on Friday. On Sunday the judge is handed the Resident phone. Optional: assign the judge's own number (one API call) and they text "hi" (30 s); only if they volunteer it.
2. Resident and Volunteer are two Spaces (possibly two different shared numbers). Fine: the backend coordinates.
3. No group chat. Don't promise one.
4. Voice needs: a bought SMS number ($2, card on file), a SIP vendor, and the Grok bridge (§6.8). That is why voice is a stretch and why SpaceXAI is conditional.
5. Inbound via Socket.IO from the backend; no ngrok needed for texts. (A public URL is still useful for the vendor's voice webhooks; a cheap VM or Cloudflare Tunnel on Friday.)

**Ask at the Fri 4–5 PM Photon workshop [UNVERIFIED]:** does free/hackathon credit cover the SMS number and outbound voice without a card; are `message.received` and `call.*` live for iMessage/voice in beta and what are the exact payload fields; Beta rate limit and max message length; does Beta iMessage fall back to SMS for Android handles; will they lend a dedicated line; which dashboard is canonical (app.beta.photon.codes vs app.photon.codes).

### 6.7 LLM need extraction [DESIGN; standard tool-use]
- One call per inbound message: input = message text + household record; output = JSON `{kind: no_car|mobility|staying|report_closure|question|other, people: n, details, confidence}` via tool-use/structured output. Second call turns `{instruction}` into one sentence in the household's language. Model: Claude Haiku 5.5 (`claude-haiku-5-5`) for speed, or Grok text if we standardize on xAI for voice (one vendor, one key). Guardrail: the model never sees or emits a route; routes are injected by the engine into the instruction JSON before the sentence call. Low confidence → ask one clarifying question, never guess.

### 6.8 Voice path (stretch) [VERIFIED ends, UNVERIFIED join]
- **xAI Grok Voice [VERIFIED]:** "Speech to Speech" at `wss://api.x.ai/v1/realtime?model=grok-voice-latest` (alias of `grok-voice-3.0`); "The Grok Speech to Speech API is compatible with the OpenAI Realtime API."; codecs `audio/pcm|pcmu|pcma|opus`; "define custom function tools with JSON schemas"; telephony: "Connect via SIP, WebSocket, or LiveKit."; demo "A callable phone agent using Twilio." Pricing "$0.08 / min". Separate STT (`/v1/stt`, $0.10/hr) and TTS (`/v1/tts`, $15/1M chars). Billing is prepaid, "minimum $5"; **no free credits documented** → someone preloads $10.
- **Photon side [VERIFIED]:** voice profile inbound `destinationUri` → SIP vendor; LiveKit and Twilio cookbooks exist.
- **The join [UNVERIFIED]:** Photon → SIP → (LiveKit SIP trunk → LiveKit agent → Grok realtime) **or** Photon → SIP → (Twilio SIP domain → Twilio media stream → Grok realtime). Both ends are documented; the middle is the risk. P3 picks one at the Photon workshop (Fri) and SpaceXAI workshop (Sat 1:30) and time-boxes it to 4 hours Saturday afternoon. Tools exposed to the voice agent: `get_route(cross_street)` and `record_need(kind, details)`, both served by our backend; the agent reads the engine's answer aloud and never invents a road.
- Alternative with less glue: use ElevenLabs or Retell as the full voice agent (Photon cookbook exists), with our backend as the tool server. That ships voice for the Photon prize but drops SpaceXAI eligibility.

### 6.9 deck.gl 9.4 + MapLibre [VERIFIED]
- `TripsLayer` (`@deck.gl/geo-layers`): props `currentTime` (default 0), `trailLength` (default 120), `fadeTrail`, `getPath`, `getTimestamps` (one per vertex). **Caveat (verbatim):** "Because timestamps are stored as 32-bit floating numbers, raw unix epoch time can not be used." → our `t` is seconds since sim start (contract §5.2).
- `PolygonLayer` (fire front; "The first ring is the exterior boundary"), `PathLayer` (roads, `widthMinPixels`, `getWidth` ← queue length/colour ← occupancy).
- Basemap without a token: `@deck.gl/maplibre` (new in 9.4, "forked from the former @deck.gl/mapbox module"); React: `import {Map} from 'react-map-gl/maplibre'` + `DeckGL` from `@deck.gl/react`, `mapStyle="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"` (CARTO basemaps allowed "as a non-commercial application"). Older tutorials use `MapboxOverlay`; don't copy them.
- Performance: no TripsLayer-specific benchmark published; general guide: 60 FPS "up to about 1M data items". 10k trips is fine.
- Scatter of optimizer runs: any chart lib (Recharts/Plotly) fed by `scatter_point` WebSocket messages.

### 6.10 Backend [DESIGN]
FastAPI + SQLite (one file, enough for the weekend) or Postgres if P3 prefers; `python-socketio` client for Photon events; WebSocket to the web app; `asyncio` orchestrator for the Daytona pool lives in `engine/` but is called from the backend's `POST /optimize`. Deploy the backend to a small VM Friday night (or run on a laptop + Cloudflare Tunnel) so the laptop isn't a single point of failure and the voice vendor has a public URL.

---

## 7. The 3-minute demo (expo table, judge-driven)

Table setup: laptop on hotspot (not venue Wi-Fi), external monitor (ASUS lends monitors on this track), two iPhones labelled RESIDENT and VOLUNTEER already opted in, a third phone for the voice call, 40-second backup video on a second laptop.

- **0:00** Photo of Paradise's Skyway gridlock. "Fires close escape routes before towns can clear. NIST documented it: orders at 08:03, Skyway restricted by 10:45. 85 people died."
- **0:20** Map: real Paradise, 11k households, ignition from the VIIRS hotspots of Nov 8. Press play on the *immediate* plan. Exits close in order; Skyway turns red. Metrics: exposed vehicles, clearance, vulnerable delay. Click the edge inspector on Skyway: occupancy, outflow, closure ETA. "Historical inputs: ignition, wind, order time. We compare closure order and the Skyway hour."
- **0:55** Press **Find a robust plan**. Scatter fills live as Daytona sandboxes return (sandbox count on screen). Side by side: immediate vs robust. "Best worst-case, not best average. And here is a scenario where it refuses to stage: everyone goes now."
- **1:30** Judge holds RESIDENT. It buzzes: *"[Ember drill] Zone 7: leave in 8 min via Clark Rd. Skyway is closed. Reply if you need help."* Judge types anything, e.g. "no car, my mom's in a wheelchair." Dashboard shows the extracted need *before* anything moves. VOLUNTEER buzzes: *"Your neighbor at 12 Elm needs a ride, you leave in 6 min, pick them up on the way to Clark Rd."* Teammate taps accept; map shows the assignment and feasibility (pickup before closure). Judge: "they can't come." Revoked, next candidate.
- **2:20** (if voice shipped) Teammate calls the Ember number: "I'm on Pentz near the school, smoke ahead." Room hears the live route from the engine's current closures.
- **2:40** One slide: architecture, prior work (NIST, the 2020 Google/Paradise SUMO pipeline, AgentEvac), what's real vs synthetic, the "no staging" case, vehicle-hours saved.

Every message opens with "[Ember drill]" and we never imply official authority.

---

## 8. Team split (3 people, zero overlap, one coding agent each)

| | **P1 — Engine & compute** | **P2 — Map, story, submission** | **P3 — Residents & voice** |
|---|---|---|---|
| Owns | `engine/`, `contracts/*town*,plan,job,metrics,trajectories` | `web/`, `docs/`, Devpost, video, slides | `residents/`, `contracts/household,need,assignment`, phones, Photon, voice |
| Language | Python 3.12, numpy, osmnx, daytona SDK | TypeScript, React, deck.gl 9.4, react-map-gl/maplibre | Python 3.12, FastAPI, httpx/photonhq-api, python-socketio, LLM SDK |
| Agent | Claude Code or Codex | Claude Code or Codex | **Cursor** (SpaceXAI requires "built with Cursor"; keep screenshots/commits as evidence) |
| Workshops | Sat 2:30 Daytona | Sat 10–12 sponsor fair (ASUS content, Chalk 30-min check) | **Fri 4–5 Photon**, Sat 1:30 SpaceXAI |
| Deliverables | town.json builder; queue model; fire; metrics; `run_job`; Daytona snapshot + pool; robust optimizer; calibration numbers | map with trips/fire/paths; edge inspector; scatter; before/after; three thread panels; calibration slide; README; Devpost (≥900 words, ≥8 images, video) | DB; Photon assignments + WS inbound + sends; need extraction; assignment state machine; `POST /replan`; voice (time-boxed); demo phones |

**Non-interference rules**
1. **Fixtures before features.** By Fri 6 PM, `contracts/` has schemas and realistic fixture files (a 200-vehicle trajectory set, a sample plan, sample metrics, three sample threads). P2 renders fixtures; P3 drives the state machine from fixtures; neither waits on P1.
2. **Nobody edits another directory.** Need a contract change? Post it in the team chat, get one 👍, bump the schema version, update the fixture. Three touches per day max.
3. **Integration points are two:** P1→P3 via `run_job`/`optimize` function import, P3→P2 via the `/ws` message types. Integrate at **Sat 11 AM** and **Sat 8 PM**, then freeze.
4. Each person keeps their own `.env`; secrets never in git. Shared keys (Daytona, Photon, FIRMS, xAI) go in a password-manager note.
5. One git branch per person, merge to `main` only at integration points; P2 owns `main` hygiene.

---

## 9. Timeline with gates (Fri 4 PM → Sun 8 AM)

| When | P1 | P2 | P3 | Gate |
|---|---|---|---|---|
| **Thu/Fri before kickoff** | Daytona account, card + $25 → Tier 2; FIRMS MAP_KEY; test the Camp Fire query; `pip install daytona osmnx` | Repo, CI-less monorepo, deck.gl skeleton rendering a static road graph; CARTO basemap | Photon beta account + key; `pip install photonhq-api`; two iPhones opted in; xAI prepaid $10; small VM or tunnel | Accounts live |
| Fri 4–6 PM | Build Paradise `town.json` (roads, buildings→households, zones, exits) | Commit contracts + fixtures; render fixture trips | **Photon workshop**; then assignments + first inbound event seen | **Contracts frozen 6 PM** |
| Fri 6–10 PM | Queue model v0; cars move; metrics | Fire polygon, metrics panel, edge inspector from fixtures | Backend DB; outbound order message to RESIDENT phone works | **GATE A (10 PM): rotate wind 90°, a different exit closes first.** If not, no UI work for P1 until it does. |
| Fri 10 PM–1 AM | Fire front + closures + exposed; `run_job` returns `metrics.json` | Scatter component; before/after split view | Need extraction call; `needs` table; reply sentence | `run_job` on fixtures end-to-end |
| Sat 8–11 AM | Snapshot built; pool of N sandboxes; 100-job fan-out returns | Thread panels; map wired to `/ws` | Assignment state machine; VOLUNTEER thread; accept/revoke | **Integration 1 (11 AM): optimize → scatter → plan → message** |
| Sat 11–1:30 | Robust objective + evolutionary loop; "no staging" rule | Calibration slide draft (closure order vs TN 2252) | `POST /replan`; pickup feasibility vs closure ETA | |
| Sat 1:30–3:30 | **Daytona workshop** (tier/credits) | Sponsor fair; ASUS content video | **SpaceXAI workshop**; pick voice join | |
| Sat 3:30–8 PM | Calibration run vs NIST times + FIRMS overlay; perf tuning | Polish; thread panels show extracted need before action | Voice, time-boxed 4 h; if not working by 7:30, cut | **Integration 2 (8 PM). Feature freeze.** |
| Sat 8 PM–12 AM | Precompute generations; measure throughput; fallback switch (local pool) | Devpost text + 8 screenshots; record backup video; README | Demo phones rehearsal; opt-in check; hotspot test | Full run-through ×3 |
| Sun 12–8 AM | Sleep in shifts; one person awake for the 8 AM submit | | | **Submit by 7:30 AM** |
| Sun 9:00 | Table set; backup laptop; phones charged | | | Expo |

---

## 10. Risks and fallbacks (ordered)

1. **Engine thinner than the story** (Gate A fails). Fallback: coarser ticks, fewer vehicles, but closure *order* must vary with wind; otherwise reframe the demo around the human loop only.
2. **Daytona stuck on Tier 1** (10 sandboxes). Fallback: precompute generations Saturday, run a 100-job slice live, and a local `multiprocessing` pool behind an env flag. Say it plainly on stage.
3. **Photon opt-in or events misbehave in beta.** Fallback: polling `GET /messages?direction=received` every 2 s (documented); team phones pre-opted-in Friday; backup video.
4. **Venue Wi-Fi.** Hotspot from a phone; backend on a VM, not the laptop.
5. **Voice join doesn't work.** Cut by Sat 7:30 PM; keep text; drop SpaceXAI submission rather than bolt on Imagine.
6. **Calibration looks tuned.** State inputs vs outputs explicitly; show the ±X min, not a perfect match.
7. **TripsLayer timestamps** overflow float32 → use seconds since sim start (already in the contract).
8. **`process.exec` 10 s default timeout** kills long jobs → always pass `timeout`; prefer `code_interpreter.run_code`.
9. **Photon Python client is one day old.** Keep a raw-HTTPS `httpx` path ready.

---

## 11. Friday-morning checklist (before you leave for Harvard)
- [ ] Daytona: account, API key, card linked, $25 top-up, confirm "Tier 2" in dashboard; `pip install daytona`; create a throwaway sandbox and run `code_interpreter.run_code("print(1)")`.
- [ ] FIRMS: MAP_KEY; run the Camp Fire area query; save CSV to `data/`.
- [ ] OSMnx: `graph_from_place("Paradise, Butte County, California, USA", network_type="drive")` cached to `data/`.
- [ ] NIST: download TN 2252 + sup PDFs; extract the timestamps into `docs/calibration.md`.
- [ ] Photon: beta account, project, key with `project:read/write, platforms:read/write`; two iPhones assigned and opted in with a first text; Socket.IO connection prints an event.
- [ ] xAI: account, $10 prepaid, a 10-second realtime handshake works (P3).
- [ ] Hosting: small VM or Cloudflare Tunnel for the backend; hotspot tested.
- [ ] Devpost: team registered on the HackHarvard 2026 Devpost as soon as organizers post it.
- [ ] Cursor installed for P3 (SpaceXAI evidence).

---

## 12. Devpost / README checklist (winners' write-ups were ~970 words with ~8 images and a video)
- Opening: NIST quotes (08:03 order, 10:45 Skyway), 85 deaths, the staged-evacuation gap. No "one text caused it."
- Sections: Problem → What Ember does (the loop) → Engine (queue model, fire, metrics) → Robust planning (worst-20%, "no staging" case) → Residents (Photon threads, need extraction, accept/revoke) → Calibration (inputs vs outputs, ±X min) → Prior work (NIST, 2020 Paradise SUMO pipeline, AgentEvac) → What's real vs synthetic → Sustainability (adaptation, vehicle-hours) → Why Daytona / Why Photon / Space data (FIRMS) → Team (who built what, one learning each; the Teamwork criterion is 25% of the score).
- Images: Skyway run, scatter, before/after, edge inspector, both phone threads, FIRMS overlay, architecture.
- Video < 3 min, recorded Saturday night.
- README: run instructions, the contracts, "Where Daytona is used", "Where Photon is used", "Where Grok Voice is used" (if shipped), safety note ("drill only; never implies official authority; no auto-assignment of unwilling helpers").

---

## 13. Sources (official, fetched 2026-10-16)
- HackHarvard: https://hhuh.io/ (tracks in `js/main.js`, challenges and schedule on the page); judging: https://info.hackharvard.io/rules/judging_criteria/
- Daytona: https://www.daytona.io/docs/en/python-sdk · /sandboxes · /limits · /network-limits · /snapshots · /python-sdk/sync/code-interpreter · /python-sdk/sync/process · /python-sdk/async/async-daytona · /declarative-builder · /volumes · /preview · /billing · https://www.daytona.io/pricing · https://pypi.org/project/daytona/
- Photon: https://photon.codes/blog/introducing-photon-2.0 · https://photon.codes/docs/beta/index · /get-started/project · /get-started/imessage · /get-started/voice · /api-client · /websocket/connect · /websocket/events · /plans-and-billing · /billing · cookbooks/voice/{retell,elevenlabs,livekit,twilio} · https://api.photon.codes/openapi.json · hackathon guidelines (Notion, linked from hhuh.io "Guidelines & docs")
- NASA FIRMS: https://firms.modaps.eosdis.nasa.gov/api/area/ · https://firms.modaps.eosdis.nasa.gov/content/academy/data_api/firms_api_use.html · https://www.earthdata.nasa.gov/data/tools/firms/active-fire-data-attributes-modis-viirs · https://www.earthdata.nasa.gov/data/tools/firms/faq
- OSMnx: https://osmnx.readthedocs.io/en/stable/user-reference.html
- deck.gl: https://deck.gl/docs/api-reference/geo-layers/trips-layer · https://deck.gl/docs/developer-guide/base-maps/using-with-maplibre · https://deck.gl/docs/whats-new · https://deck.gl/docs/developer-guide/performance
- NIST: https://doi.org/10.6028/NIST.TN.2135 · https://doi.org/10.6028/NIST.TN.2252 · https://nvlpubs.nist.gov/nistpubs/TechnicalNotes/NIST.TN.2252sup.pdf
- Prior work: arXiv 2002.06198 and https://github.com/google-research/google-research/tree/master/simulation_research ; https://github.com/denoslab/AgentEvac
- xAI: https://docs.x.ai/developers/model-capabilities/audio/voice · https://docs.x.ai/developers/pricing
