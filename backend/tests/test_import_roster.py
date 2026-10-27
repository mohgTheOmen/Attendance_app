from openpyxl import Workbook

from app.import_roster import read_roster


def test_read_roster_accepts_both_sheet_layouts(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Group 1241EA", None, None])
    ws.append(["NrCrt", "Nume", "Grupa"])
    ws.append([1, "POPESCU A. Ana", "1241EA"])
    ws.append([None, None, None])
    ws.append(["Nr Crt", "Grupa", "Numele și prenumele studentului"])
    ws.append([1, "Grupa 1280", "SMITH John"])
    ws.append([2, "Grupa 1281", "DOE Jane"])
    path = tmp_path / "roster.xlsx"
    wb.save(path)

    assert read_roster(path) == [
        ("POPESCU A. Ana", "1241EA"),
        ("SMITH John", "1280"),
        ("DOE Jane", "1281"),
    ]
