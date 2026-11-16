"""
FileUzi Settings Panel.

A PyQt6 QDialog that exposes the filing-rule configuration dicts from
fileuzi.config.settings for editing and persists changes back to
settings.py using AST-spliced text replacement.
"""

from __future__ import annotations

import ast
import copy
import importlib
import os
import re
import shutil
from typing import Any, Dict, List, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QDoubleSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fileuzi.config import settings as settings_module

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MANAGED_NAMES = [
    'PDF_EXTRACTION_RULES',
    'JOB_NUMBER_PATTERNS',
    'DRAWING_NUMBER_PATTERNS',
    'PROJECT_MAPPING_COLUMNS',
    'FILING_RULES_ENGINE',
    'EMAIL_PARSING_RULES',
    'ATTACHMENT_FILTERING',
    'CONTACT_MANAGEMENT',
    'FOLDER_KEYWORDS',
    'OPERATION_LIMITS',
    'STAGE_HIERARCHY',
]

# Keys inside OPERATION_LIMITS that should be rendered as MB (bytes on disk).
BYTES_AS_MB_KEYS = {'max_email_attachment_size'}

HEX_COLOR_RE = re.compile(r'^#[0-9A-Fa-f]{6}$')


# ---------------------------------------------------------------------------
# Helpers for detecting value types
# ---------------------------------------------------------------------------

def _looks_like_regex(key: str, value: Any) -> bool:
    """Heuristic: treat as regex if the key hints at one, or value has regex-y chars."""
    if not isinstance(value, str):
        return False
    lk = key.lower()
    if 'pattern' in lk or 'regex' in lk:
        return True
    if value.startswith('^') or value.endswith('$'):
        return True
    if '\\' in value:
        return True
    return False


