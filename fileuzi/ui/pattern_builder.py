"""Visual pattern builder for FileUzi filing patterns.

Provides a PyQt6 widget allowing end-users to build regex-style filing
patterns from a palette of semantic components (job number, drawing
number, separators, etc.) without ever having to see raw regex.

Public API:
    PatternComponent         - dataclass for a single pattern component
    PatternDefinition        - dataclass for a named pattern (list of components)
    PatternBuilderWidget     - QWidget for visually editing a PatternDefinition
    compile_pattern_components - helper to compile a list of dicts to regex
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QWidget,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QCheckBox,
    QLineEdit,
    QComboBox,
    QRadioButton,
    QButtonGroup,
    QPlainTextEdit,
    QTextEdit,
    QScrollArea,
    QFrame,
    QMessageBox,
    QGroupBox,
    QSizePolicy,
    QSplitter,
)


# ---------------------------------------------------------------------------
# Component type registry
# ---------------------------------------------------------------------------

COMPONENT_TYPES = [
    "job_number",
    "drawing_number",
    "stage_prefix",
    "revision",
    "separator",
    "project_name",
    "free_text",
    "custom_prefix",
]

COMPONENT_TYPE_LABELS = {
    "job_number": "Job Number",
    "drawing_number": "Drawing Number",
    "stage_prefix": "Stage Prefix",
    "revision": "Revision",
    "separator": "Separator",
    "project_name": "Project Name",
    "free_text": "Free Text",
    "custom_prefix": "Custom Prefix",
}


def _default_properties(component_type: str) -> dict:
    """Return the default properties dict for a given component type."""
    if component_type == "job_number":
        return {"min_digits": 4, "max_digits": 5}
    if component_type == "drawing_number":
        return {"min_digits": 2, "max_digits": 3, "optional_letter": True}
    if component_type == "stage_prefix":
        return {}
    if component_type == "revision":
        return {"digits": 2}
    if component_type == "separator":
        return {"char": " - ", "allow_whitespace": True}
    if component_type == "project_name":
        return {"content_type": "any"}
    if component_type == "free_text":
        return {}
    if component_type == "custom_prefix":
        return {"text": "", "optional": False}
    return {}


# ---------------------------------------------------------------------------
# PatternComponent
# ---------------------------------------------------------------------------


@dataclass
class PatternComponent:
    """A single component in a filing pattern."""

    type: str
    properties: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type not in COMPONENT_TYPES:
            raise ValueError(f"Unknown component type: {self.type!r}")
        # Fill in missing defaults without overwriting user values.
        defaults = _default_properties(self.type)
        for key, val in defaults.items():
            self.properties.setdefault(key, val)

    # -- regex compilation ------------------------------------------------
    def to_regex(self, stage_hierarchy: Optional[list] = None) -> str:
        t = self.type
        p = self.properties

        if t == "job_number":
            mn = int(p.get("min_digits", 4))
            mx = int(p.get("max_digits", 5))
            return r"(\d{%d,%d})" % (mn, mx)

        if t == "drawing_number":
            mn = int(p.get("min_digits", 2))
            mx = int(p.get("max_digits", 3))
            base = r"(\d{%d,%d})" % (mn, mx)
            if p.get("optional_letter", True):
                return base + r"([A-Z])?"
            return base

        if t == "stage_prefix":
            if not stage_hierarchy:
                raise ValueError(
                    "stage_prefix component requires a non-empty stage_hierarchy"
                )
            stages = "|".join(re.escape(s) for s in stage_hierarchy)
            return f"({stages})"

        if t == "revision":
            digits = int(p.get("digits", 2))
            return r"(\d{%d})" % digits

        if t == "separator":
            char = p.get("char", " - ")
            if char == " - ":
                return r"\s*[-–]\s*"
            if char == "_":
                return r"_"
            if char == "-":
                return r"-"
            if char == " ":
                return r"\s+"
            frag = re.escape(char)
            if p.get("allow_whitespace", False):
                frag = r"\s*" + frag + r"\s*"
            return frag

        if t == "project_name":
            ct = p.get("content_type", "any")
            if ct == "alphanumeric":
                return r"([A-Za-z0-9]+)"
            if ct == "no_spaces":
                return r"(\S+)"
            if ct == "letters_only":
                return r"([A-Za-z]+)"
            return r"(.+)"

        if t == "free_text":
            return r".*"

        if t == "custom_prefix":
            text = p.get("text", "")
            escaped = re.escape(text)
            if p.get("optional", False):
                return f"({escaped})?"
            return f"({escaped})"

        raise ValueError(f"Unknown component type: {t!r}")

    # -- UI label ----------------------------------------------------------
    def display_label(self) -> str:
        t = self.type
        p = self.properties
        title = COMPONENT_TYPE_LABELS.get(t, t)

        if t == "job_number":
            return f"{title}\n{p.get('min_digits', 4)}-{p.get('max_digits', 5)} digits"
        if t == "drawing_number":
            detail = f"{p.get('min_digits', 2)}-{p.get('max_digits', 3)} digits"
            if p.get("optional_letter", True):
                detail += "\n+ optional letter"
            return f"{title}\n{detail}"
        if t == "stage_prefix":
            return f"{title}\n(from hierarchy)"
        if t == "revision":
            return f"{title}\n{p.get('digits', 2)} digits"
        if t == "separator":
            char = p.get("char", " - ")
            vis = {" - ": "' - '", " ": "' '", "_": "'_'", "-": "'-'"}.get(
                char, f"'{char}'"
            )
            return f"{title}\n{vis}"
        if t == "project_name":
            return f"{title}\n{p.get('content_type', 'any')}"
        if t == "free_text":
            return f"{title}\n(any)"
        if t == "custom_prefix":
            text = p.get("text", "") or "(empty)"
            suffix = " (optional)" if p.get("optional") else ""
            return f"{title}\n'{text}'{suffix}"
        return title


# ---------------------------------------------------------------------------
# PatternDefinition
# ---------------------------------------------------------------------------


@dataclass
class PatternDefinition:
    """A named filing pattern comprised of ordered components."""

    name: str = ""
    components: list = field(default_factory=list)

    def compile(self, stage_hierarchy: Optional[list] = None) -> str:
        body = "".join(c.to_regex(stage_hierarchy) for c in self.components)
        return "^" + body + "$"

    def test(
        self,
        test_strings: list,
        stage_hierarchy: Optional[list] = None,
    ) -> dict:
        results: dict = {}
        try:
            pattern_str = self.compile(stage_hierarchy)
            compiled = re.compile(pattern_str)
            compile_error = None
        except (re.error, ValueError) as exc:
            compiled = None
            compile_error = str(exc)

        # Pre-compute group labels (one per capturing group, in order).
        group_labels = self._group_labels(stage_hierarchy)

        for s in test_strings:
            if compile_error is not None:
                results[s] = {
                    "matches": False,
                    "groups": None,
                    "explanation": f"Pattern error: {compile_error}",
                }
                continue
            m = compiled.match(s)
            if m is None:
                results[s] = {
                    "matches": False,
                    "groups": None,
                    "explanation": "No match",
                }
                continue
            groups = m.groups()
            parts = []
            for i, g in enumerate(groups):
                label = group_labels[i] if i < len(group_labels) else f"group{i+1}"
                parts.append(f"{label}={g!r}")
            explanation = "Match: " + ", ".join(parts) if parts else "Match"
            results[s] = {
                "matches": True,
                "groups": groups,
                "explanation": explanation,
            }
        return results

    def _group_labels(self, stage_hierarchy: Optional[list]) -> list:
        """Return a flat list of labels, one per capturing group in order."""
        labels: list = []
        for c in self.components:
            t = c.type
            if t == "job_number":
                labels.append("job_number")
            elif t == "drawing_number":
                labels.append("drawing_number")
                if c.properties.get("optional_letter", True):
                    labels.append("drawing_letter")
            elif t == "stage_prefix":
                labels.append("stage_prefix")
            elif t == "revision":
                labels.append("revision")
            elif t == "project_name":
                labels.append("project_name")
            elif t == "custom_prefix":
                labels.append("custom_prefix")
            # separator and free_text produce no capture groups
        return labels

    def to_serializable(self) -> dict:
        return {
            "name": self.name,
            "components": [
                {"type": c.type, "properties": dict(c.properties)}
                for c in self.components
            ],
        }

    @classmethod
    def from_serializable(cls, d: dict) -> "PatternDefinition":
        comps = [
            PatternComponent(type=cd["type"], properties=dict(cd.get("properties", {})))
            for cd in d.get("components", [])
        ]
        return cls(name=d.get("name", ""), components=comps)


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------


def compile_pattern_components(
    components: list, stage_hierarchy: Optional[list] = None
) -> str:
    """Compile a list of component dicts into a full ``^...$`` regex."""
    parts = []
    for cd in components:
        comp = PatternComponent(
            type=cd["type"], properties=dict(cd.get("properties", {}))
        )
        parts.append(comp.to_regex(stage_hierarchy))
    return "^" + "".join(parts) + "$"


# ---------------------------------------------------------------------------
# Properties dialog
# ---------------------------------------------------------------------------


class ComponentPropertiesDialog(QDialog):
    """Generic properties editor dialog that renders fields per component.type."""

    def __init__(self, component: PatternComponent, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(
            f"Edit {COMPONENT_TYPE_LABELS.get(component.type, component.type)}"
        )
        self.component = component
        self._fields: dict = {}
        self._sep_group: Optional[QButtonGroup] = None

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self._build_fields(component, form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _build_fields(self, comp: PatternComponent, form: QFormLayout) -> None:
        t = comp.type
        p = comp.properties

        if t == "job_number":
            mn = QSpinBox()
            mn.setRange(1, 20)
            mn.setValue(int(p.get("min_digits", 4)))
            mx = QSpinBox()
            mx.setRange(1, 20)
            mx.setValue(int(p.get("max_digits", 5)))
            form.addRow("Min digits:", mn)
            form.addRow("Max digits:", mx)
            self._fields["min_digits"] = mn
            self._fields["max_digits"] = mx

        elif t == "drawing_number":
            mn = QSpinBox()
            mn.setRange(1, 20)
            mn.setValue(int(p.get("min_digits", 2)))
            mx = QSpinBox()
            mx.setRange(1, 20)
            mx.setValue(int(p.get("max_digits", 3)))
            ol = QCheckBox("Allow optional trailing letter (A-Z)")
            ol.setChecked(bool(p.get("optional_letter", True)))
            form.addRow("Min digits:", mn)
            form.addRow("Max digits:", mx)
            form.addRow("", ol)
            self._fields["min_digits"] = mn
            self._fields["max_digits"] = mx
            self._fields["optional_letter"] = ol

        elif t == "stage_prefix":
            info = QLabel(
                "Stage prefix uses the project's stage hierarchy.\nNo properties to edit."
            )
            info.setWordWrap(True)
            form.addRow(info)

        elif t == "revision":
            d = QSpinBox()
            d.setRange(1, 10)
            d.setValue(int(p.get("digits", 2)))
            form.addRow("Digits:", d)
            self._fields["digits"] = d

        elif t == "separator":
            group_box = QGroupBox("Separator character")
            vbox = QVBoxLayout(group_box)
            self._sep_group = QButtonGroup(self)
            options = [
                (" - ", "Dash with spaces  ' - '"),
                ("-", "Hyphen  '-'"),
                ("_", "Underscore  '_'"),
                (" ", "Space  ' '"),
                ("__custom__", "Custom..."),
            ]
            current = p.get("char", " - ")
            matched = False
            for value, label in options:
                rb = QRadioButton(label)
                rb.setProperty("sep_value", value)
                self._sep_group.addButton(rb)
                vbox.addWidget(rb)
                if value == current:
                    rb.setChecked(True)
                    matched = True
            custom_edit = QLineEdit()
            custom_edit.setPlaceholderText("Custom separator text")
            vbox.addWidget(custom_edit)
            if not matched:
                # Current value doesn't match a preset -> treat as custom.
                # Find the custom radio and select it.
                for btn in self._sep_group.buttons():
                    if btn.property("sep_value") == "__custom__":
                        btn.setChecked(True)
                        break
                custom_edit.setText(current)
            form.addRow(group_box)

            aw = QCheckBox("Allow surrounding whitespace")
            aw.setChecked(bool(p.get("allow_whitespace", True)))
            form.addRow("", aw)
            self._fields["__sep_custom__"] = custom_edit
            self._fields["allow_whitespace"] = aw

        elif t == "project_name":
            combo = QComboBox()
            combo.addItem("Any characters", "any")
            combo.addItem("Alphanumeric only", "alphanumeric")
            combo.addItem("No spaces", "no_spaces")
            combo.addItem("Letters only", "letters_only")
            current = p.get("content_type", "any")
            for i in range(combo.count()):
                if combo.itemData(i) == current:
                    combo.setCurrentIndex(i)
                    break
            form.addRow("Content type:", combo)
            self._fields["content_type"] = combo

        elif t == "free_text":
            info = QLabel("Free text matches anything (.*). No properties to edit.")
            info.setWordWrap(True)
            form.addRow(info)

        elif t == "custom_prefix":
            le = QLineEdit(str(p.get("text", "")))
            opt = QCheckBox("Optional (may be absent)")
            opt.setChecked(bool(p.get("optional", False)))
            form.addRow("Prefix text:", le)
            form.addRow("", opt)
            self._fields["text"] = le
            self._fields["optional"] = opt

    def get_properties(self) -> dict:
        """Read field values and return the updated properties dict."""
        t = self.component.type
        out = dict(self.component.properties)

        if t in ("job_number", "drawing_number"):
            out["min_digits"] = self._fields["min_digits"].value()
            out["max_digits"] = self._fields["max_digits"].value()
            if t == "drawing_number":
                out["optional_letter"] = self._fields["optional_letter"].isChecked()

        elif t == "revision":
            out["digits"] = self._fields["digits"].value()

        elif t == "separator":
            if self._sep_group is not None:
                checked = self._sep_group.checkedButton()
                if checked is not None:
                    val = checked.property("sep_value")
                    if val == "__custom__":
                        out["char"] = self._fields["__sep_custom__"].text() or " - "
                    else:
                        out["char"] = val
            out["allow_whitespace"] = self._fields["allow_whitespace"].isChecked()

        elif t == "project_name":
            combo = self._fields["content_type"]
            out["content_type"] = combo.itemData(combo.currentIndex())

        elif t == "custom_prefix":
            out["text"] = self._fields["text"].text()
            out["optional"] = self._fields["optional"].isChecked()

        return out


# ---------------------------------------------------------------------------
# Component widget (one tile on the canvas)
# ---------------------------------------------------------------------------


class _ComponentTile(QFrame):
    """A visual tile representing one PatternComponent on the canvas."""

    edit_requested = pyqtSignal(object)
    remove_requested = pyqtSignal(object)
    move_left_requested = pyqtSignal(object)
    move_right_requested = pyqtSignal(object)

    def __init__(self, component: PatternComponent, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.component = component
        self.setFrameShape(QFrame.Shape.Box)
        self.setFrameShadow(QFrame.Shadow.Raised)
        self.setLineWidth(2)
        self.setMinimumWidth(140)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)

        self.label = QLabel(component.display_label())
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setBold(True)
        self.label.setFont(font)
        self.label.setWordWrap(True)
        v.addWidget(self.label)

        # Movement arrows
        arrows = QHBoxLayout()
        left_btn = QPushButton("\u2190")
        left_btn.setFixedWidth(30)
        left_btn.setToolTip("Move left")
        left_btn.clicked.connect(lambda: self.move_left_requested.emit(self))
        right_btn = QPushButton("\u2192")
        right_btn.setFixedWidth(30)
        right_btn.setToolTip("Move right")
        right_btn.clicked.connect(lambda: self.move_right_requested.emit(self))
        arrows.addWidget(left_btn)
        arrows.addWidget(right_btn)
        v.addLayout(arrows)

        btns = QHBoxLayout()
        edit_btn = QPushButton("Edit")
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self))
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        btns.addWidget(edit_btn)
        btns.addWidget(remove_btn)
        v.addLayout(btns)

        # Disable arrows for non-editable types that still support it - all do.
        self._left_btn = left_btn
        self._right_btn = right_btn

    def refresh(self) -> None:
        self.label.setText(self.component.display_label())


# ---------------------------------------------------------------------------
# Main PatternBuilderWidget
# ---------------------------------------------------------------------------


class PatternBuilderWidget(QWidget):
    """Visual editor for a PatternDefinition."""

    pattern_changed = pyqtSignal(object)

    def __init__(
        self,
        pattern_def: Optional[PatternDefinition] = None,
        stage_hierarchy: Optional[list] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._stage_hierarchy = list(stage_hierarchy) if stage_hierarchy else []
        self._tiles: list = []
        self._pattern_name: str = ""

        self._build_ui()

        if pattern_def is not None:
            self.load_pattern(pattern_def)
        else:
            self._update_canvas()
            self._run_tests()

    # -- UI construction ---------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Vertical)
        root.addWidget(splitter, 1)

        # Top row: palette (left) + canvas (center)
        top_widget = QWidget()
        top_h = QHBoxLayout(top_widget)

        # --- Palette ---
        palette_box = QGroupBox("Add component")
        palette_v = QVBoxLayout(palette_box)
        for ctype in COMPONENT_TYPES:
            btn = QPushButton(COMPONENT_TYPE_LABELS.get(ctype, ctype))
            btn.clicked.connect(lambda _=False, t=ctype: self._add_component(t))
            palette_v.addWidget(btn)
        palette_v.addStretch(1)
        palette_box.setMaximumWidth(200)
        top_h.addWidget(palette_box)

        # --- Canvas (scrollable horizontal strip) ---
        canvas_box = QGroupBox("Pattern")
        canvas_v = QVBoxLayout(canvas_box)
        self._canvas_scroll = QScrollArea()
        self._canvas_scroll.setWidgetResizable(True)
        self._canvas_inner = QWidget()
        self._canvas_layout = QHBoxLayout(self._canvas_inner)
        self._canvas_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._canvas_layout.setSpacing(4)
        self._canvas_scroll.setWidget(self._canvas_inner)
        canvas_v.addWidget(self._canvas_scroll)

        self._empty_label = QLabel(
            "No components yet.\nClick a button on the left to add one."
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        canvas_v.addWidget(self._empty_label)

        top_h.addWidget(canvas_box, 1)

        splitter.addWidget(top_widget)

        # Bottom: live test panel
        bottom_widget = QWidget()
        bottom_v = QVBoxLayout(bottom_widget)

        # Collapsible regex section
        regex_row = QHBoxLayout()
        self._regex_toggle = QPushButton("Show compiled regex")
        self._regex_toggle.setCheckable(True)
        self._regex_toggle.toggled.connect(self._toggle_regex_display)
        regex_row.addWidget(self._regex_toggle)
        regex_row.addStretch(1)
        bottom_v.addLayout(regex_row)

        self._regex_display = QLineEdit()
        self._regex_display.setReadOnly(True)
        self._regex_display.setVisible(False)
        self._regex_display.setFont(QFont("Courier"))
        bottom_v.addWidget(self._regex_display)

        test_box = QGroupBox("Test strings (one per line)")
        test_v = QVBoxLayout(test_box)
        self._test_input = QPlainTextEdit()
        self._test_input.setPlaceholderText(
            "Enter filenames or strings to test against the pattern..."
        )
        self._test_input.textChanged.connect(self._run_tests)
        test_v.addWidget(self._test_input)
        bottom_v.addWidget(test_box)

        result_box = QGroupBox("Results")
        result_v = QVBoxLayout(result_box)
        self._test_output = QTextEdit()
        self._test_output.setReadOnly(True)
        result_v.addWidget(self._test_output)
        bottom_v.addWidget(result_box)

        splitter.addWidget(bottom_widget)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

    def _toggle_regex_display(self, checked: bool) -> None:
        self._regex_display.setVisible(checked)
        self._regex_toggle.setText(
            "Hide compiled regex" if checked else "Show compiled regex"
        )

    # -- Public API --------------------------------------------------------
    def get_pattern(self, name: str) -> PatternDefinition:
        return PatternDefinition(
            name=name,
            components=[
                PatternComponent(type=t.component.type, properties=dict(t.component.properties))
                for t in self._tiles
            ],
        )

    def load_pattern(self, pattern_def: PatternDefinition) -> None:
        self._pattern_name = pattern_def.name
        # Clear existing tiles
        for tile in list(self._tiles):
            self._canvas_layout.removeWidget(tile)
            tile.setParent(None)
            tile.deleteLater()
        self._tiles = []
        # Add new
        for comp in pattern_def.components:
            new_comp = PatternComponent(type=comp.type, properties=dict(comp.properties))
            self._append_tile(new_comp, emit=False)
        self._update_canvas()
        self._emit_changed()

    def set_stage_hierarchy(self, stage_hierarchy: Optional[list]) -> None:
        self._stage_hierarchy = list(stage_hierarchy) if stage_hierarchy else []
        self._run_tests()

    # -- Internal ----------------------------------------------------------
    def _add_component(self, component_type: str) -> None:
        comp = PatternComponent(type=component_type, properties=_default_properties(component_type))
        self._append_tile(comp, emit=True)

    def _append_tile(self, comp: PatternComponent, emit: bool = True) -> None:
        tile = _ComponentTile(comp)
        tile.edit_requested.connect(self._edit_tile)
        tile.remove_requested.connect(self._remove_tile)
        tile.move_left_requested.connect(self._move_left)
        tile.move_right_requested.connect(self._move_right)
        self._canvas_layout.addWidget(tile)
        self._tiles.append(tile)
        self._update_canvas()
        if emit:
            self._emit_changed()

    def _edit_tile(self, tile: _ComponentTile) -> None:
        dlg = ComponentPropertiesDialog(tile.component, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            tile.component.properties = dlg.get_properties()
            tile.refresh()
            self._emit_changed()

    def _remove_tile(self, tile: _ComponentTile) -> None:
        reply = QMessageBox.question(
            self,
            "Remove component",
            f"Remove this {COMPONENT_TYPE_LABELS.get(tile.component.type, tile.component.type)} component?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        idx = self._tiles.index(tile)
        self._tiles.pop(idx)
        self._canvas_layout.removeWidget(tile)
        tile.setParent(None)
        tile.deleteLater()
        self._update_canvas()
        self._emit_changed()

    def _move_left(self, tile: _ComponentTile) -> None:
        idx = self._tiles.index(tile)
        if idx <= 0:
            return
        self._tiles[idx - 1], self._tiles[idx] = self._tiles[idx], self._tiles[idx - 1]
        self._rebuild_canvas_order()
        self._emit_changed()

    def _move_right(self, tile: _ComponentTile) -> None:
        idx = self._tiles.index(tile)
        if idx >= len(self._tiles) - 1:
            return
        self._tiles[idx + 1], self._tiles[idx] = self._tiles[idx], self._tiles[idx + 1]
        self._rebuild_canvas_order()
        self._emit_changed()

    def _rebuild_canvas_order(self) -> None:
        # Remove all tiles from layout, then re-add in new order.
        for i in reversed(range(self._canvas_layout.count())):
            item = self._canvas_layout.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                self._canvas_layout.removeWidget(w)
        for tile in self._tiles:
            self._canvas_layout.addWidget(tile)

    def _update_canvas(self) -> None:
        has_tiles = bool(self._tiles)
        self._empty_label.setVisible(not has_tiles)
        self._canvas_scroll.setVisible(True)

    def _current_definition(self) -> PatternDefinition:
        return PatternDefinition(
            name=self._pattern_name,
            components=[
                PatternComponent(type=t.component.type, properties=dict(t.component.properties))
                for t in self._tiles
            ],
        )

    def _emit_changed(self) -> None:
        definition = self._current_definition()
        self.pattern_changed.emit(definition)
        self._run_tests()

    def _run_tests(self) -> None:
        definition = self._current_definition()
        try:
            regex_str = definition.compile(self._stage_hierarchy or None)
            self._regex_display.setText(regex_str)
        except (re.error, ValueError) as exc:
            self._regex_display.setText(f"<error: {exc}>")

        raw = self._test_input.toPlainText().splitlines()
        test_strings = [s for s in raw if s.strip() != ""]
        if not test_strings:
            self._test_output.setHtml(
                "<i>Enter test strings above to see match results.</i>"
            )
            return
        try:
            results = definition.test(test_strings, self._stage_hierarchy or None)
        except (re.error, ValueError) as exc:
            self._test_output.setHtml(
                f"<span style='color:#b00;'><b>Pattern error:</b> {exc}</span>"
            )
            return

        html_parts = []
        for s in test_strings:
            r = results.get(s, {"matches": False, "explanation": "n/a"})
            if r["matches"]:
                color = "#1a7a1a"
                icon = "&#10003;"  # check
            else:
                color = "#b00020"
                icon = "&#10007;"  # cross
            safe_s = (
                s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            )
            safe_exp = (
                r["explanation"]
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            html_parts.append(
                f"<div style='margin-bottom:4px;'>"
                f"<span style='color:{color};font-weight:bold;'>{icon}</span> "
                f"<code>{safe_s}</code> &mdash; "
                f"<span style='color:{color};'>{safe_exp}</span>"
                f"</div>"
            )
        self._test_output.setHtml("".join(html_parts))


__all__ = [
    "PatternComponent",
    "PatternDefinition",
    "PatternBuilderWidget",
    "compile_pattern_components",
    "ComponentPropertiesDialog",
    "COMPONENT_TYPES",
    "COMPONENT_TYPE_LABELS",
]
