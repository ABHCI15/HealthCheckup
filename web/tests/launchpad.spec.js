import { expect, test } from "@playwright/test";

test("launchpad page loads, links to the app, and labels future work", async ({ page }) => {
  await page.goto("/launchpad.html");
  await expect(page.getByRole("heading", { name: "HealthCheckup" }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Open the app" }).first()).toHaveAttribute("href", "/");
  await expect(page.getByText("Not built yet").first()).toBeVisible();
  await page.screenshot({ path: "test-results/launchpad.png", fullPage: true });
  await page.setViewportSize({ width: 380, height: 800 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
