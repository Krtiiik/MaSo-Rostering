"""Awaitable dialogs shared by every screen. NiceGUI dialogs can open on top of
each other, so a confirmation opens right where it is needed (even over the
person drawer or another dialog) and the caller simply awaits the answer."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional, Sequence

from nicegui import ui


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


async def confirm(spec: ConfirmSpec) -> bool:
    """Ask before something that cannot be undone; ``True`` on yes."""
    with ui.dialog() as dialog, ui.card().classes("min-w-[24rem] max-w-[40rem]"):
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
            )
    result = await dialog
    dialog.delete()
    return bool(result)


async def ask_text(
    title: str,
    label: str,
    *,
    value: str = "",
    hint: str = "",
    ok_label: str = "Uložit",
    intro: str = "",
) -> Optional[str]:
    """A one-field form in a dialog; the stripped text, or ``None`` when cancelled."""
    with ui.dialog() as dialog, ui.card().classes("min-w-[22rem]"):
        ui.label(title).classes("text-lg font-bold")
        if intro:
            ui.markdown(intro)
        field = ui.input(label, value=value).props(f'hint="{hint}"' if hint else "").classes("w-full")
        field.on("keydown.enter", lambda: dialog.submit(field.value))
        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button(CANCEL, on_click=lambda: dialog.submit(None)).props("flat")
            ui.button(ok_label, on_click=lambda: dialog.submit(field.value)).props("color=primary")
    result = await dialog
    dialog.delete()
    if result is None:
        return None
    return str(result).strip()
