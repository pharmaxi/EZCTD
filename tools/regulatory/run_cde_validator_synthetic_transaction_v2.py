from __future__ import annotations

"""Compatibility launcher for the CDE validator transaction harness.

The first transaction attempt proved that ``Desktop(...).windows()`` returns a
``UIAWrapper``.  That wrapper exposes ``descendants()`` but not the
``child_window()`` specification method that belongs to Application/Window
specifications.  The v1 harness intentionally remains frozen as evidence of the
failed attempt.  This launcher adds only the missing descendant-selection
adapter and then executes the unchanged v1 transaction harness.
"""

import runpy
from pathlib import Path
from typing import Any

from pywinauto.controls.uiawrapper import UIAWrapper


class _DescendantSpecification:
    """Small subset of pywinauto's specification API used by the v1 harness."""

    def __init__(self, root: UIAWrapper, criteria: dict[str, Any]) -> None:
        self._root = root
        self._criteria = criteria

    @staticmethod
    def _text(wrapper: Any) -> str:
        try:
            return str(wrapper.window_text() or "").strip()
        except Exception:
            try:
                return str(wrapper.element_info.name or "").strip()
            except Exception:
                return ""

    @staticmethod
    def _value(wrapper: Any, name: str) -> Any:
        try:
            info = wrapper.element_info
            mapping = {
                "control_type": info.control_type,
                "automation_id": info.automation_id,
                "class_name": info.class_name,
                "title": info.name,
            }
            return mapping.get(name)
        except Exception:
            return None

    def _matches(self, wrapper: Any) -> bool:
        for key, expected in self._criteria.items():
            if key in {"found_index", "visible_only", "enabled_only"}:
                continue
            if key == "title":
                if self._text(wrapper) != str(expected).strip():
                    return False
                continue
            actual = self._value(wrapper, key)
            if actual != expected:
                return False
        if self._criteria.get("visible_only"):
            try:
                if not wrapper.is_visible():
                    return False
            except Exception:
                return False
        if self._criteria.get("enabled_only"):
            try:
                if not wrapper.is_enabled():
                    return False
            except Exception:
                return False
        return True

    @staticmethod
    def _rank(wrapper: Any) -> tuple[int, int, int]:
        """Prefer visible, enabled and non-empty-name controls deterministically."""
        try:
            visible = int(bool(wrapper.is_visible()))
        except Exception:
            visible = 0
        try:
            enabled = int(bool(wrapper.is_enabled()))
        except Exception:
            enabled = 0
        try:
            named = int(bool(str(wrapper.element_info.name or "").strip()))
        except Exception:
            named = 0
        return visible, enabled, named

    def wrapper_object(self) -> Any:
        try:
            descendants = list(self._root.descendants())
        except Exception as exc:
            raise LookupError(
                f"Unable to enumerate UIA descendants for criteria={self._criteria}: {exc}"
            ) from exc

        matches = [item for item in descendants if self._matches(item)]
        matches.sort(key=self._rank, reverse=True)
        found_index = int(self._criteria.get("found_index", 0) or 0)
        if found_index < len(matches):
            return matches[found_index]

        available: list[dict[str, Any]] = []
        for item in descendants[:250]:
            try:
                info = item.element_info
                available.append(
                    {
                        "title": self._text(item),
                        "control_type": info.control_type,
                        "automation_id": info.automation_id,
                        "class_name": info.class_name,
                    }
                )
            except Exception:
                continue
        raise LookupError(
            "No UIA descendant matched "
            f"criteria={self._criteria}; available_controls={available}"
        )


def _child_window(self: UIAWrapper, **criteria: Any) -> _DescendantSpecification:
    return _DescendantSpecification(self, criteria)


# Patch only when the installed pywinauto wrapper lacks this convenience method.
if not hasattr(UIAWrapper, "child_window"):
    setattr(UIAWrapper, "child_window", _child_window)


if __name__ == "__main__":
    harness = Path(__file__).with_name("run_cde_validator_synthetic_transaction.py")
    runpy.run_path(str(harness), run_name="__main__")
