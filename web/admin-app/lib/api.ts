/**
 * Browser: same-origin `/api/proxy/*` → BACKEND_URL (next.config.ts).
 * Override: `?api=http://127.0.0.1:8002` on the page URL.
 */

import type { AuthState } from "./types";

export function getApiBase(): string {
  if (typeof window !== "undefined") {
    const q = new URLSearchParams(window.location.search).get("api");
    if (q) return q.trim().replace(/\/$/, "");
    return "";
  }
  return (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8002").replace(/\/$/, "");
}

export function apiUrl(path: string): string {
  const p = path.startsWith("/") ? path.slice(1) : path;
  const segment = `v1/${p}`;
  const base = getApiBase();
  if (base === "") {
    return `/api/proxy/${segment}`;
  }
  return `${base}/api/${segment}`;
}

/** Build auth headers from AuthState. */
export function authHeaders(auth: AuthState): Record<string, string> {
  if (auth.type === "admin_key") return { "X-Admin-Key": auth.key };
  if (auth.type === "staff") return { "Authorization": `Bearer ${auth.token}` };
  return {};
}

/** Combined content-type + auth headers for JSON POST/PATCH. */
export function jsonAuthHeaders(auth: AuthState): Record<string, string> {
  return { "Content-Type": "application/json", ...authHeaders(auth) };
}

const NETWORK_DETAIL =
  "Cannot reach the API. Start backend on port 8002; set BACKEND_URL in admin-app env if not local.";

/** Same as fetch; on failure returns 503 JSON so callers can use r.ok / formatApiError. */
export async function fetchApi(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch {
    const target = getApiBase() || "/api/proxy (Next.js → BACKEND_URL)";
    const body = JSON.stringify({ detail: `${NETWORK_DETAIL} Target: ${target}` });
    return new Response(body, {
      status: 503,
      statusText: "Network Error",
      headers: { "Content-Type": "application/json" },
    });
  }
}

export function formatApiError(data: unknown): string {
  if (!data || typeof data !== "object") return "Request failed";
  const d = data as { detail?: unknown };
  if (typeof d.detail === "string") return d.detail;
  if (Array.isArray(d.detail)) return JSON.stringify(d.detail);
  return JSON.stringify(data);
}
