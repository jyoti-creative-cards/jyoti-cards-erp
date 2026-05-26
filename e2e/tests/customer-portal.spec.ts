import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";

function loadSeed(): { phone: string; password: string } {
  const p = path.join(__dirname, "..", ".cache", "seed.json");
  const raw = fs.readFileSync(p, "utf8");
  const j = JSON.parse(raw) as { phone: string; password: string };
  return j;
}

test.describe("customer portal", () => {
  test("login and all portal tabs render", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));

    await page.goto("/");
    const { phone, password } = loadSeed();
    await page.getByTestId("portal-phone").fill(phone);
    await page.getByTestId("portal-password").fill(password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByText(/Hello/i)).toBeVisible({ timeout: 20_000 });

    await page.getByTestId("portal-tab-browse").click();
    await expect(page.getByRole("heading", { name: /Find products/i })).toBeVisible();

    await page.getByTestId("portal-tab-bag").click();
    await expect(page.getByRole("heading", { name: "Your bag" })).toBeVisible();

    await page.getByTestId("portal-tab-orders").click();
    await expect(page.getByRole("heading", { name: "Your orders" })).toBeVisible();

    expect(errors, `page errors: ${errors.join("; ")}`).toEqual([]);
  });
});
