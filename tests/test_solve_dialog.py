"""The undismissible dialog a Solve runs in (rendered headlessly with AppTest)."""
from streamlit.testing.v1 import AppTest


def _app(failure: str = ""):
    import streamlit as st

    from rostering.webapp import mutations
    from rostering.streamlit_app import solve_prompt

    def work() -> None:
        st.session_state["worked"] = st.session_state.get("worked", 0) + 1
        if failure == "rostering":
            raise mutations.RosteringError("No roster found within 60 seconds")
        if failure == "crash":
            raise RuntimeError("boom")

    if st.button("go"):
        solve_prompt.request_place(work)
    solve_prompt.run_pending()


def _run(failure: str) -> AppTest:
    at = AppTest.from_function(_app, kwargs={"failure": failure}, default_timeout=30).run()
    at.button[0].click().run()
    return at


def test_a_finished_solve_closes_its_dialog_by_itself():
    at = _run("")
    assert at.session_state["worked"] == 1
    assert not at.error


def test_a_failed_solve_keeps_the_dialog_open_with_the_message_and_a_close_button():
    at = _run("rostering")
    assert [e.value for e in at.error] == ["No roster found within 60 seconds"]
    assert [b.label for b in at.button if b.key == "solve_error_close"] == ["Zavřít"]


def test_an_unexpected_error_never_leaves_the_dialog_stuck():
    at = _run("crash")
    assert [e.value for e in at.error] == ["Neočekávaná chyba: boom"]


def test_closing_the_error_does_not_run_the_work_again():
    at = _run("rostering")
    close = next(b for b in at.button if b.key == "solve_error_close")
    close.click().run()
    assert at.session_state["worked"] == 1
    assert not at.error
