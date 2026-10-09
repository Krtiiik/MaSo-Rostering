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
    assert wb.sheetnames == ["Pomocníci v místnostech", "Trička", "Malá Strana"]

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
    assert wb.sheetnames[:2] == ["Pomocníci v místnostech", _TSHIRT_SHEET]
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


# ---- Two-column overflow for Large rooms ----

_ROSTER_SHEET = "Pomocníci v místnostech"
_ROLE_LABEL = {
    Role.Opravovatel: "Opravovatelé",
    Role.Menic: "Měniči",
    Role.Skenovac: "Skenovači",
    Role.Kreslic: "Kresliči",
    Role.Fotograf: "Fotografové",
}
_EMPTY_SLOT_RGB = "F2F2F2"


class _Sheet:
    """A written roster sheet read back through openpyxl: cell values, merged
    ranges (0-based, inclusive) and helpers to locate a Room's columns and a
    Role band's rows."""

    def __init__(self, ws):
        self.ws = ws
        self.values = [[c.value for c in row] for row in ws.iter_rows()]
        self.merges = {(m.min_row - 1, m.min_col - 1, m.max_row - 1, m.max_col - 1) for m in ws.merged_cells.ranges}

    def span(self, row, col):
        """(first col, last col) of the cell at (row, col), following a merge."""
        for r0, c0, r1, c1 in self.merges:
            if r0 <= row <= r1 and c0 <= col <= c1:
                return c0, c1
        return col, col

    def room_cols(self, room):
        return self.span(1, self.values[1].index(room))

    def room_width(self, room):
        c0, c1 = self.room_cols(room)
        return c1 - c0 + 1

    def building_cols(self, building):
        return self.span(0, self.values[0].index(building))

    def label_row(self, label):
        return next(i for i, r in enumerate(self.values) if r[0] == label)

    def band_rows(self, label):
        """(first row, last row) of the block whose label is in column 0."""
        row = self.label_row(label)
        for r0, c0, r1, c1 in self.merges:
            if c0 == 0 and c1 == 0 and r0 == row:
                return r0, r1
        return row, row

    def band(self, role, room):
        """The room's cells in the role's band, one list per row, over the
        room's columns."""
        r0, r1 = self.band_rows(_ROLE_LABEL[role])
        c0, c1 = self.room_cols(room)
        return [[self.values[r][c] for c in range(c0, c1 + 1)] for r in range(r0, r1 + 1)]

    def band_height(self, role):
        r0, r1 = self.band_rows(_ROLE_LABEL[role])
        return r1 - r0 + 1

    def is_grey(self, row, col):
        return self.ws.cell(row + 1, col + 1).fill.fgColor.rgb.endswith(_EMPTY_SLOT_RGB)

    def border(self, row, col):
        """(top, left, bottom, right) border styles of the cell at (row, col)."""
        b = self.ws.cell(row + 1, col + 1).border
        return b.top.style, b.left.style, b.bottom.style, b.right.style

    def col_width(self, col):
        """Width of column ``col`` (0-based); openpyxl groups equal adjacent columns."""
        for dim in self.ws.column_dimensions.values():
            if dim.min is not None and dim.min <= col + 1 <= dim.max:
                return dim.width
        return None


def _overflow_sheet(tmp_path, spec, *, cell_merges=None, manual=None, extra_assignments=(), minimums=None):
    """Write a roster for ``spec`` = {building: {room: {Role: count}}} (each
    count placing that many synthetic Helpers there) and read it back.
    ``extra_assignments`` = [(building, room, Role, count)]; ``minimums`` =
    {(building, room): {Role: configured minimum headcount}}."""
    buildings = {}
    helpers = []
    assignments = []

    def place(building, room, role, count):
        for _ in range(count):
            hid = len(helpers) + 1
            name = f"{room}-{role.name}-{hid}"
            helpers.append(Helper(id=hid, name=name))
            assignments.append(Assignment(helper_id=hid, helper_name=name, building=building, room=room, role=role))

    for bname, rooms in spec.items():
        buildings[bname] = Building(
            name=bname,
            rooms=[
                Room(name=r, capacities={k: RoleCapacity(n) for k, n in (minimums or {}).get((bname, r), {}).items()})
                for r in rooms
            ],
        )
        for rname, counts in rooms.items():
            for role, count in counts.items():
                place(bname, rname, role, count)
    for building, room, role, count in extra_assignments:
        place(building, room, role, count)

    comp = Competition(buildings=buildings, helpers=helpers)
    result = SolveResult(assignments=assignments, status="OPTIMAL", objective_value=0.0)
    out_path = tmp_path / "roster.xlsx"
    write_roster(comp, result, manual or ManualRoles(), out_path, cell_merges=cell_merges)
    return _Sheet(openpyxl.load_workbook(out_path)[_ROSTER_SHEET])


def _per_role(n):
    """``n`` Helpers in each of the five Room-band Roles."""
    return {Role.Opravovatel: n, Role.Menic: n, Role.Skenovac: n, Role.Kreslic: n, Role.Fotograf: n}


def _jaro_like_spec():
    """One Room with 20, an N-group Room with 19, four others with 10."""
    return {
        "Malá Strana": {"M1": _per_role(4)},
        "Karlín": {"K1": _per_role(2), "K2": _per_role(2), "K3": _per_role(2), "K4": _per_role(2)},
        "N": {"N1": {**_per_role(4), Role.Fotograf: 3}},
    }


