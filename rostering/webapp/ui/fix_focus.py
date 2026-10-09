"""The "Go fix" hand-off from a Broken rule to the tab where it is fixed.

"Go fix" switches tab and *preselects the entity*: the target tab shows what to
fix (a callout naming the rule, and a marker on the Building / person / Tag /
group), for as long as that rule instance is still broken — once the rule holds
again the focus disappears by itself.
"""
from __future__ import annotations

from typing import Optional

from nicegui import ui

from rostering.domain import BrokenRule, FixTarget
from rostering.webapp import labels, mutations
from rostering.webapp.ui.session import FixFocus, UiSession

# Logical FixTarget.tab -> the tab it is fixed on. A rule family whose tab does
# not exist has no entry, hence no "Go fix" button.
TAB_LABELS = {
    "buildings": labels.TAB_BUILDINGS,
    "helpers": labels.TAB_PEOPLE,
    "tags": labels.TAB_TAGS,
    "forced_friends": labels.TAB_FORCED,
}


def can_go_fix(broken: BrokenRule) -> bool:
    return broken.fix is not None and broken.fix.tab in TAB_LABELS


def go_fix(session: UiSession, broken: BrokenRule) -> None:
    """Remember what to preselect and switch to the rule's fix tab."""
    assert broken.fix is not None
    session.view.fix_focus = FixFocus(
        kind=broken.instance.kind, entity=tuple(broken.instance.entity), line=broken.line, fix=broken.fix
    )
    if broken.fix.tab == "tags" and broken.fix.tag_id is not None:
        session.view.selected_tag = broken.fix.tag_id
    if broken.fix.tab == "forced_friends" and broken.fix.group_id is not None:
        session.view.focus_group_id = broken.fix.group_id
    session.switch_tab(TAB_LABELS[broken.fix.tab])


def current(session: UiSession, tab: str) -> Optional[FixTarget]:
    """The FixTarget to preselect on ``tab`` (a ``FixTarget.tab`` name), or
    ``None`` — also when the focused rule instance no longer breaks."""
    focus = session.view.fix_focus
    if focus is None or focus.fix.tab != tab:
        return None
    instance = (focus.kind, focus.entity)
    if not any((b.instance.kind, tuple(b.instance.entity)) == instance for b in mutations.broken_rules(session.state)):
        session.view.fix_focus = None
        return None
    return focus.fix


def render_callout(session: UiSession, tab: str) -> Optional[FixTarget]:
    """Show the focused rule on its tab, with a way to dismiss it. Returns the
    target so the tab can also mark what it names."""
    fix = current(session, tab)
    if fix is None:
        return None
    assert session.view.fix_focus is not None

    def dismiss() -> None:
        session.view.fix_focus = None
        session.refresh()

    with ui.row().classes("w-full items-center gap-2 rounded bg-blue-50 px-3 py-2 no-wrap"):
        ui.icon("build", color="primary")
        ui.markdown(f"**Opravujete:** {session.view.fix_focus.line}").classes("grow")
        ui.button("Skrýt", on_click=dismiss).props("flat dense")
    return fix
