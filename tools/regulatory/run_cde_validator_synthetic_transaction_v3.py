from __future__ import annotations

"""Resilient launcher for one bounded CDE validator UI transaction.

The v2 attempt proved that the JavaFX accessibility tree is visible to UIA but
its InvokePattern and cached wrappers can become invalid between enumeration
and action.  This compatibility layer keeps the original transaction harness
and evidence contract, but changes the interaction transport only:

* never retain a JavaFX main-window or main-control UIA element across actions;
* reacquire the main window and target descendant immediately before use;
* foreground the native window and click the current on-screen rectangle;
* retry stale UIA reads with a fresh Desktop enumeration;
* preserve every click attempt in RESILIENT_CLICK_EVENTS.json.

The official executable is not modified, injected into, decompiled, or called
through private application APIs.  This remains black-box UI interaction.
"""

import ctypes
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from pywinauto import Desktop, mouse

# Importing v2 installs the small UIAWrapper.child_window compatibility adapter
# required by native dialogs on the hosted runner.  It does not execute v2's
# harness because its entry point is guarded by ``if __name__ == '__main__'``.
import run_cde_validator_synthetic_transaction_v2 as _uia_compat  # noqa: F401
import run_cde_validator_synthetic_transaction as legacy

MAIN_TITLE = "验证标准校验"
CLICK_EVENTS: list[dict[str, Any]] = []


def _utc_now() -> str:
    return legacy.utc_now()


def _output_path() -> Path | None:
    try:
        index = sys.argv.index("--output")
        return Path(sys.argv[index + 1])
    except (ValueError, IndexError):
        return None


def _record(event: dict[str, Any]) -> None:
    CLICK_EVENTS.append({"at": _utc_now(), **event})


def _focus_handle(handle: int) -> dict[str, Any]:
    result: dict[str, Any] = {"handle": handle, "calls": {}}
    try:
        user32 = ctypes.windll.user32
        result["calls"]["ShowWindow"] = bool(user32.ShowWindow(handle, 9))
        result["calls"]["BringWindowToTop"] = bool(user32.BringWindowToTop(handle))
        result["calls"]["SetForegroundWindow"] = bool(user32.SetForegroundWindow(handle))
    except Exception as exc:  # pragma: no cover - Windows-only failure evidence
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _fresh_main(timeout: float = 15.0) -> Any:
    deadline = time.time() + timeout
    errors: list[str] = []
    while time.time() < deadline:
        try:
            windows = Desktop(backend="uia").windows()
            for window in windows:
                try:
                    if window.window_text() == MAIN_TITLE and window.is_visible():
                        # Touch the handle while the wrapper is known to be live.
                        _ = int(window.handle)
                        return window
                except Exception as exc:
                    errors.append(f"window:{type(exc).__name__}:{exc}")
        except Exception as exc:
            errors.append(f"desktop:{type(exc).__name__}:{exc}")
        time.sleep(0.25)
    raise TimeoutError(f"fresh main window not found; errors={errors[-12:]}")


def _safe_text(wrapper: Any) -> str:
    try:
        return str(wrapper.window_text() or "").strip()
    except Exception:
        try:
            return str(wrapper.element_info.name or "").strip()
        except Exception:
            return ""


def _matches(wrapper: Any, criteria: dict[str, Any]) -> bool:
    try:
        info = wrapper.element_info
    except Exception:
        return False
    for key, expected in criteria.items():
        if key in {"found_index", "visible_only", "enabled_only"}:
            continue
        if key == "title":
            if _safe_text(wrapper) != str(expected).strip():
                return False
        elif key == "control_type" and info.control_type != expected:
            return False
        elif key == "automation_id" and info.automation_id != expected:
            return False
        elif key == "class_name" and info.class_name != expected:
            return False
    if criteria.get("visible_only", True):
        try:
            if not wrapper.is_visible():
                return False
        except Exception:
            return False
    if criteria.get("enabled_only", True):
        try:
            if not wrapper.is_enabled():
                return False
        except Exception:
            return False
    return True


def _rectangle_dict(rectangle: Any) -> dict[str, int]:
    return {
        "left": int(rectangle.left),
        "top": int(rectangle.top),
        "right": int(rectangle.right),
        "bottom": int(rectangle.bottom),
        "width": int(rectangle.width()),
        "height": int(rectangle.height()),
    }


