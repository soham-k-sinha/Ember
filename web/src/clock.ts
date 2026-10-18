import { useEffect, useState } from "react";

/** The simulation clock lives outside React so a running clock re-renders only what subscribes to it. */
export type Clock = { get: () => number; set: (t: number) => void; subscribe: (listener: () => void) => () => void };

export function createClock(): Clock {
  let t = 0;
  const listeners = new Set<() => void>();
  return {
    get: () => t,
    set: (next) => {
      if (next === t) return;
      t = next;
      for (const listener of listeners) listener();
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

/** The clock as React state, re-rendering at most every `ms` milliseconds (0: on every change). */
export function useClock(clock: Clock, ms = 0): number {
  const [t, setT] = useState(clock.get);
  useEffect(() => {
    let timer = 0;
    const flush = () => {
      timer = 0;
      setT(clock.get());
    };
    setT(clock.get());
    const stop = clock.subscribe(() => {
      if (ms === 0) flush();
      else if (!timer) timer = window.setTimeout(flush, ms);
    });
    return () => {
      stop();
      window.clearTimeout(timer);
    };
  }, [clock, ms]);
  return t;
}
