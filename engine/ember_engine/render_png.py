"""Quick PNG render for sanity checks (the real renderer is web/ with deck.gl)."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def render(world, out: Path, hazard=None, t_s: float = 0.0, closed: np.ndarray | None = None,
           occupancy: np.ndarray | None = None, title: str | None = None, show_paths: bool = True):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    fig, ax = plt.subplots(figsize=(14, 14), dpi=160)
    ax.set_facecolor("#0b1020")
    fig.patch.set_facecolor("#0b1020")

    # footways
    if show_paths and world.paths:
        from .geo import local_projector
        to_xy, _ = local_projector(*world.center)
        segs = []
        for p in world.paths:
            g = np.asarray(p["geom"]); x, y = to_xy(g[:, 0], g[:, 1]); segs.append(np.c_[x, y])
        ax.add_collection(LineCollection(segs, colors="#2a3350", linewidths=0.4, zorder=1))

    # roads
    segs, cols, lws = [], [], []
    for e in range(world.n_edges):
        s, c = world.geom_start[e], world.geom_count[e]
        segs.append(np.c_[world.geom_x[s:s + c], world.geom_y[s:s + c]])
        if closed is not None and closed[e]:
            cols.append("#ff3b3b"); lws.append(2.2)
        elif occupancy is not None:
            o = float(np.clip(occupancy[e], 0, 1))
            cols.append((0.3 + 0.7 * o, 0.9 - 0.6 * o, 0.3, 1.0)); lws.append(0.8 + 2.5 * o)
        else:
            cols.append("#8a93b2"); lws.append(0.9)
    ax.add_collection(LineCollection(segs, colors=cols, linewidths=lws, zorder=2))

    # households by zone
    from .geo import local_projector
    to_xy, _ = local_projector(*world.center)
    hx, hy = to_xy(world.hh_lon, world.hh_lat)
    ax.scatter(hx, hy, s=1.2, c=world.hh_zone, cmap="tab10", alpha=0.55, zorder=3, linewidths=0)

    # exits
    ax.scatter(world.node_x[world.exits], world.node_y[world.exits], s=40, marker="^", c="#ffd166", edgecolors="k", zorder=5, label="exits")

    # assets
    markers = {"hospital": ("P", "#ff6b6b"), "clinic": ("P", "#ff9f9f"), "fire_station": ("s", "#ff8c42"), "police": ("s", "#4cc9f0"),
               "substation": ("D", "#f9c74f"), "plant": ("D", "#f9844a"), "pumping_station": ("o", "#4895ef"),
               "water_works": ("o", "#4361ee"), "wastewater_plant": ("o", "#7209b7"), "water_tower": ("o", "#90e0ef"),
               "storage_tank": ("o", "#b5e48c"), "ambulance_station": ("P", "#ff6b6b")}
    for a in world.assets:
        m, c = markers.get(a["type"], ("o", "#ffffff"))
        x, y = to_xy(a["lon"], a["lat"])
        ax.scatter([x], [y], s=90, marker=m, c=c, edgecolors="k", zorder=6)
        ax.annotate(a["name"] or a["type"], (x, y), fontsize=5.5, color="#dddddd", xytext=(4, 4), textcoords="offset points", zorder=7)

    # venue
    vx, vy = to_xy(world.venue["lon"], world.venue["lat"])
    ax.scatter([vx], [vy], s=320, marker="*", c="#ffffff", edgecolors="#ff006e", linewidths=1.5, zorder=8)
    ax.annotate("David Rubenstein Treehouse", (vx, vy), fontsize=8, color="white", xytext=(8, 8), textcoords="offset points", zorder=8, weight="bold")

    # hazard
    if hazard is not None:
        poly = hazard.polygon_at(t_s)
        if poly is not None and not poly.is_empty:
            xs, ys = poly.exterior.xy
            ax.fill(xs, ys, color="#ff4d00", alpha=0.25, zorder=4)
            ax.plot(xs, ys, color="#ff4d00", linewidth=1.2, zorder=4)

    r = world.meta["dist_m"]
    ax.set_xlim(-r, r); ax.set_ylim(-r, r); ax.set_aspect("equal"); ax.axis("off")
    c = world.meta["counts"]
    ax.set_title(title or f"Ember world · {c['edges']} edges · {c['households']} households · {c['assets']} assets · t={t_s:.0f}s",
                 color="white", fontsize=12)
    out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return out
