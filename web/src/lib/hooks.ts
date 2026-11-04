"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { api, ApiError } from "./api";

type Loaded<T> = { key: string | null; data: T | null; error: ApiError | null };

/** GET a JSON path. Loading is derived from whether the latest request has answered,
 *  so no state is set synchronously inside the effect. */
export function useApi<T>(path: string | null) {
  const [nonce, setNonce] = useState(0);
  const key = path ? `${path}#${nonce}` : null;
  const [state, setState] = useState<Loaded<T>>({ key: null, data: null, error: null });
  useEffect(() => {
    if (!path || !key) return;
    let gone = false;
    api<T>(path)
      .then((data) => { if (!gone) setState({ key, data, error: null }); })
      .catch((e) => { if (!gone) setState({ key, data: null, error: e instanceof ApiError ? e : new ApiError(0, String(e)) }); });
    return () => { gone = true; };
  }, [path, key]);
  const fresh = state.key === key;
  return {
    data: fresh ? state.data : null,
    error: fresh ? state.error : null,
    loading: key !== null && !fresh,
    reload: useCallback(() => setNonce((n) => n + 1), []),
  };
}

const MOTION = "(prefers-reduced-motion: reduce)";

export function useReducedMotion(): boolean {
  return useSyncExternalStore(
    (on) => { const m = matchMedia(MOTION); m.addEventListener("change", on); return () => m.removeEventListener("change", on); },
    () => matchMedia(MOTION).matches,
    () => true, // server: assume reduced, so nothing animates before hydration
  );
}

// Theme: the boot script in layout.tsx sets data-theme before paint; this mirrors it.
const THEME_EVENT = "dd-theme";

export function useTheme(): [string, () => void] {
  const theme = useSyncExternalStore(
    (on) => { window.addEventListener(THEME_EVENT, on); return () => window.removeEventListener(THEME_EVENT, on); },
    () => document.documentElement.dataset.theme ?? "light",
    () => "light",
  );
  const flip = useCallback(() => {
    const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem("dd-theme", t); } catch { /* private mode */ }
    window.dispatchEvent(new Event(THEME_EVENT));
  }, []);
  return [theme, flip];
}
