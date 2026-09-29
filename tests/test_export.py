import openpyxl

from rostering.domain import (
    Assignment,
    Building,
    Competition,
    Helper,
    ManualRoles,
    OverlayAssignment,
    OverlayRole,
    Role,
    RoleCapacity,
    Room,
    SolveResult,
    StructuralAssignment,
    StructuralRole,
)
from rostering.export.excel import write_roster


def test_write_roster_produces_readable_workbook_with_manual_roles(tmp_path):
    room = Room(name="S3", capacities={Role.Opravovatel: RoleCapacity(1), Role.Zaloha: RoleCapacity(0)})
    building = Building(name="Malá Strana", rooms=[room])
    helpers = [
        Helper(id=1, name="Anna"),
        Helper(id=2, name="Petr"),
    ]
    comp = Competition(buildings={"Malá Strana": building}, helpers=helpers)
    result = SolveResult(
        assignments=[
            Assignment(helper_id=1, helper_name="Anna", building="Malá Strana", room="S3", role=Role.Opravovatel),
            Assignment(helper_id=2, helper_name="Petr", building="Malá Strana", room="S3", role=Role.Zaloha),
        ],
        status="OPTIMAL",
        objective_value=0.0,
    )
    manual = ManualRoles(
        structural=[
            StructuralAssignment(role=StructuralRole.VedouciBudovy, building="Malá Strana", helper_id=1),
        ],
        # Overlay entries have no building of their own — write_roster locates
        # Petr's building via his solved assignment above.
        overlay=[OverlayAssignment(role=OverlayRole.Registrace, helper_id=2)],
    )

    out_path = tmp_path / "roster.xlsx"
    write_roster(comp, result, manual, out_path)

    assert out_path.exists()
    wb = openpyxl.load_workbook(out_path)
    assert wb.sheetnames == ["Pomocníci v místnostech", "Trička"]

    ws = wb["Pomocníci v místnostech"]
    values = {cell.value for row in ws.iter_rows() for cell in row if cell.value}
    assert "Anna" in values
    assert "Vedoucí budovy" in values
    assert any(cell.value and "Petr" in cell.value for row in ws.iter_rows() for cell in row)


def test_write_roster_merges_cells_within_one_row_only(tmp_path):
    rooms = [
        Room(
            name="R1",
            capacities={Role.Opravovatel: RoleCapacity(1), Role.Menic: RoleCapacity(1)},
        ),
        Room(
            name="R2",
            capacities={Role.Opravovatel: RoleCapacity(1), Role.Menic: RoleCapacity(1)},
        ),
    ]
    building = Building(name="B", rooms=rooms)
    helpers = [
        Helper(id=1, name="Anna"),
        Helper(id=2, name="Petr"),
        Helper(id=3, name="Klara"),
        Helper(id=4, name="David"),
    ]
    comp = Competition(buildings={"B": building}, helpers=helpers)
    result = SolveResult(
        assignments=[
            Assignment(helper_id=1, helper_name="Anna", building="B", room="R1", role=Role.Opravovatel),
            Assignment(helper_id=2, helper_name="Petr", building="B", room="R2", role=Role.Opravovatel),
            # Menic (a different row) is deliberately left unmerged, to
            # confirm the Opravovatel merge doesn't leak into other rows.
            Assignment(helper_id=3, helper_name="Klara", building="B", room="R1", role=Role.Menic),
            Assignment(helper_id=4, helper_name="David", building="B", room="R2", role=Role.Menic),
        ],
        status="OPTIMAL",
        objective_value=0.0,
    )

    out_path = tmp_path / "roster.xlsx"
    # Merge R1/R2 for the Opravovatel row only — like merging cells in
    # Excel, not the whole column.
    write_roster(comp, result, ManualRoles(), out_path, cell_merges={"Opravovatel": {"B": [["R1", "R2"]]}})

    wb = openpyxl.load_workbook(out_path)
    ws = wb["Pomocníci v místnostech"]
    values = [[cell.value for cell in row] for row in ws.iter_rows()]

    # Header room row is untouched by a row-scoped merge — still two
    # separate room columns.
    assert values[1][1] == "R1"
    assert values[1][2] == "R2"

    # Opravovatel row: R1/R2 merged into one cell for this row only — Anna
    # and Petr both land under column 1 (stacked), column 2 is empty
    # (consumed by the merge).
    opravovatel_row_idx = next(i for i, r in enumerate(values) if r[0] == "Opravovatelé")
    assert values[opravovatel_row_idx][1] == "Anna"
    assert values[opravovatel_row_idx + 1][1] == "Petr"
    assert values[opravovatel_row_idx][2] is None
    assert values[opravovatel_row_idx + 1][2] is None

    # Menic row has no merge applied — stays two separate columns.
    menic_row = next(r for r in values if r[0] == "Měniči")
    assert menic_row[1] == "Klara"
    assert menic_row[2] == "David"


