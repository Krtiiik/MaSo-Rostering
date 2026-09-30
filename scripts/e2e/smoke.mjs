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
// checks the Roster tab's "Show tags" toggle and Tag filter (creating one Tag
// and tagging one Helper first), and clicks Export.
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
  // With no Season open the upload first asks to confirm the Season's label
  // (prefilled from the export's timestamps; typed in if they can't be read).
  const createSeason = page.getByRole("button", { name: "Create Season and load responses" });
  await createSeason.waitFor({ timeout: 30000 });
  const labelInput = page.getByLabel("Season label", { exact: true });
  if (!(await labelInput.inputValue())) {
    await labelInput.fill("2026-jaro");
  }
  await createSeason.click();
  await page.waitForSelector('[data-testid="stDataFrame"]', { timeout: 30000 });
  await page.screenshot({ path: path.join(SHOT_DIR, "02-helpers-loaded.png"), fullPage: true });
  console.log("helpers dataframe rendered");

  // Resolve one unresolved friend name to a candidate, and dismiss another as
  // "not attending", if any exist. Each unresolved name is its own inline
  // selectbox (placeholder = the quoted name; options are the unselected
  // placeholder, then a "not attending" sentinel, then every other helper as
  // a candidate — in that order so "not attending" doesn't require scrolling
  // past a long, virtualized candidate list) that applies immediately on
  // selection — there are no separate Match/dismiss buttons any more.
  const friendSelects = page.locator('[data-testid="stSelectbox"]:visible');
  const friendSelectCount = await friendSelects.count();
  console.log(`unresolved friend selectboxes: ${friendSelectCount}`);
  if (friendSelectCount > 0) {
    await friendSelects.first().scrollIntoViewIfNeeded();
    await friendSelects.first().click();
    await page.waitForSelector('[role="listbox"]', { timeout: 5000 });
    await page.getByRole("option").nth(2).click(); // 0 = placeholder, 1 = "not attending", 2 = first candidate
    await page.waitForTimeout(500);
  }
  const friendSelectsAfter = page.locator('[data-testid="stSelectbox"]:visible');
  if ((await friendSelectsAfter.count()) > 0) {
    await friendSelectsAfter.first().scrollIntoViewIfNeeded();
    await friendSelectsAfter.first().click();
    await page.waitForSelector('[role="listbox"]', { timeout: 5000 });
    await page.getByRole("option").nth(1).click(); // "not attending"
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

  // Tag pills and the Tag filter. Create one Tag in the Tags tab and give it to
  // one Helper, then on the Roster tab check that the "Show tags" toggle renders
  // pills (hidden by default), and that the filter dims every other Helper
  // without hiding anyone, whether or not the pills are shown.
  // A multiselect toggles on click and the app may still be rerunning under
  // the first one, so click until its option list is really open.
  const openMultiselect = async (label) => {
    const input = page.locator('[data-testid="stMultiSelect"]').filter({ hasText: label }).locator("input");
    for (let attempt = 0; attempt < 5; attempt++) {
      await input.click();
      try {
        await page.getByRole("option").first().waitFor({ timeout: 1500 });
        return;
      } catch {
        // closed again (or not yet open): click once more
      }
    }
    throw new Error(`could not open the "${label}" multiselect`);
  };
  await page.getByRole("radio", { name: "Tags" }).click();
  await page.getByRole("button", { name: "New tag" }).click();
  await page.getByLabel("Name", { exact: true }).fill("SmokeTag");
  await page.getByRole("button", { name: "Create tag" }).click();
  await page.getByText("Add tag to others", { exact: true }).waitFor({ timeout: 10000 });
  await openMultiselect("Helpers to add");
  await page.getByRole("option").nth(1).click(); // 0 = "Select all"
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Add 1 to SmokeTag" }).click();
  await page.getByText("Has this tag (1)").waitFor({ timeout: 10000 });

  await page.getByRole("radio", { name: "Roster" }).click();
  await page.waitForSelector("div.helper-chip", { timeout: 10000 });
  const chipCount = await page.locator("div.helper-chip").count();
  const expect = (cond, message) => {
    if (!cond) {
      console.error(`FAILED: ${message}`);
      errors.push(message);
    } else {
      console.log(`ok: ${message}`);
    }
  };
  expect((await page.locator(".tag-pill").count()) === 0, "tag pills are hidden by default");

  // Idempotent: click the toggle until it is in the wanted state.
  const setShowTags = async (on) => {
    const toggle = page.getByRole("switch", { name: "Show tags" });
    for (let attempt = 0; attempt < 5 && (await toggle.isChecked()) !== on; attempt++) {
      await page.getByText("Show tags", { exact: true }).click();
      await page.waitForTimeout(700);
    }
  };
  await setShowTags(true);
  await page.waitForSelector(".tag-pill", { timeout: 10000 });
  expect((await page.locator(".tag-pill-direct").count()) === 1, "Show tags renders the direct pill under one Helper");
  expect((await page.locator("div.helper-chip.dimmed").count()) === 0, "no filter dims nobody");

  await openMultiselect("Filter by tags");
  await page.getByRole("option", { name: "SmokeTag" }).click();
  await page.keyboard.press("Escape");
  await page.waitForFunction((n) => document.querySelectorAll("div.helper-chip.dimmed").length === n, chipCount - 1, {
    timeout: 10000,
  }).catch(() => {});
  expect((await page.locator("div.helper-chip.dimmed").count()) === chipCount - 1, "the filter dims every non-matching Helper");
  expect((await page.locator("div.helper-chip").count()) === chipCount, "the filter never hides a Helper");

  await setShowTags(false);
  await page.waitForFunction(() => document.querySelectorAll(".tag-pill").length === 0, null, { timeout: 10000 }).catch(() => {});
  expect((await page.locator(".tag-pill").count()) === 0, "pills hide again when toggled off");
  expect(
    (await page.locator("div.helper-chip.dimmed").count()) === chipCount - 1,
    "the filter still dims with the pills hidden",
  );
  await page.screenshot({ path: path.join(SHOT_DIR, "06-tag-filter.png"), fullPage: true });

  const exportButton = page.getByRole("button", { name: "Export to Excel" });
  if ((await exportButton.count()) > 0) {
    console.log("export button present");
  }
}

console.log("console errors:", errors.length ? errors : "none");
await browser.close();
process.exit(errors.length ? 1 : 0);