def _looks_like_hex_color(key: str, value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if 'color' in key.lower() or 'colour' in key.lower():
        if value.startswith('#'):
            return True
    return False


def _is_float_0_1(value: Any) -> bool:
    return isinstance(value, float) and 0.0 <= value <= 1.0


# ---------------------------------------------------------------------------
# Python value formatter for writing back to settings.py
# ---------------------------------------------------------------------------

def _format_string(s: str) -> str:
    """Return a safe Python string literal. Prefers r'...' for regex-like strings."""
    if '\\' in s and "'" not in s and '\n' not in s and '\r' not in s:
        # Safe to use a raw single-quoted string
        return "r'" + s + "'"
    # Fall back to repr (handles quotes/escapes safely)
    return repr(s)


def _format_py_value(v: Any, indent: int = 0) -> str:
    """Recursively emit a Python literal for *v* with the given *indent*."""
    pad = ' ' * indent
    child_pad = ' ' * (indent + 4)

    if isinstance(v, bool):
        return 'True' if v else 'False'
    if v is None:
        return 'None'
    if isinstance(v, int):
        return repr(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return _format_string(v)
    if isinstance(v, list):
        if not v:
            return '[]'
        # Try a single-line rendering first
        items = [_format_py_value(x, indent + 4) for x in v]
        single = '[' + ', '.join(items) + ']'
        if all(isinstance(x, (int, float, str)) for x in v) and len(single) <= 100:
            return single
        inner = ',\n'.join(child_pad + item for item in items)
        return '[\n' + inner + ',\n' + pad + ']'
    if isinstance(v, tuple):
        items = [_format_py_value(x, indent + 4) for x in v]
        if len(v) == 1:
            return '(' + items[0] + ',)'
        return '(' + ', '.join(items) + ')'
    if isinstance(v, dict):
        if not v:
            return '{}'
        lines = []
        for k, val in v.items():
            key_repr = repr(k) if not isinstance(k, str) else _format_string(k)
            val_repr = _format_py_value(val, indent + 4)
            lines.append(f"{child_pad}{key_repr}: {val_repr},")
        return '{\n' + '\n'.join(lines) + '\n' + pad + '}'
    # Fallback
    return repr(v)


# ---------------------------------------------------------------------------
# AST-based assignment replacement
# ---------------------------------------------------------------------------

def _replace_assignment(src: str, name: str, new_value: Any) -> str:
    """Replace the top-level assignment ``name = ...`` with formatted *new_value*."""
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id != name:
            continue

        start = node.lineno - 1  # 0-based
        end = (node.end_lineno or node.lineno)  # exclusive slice bound: use as-is

        formatted = _format_py_value(new_value, indent=0)
        new_line = f"{name} = {formatted}\n"

        return ''.join(lines[:start]) + new_line + ''.join(lines[end:])

    # If we didn't find it, append.
    formatted = _format_py_value(new_value, indent=0)
    return src + f"\n{name} = {formatted}\n"


def _persist_changes(values: Dict[str, Any]) -> Tuple[bool, str]:
    """Write *values* back into settings.py. Returns (ok, message)."""
    path = settings_module.__file__
    if path is None:
        return False, "Could not locate settings.py on disk."

    try:
        with open(path, 'r', encoding='utf-8') as fh:
            original_src = fh.read()
    except OSError as exc:
        return False, f"Could not read settings.py: {exc}"

    # Back up
    bak_path = path + '.bak'
    try:
        shutil.copyfile(path, bak_path)
    except OSError as exc:
        return False, f"Could not create backup: {exc}"

    new_src = original_src
    for name in MANAGED_NAMES:
        if name not in values:
            continue
        try:
            new_src = _replace_assignment(new_src, name, values[name])
        except Exception as exc:  # pragma: no cover - defensive
            return False, f"Failed to rewrite {name}: {exc}"

    # Verify it still parses
    try:
        ast.parse(new_src)
    except SyntaxError as exc:
        # Restore from backup and bail out
        try:
            shutil.copyfile(bak_path, path)
        except OSError:
            pass
        return False, f"Generated settings.py did not parse: {exc}"

    try:
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(new_src)
    except OSError as exc:
        # Try to restore
        try:
            shutil.copyfile(bak_path, path)
        except OSError:
            pass
        return False, f"Could not write settings.py: {exc}"

    return True, "ok"


# ---------------------------------------------------------------------------
# Per-tab widget helpers
# ---------------------------------------------------------------------------

class _TabState:
    """Holds editor widgets for a single dict so we can read/reset them."""

    def __init__(self, name: str, defaults: Any):
        self.name = name
        self.defaults = copy.deepcopy(defaults)
        # Mapping: key-path (tuple of strings) -> callable returning current value
        self.getters: Dict[Tuple[str, ...], Any] = {}
        # Mapping: key-path -> callable accepting a value to reset the widget
        self.setters: Dict[Tuple[str, ...], Any] = {}
        self.error_label: QLabel | None = None
        # For top-level list values (STAGE_HIERARCHY style)
        self.list_widget: QListWidget | None = None

    def read_value(self) -> Any:
        """Rebuild the current dict/list from the widget state."""
        if self.list_widget is not None and not self.getters:
            # Top-level list
            return [self.list_widget.item(i).text()
                    for i in range(self.list_widget.count())]

        # Reconstruct by walking the defaults structure
        return _rebuild(self.defaults, self.getters, path=())


def _rebuild(template: Any, getters: Dict[Tuple[str, ...], Any],
             path: Tuple[str, ...]) -> Any:
    """Walk *template* and substitute leaves from *getters* by key-path."""
    if isinstance(template, dict):
        out: Dict[str, Any] = {}
        for k, v in template.items():
            out[k] = _rebuild(v, getters, path + (k,))
        return out
    if isinstance(template, list):
        # For leaf lists (list of strings) we stash a getter at this path.
        if path in getters:
            return getters[path]()
        return list(template)
    if path in getters:
        return getters[path]()
    return copy.deepcopy(template)


# ---------------------------------------------------------------------------
# The dialog
# ---------------------------------------------------------------------------

class SettingsPanel(QDialog):
    """Dialog for editing filing-rule settings dicts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FileUzi Settings")
        self.resize(760, 640)

        # Reload settings so we see the latest file-on-disk values
        try:
            importlib.reload(settings_module)
        except Exception:
            pass

        # Snapshot for "Reset This Tab"
        self._snapshot: Dict[str, Any] = {
            name: copy.deepcopy(getattr(settings_module, name, None))
            for name in MANAGED_NAMES
        }

        self._tabs: Dict[str, _TabState] = {}

        root = QVBoxLayout(self)
        self.tab_widget = QTabWidget(self)
        root.addWidget(self.tab_widget, 1)

        # Build each tab
        for name in MANAGED_NAMES:
            value = self._snapshot.get(name)
            if value is None:
                continue
            tab = self._build_tab(name, value)
            self.tab_widget.addTab(tab, name)

        # Button row
        row = QHBoxLayout()
        self.reset_btn = QPushButton("Reset This Tab")
        self.reset_btn.clicked.connect(self._reset_current_tab)
        row.addWidget(self.reset_btn)
        row.addStretch(1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.save_btn = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        self.buttons.accepted.connect(self._on_save)
        self.buttons.rejected.connect(self.reject)
        row.addWidget(self.buttons)
        root.addLayout(row)

        self._revalidate_all()

    # ------------------------------------------------------------------
    # Tab construction
    # ------------------------------------------------------------------
    def _build_tab(self, name: str, value: Any) -> QWidget:
        state = _TabState(name, value)
        self._tabs[name] = state

        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(6, 6, 6, 6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        scroll.setWidget(inner)
        outer_layout.addWidget(scroll, 1)

        if isinstance(value, list):
            # STAGE_HIERARCHY: whole tab is a reorderable list
            self._build_reorderable_list(inner, state, value)
        elif isinstance(value, dict):
            form = QFormLayout(inner)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            self._populate_form(form, state, value, path=(), name=name)
        else:
            # Unknown shape: show a stub label
            lbl = QLabel(f"(unsupported value type for {name})", inner)
            v = QVBoxLayout(inner)
            v.addWidget(lbl)

        err = QLabel("", outer)
        err.setStyleSheet("color: #dc2626;")
        err.setWordWrap(True)
        state.error_label = err
        outer_layout.addWidget(err)

        return outer

    # ------------------------------------------------------------------
    def _populate_form(self, form: QFormLayout, state: _TabState, data: Dict[str, Any],
                       path: Tuple[str, ...], name: str) -> None:
        for key, val in data.items():
            sub_path = path + (key,)
            label = ".".join(sub_path)
            widget = self._make_widget_for(state, name, sub_path, key, val)
            if widget is not None:
                form.addRow(label, widget)

    # ------------------------------------------------------------------
    def _make_widget_for(self, state: _TabState, tab_name: str,
                         path: Tuple[str, ...], key: str, val: Any) -> QWidget | None:
        """Return the editor widget, register getters/setters into *state*."""
        # OPERATION_LIMITS bytes-as-MB
        if tab_name == 'OPERATION_LIMITS' and key in BYTES_AS_MB_KEYS and isinstance(val, int):
            return self._make_mb_spin(state, path, val)

        # Dict-of-regex (e.g. ATTACHMENT_FILTERING['embedded_image_patterns'])
        if isinstance(val, dict):
            return self._make_sub_dict(state, tab_name, path, val)

        # Hex colour
        if _looks_like_hex_color(key, val):
            return self._make_color_picker(state, path, val)

        # Regex string
        if _looks_like_regex(key, val):
            return self._make_regex_line(state, path, val)

        # Plain string
        if isinstance(val, str):
            return self._make_plain_line(state, path, val)

        # Bool
        if isinstance(val, bool):
            return self._make_bool(state, path, val)

        # Float (0-1) probability/threshold
        if _is_float_0_1(val):
            return self._make_float_01(state, path, val)

        # Int
        if isinstance(val, int):
            return self._make_int(state, path, val)

        # Other float
        if isinstance(val, float):
            return self._make_float_generic(state, path, val)

        # List (of strings)
        if isinstance(val, list):
            return self._make_string_list(state, path, val)

        # Fallback
        lbl = QLabel(f"(unsupported: {type(val).__name__})")
        return lbl

    # ------------------------------------------------------------------
    # Individual widget factories
    # ------------------------------------------------------------------
    def _make_int(self, state: _TabState, path: Tuple[str, ...], val: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, 1_000_000)
        spin.setValue(int(val))
        state.getters[path] = spin.value
        state.setters[path] = lambda v, w=spin: w.setValue(int(v))
        return spin

    def _make_mb_spin(self, state: _TabState, path: Tuple[str, ...], val: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, 1_000_000)
        spin.setSuffix(" MB")
        mb = max(0, int(val) // (1024 * 1024))
        spin.setValue(mb)
        state.getters[path] = lambda w=spin: int(w.value()) * 1024 * 1024
        state.setters[path] = lambda v, w=spin: w.setValue(max(0, int(v) // (1024 * 1024)))
        return spin

    def _make_float_01(self, state: _TabState, path: Tuple[str, ...], val: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 1.0)
        spin.setDecimals(2)
        spin.setSingleStep(0.05)
        spin.setValue(float(val))
        state.getters[path] = spin.value
        state.setters[path] = lambda v, w=spin: w.setValue(float(v))
        return spin

    def _make_float_generic(self, state: _TabState, path: Tuple[str, ...], val: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(-1_000_000.0, 1_000_000.0)
        spin.setDecimals(4)
        spin.setSingleStep(0.1)
        spin.setValue(float(val))
        state.getters[path] = spin.value
        state.setters[path] = lambda v, w=spin: w.setValue(float(v))
        return spin

    def _make_bool(self, state: _TabState, path: Tuple[str, ...], val: bool) -> QWidget:
        # We don't have a QCheckBox import listed; use a simple line for v1.
        line = QLineEdit("true" if val else "false")
        state.getters[path] = lambda w=line: w.text().strip().lower() in ('1', 'true', 'yes', 'y')
        state.setters[path] = lambda v, w=line: w.setText("true" if v else "false")
        return line

    def _make_plain_line(self, state: _TabState, path: Tuple[str, ...], val: str) -> QLineEdit:
        line = QLineEdit(val)
        state.getters[path] = line.text
        state.setters[path] = lambda v, w=line: w.setText(str(v))
        line.textChanged.connect(self._revalidate_all)
        return line

    def _make_regex_line(self, state: _TabState, path: Tuple[str, ...], val: str) -> QLineEdit:
        line = QLineEdit(val)
        line.setStyleSheet("font-family: monospace;")
        line.setToolTip("Regular expression")
        line.setProperty("_fu_regex", True)
        state.getters[path] = line.text
        state.setters[path] = lambda v, w=line: w.setText(str(v))
        line.textChanged.connect(self._revalidate_all)
        return line

    def _make_color_picker(self, state: _TabState, path: Tuple[str, ...], val: str) -> QWidget:
        container = QWidget()
        h = QHBoxLayout(container)
        h.setContentsMargins(0, 0, 0, 0)
        line = QLineEdit(val)
        line.setProperty("_fu_color", True)
        h.addWidget(line, 1)
        btn = QPushButton("Pick…")

        def pick():
            current = QColor(line.text()) if HEX_COLOR_RE.match(line.text() or '') else QColor('#000000')
            chosen = QColorDialog.getColor(current, self, "Select colour")
            if chosen.isValid():
                line.setText(chosen.name())

        btn.clicked.connect(pick)
        h.addWidget(btn)

        state.getters[path] = line.text
        state.setters[path] = lambda v, w=line: w.setText(str(v))
        line.textChanged.connect(self._revalidate_all)
        return container

    def _make_string_list(self, state: _TabState, path: Tuple[str, ...], val: List[str]) -> QWidget:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)

        lst = QListWidget()
        lst.setMaximumHeight(140)
        for item in val:
            lst.addItem(str(item))
        v.addWidget(lst)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add")
        rem_btn = QPushButton("Remove")
        btn_row.addWidget(add_btn)
        btn_row.addWidget(rem_btn)
        btn_row.addStretch(1)
        v.addLayout(btn_row)

        def add():
            text, ok = QInputDialog.getText(self, "Add item", "Value:")
            if ok and text:
                lst.addItem(text)
                self._revalidate_all()

        def rem():
            for it in lst.selectedItems():
                lst.takeItem(lst.row(it))
            self._revalidate_all()

        add_btn.clicked.connect(add)
        rem_btn.clicked.connect(rem)

        def getter():
            return [lst.item(i).text() for i in range(lst.count())]

        def setter(new_val, widget=lst):
            widget.clear()
            for item in (new_val or []):
                widget.addItem(str(item))

        state.getters[path] = getter
        state.setters[path] = setter
        return container

    def _make_sub_dict(self, state: _TabState, tab_name: str,
                       path: Tuple[str, ...], val: Dict[str, Any]) -> QWidget:
        """Render a nested dict as a bordered group with its own form layout."""
        container = QWidget()
        form = QFormLayout(container)
        form.setContentsMargins(12, 4, 4, 4)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for k, v in val.items():
            sub_path = path + (k,)
            w = self._make_widget_for(state, tab_name, sub_path, k, v)
            if w is not None:
                form.addRow(k, w)
        container.setStyleSheet("QWidget { border-left: 2px solid #e2e8f0; }")
        return container

    # ------------------------------------------------------------------
    def _build_reorderable_list(self, inner: QWidget, state: _TabState,
                                values: List[str]) -> None:
        v = QVBoxLayout(inner)
        lst = QListWidget()
        for item in values:
            lst.addItem(str(item))
        v.addWidget(lst, 1)
        state.list_widget = lst

        row = QHBoxLayout()
        add_btn = QPushButton("Add")
        rem_btn = QPushButton("Remove")
        up_btn = QPushButton("Move Up")
        down_btn = QPushButton("Move Down")
        row.addWidget(add_btn)
        row.addWidget(rem_btn)
        row.addWidget(up_btn)
        row.addWidget(down_btn)
        row.addStretch(1)
        v.addLayout(row)

        def add():
            text, ok = QInputDialog.getText(self, "Add stage", "Stage prefix:")
            if ok and text:
                lst.addItem(text.strip())

        def rem():
            for it in lst.selectedItems():
                lst.takeItem(lst.row(it))

        def move(delta: int):
            row_ix = lst.currentRow()
            if row_ix < 0:
                return
            new_ix = row_ix + delta
            if new_ix < 0 or new_ix >= lst.count():
                return
            item = lst.takeItem(row_ix)
            lst.insertItem(new_ix, item)
            lst.setCurrentRow(new_ix)

        add_btn.clicked.connect(add)
        rem_btn.clicked.connect(rem)
        up_btn.clicked.connect(lambda: move(-1))
        down_btn.clicked.connect(lambda: move(1))

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def _revalidate_all(self) -> None:
        any_error = False
        for name, state in self._tabs.items():
            errs: List[str] = []
            # Walk child widgets for regex + colour markers
            tab_widget = self._find_tab_widget(name)
            if tab_widget is None:
                continue
            for w in tab_widget.findChildren(QLineEdit):
                if w.property("_fu_regex"):
                    pat = w.text()
                    try:
                        re.compile(pat)
                    except re.error as exc:
                        errs.append(f"Invalid regex: {exc}")
                if w.property("_fu_color"):
                    if not HEX_COLOR_RE.match(w.text() or ''):
                        errs.append(f"Invalid hex colour: {w.text()!r}")
            if state.error_label is not None:
                state.error_label.setText("\n".join(errs))
            if errs:
                any_error = True
        if self.save_btn is not None:
            self.save_btn.setEnabled(not any_error)

    def _find_tab_widget(self, name: str) -> QWidget | None:
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == name:
                return self.tab_widget.widget(i)
        return None

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------
    def _reset_current_tab(self) -> None:
        ix = self.tab_widget.currentIndex()
        if ix < 0:
            return
        name = self.tab_widget.tabText(ix)
        state = self._tabs.get(name)
        if state is None:
            return

        defaults = self._snapshot.get(name)
        if defaults is None:
            return

        # Reset all registered setters by walking the defaults
        if state.list_widget is not None and isinstance(defaults, list):
            state.list_widget.clear()
            for item in defaults:
                state.list_widget.addItem(str(item))
            return

        self._apply_defaults(state, defaults, path=())

        # Handle bytes-as-MB re-application & nested lists
        self._revalidate_all()

    def _apply_defaults(self, state: _TabState, template: Any,
                        path: Tuple[str, ...]) -> None:
        if isinstance(template, dict):
            for k, v in template.items():
                self._apply_defaults(state, v, path + (k,))
            return
        # For lists, we stored a setter at this path
        setter = state.setters.get(path)
        if setter is not None:
            try:
                setter(template)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    def _on_save(self) -> None:
        # Gather values
        new_values: Dict[str, Any] = {}
        try:
            for name, state in self._tabs.items():
                new_values[name] = state.read_value()
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Could not collect values: {exc}")
            return

        ok, msg = _persist_changes(new_values)
        if not ok:
            QMessageBox.critical(self, "Save failed", msg)
            return

        QMessageBox.information(
            self,
            "Saved",
            "Settings saved. Please restart FileUzi for all changes to take effect.",
        )
        self.accept()


# ---------------------------------------------------------------------------
# Optional integration hook for the pattern builder (guarded)
# ---------------------------------------------------------------------------

try:  # pragma: no cover - optional
    from fileuzi.ui import pattern_builder as _pattern_builder  # noqa: F401
except Exception:  # pragma: no cover
    _pattern_builder = None  # type: ignore


__all__ = ["SettingsPanel", "MANAGED_NAMES"]
