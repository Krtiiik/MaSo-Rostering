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
    assert wb.sheetnames == ["Pomocníci v místnostech"]

    ws = wb["Pomocníci v místnostech"]
    values = {cell.value for row in ws.iter_rows() for cell in row if cell.value}
    assert "Anna" in values
    assert "Vedoucí budovy" in values
    assert any(cell.value and "Petr" in cell.value for row in ws.iter_rows() for cell in row)


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
