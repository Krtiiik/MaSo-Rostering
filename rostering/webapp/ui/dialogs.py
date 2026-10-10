"""Awaitable dialogs shared by every screen. NiceGUI dialogs can open on top of
each other, so a confirmation opens right where it is needed (even over the
person drawer or another dialog) and the caller simply awaits the answer."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional, Sequence

from nicegui import Client, ui


@dataclass(frozen=True)
class ConfirmSpec:
    title: str
    ok_label: str
    intro: str = ""
    caption: str = ""
    lines: tuple[str, ...] = ()
    danger: bool = True

    def with_lines(self, lines: Sequence[str]) -> "ConfirmSpec":
        return replace(self, lines=tuple(lines))


CANCEL = "Zrušit"


def page_dialog(*, auto_delete: bool = True, client: Optional[Client] = None) -> ui.dialog:
    """A dialog attached to the page's root layout rather than to whatever view
    opened it, so a redraw of that view (every mutation redraws the tab) never
    deletes the dialog while it is open. ``auto_delete`` removes it once closed;
    an awaited dialog is deleted by its awaiter instead. Pass the page's
    ``client`` (``UiSession.client``) from a handler whose own view may have been
    redrawn already: NiceGUI can no longer find the page through it."""
    with (client or ui.context.client).layout:
        dialog = ui.dialog()
    if auto_delete:
        dialog.on_value_change(lambda e: None if e.value or dialog.is_deleted else dialog.delete())
    return dialog


def discard(dialog: ui.dialog) -> None:
    if not dialog.is_deleted:
        dialog.delete()


async def confirm(spec: ConfirmSpec, *, client: Optional[Client] = None) -> bool:
    """Ask before something that cannot be undone; ``True`` on yes."""
    with page_dialog(auto_delete=False, client=client) as dialog, ui.card().classes("min-w-[24rem] max-w-[40rem]"):
        ui.label(spec.title).classes("text-lg font-bold")
        if spec.intro:
            ui.markdown(spec.intro)
        if spec.lines:
            with ui.column().classes("gap-1 pl-2"):
                for line in spec.lines:
                    ui.label(f"• {line}")
        if spec.caption:
            ui.label(spec.caption).classes("text-sm text-gray-600")
        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button(CANCEL, on_click=lambda: dialog.submit(False)).props("flat")
            ui.button(spec.ok_label, on_click=lambda: dialog.submit(True)).props(
                "color=negative" if spec.danger else "color=primary"
            ).mark("confirm-ok")
    result = await dialog
    discard(dialog)
    return bool(result)


async def choose(
    title: str,
    options: Sequence[tuple[str, object]],
    *,
    intro: str = "",
    caption: str = "",
    client: Optional[Client] = None,
) -> object:
    """Ask which of several actions to take: one button per ``(label, value)``
    option plus Cancel. The chosen value, or ``None`` when cancelled."""
    with page_dialog(auto_delete=False, client=client) as dialog, ui.card().classes("min-w-[24rem] max-w-[40rem]"):
        ui.label(title).classes("text-lg font-bold")
        if intro:
            ui.markdown(intro)
        if caption:
            ui.label(caption).classes("text-sm text-gray-600")
        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button(CANCEL, on_click=lambda: dialog.submit(None)).props("flat")
            for index, (label, value) in enumerate(options):
                ui.button(label, on_click=lambda _, v=value: dialog.submit(v)).props("color=negative").mark(f"choose-{index}")
    result = await dialog
    discard(dialog)
    return result


async def ask_text(
    title: str,
    label: str,
    *,
    value: str = "",
    hint: str = "",
    ok_label: str = "Uložit",
    intro: str = "",
    client: Optional[Client] = None,
) -> Optional[str]:
    """A one-field form in a dialog; the stripped text, or ``None`` when cancelled."""
    with page_dialog(auto_delete=False, client=client) as dialog, ui.card().classes("min-w-[22rem]"):
        ui.label(title).classes("text-lg font-bold")
        if intro:
            ui.markdown(intro)
        field = ui.input(label, value=value).props(f'hint="{hint}"' if hint else "").classes("w-full").mark("ask-field")
        field.on("keydown.enter", lambda: dialog.submit(field.value))
        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button(CANCEL, on_click=lambda: dialog.submit(None)).props("flat")
            ui.button(ok_label, on_click=lambda: dialog.submit(field.value)).props("color=primary").mark("ask-ok")
    result = await dialog
    discard(dialog)
    if result is None:
        return None
    return str(result).strip()
