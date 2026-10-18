/** Small line icons for the dashboard (24-unit grid, currentColor). */

const PATHS: Record<string, string> = {
  laptop: "M4 6h16v10H4zM2 19h20",
  cloud: "M7 18a4 4 0 0 1-.6-7.95A6 6 0 0 1 18 9a4.5 4.5 0 0 1-.5 9z",
  dots: "M6 16h.01M10 10h.01M14 14h.01M18 7h.01M8 7h.01M17 17h.01",
  check: "M5 12.5l4.5 4.5L19 7",
  phone: "M8 3h8v18H8zM11 18h2",
  signal: "M4 20a12 12 0 0 1 16 0M7 16.5a7.5 7.5 0 0 1 10 0M10.5 13a3 3 0 0 1 3 0M12 7v0",
  read: "M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6zM12 9.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z",
  route: "M6 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM8 17h6a3 3 0 0 0 0-6h-4a3 3 0 0 1 0-6h6",
  send: "M4 12l16-8-6 16-3-7z",
  people: "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM3 20a6 6 0 0 1 12 0M16 11a3 3 0 1 0 0-6M21 20a6 6 0 0 0-4-5.6",
  hospital: "M4 20V6h16v14M12 9v6M9 12h6M2 20h20",
  water: "M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z",
  pin: "M12 21s7-6.2 7-12a7 7 0 0 0-14 0c0 5.8 7 12 7 12zM12 11a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  van: "M3 16V7h11l4 4h3v5M3 16h18M7 18.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM17 18.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z",
};

export function Icon(props: { name: string; size?: number }) {
  const size = props.size ?? 16;
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 24 24" aria-hidden fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d={PATHS[props.name] ?? PATHS.dots} />
    </svg>
  );
}
