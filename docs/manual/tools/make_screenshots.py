"""Regenerates the screenshots of the user manual (docs/manual/navod.md).

Drives a throwaway copy of the app with Playwright (Edge) over fully fictional
data from tests/survey_factory.py, and highlights what the manual tells the
reader to do with a red outline and a numbered badge, drawn over the page just
before each screenshot.

Usage (from the repo root, with the project venv; Playwright is installed
separately because it is only needed here):

    pip install playwright
    python docs/manual/tools/make_screenshots.py

The script starts its own server on a free port against a temporary seasons
folder, so the real data/ folder is never touched.
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "docs" / "manual" / "img"
sys.path.insert(0, str(REPO))

from tests.survey_factory import organizer_survey_bytes, write_survey  # noqa: E402

# Tall enough that a drop target is not near the bottom edge, where the grid auto-scrolls during a drag.
VIEWPORT = {"width": 1500, "height": 1000}
RED = "#e11d48"

# Buildings of the fictional Season: name -> rooms. The survey offers a fourth
# one ("Impakt + Troja") that is left out on purpose, to show the to-do about
# building names without a match.
BUILDINGS = {
    "Malá Strana": ["MS 1", "MS 2"],
    "Karlov": ["M 1", "M 2"],
    "Karlín": ["K 1", "K 2"],
}
# Minimum helpers per room: label of the Role -> count.
ROOM_COUNTS = {"Opravovatel": 2, "Měnič": 1, "Skenovač": 1, "Kreslič": 1, "Fotograf": 1}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(seasons: Path, port: int) -> subprocess.Popen:
    env = {**os.environ, "ROSTERING_SEASONS_DIR": str(seasons)}
    proc = subprocess.Popen(
        [sys.executable, "-c", f"from rostering.cli import main; main(['serve','--port','{port}','--headless'])"],
        cwd=seasons.parent,
        env={**env, "PYTHONPATH": str(REPO)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return proc
        except OSError:
            time.sleep(1)
    proc.kill()
    raise RuntimeError("the app did not start")


_OVERLAY_JS = """
(items) => {
  document.querySelectorAll('.manual-hl').forEach(e => e.remove());
  for (const {box, label, pad} of items) {
    const o = document.createElement('div');
    o.className = 'manual-hl';
    Object.assign(o.style, {
      position: 'fixed', zIndex: 99999, pointerEvents: 'none',
      left: (box.x - pad) + 'px', top: (box.y - pad) + 'px',
      width: (box.width + 2 * pad) + 'px', height: (box.height + 2 * pad) + 'px',
      border: '3px solid %s', borderRadius: '8px',
      boxShadow: '0 0 0 3px rgba(255,255,255,.7)',
    });
    if (label) {
      const b = document.createElement('div');
      b.textContent = label;
      Object.assign(b.style, {
        position: 'absolute', left: '-14px', top: '-14px', width: '26px', height: '26px',
        borderRadius: '50%%', background: '%s', color: '#fff', font: 'bold 15px sans-serif',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        boxShadow: '0 1px 4px rgba(0,0,0,.5)',
      });
      o.appendChild(b);
    }
    document.body.appendChild(o);
  }
}
""" % (RED, RED)


class Shooter:
    def __init__(self, page: Page) -> None:
        self.page = page
        self.count = 0

    def shot(
        self, name: str, targets=(), pad: int = 4, clip: dict | None = None, keep_toast: bool = False, scroll: bool = True
    ) -> None:
        """Screenshot of the viewport with ``targets`` (locators, numbered 1..n)
        highlighted. ``clip`` crops to a region in viewport pixels."""
        page = self.page
        page.wait_for_timeout(700)
        items = []
        if scroll:
            for loc in targets:
                loc.first.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        for i, loc in enumerate(targets, 1):
            box = loc.first.bounding_box()
            if box is None:
                raise RuntimeError(f"{name}: target {i} is not visible")
            items.append({"box": box, "label": str(i) if len(targets) > 1 else "", "pad": pad})
        page.evaluate(_OVERLAY_JS, items)
        # Toasts would cover the page the reader should look at.
        page.evaluate(
            "hide => { let s = document.getElementById('manual-toasts');"
            " if (!s) { s = document.createElement('style'); s.id = 'manual-toasts'; document.head.appendChild(s); }"
            " s.textContent = hide ? '.q-notifications { visibility: hidden !important; }' : ''; }",
            not keep_toast,
        )
        self.count += 1
        path = OUT / f"{self.count:02d}-{name}.png"
        page.screenshot(path=str(path), clip=clip)
        page.evaluate("document.querySelectorAll('.manual-hl').forEach(e => e.remove())")
        print("wrote", path.name)


def tab(page: Page, name: str):
    return page.get_by_role("tab", name=name)


def run(base: str, tmp: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):  # numbering may have changed since the last run
        old.unlink()
    helpers_xlsx = write_survey(tmp / "pomocnici.xlsx", count=40, seed=7)
    organizers_xlsx = tmp / "organizatori.xlsx"
    organizers_xlsx.write_bytes(organizer_survey_bytes(6, seed=1))

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("PLAYWRIGHT_CHANNEL", "msedge"))
        page = browser.new_page(viewport=VIEWPORT, color_scheme="light", locale="cs-CZ")
        page.goto(base)
        page.wait_for_selector('input[type="file"]', state="attached", timeout=30000)
        s = Shooter(page)
        try:
            steps(page, s, helpers_xlsx, organizers_xlsx)
        except Exception:
            failure = Path(os.environ.get("MANUAL_FAILURE_PNG", tmp / "failure.png"))
            page.screenshot(path=str(failure))
            print("the page at the failure was saved to", failure)
            raise
        browser.close()


def upload(page: Page, button: str, path: Path) -> None:
    with page.expect_file_chooser() as chooser:
        page.get_by_role("button", name=button).click()
    chooser.value.set_files(str(path))


def steps(page: Page, s: Shooter, helpers_xlsx: Path, organizers_xlsx: Path) -> None:
    btn = lambda name, **kw: page.get_by_role("button", name=name, **kw)  # noqa: E731

    # --- 1. Start and the first upload -------------------------------------
    s.shot("start", [btn("Načíst pomocníky")])
    upload(page, "Načíst pomocníky", helpers_xlsx)
    create = btn("Vytvořit ročník a načíst odpovědi")
    create.wait_for()
    s.shot("rocnik-oznaceni", [page.get_by_label("Označení ročníku", exact=True), create])
    create.click()
    page.get_by_text("Pomocníci (").wait_for()
    page.wait_for_timeout(1500)
    s.shot("lide", [page.get_by_text("Pomocníci (", exact=False).first, btn(re.compile("k přiřazení")).first])

    # --- 2. Friends that need matching ------------------------------------
    btn(re.compile("k přiřazení")).first.click()
    sheet = page.locator(".q-dialog").last
    sheet.get_by_role("button", name="Nezúčastní se").first.wait_for()
    s.shot("kamarad-prirazeni", [sheet.locator(".q-select").first, sheet.get_by_role("button", name="Nezúčastní se").first])
    sheet.get_by_role("button", name="Nezúčastní se").first.click()
    page.wait_for_timeout(800)
    sheet.get_by_role("button").filter(has_text="close").first.click()
    page.wait_for_timeout(500)

    # --- 3. Organizers ----------------------------------------------------
    upload(page, "Načíst organizátory", organizers_xlsx)
    page.get_by_text("Organizátoři (6)").wait_for(timeout=20000)
    page.wait_for_timeout(1500)
    s.shot("organizatori", [page.get_by_text("Organizátoři (6)")])

    # --- 4. Left drawer: Seasons and Versions -----------------------------
    s.shot(
        "rocniky-verze",
        [page.get_by_text("2026-jaro", exact=True).first, btn("Nový ročník"), page.get_by_placeholder("Název verze…")],
        clip={"x": 0, "y": 50, "width": 300, "height": 330},
    )

    # --- 5. Tags and Forced friends (both optional) -----------------------
    tab(page, "2. Štítky").click()
    page.wait_for_timeout(800)
    s.shot("stitky", [btn("Nový štítek")])
    tab(page, "3. Vynucené skupinky kamarádů").click()
    page.wait_for_timeout(800)
    s.shot("skupinky", [btn("Nová skupinka")])

    # --- 6. Buildings -----------------------------------------------------
    tab(page, "4. Budovy").click()
    page.wait_for_timeout(800)
    s.shot("budovy-prazdne", [btn("Přidat budovu")])
    for _ in BUILDINGS:
        btn("Přidat budovu").click()
        page.wait_for_timeout(400)
    cards = page.locator(".q-card").filter(has=page.get_by_label("Název budovy"))
    for bi, (name, rooms) in enumerate(BUILDINGS.items()):
        card = cards.nth(bi)
        for _ in rooms:
            card.get_by_role("button", name="Přidat místnost").click()
            page.wait_for_timeout(300)
        texts = card.locator("input:not([type=number])")
        texts.nth(0).fill(name)
        for ri, room in enumerate(rooms):
            texts.nth(1 + ri).fill(room)
        numbers = card.locator("input[type=number]")
        columns = 1 + len(rooms)
        for role_index, count in enumerate(ROOM_COUNTS.values()):
            for ri in range(len(rooms)):
                numbers.nth(role_index * columns + 1 + ri).fill(str(count))
    first = cards.first
    s.shot(
        "budovy-vyplnene",
        [
            first.get_by_label("Název budovy"),
            first.get_by_role("button", name="Přidat místnost"),
            first.locator("input[type=number]").nth(1),
        ],
    )
    s.shot("budovy-ulozit", [btn("Uložit konfiguraci"), btn("Uložit a sestavit rozdělení")], clip={"x": 300, "y": 760, "width": 1200, "height": 140})
    btn("Uložit konfiguraci").click()
    page.wait_for_timeout(1000)

    # --- 7. To-do panel: a building name from the survey with no match -----
    page.evaluate("window.scrollTo(0, 0)")
    page.get_by_role("button").filter(has_text="checklist").first.click()
    page.get_by_text("Budovy z dotazníku bez shody").wait_for(timeout=10000)
    for summary in page.get_by_role("button", name="Skrýt").all():  # the upload summaries are not the point here
        summary.click()
        page.wait_for_timeout(300)
    s.shot(
        "k-vyrizeni",
        [page.get_by_text("Budovy z dotazníku bez shody"), page.get_by_text("Odpovídající budovy").first, btn("Přiřadit").first],
    )
    page.get_by_role("button").filter(has_text="checklist").first.click()  # closes the panel again
    page.wait_for_timeout(500)

    tab(page, "5. Parametry rozřazování").click()
    page.wait_for_timeout(800)
    s.shot("parametry", [page.get_by_text("Časový limit (sekundy)")])
    tab(page, "4. Budovy").click()
    page.wait_for_timeout(800)

    # --- 8. Solve ---------------------------------------------------------
    btn("Uložit a sestavit rozdělení").click()
    try:
        page.get_by_text("Sestavuji rozdělení").wait_for(timeout=4000)
        s.shot("sestavovani", [page.get_by_text("Sestavuji rozdělení")])
    except Exception:  # solved faster than we could look
        print("note: the solving dialog was not caught")
    page.wait_for_selector("div.helper-chip", timeout=180000)
    page.get_by_role("button").filter(has_text="menu").first.click()  # close the left drawer: the grid is wide
    page.wait_for_timeout(1500)
    s.shot(
        "rozdeleni",
        [btn("Sestavit znovu"), btn("Export do Excelu"), page.get_by_text("Zobrazení:")],
        clip={"x": 0, "y": 0, "width": 1500, "height": 330},
    )
    grid = page.locator(".roster-grid")
    s.shot(
        "mrizka",
        [
            grid.get_by_text("Karlov", exact=True).first,
            grid.get_by_text("M 1", exact=True).first,
            grid.get_by_text("Skenovač", exact=True).first,
            grid.locator("div.helper-chip").first,
        ],
    )

    # --- 9. A late registrant waits in "Nezařazení" -----------------------
    tab(page, "1. Lidé").click()
    page.wait_for_timeout(800)
    btn("Přidat").nth(1).click()
    page.get_by_label("Jméno (povinné)").fill("Adam Pozdní")
    page.get_by_label("Kontakt (povinný)").fill("adam.pozdni@example.test")
    s.shot("novy-pomocnik", [page.get_by_label("Jméno (povinné)"), page.get_by_label("Kontakt (povinný)"), btn("Přidat pomocníka")])
    btn("Přidat pomocníka").click()
    page.wait_for_timeout(1000)
    tab(page, "6. Rozdělení pomocníků").click()
    page.wait_for_selector(".unassigned-pool div.helper-chip")
    pooled = page.locator(".unassigned-pool div.helper-chip").first
    name = pooled.get_attribute("data-name")
    cell = page.locator('td[data-drop="role"][data-role="Zaloha"]').nth(4)  # an empty reserve cell: it has no minimum to upset
    page.evaluate("window.scrollBy(0, 90)")  # both the waiting chip and the target cell in view
    s.shot("presun-pred", [pooled, cell, btn("Zařadit nové registrované")], scroll=False)
    pooled.drag_to(cell)
    page.wait_for_timeout(1500)
    s.shot("presun-po", [page.locator(f'td div.helper-chip[data-name="{name}"]')])

    # --- 10. Details card and lock ---------------------------------------
    page.locator(f'td div.helper-chip[data-name="{name}"]').click()
    card = page.locator(".helper-card")
    card.wait_for()
    s.shot("karta", [card, card.get_by_role("button", name=re.compile("Zamknout"))])
    page.keyboard.press("Escape")

    # --- 11. Overlays -----------------------------------------------------
    for label in ("Spokojenost s rolí", "Spokojenost s budovou"):
        page.locator(".q-chip").filter(has_text=label).click()
        page.wait_for_timeout(600)
    s.shot("zobrazeni", [page.get_by_text("Zobrazení:"), page.locator(".q-chip").filter(has_text="Spokojenost s rolí")])

    # --- 12. Organizers ---------------------------------------------------
    org_chip = page.locator(".organizers-pool .organizer-chip").first
    org_cell = page.locator('td[data-drop="org"]').first
    s.shot("organizator-pred", [org_chip, org_cell])
    org_chip.drag_to(org_cell)
    page.wait_for_timeout(1500)
    s.shot("organizator-po", [org_cell])

    # --- 13. Version and export -------------------------------------------
    page.get_by_role("button").filter(has_text="menu").first.click()
    page.wait_for_timeout(600)
    version = page.get_by_placeholder("Název verze…")
    version.fill("Před exportem")
    version.press("Enter")
    page.wait_for_timeout(1000)
    s.shot("verze", [page.get_by_text("Před exportem").first], clip={"x": 0, "y": 50, "width": 300, "height": 330})
    page.get_by_role("button").filter(has_text="menu").first.click()  # the grid needs the whole width again
    page.wait_for_timeout(600)
    btn("Export do Excelu").click()
    saved = page.get_by_text("Rozdělení uloženo do")
    saved.wait_for(timeout=20000)
    # The path would show the name of the account that ran the script.
    page.evaluate(
        "() => { for (const e of document.querySelectorAll('*')) { if (e.children.length === 0 &&"
        " e.textContent.includes('Rozdělení uloženo do')) e.textContent = 'Rozdělení uloženo do …\\\\2026-jaro\\\\Rozdělení pomocníků.xlsx'; } }"
    )
    page.evaluate("document.querySelector('.roster-toolbar').style.position = 'static'")  # else it covers the note
    page.mouse.move(700, 600)  # no tooltip over the button
    page.evaluate("window.scrollTo(0, 0)")
    s.shot("export", [btn("Export do Excelu"), saved], scroll=False)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        seasons = tmp / "seasons"
        port = free_port()
        server = start_server(seasons, port)
        try:
            run(f"http://127.0.0.1:{port}/", tmp)
        finally:
            server.terminate()
