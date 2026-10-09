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

# What a redraw is for, narrowest first: another step shown, view state changed
# (and so possibly any step), the Season's data changed (everything).
_SCOPES = ("tab", "view", "data")


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
    # What came with a layout read from a sheet and waits for its save (see
    # mutations.read_building_sheet); goes with the draft.
    sheet_pending: Optional[dict] = None
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
    late_link_organizer_id: Optional[int] = None
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
        # Step label -> "does it hold unsaved changes?"; a step with a guard that
        # says yes can't be left by :meth:`switch_tab`.
        self.leave_guards: dict[str, Callable[[], bool]] = {}
        # (callback, the narrowest change it redraws on: see :meth:`on_change`)
        self._listeners: list[tuple[Callable[[], None], str]] = []
        self._pending: Optional[str] = None  # the widest scope scheduled, while a redraw is
        # Results of the queries the views share (see :meth:`cached`), dropped
        # whenever anything may have changed.
        self._cache: dict[str, Any] = {}

    # ------------------------------------------------------------------ refresh
    def on_change(self, callback: Callable[[], None], *, on: str = "data") -> None:
        """Call ``callback`` after every :meth:`apply` (views refresh themselves).
        ``on`` widens that: ``"view"`` also after :meth:`refresh_view` (for what
        shows the session's view state: a selection, a draft, ...), ``"tab"``
        also after :meth:`switch_tab` (for what depends on the active step)."""
        assert on in _SCOPES
        self._listeners.append((callback, on))

    def refresh(self) -> None:
        """Redraw the views on the next turn of the event loop (several changes
        in one handler redraw once). Deferred so the handler that asked can still
        use its own view (notify, open a dialog) before the redraw replaces it."""
        self._cache.clear()
        self._schedule("data")

    def refresh_view(self) -> None:
        """Redraw only what shows the view state (the steps, the Tag sheet) after
        a change of view state alone: the Season's data is as it was, so the
        header's to-do count, the to-do panel and the sidebar, which read every
        stored Season, are left alone."""
        self._schedule("view")

    def _schedule(self, scope: str) -> None:
        if self._pending is not None and _SCOPES.index(self._pending) >= _SCOPES.index(scope):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # no event loop (plain synchronous use): redraw now
            self._redraw(scope)
            return
        if self._pending is None:
            loop.call_soon(self._redraw_pending)
        self._pending = scope

    def _redraw_pending(self) -> None:
        scope, self._pending = self._pending, None
        if scope is not None:
            self._redraw(scope)

    def _redraw(self, scope: str) -> None:
        width = _SCOPES.index(scope)
        for callback, on in list(self._listeners):
            if _SCOPES.index(on) > width:
                continue
            try:
                callback()
            except Exception:  # one broken view must not keep the others stale
                _log.exception("Redrawing a view failed")

    def cached(self, key: str, compute: Callable[[], Any]) -> Any:
        """``compute()``, computed once until the next :meth:`refresh`: for the
        queries several views make on every redraw (the to-do items, ...)."""
        if key not in self._cache:
            self._cache[key] = compute()
        return self._cache[key]

    def forget_cached(self) -> None:
        """Drop what :meth:`cached` holds (another browser tab may have changed
        the stored Seasons since): for a view drawn outside a redraw."""
        self._cache.clear()

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
            self.view.sheet_pending = None
            self.view.solver_draft = None
        else:
            self.view = SeasonView()
            self.active_tab = labels.TABS[0]
        self.apply(new_state)

    def switch_tab(self, tab: str) -> bool:
        """Show another step. Refused (returns False, with a notification) while
        the current step holds unsaved changes (see ``leave_guards``)."""
        if tab != self.active_tab:
            guard = self.leave_guards.get(self.active_tab)
            if guard is not None and guard():
                ui.notify(
                    "Máte neuložené změny. Nejdřív je uložte, nebo je vraťte zpět.", type="warning", multi_line=True
                )
                return False
        self.active_tab = tab
        self._schedule("tab")
        return True

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

