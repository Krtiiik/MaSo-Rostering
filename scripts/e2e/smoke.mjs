// Playwright driver for the rostering web app (NiceGUI).
// Lives in scripts/e2e/ (own package.json + node_modules) rather than inside
// a Claude Code skill directory: Node's ESM resolver walks up from the
// script's own file location, not the process's cwd, so `playwright` must be
// found in a node_modules that's a physical ancestor of this file.
//
// Usage (from scripts/e2e/):
//   npm run smoke -- [path/to/raw-response.xlsx]
//   node smoke.mjs [path/to/raw-response.xlsx]
// ROSTERING_APP_URL picks the running app (default http://localhost:8000/).
//
// With no xlsx path, only checks that the app shell loads. With a path (and no
// Season open), uploads it via the People tab, which creates the Season, matches
// one friend name in a person sheet, saves & solves from the Buildings tab,
// drags one helper chip in the roster grid, checks the Overlays chips (Tags
// stripes, Friends) and the Tag filter (creating one Tag and tagging one Helper
// first), the details card, and that Export is offered.
//
// Screenshots land next to this script in ./screenshots/.

import { chromium } from "playwright";
import path from "node:path";
import { fileURLToPath } from "node:url";
import fs from "node:fs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SHOT_DIR = path.join(HERE, "screenshots");
fs.mkdirSync(SHOT_DIR, { recursive: true });

const BASE_URL = process.env.ROSTERING_APP_URL || "http://localhost:8000/";
const xlsxPath = process.argv[2] ? path.resolve(process.argv[2]) : null;

// PLAYWRIGHT_CHANNEL (e.g. "chromium", "msedge", "chrome") runs another browser build
// than the headless shell Playwright downloads by default.
const browser = await chromium.launch(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {});
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
const errors = [];
page.on("console", (msg) => {
  if (msg.type() === "error") errors.push(msg.text());
});
page.on("pageerror", (err) => errors.push(String(err)));