def test_large_rooms_of_a_jaro_like_sheet_get_two_columns_and_the_rest_one(tmp_path):
    sheet = _overflow_sheet(tmp_path, _jaro_like_spec())

    assert sheet.room_width("M1") == 2
    assert sheet.room_width("N1") == 2
    for room in ("K1", "K2", "K3", "K4"):
        assert sheet.room_width(room) == 1


def test_a_uniform_sheet_has_no_large_room(tmp_path):
    spec = {"A": {f"R{i}": _per_role(2) for i in range(1, 5)}, "B": {"R5": _per_role(2)}}
    sheet = _overflow_sheet(tmp_path, spec)

    assert all(sheet.room_width(f"R{i}") == 1 for i in range(1, 6))


def _four_rooms_with_a_big_one(big):
    """Three Rooms of 4 Helpers (one per Role, Fotograf empty) and a fourth
    with ``big`` counts; the median is 4."""
    small = {Role.Opravovatel: 1, Role.Menic: 1, Role.Skenovac: 1, Role.Kreslic: 1}
    return {"A": {"S1": small, "S2": small, "S3": small}, "B": {"BIG": big}}


def test_a_room_at_exactly_one_and_a_half_times_the_median_is_large(tmp_path):
    big = {Role.Opravovatel: 2, Role.Menic: 2, Role.Skenovac: 2}  # 6 = 1.5 * 4
    sheet = _overflow_sheet(tmp_path, _four_rooms_with_a_big_one(big))

    assert sheet.room_width("BIG") == 2


def test_a_room_just_under_one_and_a_half_times_the_median_stays_one_column_with_taller_bands(tmp_path):
    big = {Role.Opravovatel: 2, Role.Menic: 1, Role.Skenovac: 1, Role.Kreslic: 1}  # 5 < 6
    sheet = _overflow_sheet(tmp_path, _four_rooms_with_a_big_one(big))

    assert sheet.room_width("BIG") == 1
    assert sheet.band_height(Role.Opravovatel) == 2


def test_a_half_integer_median_needs_no_rounding(tmp_path):
    small3 = {Role.Opravovatel: 1, Role.Menic: 1, Role.Skenovac: 1}
    small4 = {Role.Opravovatel: 1, Role.Menic: 1, Role.Skenovac: 1, Role.Kreslic: 1}

    def spec(big):
        return {"A": {"S1": small3, "S2": small3, "S3": small3, "S4": small4, "S5": small4}, "B": {"BIG": big}}

    # Sizes 3, 3, 3, 4, 4 plus the Room under test: the median is 3.5, so
    # the line is 5.25 — 6 Helpers are large, 5 are not.
    large = _overflow_sheet(tmp_path, spec({Role.Opravovatel: 3, Role.Menic: 3}))
    not_large = _overflow_sheet(tmp_path, spec({Role.Opravovatel: 3, Role.Menic: 2}))

    assert large.room_width("BIG") == 2
    assert not_large.room_width("BIG") == 1


def test_fewer_than_three_rooms_never_overflow(tmp_path):
    spec = {"A": {"R1": _per_role(1)}, "B": {"R2": _per_role(10)}}
    sheet = _overflow_sheet(tmp_path, spec)

    assert sheet.room_width("R1") == 1
    assert sheet.room_width("R2") == 1


def test_only_rooms_holding_helpers_count_toward_the_three_room_minimum(tmp_path):
    empty = {}
    spec = {"A": {"R1": {Role.Opravovatel: 2}, "R2": {Role.Opravovatel: 12}, "E1": empty, "E2": empty}}
    sheet = _overflow_sheet(tmp_path, spec)

    assert sheet.room_width("R2") == 1


def test_empty_rooms_do_not_drag_the_median_down(tmp_path):
    empty = {}
    spec = {"A": {"R1": _per_role(2), "R2": _per_role(2), "R3": _per_role(2), "E1": empty, "E2": empty, "E3": empty, "E4": empty}}
    sheet = _overflow_sheet(tmp_path, spec)

    assert all(sheet.room_width(r) == 1 for r in ("R1", "R2", "R3"))


def test_a_large_room_that_never_exceeds_the_first_column_height_stays_one_column(tmp_path):
    spec = {
        "A": {
            "S1": {Role.Opravovatel: 4},
            "S2": {Role.Menic: 4},
            "S3": {Role.Opravovatel: 1, Role.Menic: 1, Role.Skenovac: 1, Role.Kreslic: 1},
        },
        # 6 Helpers = 1.5 * median 4, but no taller in a band than the others.
        "B": {"BIG": {Role.Opravovatel: 3, Role.Menic: 3}},
    }
    sheet = _overflow_sheet(tmp_path, spec)

    assert sheet.room_width("BIG") == 1


def test_a_room_merged_with_a_neighbour_never_overflows(tmp_path):
    spec = _jaro_like_spec()
    spec["Malá Strana"] = {"M1": _per_role(4), "M2": _per_role(1)}
    spec["N"]["N1"] = _per_role(8)  # taller than the merged M1 keeps every band
    sheet = _overflow_sheet(tmp_path, spec, cell_merges={"Skenovac": {"Malá Strana": [["M1", "M2"]]}})

    assert sheet.room_width("M1") == 1
    assert sheet.room_width("M2") == 1
    assert sheet.room_width("N1") == 2  # unrelated Rooms still overflow


