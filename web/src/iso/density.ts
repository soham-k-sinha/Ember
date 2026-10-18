/** Decorative crowd only: preserve the overview, spend spare frame time on close-up density. */
export const BASE_STROLLERS = 1200;
export const MAX_STROLLERS = 3200;
const MIN_STROLLERS = 100;

export type CrowdView = { x0: number; y0: number; x1: number; y1: number };

export function figureScale(figureHeight: number, cameraScale: number): number {
  return Math.max(1, 9.5 / (figureHeight * cameraScale));
}

export function populationAtZoom(scale: number): number {
  // the whole district reads as busy from afar; close up, spend the frame budget on density
  const share = Math.max(0.4, Math.min(1, (scale - 0.5) / 1.5));
  const extra = Math.max(0, Math.min(1, (scale - 1.2) / 0.8));
  return Math.min(MAX_STROLLERS, Math.round(BASE_STROLLERS * (share + 1.7 * extra)));
}

/** Include heads and a small motion margin, including oversized figures at overview scale. */
export function inCrowdView(x: number, y: number, view: CrowdView, height: number, halfWidth: number): boolean {
  return x + halfWidth + 4 >= view.x0 && x - halfWidth - 4 <= view.x1 &&
    y + 4 >= view.y0 && y - height - 4 <= view.y1;
}

export class CrowdBudget {
  limit = BASE_STROLLERS;
  frameMs = 1000 / 60;
  private slowMs = 0;
  private spareMs = 0;
  private longFrame = false;

  sample(elapsedMs: number, requested: number): number {
    // Background tabs, debugger stops and initial loading are not sustained frame pressure.
    if (!Number.isFinite(elapsedMs) || elapsedMs <= 0) {
      this.slowMs = this.spareMs = 0;
      return Math.min(requested, this.limit);
    }
    if (elapsedMs > 250) {
      if (!this.longFrame) {
        this.longFrame = true;
        this.slowMs = this.spareMs = 0;
        return Math.min(requested, this.limit);
      }
      // Repeated very slow frames are overload, rather than a one-off tab suspension.
      elapsedMs = 250;
    } else this.longFrame = false;
    this.frameMs += (elapsedMs - this.frameMs) * 0.1;
    this.slowMs = this.frameMs > 22 ? this.slowMs + elapsedMs : 0;
    this.spareMs = this.frameMs < 18 && requested > this.limit ? this.spareMs + elapsedMs : 0;
    if (this.slowMs >= 500) {
      this.limit = Math.max(MIN_STROLLERS, Math.floor(Math.min(requested, this.limit) * 0.8));
      this.slowMs = this.spareMs = 0;
    } else if (this.spareMs >= 2000) {
      this.limit = Math.min(MAX_STROLLERS, this.limit + 175);
      this.spareMs = 0;
    }
    return Math.min(requested, this.limit);
  }
}
