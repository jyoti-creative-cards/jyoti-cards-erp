import fs from "fs";
import path from "path";
import type { FullConfig } from "@playwright/test";

function loadAdminKeyFromBackendEnv(): string {
  const envFile = path.join(__dirname, "..", "backend", ".env");
  if (!fs.existsSync(envFile)) return "";
  for (const line of fs.readFileSync(envFile, "utf8").split(/\r?\n/)) {
    const m = line.match(/^ADMIN_API_KEY=(.*)$/);
    if (m) return m[1].trim().replace(/^["']|["']$/g, "");
  }
  return "";
}

async function waitHealth(api: string, maxMs: number): Promise<void> {
  const deadline = Date.now() + maxMs;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`${api.replace(/\/$/, "")}/api/health`);
      if (r.ok) return;
    } catch {
      /* retry */
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`API not reachable: ${api}/api/health`);
}

export default async function globalSetup(_config: FullConfig) {
  const api = (process.env.E2E_API_URL || "http://127.0.0.1:8002").replace(/\/$/, "");
  await waitHealth(api, 90_000);

  let admin = (process.env.ADMIN_API_KEY || "").trim();
  if (!admin) admin = loadAdminKeyFromBackendEnv();
  if (!admin) throw new Error("ADMIN_API_KEY missing (export or put in backend/.env)");

  const phone = `91${String(Math.floor(1e9 + Math.random() * 9e9))}`;
  const password = "e2e-ui-pass-99";
  const cr = await fetch(`${api}/api/v1/customers`, {
    method: "POST",
    headers: { "X-Admin-Key": admin, "Content-Type": "application/json" },
    body: JSON.stringify({
      name: "E2E UI Customer",
      phone,
      password,
    }),
  });
  if (!cr.ok) {
    const t = await cr.text();
    throw new Error(`POST /customers failed ${cr.status}: ${t.slice(0, 400)}`);
  }

  const cacheDir = path.join(__dirname, ".cache");
  fs.mkdirSync(cacheDir, { recursive: true });
  fs.writeFileSync(
    path.join(cacheDir, "seed.json"),
    JSON.stringify({ api, adminKey: admin, phone, password }, null, 2),
    "utf8",
  );
}