def test_a_room_merged_only_in_a_leader_row_never_overflows(tmp_path):
    spec = _jaro_like_spec()
    spec["Malá Strana"] = {"M1": _per_role(4), "M2": _per_role(1)}
    sheet = _overflow_sheet(tmp_path, spec, cell_merges={"PravaRuka": {"Malá Strana": [["M1", "M2"]]}})

    assert sheet.room_width("M1") == 1


def test_a_stale_merge_pair_does_not_stop_a_room_overflowing(tmp_path):
    sheet = _overflow_sheet(tmp_path, _jaro_like_spec(), cell_merges={"Opravovatel": {"Karlín": [["K1", "M1"]]}})

    assert sheet.room_width("M1") == 2


def test_zaloha_placements_do_not_count_toward_room_size(tmp_path):
    spec = {"A": {f"R{i}": _per_role(2) for i in range(1, 5)}}
    sheet = _overflow_sheet(tmp_path, spec, extra_assignments=[("A", "R1", Role.Zaloha, 30)])

    assert sheet.room_width("R1") == 1


def test_manual_roles_do_not_count_toward_room_size(tmp_path):
    spec = {"A": {f"R{i}": _per_role(2) for i in range(1, 5)}}
    manual = ManualRoles(
        structural=[
            StructuralAssignment(role=StructuralRole.VedouciMistnosti, building="A", room="R1", helper_name=f"Vedoucí {i}")
            for i in range(30)
        ]
    )
    sheet = _overflow_sheet(tmp_path, spec, manual=manual)

    assert sheet.room_width("R1") == 1


def test_a_large_room_fills_the_first_column_to_the_others_height_then_the_second(tmp_path):
    sheet = _overflow_sheet(tmp_path, _jaro_like_spec())

    # Others hold 2 per band, so K = 2: N1's 4 Opravovatelé fill two rows in
    # each of its two columns; its 3 Fotografové leave one grey slot.
    opr = sheet.band(Role.Opravovatel, "N1")
    assert len(opr) == 2
    assert all(cell and cell.startswith("N1-Opravovatel") for row in opr for cell in row)
    assert [c is None for row in sheet.band(Role.Fotograf, "N1") for c in row] == [False, False, False, True]
    assert sheet.band(Role.Fotograf, "K1")[0][0] is not None


def test_unused_second_column_slots_are_grey_in_every_band(tmp_path):
    spec = _jaro_like_spec()
    spec["Malá Strana"] = {"M1": {**_per_role(4), Role.Fotograf: 0, Role.Kreslic: 3}}
    sheet = _overflow_sheet(tmp_path, spec)

    r0, r1 = sheet.band_rows(_ROLE_LABEL[Role.Fotograf])
    c0, c1 = sheet.room_cols("M1")
    assert all(sheet.is_grey(r, c) for r in range(r0, r1 + 1) for c in (c0, c1))
    # Kreslič: 3 Helpers over K = 2 rows fill three slots; the fourth is grey.
    r0, _ = sheet.band_rows(_ROLE_LABEL[Role.Kreslic])
    assert not sheet.is_grey(r0, c1)
    assert not sheet.is_grey(r0 + 1, c0)
    assert sheet.is_grey(r0 + 1, c1)


def test_a_large_room_needing_more_than_twice_the_first_column_raises_it_instead_of_adding_a_column(tmp_path):
    small = {Role.Opravovatel: 2, Role.Menic: 2, Role.Skenovac: 2, Role.Kreslic: 2, Role.Fotograf: 2}
    spec = {
        "A": {"S1": small, "S2": small, "S3": small},
        "B": {"BIG": {**_per_role(2), Role.Opravovatel: 9}},
    }
    sheet = _overflow_sheet(tmp_path, spec)

    assert sheet.room_width("BIG") == 2
    # 9 Opravovatelé > 2 * K(2): K rises to ceil(9 / 2) = 5, for the whole sheet.
    assert sheet.band_height(Role.Opravovatel) == 5
    assert sheet.band_height(Role.Menic) == 2
    opr = sheet.band(Role.Opravovatel, "BIG")
    assert [c for row in opr for c in row].count(None) == 1
    assert opr[4][1] is None
    # The other Rooms just get taller bands, with grey padding.
    assert sheet.band(Role.Opravovatel, "S1")[4] == [None]


def test_the_first_column_height_is_sheet_wide_not_per_building(tmp_path):
    spec = _jaro_like_spec()
    spec["Karlín"]["K4"] = {**_per_role(2), Role.Opravovatel: 3}
    sheet = _overflow_sheet(tmp_path, spec)

    # K4 (a Room in another Building) is 3 tall in Opravovatel, so K = 3 for
    # M1's Opravovatel band too: its 4 Helpers are 3 + 1, not 2 + 2.
    m1 = sheet.band(Role.Opravovatel, "M1")
    assert len(m1) == 3
    assert all(row[0] for row in m1)
    assert [row[1] is not None for row in m1] == [True, False, False]


