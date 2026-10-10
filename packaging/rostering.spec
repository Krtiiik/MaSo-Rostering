# PyInstaller spec for a standalone ``rostering`` CLI/app executable
# (used by .github/workflows/build-executables.yml). Build with:
#
#   pyinstaller packaging/rostering.spec --noconfirm --clean
#
# Produces a one-directory build under dist/rostering/ containing the
# executable plus all supporting files — deliberately not --onefile, because
# the web app needs real files on disk at runtime: NiceGUI serves its own
# static files and every element's JavaScript (and the roster grid's
# rostering/webapp/ui/grid/roster_grid.js) from the folder next to the module
# that declares it, found through ``__file__``. ``collect_all`` puts those data
# files beside the modules, so those lookups work unmodified.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).resolve().parent  # repo root (this file lives in packaging/)

datas = []
binaries = []
hiddenimports = []

for pkg in ("nicegui", "ortools", "rostering"):
    # "rostering" is collect_all'd too, not just left to the import graph: its
    # package data (the grid's JS) is
    # not Python and so invisible to PyInstaller's import analysis.
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

a = Analysis(
    [str(root / "packaging" / "entrypoint.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="rostering",
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="rostering",
)
