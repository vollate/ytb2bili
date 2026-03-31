"""Settings page — edit AppConfig and save to YAML."""

from __future__ import annotations

from pathlib import Path

import structlog
import yaml
from nicegui import ui

from yt2bili.core.config import AppConfig
from yt2bili.core.i18n import _, translations
from yt2bili.core.paths import default_config_path

log: structlog.stdlib.BoundLogger = structlog.get_logger()


def register_settings_page(
    config: AppConfig,
    config_path: Path | None = None,
) -> None:
    """Build the settings editor UI inside the current NiceGUI page context."""

    # ── section builders ─────────────────────────────────────────────────

    inputs: dict[str, dict[str, ui.input | ui.number | ui.switch | ui.textarea]] = {}

    def _section(title_key: str, section_key: str, obj: object) -> None:
        inputs[section_key] = {}
        with ui.expansion(_(title_key), icon="settings").classes("w-full").props("default-opened"):
            with ui.column().classes("w-full gap-2 pl-4"):
                for field_name, field_info in obj.__class__.model_fields.items():
                    current_value = getattr(obj, field_name)
                    annotation = field_info.annotation
                    i18n_key = f"settings.field.{field_name}"
                    label = _(i18n_key) if i18n_key in translations.get("en", {}) else field_name

                    if annotation is bool or isinstance(current_value, bool):
                        inp = ui.switch(label, value=current_value)
                    elif annotation is int or isinstance(current_value, int):
                        inp = ui.number(label, value=float(current_value)).classes("w-full")
                    elif annotation is float or isinstance(current_value, float):
                        inp = ui.number(label, value=current_value, step=0.1).classes("w-full")
                    elif isinstance(current_value, list):
                        inp = ui.input(label, value=", ".join(str(v) for v in current_value)).classes("w-full")
                    elif isinstance(current_value, Path):
                        inp = ui.input(label, value=str(current_value)).classes("w-full")
                    else:
                        inp = ui.input(label, value=str(current_value) if current_value is not None else "").classes("w-full")

                    inputs[section_key][field_name] = inp

    def _collect_values() -> dict[str, object]:
        """Read all input widgets and build a nested config dict."""
        result: dict[str, object] = {}
        for section_key, field_map in inputs.items():
            section_data: dict[str, object] = {}
            section_obj = getattr(config, section_key, None)
            if section_obj is None:
                continue
            for field_name, widget in field_map.items():
                original = getattr(section_obj, field_name)
                raw = widget.value
                if isinstance(original, bool):
                    section_data[field_name] = bool(raw)
                elif isinstance(original, int):
                    section_data[field_name] = int(raw)  # type: ignore[arg-type]
                elif isinstance(original, float):
                    section_data[field_name] = float(raw)  # type: ignore[arg-type]
                elif isinstance(original, list):
                    section_data[field_name] = [s.strip() for s in str(raw).split(",") if s.strip()]
                elif isinstance(original, Path):
                    section_data[field_name] = str(raw)
                else:
                    section_data[field_name] = raw if raw else None
            result[section_key] = section_data
        return result

    async def _save() -> None:
        data = _collect_values()
        # Also include database_url from current config
        data["database_url"] = config.database_url

        save_path = config_path or default_config_path()
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(yaml.dump(dict(data), default_flow_style=False, allow_unicode=True), encoding="utf-8")

        log.info("settings.saved", path=str(save_path))
        ui.notify(_("settings.saved", path=str(save_path)), type="positive")

    # ── page layout ──────────────────────────────────────────────────────

    with ui.column().classes("w-full p-4 gap-4"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label(_("settings.title")).classes("text-2xl font-bold")
            ui.button(_("settings.save"), icon="save", on_click=_save).props("color=primary")

        with ui.column().classes("w-full gap-2"):
            _section("settings.section.schedule", "schedule", config.schedule)
            _section("settings.section.download", "download", config.download)
            _section("settings.section.subtitle", "subtitle", config.subtitle)
            _section("settings.section.upload", "upload", config.upload)
            _section("settings.section.webui", "webui", config.webui)
            _section("settings.section.notify", "notify", config.notify)
