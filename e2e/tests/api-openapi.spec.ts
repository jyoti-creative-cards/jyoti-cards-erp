import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";

function apiBase(): string {
  const p = path.join(__dirname, "..", ".cache", "seed.json");
  const raw = fs.readFileSync(p, "utf8");
  return (JSON.parse(raw) as { api: string }).api.replace(/\/$/, "");
}

const REQUIRED_PATH_PREFIXES = [
  "/api/v1/customers",
  "/api/v1/vendors",
  "/api/v1/catalog",
  "/api/v1/shop",
  "/api/v1/customer-orders",
  "/api/v1/purchase-orders",
  "/api/v1/inventory",
  "/api/v1/accounting",
  "/api/v1/auth",
];

test("openapi lists core v1 paths", async ({ request }) => {
  const api = apiBase();
  const r = await request.get(`${api}/openapi.json`);
  expect(r.ok(), await r.text()).toBeTruthy();
  const doc = (await r.json()) as { paths?: Record<string, unknown> };
  const paths = Object.keys(doc.paths || {});
  for (const prefix of REQUIRED_PATH_PREFIXES) {
    const hit = paths.some((p) => p.startsWith(prefix));
    expect(hit, `missing OpenAPI path prefix ${prefix}`).toBe(true);
  }
});
