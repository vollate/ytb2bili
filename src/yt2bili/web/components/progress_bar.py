"""Animated progress bar component for NiceGUI."""

from __future__ import annotations

from nicegui import ui


def render_progress_bar(
    value: float,
    *,
    label: str = "",
    color: str = "primary",
    size: str = "20px",
) -> ui.linear_progress:
    """Render an animated linear progress bar.

    Parameters
    ----------
    value:
        Progress percentage (0.0 – 100.0).
    label:
        Optional text displayed above the bar.
    color:
        Quasar colour name (e.g. ``"primary"``, ``"positive"``).
    size:
        CSS height string for the bar.

    Returns
    -------
    ui.linear_progress
        The NiceGUI progress element (caller can later call ``.set_value()``).
    """
    clamped: float = max(0.0, min(value, 100.0))
    if label:
        ui.label(f"{label}  {clamped:.0f}%").classes("text-xs text-grey-7")
    progress = (
        ui.linear_progress(value=clamped / 100.0, show_value=False, size=size)
        .props(f'color="{color}" instant-feedback')
    )
    return progress