def _virtual_screen() -> dict[str, int]:
    user32 = ctypes.windll.user32
    left = int(user32.GetSystemMetrics(76))
    top = int(user32.GetSystemMetrics(77))
    width = int(user32.GetSystemMetrics(78))
    height = int(user32.GetSystemMetrics(79))
    if width <= 0 or height <= 0:
        left = 0
        top = 0
        width = int(user32.GetSystemMetrics(0))
        height = int(user32.GetSystemMetrics(1))
    return {
        "left": left,
        "top": top,
        "right": left + width,
        "bottom": top + height,
        "width": width,
        "height": height,
    }


def _click_point(rectangle: Any) -> tuple[int, int]:
    screen = _virtual_screen()
    x = int((rectangle.left + rectangle.right) / 2)
    y = int((rectangle.top + rectangle.bottom) / 2)
    # JavaFX can report a rectangle that is partly outside the hosted runner's
    # virtual screen.  Select a point inside both the visible rectangle and the
    # virtual screen rather than silently clicking another control.
    x = min(max(x, max(int(rectangle.left) + 2, screen["left"] + 2)), min(int(rectangle.right) - 2, screen["right"] - 2))
    y = min(max(y, max(int(rectangle.top) + 2, screen["top"] + 2)), min(int(rectangle.bottom) - 2, screen["bottom"] - 2))
    if not (screen["left"] <= x < screen["right"] and screen["top"] <= y < screen["bottom"]):
        raise RuntimeError(
            f"control has no clickable intersection with virtual screen: rect={_rectangle_dict(rectangle)}, screen={screen}"
        )
    return x, y


def _fresh_descendant(criteria: dict[str, Any], timeout: float = 12.0) -> Any:
    deadline = time.time() + timeout
    failures: list[str] = []
    while time.time() < deadline:
        try:
            main = _fresh_main(timeout=min(3.0, max(0.5, deadline - time.time())))
            matches: list[Any] = []
            for item in main.descendants():
                try:
                    if not _matches(item, criteria):
                        continue
                    rectangle = item.rectangle()
                    if rectangle.width() <= 0 or rectangle.height() <= 0:
                        continue
                    matches.append(item)
                except Exception as exc:
                    failures.append(f"descendant:{type(exc).__name__}:{exc}")
            found_index = int(criteria.get("found_index", 0) or 0)
            if found_index < len(matches):
                # Re-read the rectangle immediately; stale wrappers fail here
                # and are discarded before any physical action is attempted.
                _ = matches[found_index].rectangle()
                return matches[found_index]
            failures.append(f"no-match:{criteria}")
        except Exception as exc:
            failures.append(f"lookup:{type(exc).__name__}:{exc}")
        time.sleep(0.2)
    raise LookupError(f"fresh descendant not found: criteria={criteria}; failures={failures[-16:]}")


def _physical_click_main(criteria: dict[str, Any]) -> str:
    errors: list[str] = []
    for attempt in range(1, 7):
        try:
            main = _fresh_main()
            handle = int(main.handle)
            focus = _focus_handle(handle)
            try:
                main.set_focus()
            except Exception as exc:
                focus["uia_set_focus_error"] = f"{type(exc).__name__}: {exc}"
            time.sleep(0.15)
            control = _fresh_descendant(criteria)
            rectangle = control.rectangle()
            point = _click_point(rectangle)
            event = {
                "action": "fresh_javafx_coordinate_click",
                "attempt": attempt,
                "criteria": criteria,
                "main_handle": handle,
                "focus": focus,
                "rectangle": _rectangle_dict(rectangle),
                "point": {"x": point[0], "y": point[1]},
                "virtual_screen": _virtual_screen(),
            }
            mouse.click(button="left", coords=point)
            event["status"] = "CLICK_SENT"
            _record(event)
            time.sleep(0.45)
            return "fresh_uia_coordinate_click"
        except Exception as exc:
            errors.append(f"attempt={attempt}:{type(exc).__name__}:{exc}")
            _record(
                {
                    "action": "fresh_javafx_coordinate_click",
                    "attempt": attempt,
                    "criteria": criteria,
                    "status": "RETRY",
                    "error": errors[-1],
                    "traceback": traceback.format_exc(),
                }
            )
            time.sleep(0.35)
    raise RuntimeError(f"unable to click fresh JavaFX control: criteria={criteria}; errors={errors}")


