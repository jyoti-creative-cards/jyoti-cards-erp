/**
 * ERP API calls.
 *
 * When `NEXT_PUBLIC_USE_ERP_PROXY=1`, requests go to `/erp-api/...` (Next rewrites → FastAPI).
 * Otherwise use `NEXT_PUBLIC_API_URL` (full origin, no `/api` suffix).
 */
export function apiUrl(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  const useProxy = (process.env.NEXT_PUBLIC_USE_ERP_PROXY || "1") === "1";
  if (useProxy) {
    return `/erp-api${p}`;
  }
  return `${directApiOrigin()}${p}`;
}

export function directApiOrigin(): string {
  let b =
    process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ||
    "http://127.0.0.1:8000";
  if (b.endsWith("/api")) {
    b = b.slice(0, -4);
  }
  return b;
}

/** @deprecated use apiUrl */
export function apiBase(): string {
  const useProxy = (process.env.NEXT_PUBLIC_USE_ERP_PROXY || "1") === "1";
  return useProxy ? "" : directApiOrigin();
}

/** Server Components need an absolute URL; browser can use relative `/erp-api`. */
function absoluteFetchUrl(path: string): string {
  const u = apiUrl(path);
  if (u.startsWith("http")) return u;
  const site =
    process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") ||
    "http://127.0.0.1:3000";
  return `${site}${u}`;
}

export async function apiGet<T>(path: string): Promise<T> {
  const url = absoluteFetchUrl(path);
  const res = await fetch(url, {
    cache: "no-store",
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || res.statusText);
  }
  return res.json() as Promise<T>;
}
