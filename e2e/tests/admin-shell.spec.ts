import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";

const NAV: { id: string; title: RegExp }[] = [
  { id: "dashboard", title: /Executive dashboard/i },
  { id: "accounting", title: /Financial accounting/i },
  { id: "billing", title: /Billing & documents/i },
  { id: "order_mgmt", title: /Orders & procurement/i },
  { id: "inventory", title: /Inventory & stock/i },
  { id: "customers", title: /Customers/i },
  { id: "vendors", title: /Vendors/i },
  { id: "catalog", title: /Product catalog/i },
  { id: "masterdata", title: /Master data & compliance/i },
];

function loadSeed(): { adminKey: string } {
  const p = path.join(__dirname, "..", ".cache", "seed.json");
  const raw = fs.readFileSync(p, "utf8");
  const j = JSON.parse(raw) as { adminKey: string };
  if (!j.adminKey) throw new Error("seed missing adminKey");
  return j;
}

test.describe("admin ERP shell", () => {
  test("every sidebar screen loads with admin key", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));

    await page.goto("/");
    const { adminKey } = loadSeed();
    await page.getByTestId("admin-api-key").fill(adminKey);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/Executive dashboard/i);

    for (const { id, title } of NAV) {
      await page.getByTestId(`nav-${id}`).click();
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(title);
      await page.waitForTimeout(150);
    }

    expect(errors, `page errors: ${errors.join("; ")}`).toEqual([]);
  });
});
