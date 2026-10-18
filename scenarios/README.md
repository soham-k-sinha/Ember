# scenarios/

Owned by Anshuman (see `docs/team/anshuman.md`). One folder per scenario:

```
scenarios/allston_flood_v1/
  scenario.json       # validates against contracts/scenario.schema.json (uv run --project engine ember validate-scenario <path>)
  keyframes.geojson   # flood extent rings over the storm timeline
  assumptions.md      # every assumed value: value, why, what would change it
  sources.md          # every real fact: claim, link, date accessed
```

`allston_plume_v1/` is a second hazard on the same engine (D94): a synthetic chemical plume (`hazard.type: "ellipse"`, the engine's `GrowingEllipseHazard`, sampled into keyframes on load). It has only `scenario.json` and `assumptions.md`, because nothing in it is observed data.
