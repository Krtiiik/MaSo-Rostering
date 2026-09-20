# PyInstaller spec for a standalone ``rostering`` CLI/app executable
# (used by .github/workflows/build-executables.yml). Build with:
#
#   pyinstaller packaging/rostering.spec --noconfirm --clean
#
# Produces a one-directory build under dist/rostering/ containing the
# executable plus all supporting files — deliberately not --onefile,
# because two things below need real files on disk at runtime rather than
# bytecode packed into PyInstaller's PYZ archive:
#
# 1. Streamlit's ``bootstrap.run`` reads the app's script source
#    (rostering/streamlit_app/*.py) from a real file path at run time, not
#    via a normal Python import.
# 2. The rostering-assignment-grid custom Streamlit component (CCv2) is
#    discovered via ``importlib.util.find_spec`` and then reads a sibling
#    ``pyproject.toml`` (for its declared ``asset_dir``) and the built
#    frontend/build/*.js/*.css files next to its own __init__.py — see that
#    package's docstring and rostering/CLAUDE.md.
#
# ``module_collection_mode: "pyz+py"`` for these packages forces PyInstaller
# to *also* unpack their plain .py sources onto disk (in addition to the
# normal compiled bytecode used for imports), which keeps ``__file__``-based
# lookups like the two above working unmodified.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).resolve().parent  # repo root (this file lives in packaging/)

datas = []
binaries = []
hiddenimports = []

for pkg in ("streamlit", "ortools", "rostering_assignment_grid"):
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
    module_collection_mode={
        "streamlit": "pyz+py",
        "rostering_assignment_grid": "pyz+py",
        "rostering": "pyz+py",
    },
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
