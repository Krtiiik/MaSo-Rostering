"""The NiceGUI app: one page (``/``) per browser tab, run by ``rostering serve``.

Layout: a header with the app title, the open Season's label, the six step tabs
and the "K vyřízení" (to-do) button; a left drawer with the Seasons and Versions
panels; the active step below. The person sheet (People tab) and the dialogs
open on top. Every mutation goes through the page's :class:`UiSession`, which
refreshes the views after it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from nicegui import ui

from rostering.webapp import labels, mutations
from rostering.webapp.ui import dialogs, todo
from rostering.webapp.ui.session import UiSession
from rostering.webapp.ui.sidebar import Sidebar
from rostering.webapp.ui.tabs.person_sheet import PersonSheet

# The MaSo site's own favicon (https://maso.mff.cuni.cz/favicon.ico).
_FAVICON = Path(__file__).parent / "assets" / "favicon.ico"

_CSS = """
body { background: #f7f7f9; }
.nicegui-content { padding: 0; }
"""


async def _migrate_legacy(session: UiSession) -> None:
    """First launch after Seasons were introduced: move the old single saved
    state (and its Versions) into a labelled Season. Silent when the label can
    be derived; otherwise asks once."""
    try:
        migrated = mutations.migrate_legacy_workspace(session.workspace)
    except mutations.SeasonLabelRequired as exc:
        suggested = exc.suggested_label or ""
        intro = "Vaše dřívější uložená práce se má stát uloženým ročníkem i s uloženými verzemi. " + str(exc)
        while True:
            label = await dialogs.ask_text(
                "Uložit dřívější práci jako ročník",
                labels.SEASON_LABEL_FIELD,
                value=suggested,
                hint=labels.SEASON_LABEL_HELP,
                ok_label="Uložit jako tento ročník",
                intro=intro,
                client=session.client,
            )
            if label is None:
                return
            try:
                mutations.migrate_legacy_workspace(session.workspace, label=label)
            except mutations.SeasonLabelRequired as again:
                intro = str(again)
                suggested = label
                continue
            session.workspace_replaced(mutations.get_state(session.workspace))
            return
    if migrated is not None:
        session.workspace_replaced(mutations.get_state(session.workspace))


class Page:
    def __init__(self) -> None:
        # Imported here so a tab module can import this one's helpers freely.
        from rostering.webapp.ui.tabs.buildings import BuildingsTab
        from rostering.webapp.ui.tabs.forced_friends import ForcedFriendsTab
        from rostering.webapp.ui.tabs.people import PeopleTab
        from rostering.webapp.ui.tabs.roster import RosterTab
        from rostering.webapp.ui.tabs.solver import SolverTab
        from rostering.webapp.ui.tabs.tags import TagsTab

        ui.add_css(_CSS)
        self.session = s = UiSession()
        self.sheet = PersonSheet(s)
        self.tabs: dict[str, Callable[[], None]] = {
            labels.TAB_PEOPLE: PeopleTab(s, self.sheet).render,
            labels.TAB_TAGS: TagsTab(s).render,
            labels.TAB_FORCED: ForcedFriendsTab(s).render,
            labels.TAB_BUILDINGS: BuildingsTab(s).render,
            labels.TAB_SOLVER: SolverTab(s).render,
            labels.TAB_ROSTER: RosterTab(s, self.sheet).render,
        }

        with ui.header(elevated=True).classes("bg-white text-black items-center gap-2 px-4 py-1"):
            ui.button(icon="menu", on_click=lambda: left.toggle()).props("flat round dense")
            with ui.column().classes("gap-0"):
                ui.label(labels.APP_TITLE).classes("text-lg font-bold leading-tight")
                self.season_label = ui.label().classes("text-xs text-gray-600 leading-tight")
            self.tab_strip = (
                ui.tabs(on_change=self._tab_clicked)
                .props("dense no-caps inline-label")
                .classes("grow")
                .mark("step-tabs")
            )
            with self.tab_strip:
                for name in labels.TABS:
                    ui.tab(name)
            with ui.button(icon="checklist", on_click=lambda: right.toggle()).props("flat round"):
                self.todo_badge = ui.badge(color="warning").props("floating")
                ui.tooltip("K vyřízení")
            with ui.button(icon="more_vert").props("flat round"):
                with ui.menu():
                    ui.menu_item("Začít znovu", on_click=self._start_over).mark("start-over")

        with ui.left_drawer(value=True, bordered=True).props("width=300").classes("bg-white p-3") as left:
            Sidebar(s).render()
        with ui.right_drawer(value=False, bordered=True).props("width=420 overlay").classes("bg-white p-3") as right:
            todo.TodoPanel(s).render()

        with ui.column().classes("w-full p-4 gap-3"):
            self.main()
        s.on_change(self._refresh)
        self._update_header()

    def _tab_clicked(self, e) -> None:
        if e.value and e.value != self.session.active_tab:
            self.session.switch_tab(e.value)

    def _update_header(self) -> None:
        s = self.session
        season = mutations.get_open_season(s.workspace)
        self.season_label.text = (
            f"Ročník {season['label']}" if season else "Nový ročník — zatím neuloženo; vytvoří se nahráním odpovědí"
        )
        self.tab_strip.value = s.active_tab
        waiting = todo.count(s)
        self.todo_badge.text = str(waiting)
        self.todo_badge.set_visibility(waiting > 0)

    def _refresh(self) -> None:
        self._update_header()
        self.main.refresh()

    @ui.refreshable_method
    def main(self) -> None:
        self.tabs[self.session.active_tab]()

    async def _start_over(self) -> None:
        if await dialogs.confirm(
            dialogs.ConfirmSpec(
                title="Začít znovu?",
                ok_label="Začít znovu",
                intro="Otevřený ročník se vyprázdní. Jeho označení a uložené verze zůstanou.",
            ),
            client=self.session.client,
        ):
            await self.session.act(lambda: mutations.reset_workspace(self.session.workspace), replaced=True)


async def root() -> None:
    """The page: NiceGUI 3's single root function (``ui.run(root)``), one
    :class:`Page` (and :class:`UiSession`) per browser tab."""
    page = Page()
    # Once the page is up: the legacy migration may need to ask in a dialog.
    ui.timer(0.1, lambda: _migrate_legacy(page.session), once=True)


def run(*, host: str, port: int, show: bool, reload: bool = False, watch: Optional[Path] = None) -> None:
    """Serve the app (blocking). ``reload`` (development only, see
    ``dev_server.py``) restarts it when a file under ``watch`` changes."""
    ui.run(
        root,
        host=host,
        port=port,
        title=labels.APP_TITLE,
        show=show,
        reload=reload,
        uvicorn_reload_dirs=str(watch or "."),
        uvicorn_reload_includes="*.py, *.js",
        favicon=_FAVICON,
        language="cs",
        reconnect_timeout=30,
    )