def test_write_roster_ignores_stale_cell_merge_pairs(tmp_path):
    room = Room(name="S3", capacities={Role.Zaloha: RoleCapacity(0)})
    building = Building(name="B", rooms=[room])
    helpers = [Helper(id=1, name="Anna")]
    comp = Competition(buildings={"B": building}, helpers=helpers)
    result = SolveResult(
        assignments=[Assignment(helper_id=1, helper_name="Anna", building="B", room="S3", role=Role.Zaloha)],
        status="OPTIMAL",
        objective_value=0.0,
    )

    out_path = tmp_path / "roster.xlsx"
    # "S3"/"S4" aren't adjacent rooms in this building at all — must not raise.
    write_roster(comp, result, ManualRoles(), out_path, cell_merges={"Zaloha": {"B": [["S3", "S4"]]}})
    assert out_path.exists()


def test_write_roster_with_no_manual_roles(tmp_path):
    room = Room(name="S3", capacities={Role.Zaloha: RoleCapacity(0)})
    building = Building(name="B", rooms=[room])
    helpers = [Helper(id=1, name="Anna")]
    comp = Competition(buildings={"B": building}, helpers=helpers)
    result = SolveResult(
        assignments=[Assignment(helper_id=1, helper_name="Anna", building="B", room="S3", role=Role.Zaloha)],
        status="OPTIMAL",
        objective_value=0.0,
    )

    out_path = tmp_path / "roster.xlsx"
    write_roster(comp, result, ManualRoles(), out_path)

    assert out_path.exists()
    openpyxl.load_workbook(out_path)  # does not raise


# ---- "Trička" sheet ----

_TSHIRT_SHEET = "Trička"


def _tshirt_fixture(helpers, placements, manual=None, extra_buildings=()):
    """Buildings A and B (one Room each, plus any ``extra_buildings``) with
    ``placements`` = [(helper_id, building, role)] solved into them."""
    buildings = {
        "A": Building(name="A", rooms=[Room(name="A1")]),
        "B": Building(name="B", rooms=[Room(name="B1")]),
    }
    for extra in extra_buildings:
        buildings[extra.name] = extra
    comp = Competition(buildings=buildings, helpers=helpers)
    names = {h.id: h.name for h in helpers}
    result = SolveResult(
        assignments=[
            Assignment(helper_id=hid, helper_name=names[hid], building=b, room=f"{b}1", role=role)
            for hid, b, role in placements
        ],
        status="OPTIMAL",
        objective_value=0.0,
    )
    return comp, result, manual or ManualRoles()


def _read_tshirt_sheet(tmp_path, comp, result, manual):
    out_path = tmp_path / "roster.xlsx"
    write_roster(comp, result, manual, out_path)
    wb = openpyxl.load_workbook(out_path)
    assert wb.sheetnames == ["Pomocníci v místnostech", _TSHIRT_SHEET]
    return [[c.value for c in row] for row in wb[_TSHIRT_SHEET].iter_rows()]


def test_tshirt_sheet_counts_sizes_per_building_with_celkem_and_total(tmp_path):
    helpers = [
        Helper(id=1, name="Anna", tshirt_size="XL"),
        Helper(id=2, name="Petr", tshirt_size="XL"),
        Helper(id=3, name="Klara", tshirt_size="S"),
        Helper(id=4, name="David", tshirt_size="XXL"),
    ]
    comp, result, manual = _tshirt_fixture(
        helpers,
        [(1, "A", Role.Opravovatel), (2, "A", Role.Zaloha), (3, "B", Role.Menic), (4, "B", Role.Menic)],
    )
    rows = _read_tshirt_sheet(tmp_path, comp, result, manual)

    assert rows == [
        ["Velikost", "A", "B", "Celkem"],
        ["XS", 0, 0, 0],
        ["S", 0, 1, 1],
        ["M", 0, 0, 0],
        ["L", 0, 0, 0],
        ["XL", 2, 0, 2],
        ["XXL", 0, 1, 1],
        ["Celkem", 2, 2, 4],
    ]


def test_tshirt_sheet_unknown_row_appears_only_when_someone_counted_is_unknown(tmp_path):
    known = [Helper(id=1, name="Anna", tshirt_size="M")]
    comp, result, manual = _tshirt_fixture(known, [(1, "A", Role.Opravovatel)])
    rows = _read_tshirt_sheet(tmp_path, comp, result, manual)
    assert "Unknown" not in [r[0] for r in rows]

    with_unknown = [Helper(id=1, name="Anna", tshirt_size="M"), Helper(id=2, name="Petr")]
    comp, result, manual = _tshirt_fixture(
        with_unknown, [(1, "A", Role.Opravovatel), (2, "B", Role.Opravovatel)]
    )
    rows = _read_tshirt_sheet(tmp_path, comp, result, manual)
    labels = [r[0] for r in rows]
    assert labels == ["Velikost", "XS", "S", "M", "L", "XL", "XXL", "Unknown", "Celkem"]
    assert rows[labels.index("Unknown")] == ["Unknown", 0, 1, 1]
    assert rows[-1] == ["Celkem", 1, 1, 2]