def test_room_header_and_room_scoped_leader_rows_merge_across_both_columns(tmp_path):
    manual = ManualRoles(
        structural=[
            StructuralAssignment(role=StructuralRole.VedouciMistnosti, building="Malá Strana", room="M1", helper_name="Vedoucí M1"),
            StructuralAssignment(role=StructuralRole.PravaRuka, building="Malá Strana", room="M1", helper_name="Ruka M1"),
            StructuralAssignment(role=StructuralRole.VedouciMistnosti, building="Karlín", room="K1", helper_name="Vedoucí K1"),
        ]
    )
    sheet = _overflow_sheet(tmp_path, _jaro_like_spec(), manual=manual)

    c0, c1 = sheet.room_cols("M1")
    assert c1 == c0 + 1
    for label, text in (("Vedoucí místností", "Vedoucí M1"), ("Pravá ruka", "Ruka M1")):
        row = sheet.label_row(label)
        assert sheet.values[row][c0] == text
        assert sheet.span(row, c0) == (c0, c1)
    # An ordinary Room's leader cell is still a single column.
    k0, k1 = sheet.room_cols("K1")
    row = sheet.label_row("Vedoucí místností")
    assert sheet.values[row][k0] == "Vedoucí K1"
    assert sheet.span(row, k0) == (k0, k0) and k0 == k1


def test_building_header_and_building_wide_rows_span_the_extra_column(tmp_path):
    manual = ManualRoles(
        structural=[
            StructuralAssignment(role=StructuralRole.VedouciBudovy, building="Karlín", helper_name="Vedoucí Karlín"),
            StructuralAssignment(role=StructuralRole.TechnickaPodpora, building="N", helper_name="Technik N"),
        ],
        overlay=[OverlayAssignment(role=OverlayRole.Registrace, helper_id=1)],
    )
    sheet = _overflow_sheet(
        tmp_path, _jaro_like_spec(), manual=manual, extra_assignments=[("Karlín", "K1", Role.Zaloha, 2)]
    )

    karlin = sheet.building_cols("Karlín")
    assert sheet.room_cols("K1")[0] == karlin[0]
    assert karlin[1] - karlin[0] + 1 == 4  # four single-column Rooms

    # Malá Strana and N are single-Room Buildings whose Room takes two
    # columns: their header, and every building-wide row, is a two-column cell.
    m0, m1 = sheet.building_cols("Malá Strana")
    assert m1 == m0 + 1 and sheet.room_cols("M1") == (m0, m1)
    n0, n1 = sheet.building_cols("N")
    assert n1 == n0 + 1
    for label in ("Vedoucí budovy", "Uvaděči účastníků", "Focení předávání cen", "Registrace", "Záloha", "Technická podpora"):
        row = sheet.label_row(label)
        for building in ("Malá Strana", "Karlín", "N"):
            b0, _ = sheet.building_cols(building)
            assert sheet.span(row, b0) == sheet.building_cols(building), (label, building)
    assert sheet.values[sheet.label_row("Vedoucí budovy")][karlin[0]] == "Vedoucí Karlín"


def test_a_building_mixing_a_large_room_and_ordinary_rooms_widens_only_by_one_column(tmp_path):
    spec = {
        "A": {"BIG": _per_role(4), "S1": _per_role(2), "S2": _per_role(2)},
        "B": {"S3": _per_role(2), "S4": _per_role(2)},
    }
    sheet = _overflow_sheet(tmp_path, spec)

    a0, a1 = sheet.building_cols("A")
    assert a1 - a0 + 1 == 4
    assert sheet.room_cols("BIG") == (a0, a0 + 1)
    assert sheet.room_cols("S1") == (a0 + 2, a0 + 2)
    assert sheet.building_cols("B")[0] == a1 + 1


# ---- Two-column overflow next to merged Room groups ----


def _merged_group_spec(big_opravovatel):
    """Building A: BIG (``big_opravovatel`` Opravovatelé, 4 of every other
    Role), M2 and M3 (3 Opravovatelé, 2 of every other Role) and S1 (2 of
    each). Merging M2 and M3 for Opravovatel makes a 6-tall group."""
    m = {**_per_role(2), Role.Opravovatel: 3}
    big = {**_per_role(4), Role.Opravovatel: big_opravovatel}
    return {"A": {"BIG": big, "M2": m, "M3": m, "S1": _per_role(2)}}


_MERGE_M2_M3_OPRAVOVATEL = {"Opravovatel": {"A": [["M2", "M3"]]}}


def test_a_taller_merged_group_stays_one_wide_cell_with_one_name_per_row(tmp_path):
    sheet = _overflow_sheet(tmp_path, _merged_group_spec(8), cell_merges=_MERGE_M2_M3_OPRAVOVATEL)

    r0, r1 = sheet.band_rows(_ROLE_LABEL[Role.Opravovatel])
    m2, m3 = sheet.room_cols("M2")[0], sheet.room_cols("M3")[0]
    assert (r1 - r0 + 1, m3 - m2) == (6, 1)
    for r in range(r0, r1 + 1):
        assert sheet.span(r, m2) == (m2, m3)
        assert sheet.values[r][m2]
    assert sheet.values[r0][m2].startswith("M2-")
    assert sheet.values[r0 + 3][m2].startswith("M3-")


