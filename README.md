<p align="center">
  <a href="docs/manual/navod.md">
    <img src="docs/banner.svg" alt="Český návod: Rozdělování pomocníků krok za krokem — otevřít návod" width="100%">
  </a>
</p>

<h3 align="center">
  🇨🇿 <a href="docs/manual/navod.md">Česky? Přečtěte si návod s obrázky &rarr;</a>
</h3>

# Rostering

Assigns registered helpers (*pomocníci*) to buildings, rooms and roles for the
[MaSo](https://maso.mff.cuni.cz/) math competition, based on their preferences,
and lets you tidy up the result by hand before exporting it to Excel.

The app itself is in Czech. A step-by-step guide in Czech, with screenshots, is
in [docs/manual/navod.md](docs/manual/navod.md). To work on the code, see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Getting started

You do not need Python or any other tool installed. Download the build for
your system and run it.

1. Open the [latest release](https://github.com/Krtiiik/MaSo-Rostering/releases/latest)
   and download the archive for your platform:

   | Platform | File |
   |---|---|
   | Windows | `rostering-vX.Y.Z-windows-x64.zip` |
   | Linux | `rostering-vX.Y.Z-linux-x64.tar.gz` |
   | macOS (Apple silicon) | `rostering-vX.Y.Z-macos-arm64.tar.gz` |

2. Extract the archive. You get a `rostering` folder; keep everything in it
   together.
3. Run `rostering.exe` (Windows) or `rostering` (Linux/macOS) from inside that
   folder. On Windows a double-click is enough.
4. Your browser opens the app at <http://127.0.0.1:8000>. Keep the program's
   window open while you work; closing it stops the app.

The builds are not code-signed, so your system may ask you to confirm that you
want to run the program the first time.

## What the app does

The six numbered tabs along the top follow the order of the work:

1. **Lidé** (People) — load the helpers' Google Forms export with
   "Načíst pomocníky" (and, optionally, the organizers' with "Načíst
   organizátory"). The first upload creates a Season.
2. **Štítky** (Tags) — label people and restrict where a tag's carriers may
   work.
3. **Vynucené skupinky kamarádů** (Forced friends) — groups that must end up
   together.
4. **Budovy** (Buildings) — buildings, rooms and how many helpers each role
   needs.
5. **Parametry rozřazování** (Solver) — the solver's weights.
6. **Rozdělení pomocníků** (Roster) — solve, then drag helpers between cells to
   adjust the result, and export it to Excel.

Anything waiting on a decision (possible returning helpers to link, what a
re-upload changed, ...) collects in the **K vyřízení** panel behind the
checklist button in the header. Named versions of the roster can be saved,
restored and deleted from the left drawer.

A new Season starts with no buildings. Bring the layout in from an earlier
Season (the "Rozložení budov" part of the import from an earlier Season), load it
from the "Pomocníci v místnostech" sheet, or enter it on the Buildings tab.

## Your data

Every Season (a year plus `jaro` or `podzim`, e.g. `2026-jaro`) is stored
automatically and can be opened, renamed or deleted from the **Ročníky** panel
in the left drawer. The data is kept in a `data/` folder created in the folder
you start the program from — for the executable, the extracted `rostering`
folder if you double-click it. It holds real helpers' personal data, so do not
share or publish it.

The **Ročníky** panel can also export chosen Seasons (with or without their
saved versions) to one `.zip` and import such a file elsewhere — to move to
another machine or hand a Season to a colleague. Before an import changes
anything, your stored Seasons are backed up as a `.zip` in `data/backups/`.

To move to a new version of the app, copy your `data/` folder next to the new
one.
