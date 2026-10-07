from rostering.streamlit_app import reveal


def test_windows_selects_the_file_in_explorer(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(reveal.sys, "platform", "win32")
    monkeypatch.setattr(reveal.subprocess, "Popen", lambda args: calls.append(args))
    path = tmp_path / "Rozdělení pomocníků Praha - 2026-podzim.xlsx"

    reveal.reveal_in_file_manager(path)

    assert calls == [f'explorer /select,"{path.resolve()}"']


def test_macos_reveals_the_file_in_finder(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(reveal.sys, "platform", "darwin")
    monkeypatch.setattr(reveal.subprocess, "Popen", lambda args: calls.append(args))

    reveal.reveal_in_file_manager(tmp_path / "a.xlsx")

    assert calls == [["open", "-R", str((tmp_path / "a.xlsx").resolve())]]