const expect = (cond, message) => {
  if (!cond) {
    console.error(`FAILED: ${message}`);
    errors.push(message);
  } else {
    console.log(`ok: ${message}`);
  }
};
const tab = (name) => page.getByRole("tab", { name, exact: false });
// A Quasar select opens its option list on click; pick the option by its text.
const pick = async (select, option) => {
  await select.click();
  const item = page.locator(".q-menu .q-item").filter({ hasText: option }).first();
  await item.waitFor({ timeout: 5000 });
  await item.click();
  await page.keyboard.press("Escape");
  await page.waitForTimeout(500);
};

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
  // With no Season open the upload first asks for the Season's label
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

  // Friend names are matched in a person's sheet: the "k přiřazení" button in the
  // Friends column opens it on the Friends tab. Dismiss the first name as "not
  // attending" (the picker saves at once and the sheet stays open), then close it.
  const flagged = page.getByRole("button", { name: /k přiřazení/ });
  const flaggedCount = await flagged.count();
  console.log(`helpers with unresolved friend names: ${flaggedCount}`);
  if (flaggedCount > 0) {
    await flagged.first().click();
    const sheet = page.locator(".q-dialog").last();
    await sheet.getByRole("button", { name: "Nezúčastní se" }).first().click();
    await sheet.locator(".q-select.q-field--disabled").first().waitFor({ timeout: 10000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "03-after-friend-actions.png"), fullPage: true });
    await sheet.getByRole("button").filter({ hasText: "close" }).first().click();
    await page.waitForTimeout(500);
  }

  // Buildings tab -> Save & solve (shows the Roster tab when done).
  await tab("4. Budovy").click();
  await page.getByRole("button", { name: "Uložit a sestavit rozdělení" }).click();
  await page.waitForTimeout(500);
  const replace = page.getByRole("button", { name: "Sestavit rozdělení", exact: true });
  if (await replace.count()) await replace.click(); // only asked over unlocked Assignments
  // The solver may use its whole time limit (60 s by default).
  await page.waitForSelector("text=Sestavuji", { state: "hidden", timeout: 180000 });
  await page.waitForSelector("div.helper-chip", { timeout: 30000 });
  await page.screenshot({ path: path.join(SHOT_DIR, "04-after-solve.png"), fullPage: true });
  console.log("solve completed, Roster tab shown");

  // Drag the first chip into a solver-Role cell (native HTML5 drag-and-drop).
  const chip = page.locator("div.helper-chip").first();
  const name = await chip.getAttribute("data-name");
  const target = page.locator('td[data-drop="role"]').nth(3);
  const role = await target.getAttribute("data-role");
  const room = await target.getAttribute("data-room");
  await chip.dragTo(target);
  await page.waitForTimeout(1500);
  const moved = page.locator(`div.helper-chip[data-name="${name}"]`);
  expect(
    (await moved.getAttribute("data-room")) === room && (await moved.locator("xpath=ancestor::td").getAttribute("data-role")) === role,
    "dragging a chip onto a cell moves the Helper there",
  );
  await page.screenshot({ path: path.join(SHOT_DIR, "05-after-drag.png"), fullPage: true });

  // Tag stripes and the Tag filter. Create one Tag in the Tags tab and give it
  // to one Helper, then on the Roster tab check that the Tags overlay renders
  // stripes (off by default) and that the filter (shown with the Tags overlay
  // only) dims every other Helper without hiding anyone.
  await tab("2. Štítky").click();
  await page.getByRole("button", { name: "Nový štítek" }).click();
  await page.getByLabel("Název", { exact: true }).fill("SmokeTag");
  await page.getByRole("button", { name: "Vytvořit štítek" }).click();
  await page.getByText("Kdo štítek nese (0)", { exact: true }).waitFor({ timeout: 10000 });
  await page.locator(".q-table tbody tr .q-checkbox").first().click();
  await page.getByRole("button", { name: "Uložit změny (přidat 1)" }).click();
  await page.getByText("Kdo štítek nese (1)").waitFor({ timeout: 10000 });

  await tab("6. Rozdělení").click();
  await page.waitForSelector("div.helper-chip", { timeout: 10000 });
  const chipCount = await page.locator("div.helper-chip").count();
  expect((await page.locator(".tag-striped").count()) === 0, "chips are not tag-coloured by default");
  const filterShown = async () => (await page.locator(".q-select").filter({ hasText: "Filtrovat podle štítků" }).count()) > 0;
  expect(!(await filterShown()), "the Tag filter is hidden while the Tags overlay is off");

  const overlay = (label) => page.locator(".q-chip").filter({ hasText: new RegExp(`^(check)?\\s*${label}$`) });
  const setOverlay = async (label, on) => {
    for (let attempt = 0; attempt < 5; attempt++) {
      const selected = ((await overlay(label).getAttribute("class")) || "").includes("q-chip--selected");
      if (selected === on) return;
      await overlay(label).click();
      await page.waitForTimeout(700);
    }
  };
  await setOverlay("Štítky", true);
  await page.waitForSelector(".tag-striped", { timeout: 10000 });
  expect((await page.locator("div.helper-chip.tag-striped").count()) === 1, "the Tags overlay colours the one tagged Helper's chip");
  expect(await filterShown(), "the Tag filter shows while the Tags overlay is on");
  expect((await page.locator("div.helper-chip.chip-dimmed").count()) === 0, "no filter dims nobody");

  await pick(page.locator(".q-select").filter({ hasText: "Filtrovat podle štítků" }), "SmokeTag");
  await page.waitForFunction((n) => document.querySelectorAll("div.helper-chip.chip-dimmed").length === n, chipCount - 1, {
    timeout: 10000,
  }).catch(() => {});
  expect((await page.locator("div.helper-chip.chip-dimmed").count()) === chipCount - 1, "the filter dims every non-matching Helper");
  expect((await page.locator("div.helper-chip").count()) === chipCount, "the filter never hides a Helper");
  await page.screenshot({ path: path.join(SHOT_DIR, "06-tag-filter.png"), fullPage: true });

  await setOverlay("Štítky", false);
  await page.waitForFunction(() => document.querySelectorAll(".tag-striped").length === 0, null, { timeout: 10000 }).catch(() => {});
  expect((await page.locator(".tag-striped").count()) === 0, "the colouring goes away when the Tags overlay is switched off");
  expect(!(await filterShown()), "the Tag filter hides again with the Tags overlay");
  expect((await page.locator("div.helper-chip.chip-dimmed").count()) === 0, "the hidden filter dims no one");

  // Friends: on to begin with; off means neither hover outlines nor the unsatisfied marker.
  await setOverlay("Kamarádi", false);
  await page.waitForFunction(() => document.querySelectorAll("div.helper-chip.unsatisfied").length === 0, null, {
    timeout: 10000,
  }).catch(() => {});
  expect((await page.locator("div.helper-chip.unsatisfied").count()) === 0, "no unsatisfied marker with the Friends overlay off");
  await setOverlay("Kamarádi", true);

  // The details card opens on a click, never on a hover, and a drag never opens it.
  const chips = page.locator("div.helper-chip");
  await chips.nth(0).hover();
  await page.waitForTimeout(800);
  expect((await page.locator(".helper-card").count()) === 0, "hovering a chip does not open the details card");
  await chips.nth(0).click();
  await page.waitForSelector(".helper-card", { timeout: 5000 });
  expect((await page.locator(".helper-card").count()) === 1, "clicking a chip opens its details card");
  await chips.nth(1).click();
  await page.waitForTimeout(500);
  expect((await page.locator(".helper-card").count()) === 1, "clicking another chip switches the card to that Helper");
  await page.locator(".roster-grid .row-label").first().click();
  await page.waitForTimeout(500);
  expect((await page.locator(".helper-card").count()) === 0, "clicking elsewhere closes the details card");
  await chips.nth(0).click();
  await page.waitForSelector(".helper-card", { timeout: 5000 });
  await page.keyboard.press("Escape");
  await page.waitForTimeout(500);
  expect((await page.locator(".helper-card").count()) === 0, "Escape closes the details card");
  await chips.nth(0).dragTo(page.locator('td[data-drop="role"]').nth(1));
  await page.waitForTimeout(1500);
  expect((await page.locator(".helper-card").count()) === 0, "dragging a chip does not open the details card");

  expect((await page.getByRole("button", { name: "Export do Excelu" }).count()) === 1, "Export is offered");
}

console.log("console errors:", errors.length ? errors : "none");
await browser.close();
process.exit(errors.length ? 1 : 0);
