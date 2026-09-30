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
// uploads it via the People tab, waits for the Organizers/Helpers tables,
// switches to Buildings, solves, switches to Roster, drags one helper chip
// into a grid cell (exercising the CCv2 assignment_grid component, which
// renders in a shadow root — not an iframe, since CCv2 doesn't use iframes),
// checks the Roster tab's Overlays pills (Tags stripes, Friends) and Tag filter (creating one Tag
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
  const createSeason = page.getByRole("button", { name: "Vytvořit ročník a načíst odpovědi" });
  await createSeason.waitFor({ timeout: 30000 });
  const labelInput = page.getByLabel("Označení ročníku", { exact: true });
  if (!(await labelInput.inputValue())) {
    await labelInput.fill("2026-jaro");
  }
  await createSeason.click();
  await page.getByText("Pomocníci (", { exact: false }).waitFor({ timeout: 30000 });
  await page.screenshot({ path: path.join(SHOT_DIR, "02-helpers-loaded.png"), fullPage: true });
  console.log("people tables rendered");

  // Friend names are matched in a helper's popup: a name button marked with a
  // warning sign has some unresolved. Open one, go to its "Friend names" tab
  // and dismiss its first name as "not attending" (each picker applies its
  // choice immediately and the popup stays open), then close the popup.
  const flagged = page.getByRole("button", { name: /^⚠/ });
  const flaggedCount = await flagged.count();
  console.log(`helpers with unresolved friend names: ${flaggedCount}`);
  if (flaggedCount > 0) {
    await flagged.first().scrollIntoViewIfNeeded();
    await flagged.first().click();
    const popup = page.getByRole("dialog");
    await popup.getByRole("tab", { name: "Jména kamarádů" }).click();
    await popup.locator('[data-testid="stMultiSelect"]').first().click();
    await page.getByRole("option").first().click(); // "not attending"
    await page.waitForTimeout(800);
    await popup.getByRole("button", { name: "Close" }).click();
    await page.waitForTimeout(500);
  }
  await page.screenshot({ path: path.join(SHOT_DIR, "03-after-friend-actions.png"), fullPage: true });

  // Buildings tab -> Save & solve -> Roster tab.
  await page.getByRole("radio", { name: "Budovy" }).click();
  await page.waitForTimeout(500);
  await page.getByRole("button", { name: "Uložit a sestavit rozdělení" }).click();
  await page.waitForTimeout(1000);
  await page.waitForSelector("text=Sestavuji", { state: "hidden", timeout: 30000 });
  await page.screenshot({ path: path.join(SHOT_DIR, "04-after-solve.png"), fullPage: true });
  console.log("solve completed");

  await page.getByRole("radio", { name: "Rozdělení pomocníků" }).click();
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

  // Tag stripes and the Tag filter. Create one Tag in the Tags tab and give it to
  // one Helper, then on the Roster tab check that the Tags overlay renders
  // stripes (hidden by default), and that the filter (shown with the Tags
  // overlay only) dims every other Helper without hiding anyone.
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
  await page.getByRole("radio", { name: "Štítky" }).click();
  await page.getByRole("button", { name: "Nový štítek" }).click();
  await page.getByLabel("Název", { exact: true }).fill("SmokeTag");
  await page.getByRole("button", { name: "Vytvořit štítek" }).click();
  await page.getByText("Kdo štítek nese (0)", { exact: true }).waitFor({ timeout: 10000 });
  await openMultiselect("Kdo štítek nese");
  await page.getByRole("option").nth(1).click(); // 0 = "Select all"
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Uložit změny (přidat 1)" }).click();
  await page.getByText("Kdo štítek nese (1)").waitFor({ timeout: 10000 });

  await page.getByRole("radio", { name: "Rozdělení pomocníků" }).click();
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
  expect((await page.locator(".tag-striped").count()) === 0, "chips are not tag-coloured by default");
  const filterShown = async () => (await page.locator('[data-testid="stMultiSelect"]').filter({ hasText: "Filtrovat podle štítků" }).count()) > 0;
  expect(!(await filterShown()), "the Tag filter is hidden while the Tags overlay is off");

  // The Overlays pills: click a pill until it is in the wanted state.
  const setOverlay = async (name, on) => {
    const pill = page.locator('[data-testid="stButtonGroup"] button[data-variant="pills"]').filter({ hasText: new RegExp(`^${name}$`) });
    for (let attempt = 0; attempt < 5; attempt++) {
      const active = (await pill.getAttribute("aria-pressed")) === "true";
      if (active === on) return;
      await pill.click();
      await page.waitForTimeout(700);
    }
  };
  await setOverlay("Štítky", true);
  await page.waitForSelector(".tag-striped", { timeout: 10000 });
  expect((await page.locator(".tag-striped").count()) === 1, "the Tags overlay colours the one tagged Helper's chip");
  expect(await filterShown(), "the Tag filter shows while the Tags overlay is on");
  expect((await page.locator("div.helper-chip.dimmed").count()) === 0, "no filter dims nobody");

  await openMultiselect("Filtrovat podle štítků");
  await page.getByRole("option", { name: "SmokeTag" }).click();
  await page.keyboard.press("Escape");
  await page.waitForFunction((n) => document.querySelectorAll("div.helper-chip.dimmed").length === n, chipCount - 1, {
    timeout: 10000,
  }).catch(() => {});
  expect((await page.locator("div.helper-chip.dimmed").count()) === chipCount - 1, "the filter dims every non-matching Helper");
  expect((await page.locator("div.helper-chip").count()) === chipCount, "the filter never hides a Helper");

  await page.screenshot({ path: path.join(SHOT_DIR, "06-tag-filter.png"), fullPage: true });

  await setOverlay("Štítky", false);
  await page.waitForFunction(() => document.querySelectorAll(".tag-striped").length === 0, null, { timeout: 10000 }).catch(() => {});
  expect((await page.locator(".tag-striped").count()) === 0, "the colouring goes away when the Tags overlay is switched off");
  expect(!(await filterShown()), "the Tag filter hides again with the Tags overlay");
  expect((await page.locator("div.helper-chip.dimmed").count()) === 0, "the hidden filter dims no one");

  // Friends: on to begin with; off means neither hover outlines nor the unsatisfied marker.
  await setOverlay("Kamarádi", false);
  await page.waitForFunction(() => document.querySelectorAll("div.helper-chip.unsatisfied").length === 0, null, {
    timeout: 10000,
  }).catch(() => {});
  expect((await page.locator("div.helper-chip.unsatisfied").count()) === 0, "no unsatisfied marker with the Friends overlay off");
  await setOverlay("Kamarádi", true);

  // The details card opens on a click, never on a hover, and a drag never opens it.
  const cardNames = () => page.locator(".helper-card .helper-card-name").allTextContents();
  const chips = page.locator("div.helper-chip");
  await chips.nth(0).hover();
  await page.waitForTimeout(800);
  expect((await page.locator(".helper-card").count()) === 0, "hovering a chip does not open the details card");
  await chips.nth(0).click();
  await page.waitForSelector(".helper-card", { timeout: 5000 });
  expect((await page.locator(".helper-card").count()) === 1, "clicking a chip opens its details card");
  await chips.nth(1).click();
  await page.waitForTimeout(300);
  const switched = await cardNames();
  expect(switched.length === 1, "clicking another chip switches the card to that Helper");
  await page.mouse.click(1380, 990);
  await page.waitForTimeout(300);
  expect((await page.locator(".helper-card").count()) === 0, "clicking elsewhere closes the details card");
  await chips.nth(0).click();
  await page.waitForSelector(".helper-card", { timeout: 5000 });
  await page.keyboard.press("Escape");
  await page.waitForTimeout(200);
  expect((await page.locator(".helper-card").count()) === 0, "Escape closes the details card");
  {
    const box = await chips.nth(0).boundingBox();
    const cell = await page.locator("td.grid-cell").nth(1).boundingBox();
    if (box && cell) {
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width / 2 + 12, box.y + box.height / 2 + 12, { steps: 5 });
      await page.mouse.move(cell.x + cell.width / 2, cell.y + cell.height / 2, { steps: 10 });
      await page.mouse.up();
      await page.waitForTimeout(1500);
      expect((await page.locator(".helper-card").count()) === 0, "dragging a chip does not open the details card");
    }
  }

  const exportButton = page.getByRole("button", { name: "Export do Excelu" });
  if ((await exportButton.count()) > 0) {
    console.log("export button present");
  }
}

console.log("console errors:", errors.length ? errors : "none");
await browser.close();
process.exit(errors.length ? 1 : 0);
