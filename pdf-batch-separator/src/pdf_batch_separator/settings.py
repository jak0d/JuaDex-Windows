"""Local settings persistence via QSettings (PRD FR-7).

Only preferences are stored. Document names, paths of processed files and any
processing history are deliberately *not* persisted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings

from .core.models import (
    DEFAULT_SEPARATOR,
    BlankSensitivity,
    ProcessingMode,
)

ORGANISATION = "PDF Batch Separator"
APPLICATION = "PDF Batch Separator"


@dataclass
class AppSettings:
    """In-memory view of the persisted preferences."""

    output_folder: str = ""
    separator_value: str = DEFAULT_SEPARATOR
    mode: ProcessingMode = ProcessingMode.SPLIT
    remove_blanks: bool = True
    blank_sensitivity: BlankSensitivity = BlankSensitivity.BALANCED
    recursive: bool = False
    theme: str = "system"  # system | light | dark
    warned_about_signatures: bool = False


class SettingsStore:
    """Thin, defensive wrapper around :class:`QSettings`."""

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings or QSettings(ORGANISATION, APPLICATION)

    # -- helpers ------------------------------------------------------
    def _get_bool(self, key: str, default: bool) -> bool:
        value = self._settings.value(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"true", "1", "yes"}

    def _get_str(self, key: str, default: str) -> str:
        value = self._settings.value(key, default)
        return default if value is None else str(value)

    # -- load / save --------------------------------------------------
    def load(self) -> AppSettings:
        settings = AppSettings()
        settings.output_folder = self._get_str("output_folder", "")

        separator = self._get_str("separator_value", DEFAULT_SEPARATOR)
        settings.separator_value = separator[:128] or DEFAULT_SEPARATOR

        try:
            settings.mode = ProcessingMode(self._get_str("mode", ProcessingMode.SPLIT.value))
        except ValueError:
            settings.mode = ProcessingMode.SPLIT

        settings.remove_blanks = self._get_bool("remove_blanks", True)

        try:
            settings.blank_sensitivity = BlankSensitivity(
                self._get_str("blank_sensitivity", BlankSensitivity.BALANCED.value)
            )
        except ValueError:
            settings.blank_sensitivity = BlankSensitivity.BALANCED

        settings.recursive = self._get_bool("recursive", False)

        theme = self._get_str("theme", "system").lower()
        settings.theme = theme if theme in {"system", "light", "dark"} else "system"

        settings.warned_about_signatures = self._get_bool("warned_about_signatures", False)

        # A remembered folder that no longer exists must not break startup.
        if settings.output_folder and not Path(settings.output_folder).is_dir():
            settings.output_folder = ""

        return settings

    def save(self, settings: AppSettings) -> None:
        self._settings.setValue("output_folder", settings.output_folder)
        self._settings.setValue("separator_value", settings.separator_value)
        self._settings.setValue("mode", settings.mode.value)
        self._settings.setValue("remove_blanks", settings.remove_blanks)
        self._settings.setValue("blank_sensitivity", settings.blank_sensitivity.value)
        self._settings.setValue("recursive", settings.recursive)
        self._settings.setValue("theme", settings.theme)
        self._settings.setValue("warned_about_signatures", settings.warned_about_signatures)
        self._settings.sync()

    def clear(self) -> None:  # pragma: no cover - used by a future reset button
        self._settings.clear()
        self._settings.sync()


__all__ = ["APPLICATION", "ORGANISATION", "AppSettings", "SettingsStore"]
