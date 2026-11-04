"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";

export function LoginForm() {
  const router = useRouter();
  const next = useSearchParams().get("next") || "/court";
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/api/session", { method: "POST", body: JSON.stringify({ passphrase: value }) });
      router.replace(next.startsWith("/") ? next : "/court");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} style={{ display: "grid", gap: 16 }}>
      <label className="field" htmlFor="pass">League passphrase
        <input id="pass" type="password" autoComplete="current-password" value={value}
               onChange={(e) => setValue(e.target.value)} aria-describedby="pass-help pass-err"
               aria-invalid={Boolean(error)} required />
      </label>
      <p id="pass-help" className="slate small" style={{ margin: 0 }}>
        Ask your league commissioner for the passphrase.
      </p>
      {error && <p id="pass-err" className="err" style={{ margin: 0 }} role="alert">{error}</p>}
      <div><button className="btn btn-primary" disabled={busy || !value}>Enter</button></div>
    </form>
  );
}
