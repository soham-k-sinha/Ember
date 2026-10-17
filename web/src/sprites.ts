/**
 * One procedurally drawn icon atlas for the street-level view (no art files): upright people
 * (white masks, tinted per layer) and top-down vehicles (full colour, pointing north so the
 * IconLayer can rotate them by heading). Drawn once at 2× for crisp edges.
 */

export type IconSpec = { x: number; y: number; width: number; height: number; anchorX?: number; anchorY?: number; mask?: boolean };

export type Atlas = { url: string; mapping: Record<string, IconSpec> };

const P = 2; // pixel ratio
const PERSON_W = 24 * P;
const PERSON_H = 44 * P;
const CAR_W = 28 * P;
const CAR_H = 56 * P;

function person(ctx: CanvasRenderingContext2D, ox: number, oy: number, pose: "stand" | "walk1" | "walk2" | "worker" | "wheel" | "wave") {
  const s = P;
  ctx.save();
  ctx.translate(ox, oy);
  ctx.fillStyle = "#fff";
  ctx.strokeStyle = "#fff";
  ctx.lineCap = "round";
  // head
  ctx.beginPath();
  ctx.arc(12 * s, 7 * s, 4.6 * s, 0, Math.PI * 2);
  ctx.fill();
  if (pose === "worker") {
    // hard hat brim
    ctx.fillRect(6 * s, 3.2 * s, 12 * s, 2.2 * s);
  }
  if (pose === "wheel") {
    // seated torso + wheel
    roundRect(ctx, 8 * s, 12 * s, 9 * s, 13 * s, 3.5 * s);
    ctx.fill();
    ctx.lineWidth = 2.4 * s;
    ctx.beginPath();
    ctx.arc(12 * s, 33 * s, 8 * s, 0, Math.PI * 2);
    ctx.stroke();
    ctx.lineWidth = 3 * s;
    ctx.beginPath();
    ctx.moveTo(15 * s, 24 * s);
    ctx.lineTo(20 * s, 30 * s);
    ctx.stroke();
    ctx.restore();
    return;
  }
  // torso
  roundRect(ctx, 7 * s, 12.5 * s, 10 * s, 15 * s, 4 * s);
  ctx.fill();
  // arms
  ctx.lineWidth = 3 * s;
  ctx.beginPath();
  if (pose === "wave") {
    ctx.moveTo(8 * s, 15 * s); ctx.lineTo(4 * s, 25 * s);
    ctx.moveTo(16 * s, 15 * s); ctx.lineTo(21 * s, 6 * s);
  } else if (pose === "walk1" || pose === "walk2") {
    const k = pose === "walk1" ? 1 : -1;
    ctx.moveTo(8 * s, 15 * s); ctx.lineTo((7 - 4 * k) * s, 25 * s);
    ctx.moveTo(16 * s, 15 * s); ctx.lineTo((17 + 4 * k) * s, 25 * s);
  } else {
    ctx.moveTo(8 * s, 15 * s); ctx.lineTo(6 * s, 26 * s);
    ctx.moveTo(16 * s, 15 * s); ctx.lineTo(18 * s, 26 * s);
  }
  ctx.stroke();
  // legs
  ctx.lineWidth = 3.6 * s;
  ctx.beginPath();
  if (pose === "walk1" || pose === "walk2") {
    const k = pose === "walk1" ? 1 : -1;
    ctx.moveTo(10 * s, 27 * s); ctx.lineTo((10 - 5 * k) * s, 41 * s);
    ctx.moveTo(14 * s, 27 * s); ctx.lineTo((14 + 5 * k) * s, 41 * s);
  } else {
    ctx.moveTo(10 * s, 27 * s); ctx.lineTo(9.5 * s, 41 * s);
    ctx.moveTo(14 * s, 27 * s); ctx.lineTo(14.5 * s, 41 * s);
  }
  ctx.stroke();
  ctx.restore();
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

type CarStyle = { body: string; roof: string; stripe?: string; badge?: "wheel" | "bolt" | "cross" | "tools"; cargo?: string; long?: boolean };

const CARS: Record<string, CarStyle> = {
  van: { body: "#f4f1ea", roof: "#d8d3c8", stripe: "#2f6fb5" },
  accessible_van: { body: "#f4f1ea", roof: "#d8d3c8", stripe: "#2f6fb5", badge: "wheel" },
  truck: { body: "#e0782f", roof: "#b85d1f", cargo: "#6b4a2b", long: true },
  generator: { body: "#f2c230", roof: "#c99a12", cargo: "#3a3a3a", badge: "bolt", long: true },
  crew: { body: "#3f7d5a", roof: "#2c5c41", cargo: "#2a2a2a", badge: "tools" },
};

function car(ctx: CanvasRenderingContext2D, ox: number, oy: number, style: CarStyle) {
  const s = P;
  ctx.save();
  ctx.translate(ox, oy);
  const w = 20 * s;
  const h = (style.long ? 50 : 44) * s;
  const x = (CAR_W - w) / 2;
  const y = (CAR_H - h) / 2;
  // shadow
  ctx.fillStyle = "rgba(0,0,0,0.35)";
  roundRect(ctx, x + 1.5 * s, y + 2.5 * s, w, h, 5 * s);
  ctx.fill();
  // body
  ctx.fillStyle = style.body;
  roundRect(ctx, x, y, w, h, 5 * s);
  ctx.fill();
  ctx.strokeStyle = "rgba(0,0,0,0.55)";
  ctx.lineWidth = 1.2 * s;
  ctx.stroke();
  // windscreen (front = top)
  ctx.fillStyle = "#1d2a36";
  roundRect(ctx, x + 2.5 * s, y + 6 * s, w - 5 * s, 7 * s, 2 * s);
  ctx.fill();
  if (style.cargo) {
    ctx.fillStyle = style.cargo;
    roundRect(ctx, x + 2 * s, y + 17 * s, w - 4 * s, h - 20 * s, 2 * s);
    ctx.fill();
  } else {
    ctx.fillStyle = style.roof;
    roundRect(ctx, x + 2.5 * s, y + 15 * s, w - 5 * s, h - 19 * s, 2.5 * s);
    ctx.fill();
  }
  if (style.stripe) {
    ctx.fillStyle = style.stripe;
    ctx.fillRect(x, y + h * 0.58, w, 3 * s);
  }
  // headlights
  ctx.fillStyle = "#fff6c8";
  ctx.fillRect(x + 2 * s, y + 0.8 * s, 4 * s, 2 * s);
  ctx.fillRect(x + w - 6 * s, y + 0.8 * s, 4 * s, 2 * s);
  // badge
  if (style.badge) {
    const cx = x + w / 2;
    const cy = y + h * 0.4 + (style.cargo ? 8 * s : 0);
    ctx.fillStyle = style.badge === "wheel" ? "#2f6fb5" : "#111";
    ctx.beginPath();
    ctx.arc(cx, cy, 5.5 * s, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#fff";
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 1.4 * s;
    if (style.badge === "wheel") {
      ctx.beginPath(); ctx.arc(cx, cy + 1 * s, 2.8 * s, 0, Math.PI * 2); ctx.stroke();
      ctx.beginPath(); ctx.arc(cx - 0.5 * s, cy - 3 * s, 1 * s, 0, Math.PI * 2); ctx.fill();
    } else if (style.badge === "bolt") {
      ctx.fillStyle = "#f2c230";
      ctx.beginPath();
      ctx.moveTo(cx + 1 * s, cy - 4 * s); ctx.lineTo(cx - 2.5 * s, cy + 0.5 * s); ctx.lineTo(cx, cy + 0.5 * s);
      ctx.lineTo(cx - 1 * s, cy + 4 * s); ctx.lineTo(cx + 2.5 * s, cy - 0.5 * s); ctx.lineTo(cx, cy - 0.5 * s);
      ctx.closePath(); ctx.fill();
    } else {
      ctx.fillRect(cx - 3 * s, cy - 0.8 * s, 6 * s, 1.6 * s);
      ctx.fillRect(cx - 0.8 * s, cy - 3 * s, 1.6 * s, 6 * s);
    }
  }
  ctx.restore();
}

function ring(ctx: CanvasRenderingContext2D, ox: number, oy: number, size: number) {
  ctx.save();
  ctx.translate(ox, oy);
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, "rgba(255,255,255,0.95)");
  g.addColorStop(0.35, "rgba(255,255,255,0.55)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  ctx.restore();
}

let cached: Atlas | null = null;

export function atlas(): Atlas {
  if (cached) return cached;
  const poses = ["stand", "walk1", "walk2", "worker", "wheel", "wave"] as const;
  const cars = Object.keys(CARS);
  const GLOW = 64 * P;
  const width = Math.max(poses.length * PERSON_W, cars.length * CAR_W, GLOW);
  const height = PERSON_H + CAR_H + GLOW;
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  const mapping: Record<string, IconSpec> = {};
  if (ctx) {
    poses.forEach((pose, i) => {
      person(ctx, i * PERSON_W, 0, pose);
      mapping[pose] = { x: i * PERSON_W, y: 0, width: PERSON_W, height: PERSON_H, anchorY: PERSON_H, mask: true };
    });
    cars.forEach((kind, i) => {
      car(ctx, i * CAR_W, PERSON_H, CARS[kind]);
      mapping[kind] = { x: i * CAR_W, y: PERSON_H, width: CAR_W, height: CAR_H, mask: false };
    });
    ring(ctx, 0, PERSON_H + CAR_H, GLOW);
    mapping.glow = { x: 0, y: PERSON_H + CAR_H, width: GLOW, height: GLOW, mask: true };
  }
  cached = { url: canvas.toDataURL("image/png"), mapping };
  return cached;
}

export const VEHICLE_KINDS = Object.keys(CARS);
