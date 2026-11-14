import { expect, test } from "@playwright/test";

// End-to-end checks of the demo path against live data sources.

test.beforeEach(async ({ request }) => {
  await request.put("/api/meds", { data: { meds: ["simvastatin", "warfarin"] } });
});

test("grapefruit juice barcode meets simvastatin at CYP3A4", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("scan-0025000051753").click();
  await expect(page.getByTestId("product-title")).toContainText(/grapefruit/i);
  const graph = page.getByTestId("graph");
  await expect(graph).toContainText("CYP3A4");
  await expect(graph).toContainText("simvastatin");
  await expect(page.getByTestId("interaction").first()).toContainText(/avoid/i);
  await page.screenshot({ path: "test-results/grapefruit.png", fullPage: true });
});

test("kale and spinach salad meets warfarin at VKORC1", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("scan-0826520107322").click();
  await expect(page.getByTestId("graph")).toContainText("VKORC1");
  await expect(page.getByTestId("graph")).toContainText("warfarin");
  await page.screenshot({ path: "test-results/salad.png", fullPage: true });
});

test("recalled ceiling fan barcode is flagged from CPSC", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("scan-840059614922").click();
  await expect(page.getByTestId("recalled")).toBeVisible();
  await expect(page.locator(".recall").first()).toContainText("CPSC");
  await page.screenshot({ path: "test-results/recall.png", fullPage: true });
});

test("recalled syrup barcode is flagged from FDA", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("scan-810123980659").click();
  await expect(page.getByTestId("recalled")).toBeVisible();
  await expect(page.locator(".recall").first()).toContainText("FDA food");
});

test("typed food with no interaction says so without claiming safety", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Barcode or name").fill("plain rice");
  await page.getByRole("button", { name: "Check" }).click();
  await expect(page.getByTestId("no-interaction")).toBeVisible();
  await expect(page.getByTestId("no-recall")).toContainText("not a guarantee");
});

test("a mistyped barcode is rejected with a reason", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Barcode or name").fill("12345");
  await page.getByRole("button", { name: "Check" }).click();
  await expect(page.locator(".banner.danger")).toContainText(/not a product barcode/i);
});

test("medicines can be added and removed", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "+ phenelzine" }).click();
  await expect(page.locator(".chip.drug", { hasText: "phenelzine" })).toBeVisible();
  await page.getByLabel("Remove phenelzine").click();
  await expect(page.locator(".chip.drug", { hasText: "phenelzine" })).toHaveCount(0);
});

test("near me shows state recalls and illness signals", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Near me" }).click();
  await expect(page.getByTestId("signal").first()).toBeVisible();
  await expect(page.locator(".recall").first()).toBeVisible();
  await page.screenshot({ path: "test-results/near-me.png", fullPage: true });
});

test("protein design tab loads a 3D structure and an honest design brief", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Protein design" }).click();
  await expect(page.getByTestId("design-limit")).toContainText("not connected");
  await page.getByLabel("Gene symbol").fill("CYP3A4");
  await page.getByRole("button", { name: "Load structure" }).click();
  await expect(page.getByTestId("structure-name")).toContainText("Cytochrome P450 3A4");
  await expect(page.getByTestId("protein3d").locator("canvas")).toBeVisible();
  await expect(page.getByTestId("brief")).toContainText("P08684");
  await page.waitForTimeout(800);
  await page.screenshot({ path: "test-results/design.png", fullPage: true });
});

test("an interaction links through to the protein in 3D", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("scan-0025000051753").click();
  await page.getByTestId("interaction").first().getByText("Evidence").click();
  await page.getByRole("button", { name: "see where simvastatin meets CYP3A4 in 3D" }).click();
  await expect(page.getByTestId("structure-name")).toContainText("Cytochrome P450 3A4");
  // No co-crystal of simvastatin in CYP3A4 is curated, so the app says so and points at HMGCR.
  await expect(page.getByTestId("no-bound")).toContainText("No experimental structure");
  await page.getByRole("button", { name: "open HMGCR" }).click();
  await expect(page.getByTestId("bound")).toContainText("HMG-CoA reductase with simvastatin");
});

test("kale salad leads to warfarin bound in VKORC1, drawn with py2Dmol", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("scan-0826520107322").click();
  const card = page.getByTestId("interaction").filter({ hasText: "VKORC1" }).first();
  await card.getByText("Evidence").click();
  await card.getByRole("button", { name: "see where warfarin meets VKORC1 in 3D" }).click();
  await expect(page.getByTestId("bound")).toContainText("VKOR) with warfarin");
  const frame = page.frameLocator('iframe[title*="bound to VKORC1"]');
  await expect(frame.locator("canvas").first()).toBeVisible();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: "test-results/bound.png", fullPage: true });
});