def test_a_large_room_fills_its_first_column_to_a_taller_merged_groups_height(tmp_path):
    sheet = _overflow_sheet(tmp_path, _merged_group_spec(8), cell_merges=_MERGE_M2_M3_OPRAVOVATEL)

    assert sheet.room_width("BIG") == 2
    # The merged group makes the band 6 tall (BIG alone would need only
    # ceil(8 / 2) = 4): BIG's first column takes six names, the second the
    # remaining two, and the unused second-column slots stay grey.
    opr = sheet.band(Role.Opravovatel, "BIG")
    assert len(opr) == 6
    assert all(row[0] for row in opr)
    assert [row[1] is not None for row in opr] == [True, True, False, False, False, False]
    r0, _ = sheet.band_rows(_ROLE_LABEL[Role.Opravovatel])
    c0, c1 = sheet.room_cols("BIG")
    assert [sheet.is_grey(r0 + i, c1) for i in range(6)] == [False, False, True, True, True, True]
    assert not any(sheet.is_grey(r0 + i, c0) for i in range(6))


def test_a_merged_group_only_stretches_its_own_band(tmp_path):
    sheet = _overflow_sheet(tmp_path, _merged_group_spec(8), cell_merges=_MERGE_M2_M3_OPRAVOVATEL)

    assert sheet.band_height(Role.Opravovatel) == 6
    for role in (Role.Menic, Role.Skenovac, Role.Kreslic, Role.Fotograf):
        assert sheet.band_height(role) == 2, role
    # BIG still splits those bands over its two columns.
    assert all(cell for row in sheet.band(Role.Menic, "BIG") for cell in row)


def test_a_room_merged_in_one_band_stays_one_column_in_every_band(tmp_path):
    # BIG and M2 would both be Large; M2 is merged with S1 for Menič only.
    spec = {"A": {"BIG": _per_role(8), "M2": _per_role(4), "S1": _per_role(2), "S2": _per_role(2), "S3": _per_role(2)}}
    sheet = _overflow_sheet(tmp_path, spec, cell_merges={"Menic": {"A": [["M2", "S1"]]}})

    assert sheet.room_width("M2") == 1
    assert sheet.room_width("S1") == 1
    assert sheet.room_width("BIG") == 2  # the unmerged neighbour is unaffected
    for role in _ROLE_LABEL:  # M2 is one column in every band, not just Menič
        assert len(sheet.band(role, "M2")[0]) == 1


def test_merges_elsewhere_neither_stop_a_large_room_overflowing_nor_stretch_other_bands(tmp_path):
    spec = _merged_group_spec(8)
    spec["B"] = {"T1": _per_role(2), "T2": _per_role(2)}
    merges = {"Opravovatel": {"B": [["T1", "T2"]]}, "Menic": {"A": [["M2", "M3"]]}}
    sheet = _overflow_sheet(tmp_path, spec, cell_merges=merges)

    assert sheet.room_width("BIG") == 2
    assert sheet.band_height(Role.Menic) == 4  # M2 + M3: 2 + 2
    assert sheet.band_height(Role.Opravovatel) == 4  # T1 + T2 and BIG's ceil(8 / 2); M2 and M3 stay apart here
    assert sheet.band_height(Role.Skenovac) == 2


def test_a_large_room_that_only_looks_tall_beside_a_merged_group_stays_one_column(tmp_path):
    one = {Role.Opravovatel: 1, Role.Menic: 1, Role.Skenovac: 1, Role.Kreslic: 1}
    big = {Role.Opravovatel: 3, Role.Menic: 1, Role.Skenovac: 1, Role.Kreslic: 1}
    spec = {"A": {"BIG": big, "M1": one, "M2": one, "M3": one}}
    sheet = _overflow_sheet(tmp_path, spec, cell_merges={"Opravovatel": {"A": [["M1", "M2"], ["M2", "M3"]]}})

    # M1 + M2 + M3 stand 3 tall in Opravovatel, so BIG's three Opravovatelé
    # already fit its first column: no second column is needed.
    assert sheet.band_height(Role.Opravovatel) == 3
    assert sheet.room_width("BIG") == 1


def test_a_merged_groups_configured_minimums_stretch_the_band_a_large_room_fills(tmp_path):
    one = {Role.Opravovatel: 1, Role.Menic: 1, Role.Skenovac: 1, Role.Kreslic: 1}
    big = {Role.Opravovatel: 3, Role.Menic: 1, Role.Skenovac: 1, Role.Kreslic: 1}
    spec = {"A": {"BIG": big, "M1": one, "M2": one, "M3": one}}
    minimums = {("A", "M1"): {Role.Opravovatel: 2}, ("A", "M2"): {Role.Opravovatel: 2}}
    sheet = _overflow_sheet(
        tmp_path, spec, cell_merges={"Opravovatel": {"A": [["M1", "M2"]]}}, minimums=minimums
    )

    assert sheet.band_height(Role.Opravovatel) == 4  # 2 + 2 minimums in the merged cell
    assert sheet.room_width("BIG") == 1


def _assert_borders(sheet, bands):
    """Every visual cell in each (first row, last row) block has a medium
    border on the block's outer rows and on its Building's outer columns, and
    thin borders everywhere else."""
    spans = [sheet.building_cols(b) for b in sheet.values[0][1:] if b]
    for r0, r1 in bands:
        for r in range(r0, r1 + 1):
            for b0, b1 in spans:
                c = b0
                while c <= b1:
                    c0, c1 = sheet.span(r, c)
                    top, left, bottom, _ = sheet.border(r, c0)
                    right = sheet.border(r, c1)[3]
                    assert top == ("medium" if r == r0 else "thin"), (r, c0)
                    assert bottom == ("medium" if r == r1 else "thin"), (r, c0)
                    assert left == ("medium" if c0 == b0 else "thin"), (r, c0)
                    assert right == ("medium" if c1 == b1 else "thin"), (r, c1)
                    c = c1 + 1