def test_tshirt_sheet_only_lists_buildings_that_have_rooms(tmp_path):
    helpers = [Helper(id=1, name="Anna", tshirt_size="M")]
    comp, result, manual = _tshirt_fixture(
        helpers, [(1, "A", Role.Opravovatel)], extra_buildings=[Building(name="Empty", rooms=[])]
    )
    rows = _read_tshirt_sheet(tmp_path, comp, result, manual)
    assert rows[0] == ["Velikost", "A", "B", "Celkem"]


def test_tshirt_sheet_counts_a_helper_with_an_additional_role_once(tmp_path):
    helpers = [Helper(id=1, name="Anna", tshirt_size="M")]
    manual = ManualRoles(
        overlay=[
            OverlayAssignment(role=OverlayRole.Registrace, helper_id=1, building="A"),
            OverlayAssignment(role=OverlayRole.UvadeciUcastniku, helper_id=1, building="A", room="A1"),
        ]
    )
    comp, result, manual = _tshirt_fixture(helpers, [(1, "A", Role.Opravovatel)], manual)
    rows = _read_tshirt_sheet(tmp_path, comp, result, manual)
    assert {r[0]: r for r in rows}["M"] == ["M", 1, 0, 1]
    assert rows[-1] == ["Celkem", 1, 0, 1]


def test_tshirt_sheet_counts_a_solved_helper_who_also_holds_an_organizer_role_once(tmp_path):
    helpers = [Helper(id=1, name="Anna", tshirt_size="L")]
    manual = ManualRoles(
        structural=[
            StructuralAssignment(role=StructuralRole.VedouciBudovy, building="A", helper_id=1),
            StructuralAssignment(role=StructuralRole.TechnickaPodpora, building="A", helper_id=1),
        ]
    )
    comp, result, manual = _tshirt_fixture(helpers, [(1, "A", Role.Opravovatel)], manual)
    rows = _read_tshirt_sheet(tmp_path, comp, result, manual)
    assert {r[0]: r for r in rows}["L"] == ["L", 1, 0, 1]
    assert rows[-1] == ["Celkem", 1, 0, 1]


def test_tshirt_sheet_counts_organizer_role_holders_in_the_building_the_role_names(tmp_path):
    helpers = [
        Helper(id=1, name="Anna", tshirt_size="M"),
        Helper(id=2, name="Petr", tshirt_size="XS"),  # registered but not solved: only an organizer
    ]
    manual = ManualRoles(
        structural=[
            StructuralAssignment(role=StructuralRole.PravaRuka, building="B", room="B1", helper_id=2),
            StructuralAssignment(role=StructuralRole.VedouciBudovy, building="B", helper_name="Jiří"),
            # Same typed name again: still one person.
            StructuralAssignment(role=StructuralRole.TechnickaPodpora, building="B", helper_name="Jiří"),
        ]
    )
    comp, result, manual = _tshirt_fixture(helpers, [(1, "A", Role.Opravovatel)], manual)
    rows = _read_tshirt_sheet(tmp_path, comp, result, manual)
    by_label = {r[0]: r for r in rows}
    assert by_label["M"] == ["M", 1, 0, 1]
    assert by_label["XS"] == ["XS", 0, 1, 1]  # keeps the Helper's size
    assert by_label["Unknown"] == ["Unknown", 0, 1, 1]  # typed name
    assert rows[-1] == ["Celkem", 1, 2, 3]


def test_tshirt_sheet_does_not_count_organizer_role_entries_without_a_building(tmp_path):
    helpers = [Helper(id=1, name="Anna", tshirt_size="M"), Helper(id=2, name="Petr", tshirt_size="S")]
    manual = ManualRoles(
        structural=[
            StructuralAssignment(role=StructuralRole.VedouciBudovy, building="", helper_id=2),
            StructuralAssignment(role=StructuralRole.VedouciBudovy, building="", helper_name="Jiří"),
        ]
    )
    comp, result, manual = _tshirt_fixture(helpers, [(1, "A", Role.Opravovatel)], manual)
    rows = _read_tshirt_sheet(tmp_path, comp, result, manual)
    assert rows[-1] == ["Celkem", 1, 0, 1]
    assert "Unknown" not in [r[0] for r in rows]
