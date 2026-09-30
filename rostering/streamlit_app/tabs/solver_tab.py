"""Tab 5: solver settings (weights, role costs, time limit, friend scoring)."""
from __future__ import annotations

import streamlit as st

from rostering.persistence.serialize import solver_config_from_dict, solver_config_to_dict
from rostering.solver.model import MAX_ROLE_COST, SolverConfig
from rostering.streamlit_app import labels, mutations, session, solve_prompt

# The five Preference costs in the order the fields are shown, one slider row
# each: (RoleCosts field, label, widget key).
_PREFERENCE_COST_FIELDS = [
    ("ano", "Ano", "w_cost_ano"),
    ("klidne", "Klidně", "w_cost_klidne"),
    ("nevadi", "Nevadí", "w_cost_nevadi"),
    ("spise_ne", "Spíš ne", "w_cost_spise_ne"),
    ("ne", "Ne", "w_cost_ne"),
]
# Záloha is not a Preference option, so its cost sits outside the slider rows.
_ZALOHA_COST_FIELD = ("zaloha", "Záloha", "w_cost_zaloha")
_ROLE_COST_FIELDS = [*_PREFERENCE_COST_FIELDS, _ZALOHA_COST_FIELD]
_ROLE_COST_UNIT_KEY = "w_role_cost_unit"


def _stars(count: int) -> str:
    """``count`` of the five stars filled, the rest outlined (Streamlit markdown
    colours, so it works inside a widget label)."""
    return f":orange[{'★' * count}]:gray[{'☆' * (len(_PREFERENCE_COST_FIELDS) - count)}]"


def _cost_row(role_costs: dict, field: str, label: str, key: str, stars: str = "") -> None:
    """One cost as a label (with its stars, when it is a Preference) on the
    left and a 0 to ``MAX_ROLE_COST`` slider on the right, written to the draft."""
    label_col, slider_col = st.columns([1, 4], vertical_alignment="center")
    label_col.markdown(f"**{label}** {stars}".rstrip())
    # A cost saved above the slider's range is shown (and saved again) at the top.
    st.session_state.setdefault(key, min(int(role_costs[field]), MAX_ROLE_COST))
    role_costs[field] = slider_col.slider(
        label, min_value=0, max_value=MAX_ROLE_COST, step=1, key=key, label_visibility="collapsed"
    )


def _ensure_draft(state: dict) -> None:
    # Read through the loader so a config saved before the role cost table
    # existed (or with keys missing) is shown with the solver defaults filled in.
    st.session_state.setdefault(
        "solver_config_draft", solver_config_to_dict(solver_config_from_dict(state["solver_config"]))
    )


def _restore_role_cost_defaults() -> None:
    """Put the role cost unit and the six rating costs back to the solver's
    defaults, in the draft (the widgets follow it)."""
    defaults = solver_config_to_dict(SolverConfig())
    draft = st.session_state["solver_config_draft"]
    draft["weights"]["role_cost_unit"] = defaults["weights"]["role_cost_unit"]
    draft["role_costs"] = dict(defaults["role_costs"])
    # Dropping a number input's own state makes it re-read the draft's value. A
    # slider keeps the value the browser holds for it instead, so its state is
    # set outright (this runs before the script, so that is allowed).
    st.session_state.pop(_ROLE_COST_UNIT_KEY, None)
    for field, _label, key in _ROLE_COST_FIELDS:
        st.session_state[key] = defaults["role_costs"][field]


def clear_drafts() -> None:
    st.session_state.pop("solver_config_draft", None)
    # The sliders are driven by their state, so another Season's draft must not
    # meet the previous one's values.
    for _field, _label, key in _ROLE_COST_FIELDS:
        st.session_state.pop(key, None)


def render() -> None:
    st.header(labels.TAB_SOLVER)
    st.write("Jak rozřazování váží preference budovy, přání kamarádů a preference rolí a jak dlouho smí hledat.")

    state = session.get_state()
    _ensure_draft(state)
    solver_config: dict = st.session_state["solver_config_draft"]

    st.subheader("Váhy")
    weights = solver_config["weights"]
    weight_cols = st.columns(2)
    weights["building_mismatch"] = weight_cols[0].number_input(
        "Váha nesplněné preference budovy", value=int(weights["building_mismatch"]), key="w_building"
    )
    weights["friend_unsatisfied"] = weight_cols[1].number_input(
        "Váha nesplněného přání kamaráda", value=int(weights["friend_unsatisfied"]), key="w_friend"
    )

    st.markdown("**Ceny rolí**")
    st.caption(
        "Kolik stojí zařazení pomocníka do role podle toho, jak ji ohodnotil (prázdná odpověď se počítá jako Nevadí; "
        "Záloha nemá hodnocení, má proto vlastní cenu). Jednotka škáluje všechny ceny; "
        "zvyšte ji, aby preference rolí vážily víc než budova a přání kamarádů. "
        f"Každá cena je 0 až {MAX_ROLE_COST}."
    )
    role_costs = solver_config["role_costs"]
    weights["role_cost_unit"] = st.number_input(
        "Jednotka cen rolí",
        min_value=0,
        step=1,
        value=int(weights["role_cost_unit"]),
        key=_ROLE_COST_UNIT_KEY,
    )

    for position, (field, label, key) in enumerate(_PREFERENCE_COST_FIELDS):
        _cost_row(role_costs, field, label, key, stars=_stars(len(_PREFERENCE_COST_FIELDS) - position))
    _cost_row(role_costs, *_ZALOHA_COST_FIELD)
    st.button("Obnovit výchozí ceny rolí", on_click=_restore_role_cost_defaults, key="w_restore_role_costs")

    solver_config["time_limit_seconds"] = st.number_input(
        "Časový limit (sekundy)",
        min_value=1,
        value=int(solver_config.get("time_limit_seconds", 10)),
        key="w_time_limit",
        help="Jak dlouho smí sestavování hledat. Skončí-li bez nalezeného rozdělení, zvyšte limit a sestavte znovu.",
    )
    friend_scoring = solver_config["friend_scoring"]
    friend_scoring["mode"] = st.selectbox(
        "Způsob hodnocení kamarádů",
        options=["pairwise", "mutual"],
        index=["pairwise", "mutual"].index(friend_scoring["mode"]),
        format_func=lambda m: "Po dvojicích (každé přání se hodnotí zvlášť)" if m == "pairwise" else "Jen vzájemná (oba se musí navzájem uvést)",
        key="w_mode",
    )
    friend_scoring["symmetric"] = st.checkbox(
        "Symetricky (vzájemná dvojice se hodnotí jako jedno přání, ne dvě)",
        value=friend_scoring["symmetric"],
        key="w_symmetric",
    )

    with st.bottom:
        action_cols = st.columns(2)
        if action_cols[0].button("Uložit parametry", key="solver_save"):
            try:
                session.set_state(mutations.put_solver_config(session.get_workspace(), solver_config))
                st.success("Parametry rozřazování uloženy.")
            except mutations.RosteringError as exc:
                st.error(str(exc))

        disabled = not state["helpers"]
        if action_cols[1].button("Uložit a sestavit rozdělení", type="primary", disabled=disabled, key="solver_save_solve"):
            try:
                saved = mutations.put_solver_config(session.get_workspace(), solver_config)
            except mutations.RosteringError as exc:
                st.error(str(exc))
            else:
                session.set_state(saved)
                solve_prompt.request_solve(saved, solve_prompt.solve_and_open_roster)
        if disabled:
            st.caption("Nejdřív nahrajte odpovědi pomocníků.")
