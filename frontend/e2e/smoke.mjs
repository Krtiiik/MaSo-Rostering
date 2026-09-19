// Playwright driver for the rostering web app (FastAPI + Vite/React).
// Lives in frontend/e2e/ (not the skill dir) so Node's ESM resolver finds
// `playwright` in frontend/node_modules -- see SKILL.md "ESM resolution
// gotcha" for why a driver outside frontend/ fails with ERR_MODULE_NOT_FOUND.
//
// Usage (from frontend/):
//   npm run e2e:smoke -- [path/to/raw-response.xlsx]
//   node e2e/smoke.mjs [path/to/raw-response.xlsx]
//
// With no xlsx path, only checks that the app shell loads. With a path,
// uploads it via the Upload tab, waits for the parsed-helpers table, and
// exercises one unresolved-friend row (match + dismiss) if any exist.
//
// Screenshots land next to this script in ./screenshots/.

import { chromium } from "playwright";
import path from "node:path";
import { fileURLToPath } from "node:url";
import fs from "node:fs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SHOT_DIR = path.join(HERE, "screenshots");
fs.mkdirSync(SHOT_DIR, { recursive: true });

const BASE_URL = process.env.ROSTERING_FRONTEND_URL || "http://localhost:5173/";
const xlsxPath = process.argv[2] ? path.resolve(process.argv[2]) : null;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
const errors = [];
page.on("console", (msg) => {
  if (msg.type() === "error") errors.push(msg.text());
});
page.on("pageerror", (err) => errors.push(String(err)));

await page.goto(BASE_URL);
await page.waitForSelector('input[type="file"]');
await page.screenshot({ path: path.join(SHOT_DIR, "01-app-loaded.png"), fullPage: true });
console.log("app shell loaded ok");

if (xlsxPath) {
  if (!fs.existsSync(xlsxPath)) {
    console.error(`xlsx not found: ${xlsxPath}`);
    await browser.close();
    process.exit(1);
  }

  await page.setInputFiles('input[type="file"]', xlsxPath);
  await page.waitForSelector("table.helpers-table", { timeout: 30000 });
  await page.screenshot({ path: path.join(SHOT_DIR, "02-helpers-table.png"), fullPage: true });

  const helperRows = await page.locator("table.helpers-table tbody tr").count();
  console.log(`helpers table rendered: ${helperRows} rows`);

  const unresolvedChip = page.locator(".friend-chip.unresolved").first();
  const unresolvedBefore = await page.locator(".friend-chip.unresolved").count();
  console.log(`unresolved friend chips: ${unresolvedBefore}`);

  if (unresolvedBefore > 0) {
    await unresolvedChip.scrollIntoViewIfNeeded();
    const select = unresolvedChip.locator("select");
    const value = await select.locator("option").nth(1).getAttribute("value");
    await select.selectOption(value);
    await page.waitForTimeout(800);
    const afterResolve = await page.locator(".friend-chip.unresolved").count();
    console.log(`after resolving one: ${afterResolve} unresolved remain (expected ${unresolvedBefore - 1})`);

    const nextChip = page.locator(".friend-chip.unresolved").first();
    if (await nextChip.count()) {
      await nextChip.locator("button", { hasText: "Not attending" }).click();
      await page.waitForTimeout(800);
      const afterDismiss = await page.locator(".friend-chip.unresolved").count();
      console.log(`after dismissing one more: ${afterDismiss} unresolved remain`);
    }
    await page.screenshot({ path: path.join(SHOT_DIR, "03-after-friend-actions.png"), fullPage: true });
  }
}

console.log("console errors:", errors.length ? errors : "none");
await browser.close();
process.exit(errors.length ? 1 : 0);