class ResilientControl:
    def __init__(self, criteria: dict[str, Any]) -> None:
        self.criteria = dict(criteria)

    def _fresh(self) -> Any:
        return _fresh_descendant(self.criteria)

    def wrapper_object(self) -> "ResilientControl":
        return self

    def invoke(self) -> None:
        _physical_click_main(self.criteria)

    def click_input(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        _physical_click_main(self.criteria)

    @property
    def element_info(self) -> Any:
        return self._fresh().element_info

    def rectangle(self) -> Any:
        return self._fresh().rectangle()

    def window_text(self) -> str:
        return _safe_text(self._fresh())

    def is_visible(self) -> bool:
        return bool(self._fresh().is_visible())

    def is_enabled(self) -> bool:
        return bool(self._fresh().is_enabled())

    def descendants(self, *args: Any, **kwargs: Any) -> list[Any]:
        return list(self._fresh().descendants(*args, **kwargs))

    def set_focus(self) -> Any:
        return self._fresh().set_focus()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._fresh(), name)


class ResilientMainWindow:
    def __init__(self, timeout: float = 75.0) -> None:
        _ = _fresh_main(timeout)

    def _fresh(self) -> Any:
        return _fresh_main()

    def child_window(self, **criteria: Any) -> ResilientControl:
        return ResilientControl(criteria)

    def wrapper_object(self) -> "ResilientMainWindow":
        return self

    @property
    def element_info(self) -> Any:
        return self._fresh().element_info

    @property
    def handle(self) -> int:
        return int(self._fresh().handle)

    def process_id(self) -> int:
        return int(self._fresh().process_id())

    def descendants(self, *args: Any, **kwargs: Any) -> list[Any]:
        return list(self._fresh().descendants(*args, **kwargs))

    def window_text(self) -> str:
        return _safe_text(self._fresh())

    def is_visible(self) -> bool:
        return bool(self._fresh().is_visible())

    def is_enabled(self) -> bool:
        return bool(self._fresh().is_enabled())

    def rectangle(self) -> Any:
        return self._fresh().rectangle()

    def set_focus(self) -> Any:
        fresh = self._fresh()
        _focus_handle(int(fresh.handle))
        return fresh.set_focus()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._fresh(), name)


def resilient_wait_main_window(timeout: int = 75) -> ResilientMainWindow:
    return ResilientMainWindow(float(timeout))


def resilient_invoke_control(control: Any) -> str:
    if isinstance(control, ResilientControl):
        control.invoke()
        return "fresh_uia_coordinate_click"

    errors: list[str] = []
    for attempt in range(1, 5):
        try:
            top = control.top_level_parent()
            try:
                _focus_handle(int(top.handle))
                top.set_focus()
            except Exception:
                pass
            rectangle = control.rectangle()
            if rectangle.width() > 0 and rectangle.height() > 0:
                point = _click_point(rectangle)
                mouse.click(button="left", coords=point)
                _record(
                    {
                        "action": "native_dialog_coordinate_click",
                        "attempt": attempt,
                        "name": _safe_text(control),
                        "rectangle": _rectangle_dict(rectangle),
                        "point": {"x": point[0], "y": point[1]},
                        "status": "CLICK_SENT",
                    }
                )
                time.sleep(0.3)
                return "native_coordinate_click"
        except Exception as exc:
            errors.append(f"coordinate:{type(exc).__name__}:{exc}")
        try:
            control.invoke()
            _record(
                {
                    "action": "native_dialog_invoke_fallback",
                    "attempt": attempt,
                    "name": _safe_text(control),
                    "status": "INVOKE_SENT",
                }
            )
            return "native_invoke_fallback"
        except Exception as exc:
            errors.append(f"invoke:{type(exc).__name__}:{exc}")
        time.sleep(0.25)
    raise RuntimeError(f"native control action failed: errors={errors}")


def _write_click_events() -> None:
    output = _output_path()
    if output is None:
        return
    output.mkdir(parents=True, exist_ok=True)
    legacy.write_json(
        output / "RESILIENT_CLICK_EVENTS.json",
        {
            "schema_version": "0.1.0",
            "transport": "fresh UIA lookup plus physical coordinate click",
            "official_binary_modified": False,
            "private_application_api_used": False,
            "events": CLICK_EVENTS,
        },
    )


legacy.wait_main_window = resilient_wait_main_window
legacy.invoke_control = resilient_invoke_control


if __name__ == "__main__":
    try:
        raise SystemExit(legacy.main())
    finally:
        _write_click_events()