def test_borders_stay_medium_around_buildings_and_bands_and_thin_inside_with_overflow_and_merges(tmp_path):
    spec = _merged_group_spec(8)
    spec["B"] = {"T1": _per_role(2), "T2": _per_role(2), "T3": _per_role(2)}
    merges = {"Opravovatel": {"A": [["M2", "M3"]]}, "Menic": {"B": [["T1", "T2"]]}}
    manual = ManualRoles(
        structural=[StructuralAssignment(role=StructuralRole.VedouciMistnosti, building="A", room="BIG", helper_name="Vedoucí")]
    )
    sheet = _overflow_sheet(tmp_path, spec, cell_merges=merges, manual=manual)

    bands = [sheet.band_rows(_ROLE_LABEL[role]) for role in _ROLE_LABEL]
    leader = sheet.label_row("Vedoucí místností")
    _assert_borders(sheet, bands + [(leader, leader)])
    # The Room header keeps its medium bottom border across both columns.
    c0, c1 = sheet.room_cols("BIG")
    assert sheet.border(1, c0)[2] == "medium" and sheet.border(1, c1)[2] == "medium"
    assert sheet.border(1, c0)[1] == "medium"  # left edge of Building A
    assert sheet.border(1, c1)[3] == "thin"  # BIG is not the last Room of A


def test_a_large_room_ending_a_building_closes_it_with_a_medium_right_border(tmp_path):
    spec = {"A": {"S1": _per_role(2), "S2": _per_role(2)}, "B": {"S3": _per_role(2), "BIG": _per_role(4)}}
    sheet = _overflow_sheet(tmp_path, spec)

    b0, b1 = sheet.building_cols("B")
    c0, c1 = sheet.room_cols("BIG")
    assert c1 == b1 and c1 == c0 + 1
    r0, r1 = sheet.band_rows(_ROLE_LABEL[Role.Opravovatel])
    for r in range(r0, r1 + 1):
        assert sheet.border(r, c0)[3] == "thin"  # between BIG's two columns
        assert sheet.border(r, c1)[3] == "medium"
        assert sheet.border(r, c0)[1] == "thin"  # after S3
    _assert_borders(sheet, [(r0, r1)])


def test_column_widths_fit_the_names_in_both_columns_of_a_large_room(tmp_path):
    long_name = "Vedoucí s velmi dlouhým jménem"
    manual = ManualRoles(
        structural=[StructuralAssignment(role=StructuralRole.PravaRuka, building="A", room="S1", helper_name=long_name)]
    )
    sheet = _overflow_sheet(tmp_path, _merged_group_spec(8), cell_merges=_MERGE_M2_M3_OPRAVOVATEL, manual=manual)

    r0, r1 = sheet.band_rows(_ROLE_LABEL[Role.Opravovatel])
    c0, c1 = sheet.room_cols("BIG")
    for c in range(c0, c1 + 1):
        longest = max(len(sheet.values[r][c]) for r in range(r0, r1 + 1) if sheet.values[r][c])
        assert sheet.col_width(c) >= longest, c
    assert sheet.col_width(sheet.room_cols("S1")[0]) >= len(long_name)
    assert sheet.col_width(0) >= len("Focení předávání cen")


# ---- Per-Building helper-list sheets ----

_LIST_HEADER = ["Jméno", "Velikost trička", "Místnost", "Role"]


def _lists_fixture(buildings, helpers, placements, manual=None):
    """``buildings`` = {building name: [room names]} (config order);
    ``placements`` = [(helper_id, building, room, role)] solved."""
    comp = Competition(
        buildings={b: Building(name=b, rooms=[Room(name=r) for r in rooms]) for b, rooms in buildings.items()},
        helpers=helpers,
    )
    names = {h.id: h.name for h in helpers}
    result = SolveResult(
        assignments=[
            Assignment(helper_id=hid, helper_name=names[hid], building=b, room=r, role=role)
            for hid, b, r, role in placements
        ],
        status="OPTIMAL",
        objective_value=0.0,
    )
    return comp, result, manual or ManualRoles()


def _read_lists(tmp_path, comp, result, manual):
    """The written workbook's sheet names and, per list sheet, its rows."""
    out_path = tmp_path / "roster.xlsx"
    write_roster(comp, result, manual, out_path)
    wb = openpyxl.load_workbook(out_path)
    rows = {
        name: [[c.value for c in row] for row in wb[name].iter_rows()]
        for name in wb.sheetnames[2:]
    }
    return wb.sheetnames, rows


def test_a_list_sheet_per_building_with_rooms_follows_the_tshirt_sheet_in_config_order(tmp_path):
    comp, result, manual = _lists_fixture(
        {"Zeta": ["Z1"], "Empty": [], "Alfa": ["A1"]},
        [Helper(id=1, name="Anna", tshirt_size="M")],
        [(1, "Alfa", "A1", Role.Opravovatel)],
    )
    sheetnames, rows = _read_lists(tmp_path, comp, result, manual)

    assert sheetnames == ["Pomocníci v místnostech", "Trička", "Zeta", "Alfa"]
    assert rows["Zeta"] == [_LIST_HEADER]  # nobody there: just the header
    assert rows["Alfa"] == [_LIST_HEADER, ["Anna", "M", "A1", "Opravovatel"]]


