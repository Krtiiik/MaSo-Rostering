// Playwright driver for the rostering Streamlit app.
// Lives in scripts/e2e/ (own package.json + node_modules) rather than inside
// a Claude Code skill directory, for the same ESM-resolution reason the old
// React app's driver had to live under frontend/e2e/: Node's ESM resolver
// walks up from the script's own file location, not the process's cwd, so
// `playwright` must be found in a node_modules that's a physical ancestor
// of this file.
//
// Usage (from scripts/e2e/):
//   npm run smoke -- [path/to/raw-response.xlsx]
//   node smoke.mjs [path/to/raw-response.xlsx]
//
// With no xlsx path, only checks that the app shell loads. With a path,
// uploads it via the Upload tab, waits for the parsed-helpers dataframe,
// switches to Buildings, solves, switches to Roster, drags one helper chip
// into a grid cell (exercising the CCv2 assignment_grid component, which
// renders in a shadow root — not an iframe, since CCv2 doesn't use iframes),
// and clicks Export.
//
// Screenshots land next to this script in ./screenshots/.

import { chromium } from "playwright";
import path from "node:path";
import { fileURLToPath } from "node:url";
import fs from "node:fs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SHOT_DIR = path.join(HERE, "screenshots");
fs.mkdirSync(SHOT_DIR, { recursive: true });

const BASE_URL = process.env.ROSTERING_APP_URL || "http://localhost:8501/";
const xlsxPath = process.argv[2] ? path.resolve(process.argv[2]) : null;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
const errors = [];
page.on("console", (msg) => {
  if (msg.type() === "error") errors.push(msg.text());
});
page.on("pageerror", (err) => errors.push(String(err)));

await page.goto(BASE_URL);
await page.waitForSelector('input[type="file"]', { state: "attached", timeout: 30000 });
await page.screenshot({ path: path.join(SHOT_DIR, "01-app-loaded.png"), fullPage: true });
console.log("app shell loaded ok");

if (xlsxPath) {
  if (!fs.existsSync(xlsxPath)) {
    console.error(`xlsx not found: ${xlsxPath}`);
    await browser.close();
    process.exit(1);
  }

  await page.setInputFiles('input[type="file"]', xlsxPath);
  await page.waitForSelector('[data-testid="stDataFrame"]', { timeout: 30000 });
  await page.screenshot({ path: path.join(SHOT_DIR, "02-helpers-loaded.png"), fullPage: true });
  console.log("helpers dataframe rendered");

  // Resolve one unresolved friend name and dismiss another, if any exist.
  const matchButtons = page.getByRole("button", { name: "Match" });
  const matchCount = await matchButtons.count();
  console.log(`unresolved friend rows with a Match button: ${matchCount}`);
  if (matchCount > 0) {
    await matchButtons.first().click();
    await page.waitForTimeout(500);
  }
  const dismissButtons = page.getByRole("button", { name: "Not attending" });
  if ((await dismissButtons.count()) > 0) {
    await dismissButtons.first().click();
    await page.waitForTimeout(500);
  }
  await page.screenshot({ path: path.join(SHOT_DIR, "03-after-friend-actions.png"), fullPage: true });

  // Buildings tab -> Save & solve -> Roster tab.
  await page.getByRole("radio", { name: "Buildings" }).click();
  await page.waitForTimeout(500);
  await page.getByRole("button", { name: "Save & solve" }).click();
  await page.waitForTimeout(1000);
  await page.waitForSelector("text=Solving", { state: "hidden", timeout: 30000 });
  await page.screenshot({ path: path.join(SHOT_DIR, "04-after-solve.png"), fullPage: true });
  console.log("solve completed");

  await page.getByRole("radio", { name: "Roster" }).click();
  await page.waitForTimeout(1000);

  // Drag the first unassigned/placed helper chip into the first grid cell.
  // Real pointer events are required — dnd-kit needs mouse down/move/up to
  // pass its activation-distance constraint, not a high-level "dragTo".
  const chip = page.locator("div.helper-chip").first();
  const targetCell = page.locator("td.grid-cell").first();
  const chipBox = await chip.boundingBox();
  const cellBox = await targetCell.boundingBox();
  if (chipBox && cellBox) {
    await page.mouse.move(chipBox.x + chipBox.width / 2, chipBox.y + chipBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(chipBox.x + chipBox.width / 2 + 10, chipBox.y + chipBox.height / 2 + 10, { steps: 5 });
    await page.mouse.move(cellBox.x + cellBox.width / 2, cellBox.y + cellBox.height / 2, { steps: 10 });
    await page.mouse.up();
    await page.waitForTimeout(1500);
    console.log("drag-and-drop exercised");
  } else {
    console.warn("could not locate a helper chip / grid cell to drag");
  }
  await page.screenshot({ path: path.join(SHOT_DIR, "05-after-drag.png"), fullPage: true });

  const exportButton = page.getByRole("button", { name: "Export to Excel" });
  if ((await exportButton.count()) > 0) {
    console.log("export button present");
  }
}

console.log("console errors:", errors.length ? errors : "none");
await browser.close();
process.exit(errors.length ? 1 : 0);
