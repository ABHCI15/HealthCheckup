import { test } from "@playwright/test";

// Records the demo walk-through as a video: npx playwright test -c record/playwright.record.config.js
test("demo walk-through", async ({ page, request }) => {
  await request.put("/api/meds", { data: { meds: [] } });
  const pause = (ms) => page.waitForTimeout(ms);
  await page.goto("/");
  await pause(1500);
  await page.getByRole("button", { name: "+ simvastatin" }).click();
  await pause(700);
  await page.getByRole("button", { name: "+ warfarin" }).click();
  await pause(1200);

  await page.getByTestId("scan-0025000051753").click();
  await page.getByTestId("graph").waitFor();
  await pause(3500);
  await page.getByTestId("interaction").first().scrollIntoViewIfNeeded();
  await pause(3000);

  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
  await page.getByTestId("scan-0826520107322").click();
  await page.getByTestId("graph").waitFor();
  await pause(4000);

  await page.getByTestId("scan-840059614922").click();
  await page.getByTestId("recalled").waitFor();
  await pause(4000);

  await page.getByTestId("scan-0025000051753").click();
  await page.getByTestId("interaction").first().getByText("Evidence").click();
  await pause(1500);
  await page.getByRole("button", { name: "view in 3D and open design brief" }).first().click();
  await page.getByTestId("structure-name").waitFor();
  await pause(7000);

  await page.getByRole("button", { name: "Near me" }).click();
  await page.getByTestId("signal").first().waitFor();
  await pause(3500);
  await request.put("/api/meds", { data: { meds: ["simvastatin", "warfarin"] } });
});
