"""One browser tab's view of the open Season.

Single-workspace design: each page load gets its own :class:`UiSession`, which
owns a :class:`Workspace` (whichever Season is open, backed by the Season
directories under ``data/seasons/`` that every tab shares on disk), the state
last read from it, and the view state that belongs to that Season (the Buildings
and Solver drafts, the Go-fix focus, the roster grid's overlays and Tag filter,
...). Views register a refresh callback; :meth:`apply` stores a mutation's new
state and refreshes them, :meth:`workspace_replaced` additionally forgets the
per-Season view state.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from nicegui import ui

from rostering.domain import FixTarget
from rostering.persistence.workspace import Workspace
from rostering.webapp import labels, mutations
from rostering.webapp.ui import dialogs

_log = logging.getLogger(__name__)


@dataclass
class FixFocus:
    """The Broken rule a "Go fix" pointed at (see :mod:`rostering.webapp.ui.fix_focus`)."""

    kind: str
    entity: tuple
    line: str
    fix: FixTarget


@dataclass
class SeasonView:
    """View state that belongs to the open Season and is forgotten when another
    one replaces it (or a Version is restored, minus what ``keep_view`` keeps)."""

    buildings_draft: Optional[list[dict]] = None
    solver_draft: Optional[dict] = None
    fix_focus: Optional[FixFocus] = None
    selected_tag: Any = None  # a Tag id, "new" or None
    focus_group_id: Optional[int] = None
    grid_overlays: list[str] = field(default_factory=lambda: ["friends"])
    grid_tag_filter: list[int] = field(default_factory=list)
    grid_tag_mode: str = "all"
    import_summary: Optional[dict] = None  # {"where", "summary"}
    import_banner_dismissed: bool = False
    late_link_helper_id: Optional[int] = None
    export_path: Optional[str] = None
    people_search: str = ""


class UiSession:
    def __init__(self, workspace: Optional[Workspace] = None) -> None:
        # The page this session belongs to: dialogs open on it even from a
        # handler whose own view a refresh has already replaced.
        self.client = ui.context.client
        self.workspace = workspace or Workspace()
        self.state: dict[str, Any] = self.workspace.load()
        self.view = SeasonView()
        self.active_tab: str = labels.TABS[0]
        self._listeners: list[Callable[[], None]] = []
        self._refresh_pending = False

    # ------------------------------------------------------------------ refresh
    def on_change(self, callback: Callable[[], None]) -> None:
        """Call ``callback`` after every :meth:`apply` (views refresh themselves)."""
        self._listeners.append(callback)

    def refresh(self) -> None:
        """Redraw the views on the next turn of the event loop (several changes
        in one handler redraw once). Deferred so the handler that asked can still
        use its own view (notify, open a dialog) before the redraw replaces it."""
        if self._refresh_pending:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # no event loop (plain synchronous use): redraw now
            self._redraw()
            return
        self._refresh_pending = True
        loop.call_soon(self._redraw)

    def _redraw(self) -> None:
        self._refresh_pending = False
        for callback in list(self._listeners):
            try:
                callback()
            except Exception:  # one broken view must not keep the others stale
                _log.exception("Redrawing a view failed")

    def apply(self, new_state: dict[str, Any]) -> None:
        self.state = new_state
        self.refresh()

    def reload(self) -> None:
        """Re-read the state from disk (after a mutation that returns none)."""
        self.apply(mutations.get_state(self.workspace))

    def workspace_replaced(self, new_state: dict[str, Any], keep_view: bool = False) -> None:
        """Another Season opened, New Season, Start over or a Version restore:
        drop the view state derived from the old one. ``keep_view`` keeps the
        current tab and everything but the drafts (a Version restore)."""
        if keep_view:
            self.view.buildings_draft = None
            self.view.solver_draft = None
        else:
            self.view = SeasonView()
            self.active_tab = labels.TABS[0]
        self.apply(new_state)

    def switch_tab(self, tab: str) -> None:
        self.active_tab = tab
        self.refresh()

    # ------------------------------------------------------------------ actions
    async def act(
        self,
        mutation: Callable[..., Any],
        *,
        confirm: Optional[dialogs.ConfirmSpec] = None,
        success: Optional[str] = None,
        replaced: bool = False,
    ) -> Optional[Any]:
        """Run a mutation and apply the state it returns.

        A ``RosteringError`` is shown as a notification and changes nothing. With
        ``confirm``, ``mutation`` takes ``confirmed``: a ``ConfirmationRequired``
        opens the confirmation (its ``lines`` listed) and, on yes, runs it again
        confirmed. Returns the mutation's result, or ``None`` when it was refused
        or declined. A mutation that returns no state (``None``) re-reads it.
        Runs on the page itself, so it works even after a redraw replaced the
        view whose handler called it."""
        with self.client:
            return await self._act(mutation, confirm=confirm, success=success, replaced=replaced)

    async def _act(
        self,
        mutation: Callable[..., Any],
        *,
        confirm: Optional[dialogs.ConfirmSpec],
        success: Optional[str],
        replaced: bool,
    ) -> Optional[Any]:
        try:
            result = await _maybe_await(mutation(confirmed=False) if confirm else mutation())
        except mutations.ConfirmationRequired as exc:
            assert confirm is not None
            if not await dialogs.confirm(confirm.with_lines(exc.lines), client=self.client):
                return None
            try:
                result = await _maybe_await(mutation(confirmed=True))
            except mutations.RosteringError as again:
                ui.notify(str(again), type="negative", multi_line=True)
                return None
        except mutations.RosteringError as exc:
            ui.notify(str(exc), type="negative", multi_line=True)
            return None
        new_state = result if isinstance(result, dict) and "helpers" in result else mutations.get_state(self.workspace)
        if replaced:
            self.workspace_replaced(new_state)
        else:
            self.apply(new_state)
        if success:
            ui.notify(success, type="positive")
        return result if result is not None else new_state


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value