def test_a_list_row_shows_name_size_room_and_role_without_phone_or_equipment_tags(tmp_path):
    helpers = [
        Helper(id=1, name="Anna Nováková", tshirt_size="XL", can_bring_notebook=True, can_bring_camera=True),
        Helper(id=2, name="Petr"),  # size Unknown
    ]
    comp, result, manual = _lists_fixture(
        {"A": ["A1", "A2"]},
        helpers,
        [(1, "A", "A2", Role.Menic), (2, "A", "A1", Role.Zaloha)],
    )
    _, rows = _read_lists(tmp_path, comp, result, manual)

    assert rows["A"] == [
        _LIST_HEADER,
        ["Anna Nováková", "XL", "A2", "Měnič"],  # no "(n, f)" tag
        ["Petr", "Unknown", "A1", "Záloha"],
    ]


def test_list_names_sort_by_czech_collation_regardless_of_locale(tmp_path):
    names = [
        "Zdeněk", "Šárka", "Sára", "Řehoř", "Rosa", "Ivo", "Chytrý", "Hana", "Čáp", "Cyril",
        "Álex", "Alex", "Adam", "Ábel", "beata", "Milan", "Mika", "Michal", "Mihal",
    ]
    helpers = [Helper(id=i, name=n, tshirt_size="M") for i, n in enumerate(names, start=1)]
    comp, result, manual = _lists_fixture(
        {"A": ["A1"]}, helpers, [(h.id, "A", "A1", Role.Zaloha) for h in helpers]
    )
    _, rows = _read_lists(tmp_path, comp, result, manual)

    # Diacritics only break ties (Ábel < Adam because b < d); "ch" is its own
    # letter between h and i; č, ř, š, ž are letters of their own; case is
    # ignored (beata between Alex and Cyril).
    assert [r[0] for r in rows["A"][1:]] == [
        "Ábel", "Adam", "Alex", "Álex", "beata", "Cyril", "Čáp", "Hana", "Chytrý",
        "Ivo", "Mihal", "Michal", "Mika", "Milan", "Rosa", "Řehoř", "Sára", "Šárka", "Zdeněk",
    ]


def test_list_sorting_uses_the_full_name_as_entered(tmp_path):
    names = ["Petr Adamec", "Anna Zelená", "Anna  Bílá", " Zoe", "Anna"]
    helpers = [Helper(id=i, name=n, tshirt_size="S") for i, n in enumerate(names, start=1)]
    comp, result, manual = _lists_fixture(
        {"A": ["A1"]}, helpers, [(h.id, "A", "A1", Role.Zaloha) for h in helpers]
    )
    _, rows = _read_lists(tmp_path, comp, result, manual)

    # No surname heuristic: plain left-to-right on the whole string, spaces
    # ahead of letters. The name is written exactly as entered.
    assert [r[0] for r in rows["A"][1:]] == [" Zoe", "Anna", "Anna  Bílá", "Anna Zelená", "Petr Adamec"]


def test_list_shows_organizer_roles_and_leaves_room_empty_at_building_level(tmp_path):
    helpers = [
        Helper(id=1, name="Anna", tshirt_size="M"),
        Helper(id=2, name="Petr", tshirt_size="XS"),  # registered, not solved: only an organizer
    ]
    manual = ManualRoles(
        structural=[
            StructuralAssignment(role=StructuralRole.VedouciBudovy, building="B", helper_id=2),
            StructuralAssignment(role=StructuralRole.PravaRuka, building="B", room="B2", helper_name="Jiří"),
            StructuralAssignment(role=StructuralRole.TechnickaPodpora, building="", helper_name="Nikdo"),
        ]
    )
    comp, result, manual = _lists_fixture(
        {"A": ["A1"], "B": ["B1", "B2"]}, helpers, [(1, "A", "A1", Role.Opravovatel)], manual
    )
    _, rows = _read_lists(tmp_path, comp, result, manual)

    assert rows["A"] == [_LIST_HEADER, ["Anna", "M", "A1", "Opravovatel"]]
    assert rows["B"] == [
        _LIST_HEADER,
        ["Jiří", "Unknown", "B2", "Pravá ruka"],  # typed name: size Unknown
        ["Petr", "XS", None, "Vedoucí budovy"],  # Building level only: no Room
    ]


