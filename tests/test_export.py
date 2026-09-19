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
    room = Room(name="S3", capacities={Role.Opravovatel: RoleCapacity(1, None), Role.Zaloha: RoleCapacity(0, None)})
    building = Building(name="Malá Strana", rooms=[room])
    helpers = [
        Helper(id=1, name="Anna"),
        Helper(id=2, name="Petr"),
    ]
    comp = Competition(buildings={"Malá Strana": building}, helpers=helpers)
    result = SolveResult(
        assignments=[
            Assignment(helper_id=1, helper_name="Anna", building="Malá Strana", room="S3", role=Role.Opravovatel),
        ],
        status="OPTIMAL",
        objective_value=0.0,
    )
    manual = ManualRoles(
        structural=[
            StructuralAssignment(role=StructuralRole.VedouciBudovy, building="Malá Strana", helper_id=1),
        ],
        overlay=[OverlayAssignment(role=OverlayRole.Registrace, helper_id=2)],
    )

    out_path = tmp_path / "roster.xlsx"
    write_roster(comp, result, manual, out_path)

    assert out_path.exists()
    wb = openpyxl.load_workbook(out_path)
    assert "Roster" in wb.sheetnames
    assert "Registrace a predavani cen" in wb.sheetnames

    roster_ws = wb["Roster"]
    values = {cell.value for row in roster_ws.iter_rows() for cell in row if cell.value}
    assert "Anna" in values
    assert "Vedoucí budovy" in values

    overlay_ws = wb["Registrace a predavani cen"]
    overlay_values = [cell.value for row in overlay_ws.iter_rows() for cell in row if cell.value]
    assert "Petr" in overlay_values


def test_write_roster_with_no_manual_roles(tmp_path):
    room = Room(name="S3", capacities={Role.Zaloha: RoleCapacity(0, None)})
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