def test_a_person_is_listed_once_whatever_roles_they_hold(tmp_path):
    helpers = [Helper(id=1, name="Anna", tshirt_size="L")]
    manual = ManualRoles(
        structural=[
            StructuralAssignment(role=StructuralRole.VedouciBudovy, building="A", helper_id=1),
            StructuralAssignment(role=StructuralRole.TechnickaPodpora, building="A", helper_id=1),
            StructuralAssignment(role=StructuralRole.VedouciBudovy, building="A", helper_name="Jiří"),
            StructuralAssignment(role=StructuralRole.TechnickaPodpora, building="A", helper_name="  jiri "),
        ],
        overlay=[
            OverlayAssignment(role=OverlayRole.Registrace, helper_id=1, building="A"),
            OverlayAssignment(role=OverlayRole.UvadeciUcastniku, helper_id=1, building="A", room="A1"),
        ],
    )
    comp, result, manual = _lists_fixture({"A": ["A1"], "B": ["B1"]}, helpers, [(1, "A", "A1", Role.Skenovac)], manual)
    _, rows = _read_lists(tmp_path, comp, result, manual)

    assert rows["B"] == [_LIST_HEADER]
    # A solved Helper who is also an Organizer-role holder is shown by their
    # Organizer role(s), in the Room they are solved into.
    assert rows["A"] == [
        _LIST_HEADER,
        ["Anna", "L", "A1", "Vedoucí budovy, Technická podpora"],
        ["Jiří", "Unknown", None, "Vedoucí budovy, Technická podpora"],
    ]


def test_list_sheet_names_drop_forbidden_characters_and_fit_excels_limit(tmp_path):
    long_name = "Budova s velmi dlouhým názvem, který se nevejde"
    comp, result, manual = _lists_fixture(
        {"A/B\\C?D*E[F]G:H": ["R1"], long_name: ["R2"]},
        [Helper(id=1, name="Anna", tshirt_size="M")],
        [(1, long_name, "R2", Role.Opravovatel)],
    )
    sheetnames, rows = _read_lists(tmp_path, comp, result, manual)

    assert sheetnames[2:] == ["ABCDEFGH", long_name[:31]]
    assert len(sheetnames[3]) == 31
    assert rows[long_name[:31]][1][0] == "Anna"


def test_colliding_list_sheet_names_are_made_unique_within_the_limit(tmp_path):
    shared = "Velmi dlouhá budova číslo"  # 25 chars
    buildings = {
        shared + " jedna": ["R1"],  # cut to 31 chars ...
        shared + " jedna a další": ["R2"],  # ... the same 31 chars
        "X:Y": ["R3"],  # ... "XY"
        "X/Y": ["R4"],  # ... "XY" again
        "xy": ["R5"],  # Excel names ignore case: collides with "XY"
    }
    comp, result, manual = _lists_fixture(buildings, [], [])
    sheetnames, _ = _read_lists(tmp_path, comp, result, manual)

    listed = sheetnames[2:]
    assert len(listed) == 5
    assert len({n.lower() for n in sheetnames}) == len(sheetnames)
    assert all(len(n) <= 31 for n in listed)
    assert listed[0] == (shared + " jedna a další")[:31]  # first keeps its plain cut name
    assert listed[2] == "XY"
    assert listed[3].startswith("XY") and listed[3] != "XY"


def test_list_sheet_names_never_collide_with_the_roster_or_tshirt_sheets(tmp_path):
    comp, result, manual = _lists_fixture(
        {"Trička": ["R1"], "trička": ["R2"], "Pomocníci v místnostech": ["R3"], "'": ["R4"], "???": ["R5"]},
        [],
        [],
    )
    sheetnames, _ = _read_lists(tmp_path, comp, result, manual)

    assert sheetnames[:2] == ["Pomocníci v místnostech", "Trička"]
    assert len(sheetnames) == 7
    assert len({n.lower() for n in sheetnames}) == 7
    assert all(n and len(n) <= 31 and not n.startswith("'") and not n.endswith("'") for n in sheetnames)


def test_configured_minimums_that_make_the_first_column_tall_enough_keep_a_large_room_one_column(tmp_path):
    # Ordinary Rooms hold 2 per band but are configured for 4, so every band is
    # 4 rows tall: M1's 4 Helpers per band all fit the first column, and a
    # second column would stay empty.
    spec = _jaro_like_spec()
    minimums = {(b, r): {role: 4 for role in _per_role(1)} for b, rooms in spec.items() for r in rooms if r.startswith("K")}
    sheet = _overflow_sheet(tmp_path, spec, minimums=minimums)

    assert sheet.room_width("M1") == 1
    assert sheet.band_height(Role.Opravovatel) == 4
    assert all(cell is not None for row in sheet.band(Role.Opravovatel, "M1") for cell in row)


def test_a_large_room_taller_than_the_minimum_height_still_gets_a_filled_second_column(tmp_path):
    spec = _jaro_like_spec()
    spec["Malá Strana"]["M1"] = _per_role(6)
    minimums = {(b, r): {role: 2 for role in _per_role(1)} for b, rooms in spec.items() for r in rooms if r.startswith("K")}
    sheet = _overflow_sheet(tmp_path, spec, minimums=minimums)

    assert sheet.room_width("M1") == 2
    opr = sheet.band(Role.Opravovatel, "M1")
    assert len(opr) == 3
    assert all(cell is not None for row in opr for cell in row)


def test_a_large_room_no_taller_than_a_merged_neighbours_unmerged_bands_stays_one_column(tmp_path):
    # M1 is Large but merged, so it stays one column and keeps every band 4 rows
    # tall; N1's 4 Helpers per band then fit a single column.
    spec = _jaro_like_spec()
    spec["Malá Strana"] = {"M1": _per_role(4), "M2": _per_role(1)}
    sheet = _overflow_sheet(tmp_path, spec, cell_merges={"Skenovac": {"Malá Strana": [["M1", "M2"]]}})

    assert sheet.room_width("N1") == 1
