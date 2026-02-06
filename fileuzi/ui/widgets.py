"""
UI Widget components for FileUzi.
"""

import re
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QFrame, QFileDialog, QLayout
)
from PyQt6.QtCore import Qt, QRect, QSize, QPoint
from PyQt6.QtGui import QFont, QDragEnterEvent, QDropEvent

from fileuzi.config import (
    COLORS,
    SECONDARY_FILING_WIDTH,
    MAX_CHIPS,
    MAX_CHIP_TEXT_LENGTH,
)


class FlowLayout(QLayout):
    """A layout that arranges widgets in a flowing manner, wrapping to next line."""

    def __init__(self, parent=None, margin=0, spacing=-1):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self._spacing = spacing
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def spacing(self):
        return self._spacing if self._spacing >= 0 else super().spacing()

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect, test_only):
        x = rect.x()
        y = rect.y()
        line_height = 0
        spacing = self.spacing()

        for item in self._items:
            widget = item.widget()
            space_x = spacing
            space_y = spacing
            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = next_x
            line_height = max(line_height, item.sizeHint().height())
        return y + line_height - rect.y()


class ClickableWordLabel(QLabel):
    """A clickable word label for the email subject or filename."""

    def __init__(self, word, parent_widget, index, word_group='subject'):
        super().__init__(word)
        self.word = word
        self.parent_widget = parent_widget
        self.index = index
        self.word_group = word_group  # 'subject' or 'filename_X' to identify source
        self.selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.update_style()

    def update_style(self):
        if self.selected:
            self.setStyleSheet(f"""
                QLabel {{
                    background-color: {COLORS['primary']};
                    color: white;
                    padding: 1px 3px;
                    border-radius: 3px;
                    font-size: 12px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QLabel {{
                    background-color: {COLORS['bg']};
                    color: {COLORS['text']};
                    padding: 1px 3px;
                    border-radius: 3px;
                    font-size: 12px;
                }}
                QLabel:hover {{
                    background-color: {COLORS['primary']}22;
                }}
            """)

    def set_selected(self, selected):
        """Set selection state and update style."""
        if self.selected != selected:
            self.selected = selected
            self.update_style()
            if self.parent_widget:
                self.parent_widget.on_subject_word_clicked(self.word, self.selected)

    def mousePressEvent(self, event):
        if self.parent_widget and self.word_group == 'subject':
            self.parent_widget.start_drag_select(self.index)
        self.set_selected(not self.selected)

    def mouseMoveEvent(self, event):
        if self.parent_widget and self.parent_widget.is_dragging and self.word_group == 'subject':
            self.parent_widget.drag_select_to(self.index)

    def mouseReleaseEvent(self, event):
        if self.parent_widget and self.word_group == 'subject':
            self.parent_widget.end_drag_select()

    def enterEvent(self, event):
        if self.parent_widget and self.parent_widget.is_dragging and self.word_group == 'subject':
            self.parent_widget.drag_select_to(self.index)
        super().enterEvent(event)


class FilingChip(QLabel):
    """A colored chip representing a secondary filing destination."""

    def __init__(self, rule, parent_widget, active=False, max_text_length=None):
        # Truncate text if longer than max length
        max_len = max_text_length or MAX_CHIP_TEXT_LENGTH
        full_text = rule['folder_type']
        if len(full_text) > max_len:
            display_text = full_text[:max_len - 2] + '..'
        else:
            display_text = full_text

        super().__init__(display_text)
        self.rule = rule
        self.parent_widget = parent_widget
        self.active = active
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Show full text on hover if truncated
        if len(full_text) > max_len:
            self.setToolTip(full_text)

        self.update_style()

    def update_style(self):
        """Update chip appearance based on active state."""
        colour = self.rule['colour']
        if self.active:
            # Active: colored background
            self.setStyleSheet(f"""
                QLabel {{
                    background-color: {colour};
                    color: white;
                    padding: 2px 8px;
                    border-radius: 10px;
                    font-size: 11px;
                    font-weight: bold;
                }}
            """)
        else:
            # Inactive: gray background
            self.setStyleSheet(f"""
                QLabel {{
                    background-color: #e2e8f0;
                    color: #64748b;
                    padding: 2px 8px;
                    border-radius: 10px;
                    font-size: 11px;
                }}
                QLabel:hover {{
                    background-color: #cbd5e1;
                }}
            """)

    def set_active(self, active):
        """Set the active state of the chip."""
        self.active = active
        self.update_style()

    def mousePressEvent(self, event):
        """Handle click - show context menu to reassign or remove."""
        if self.parent_widget:
            self.parent_widget.on_chip_clicked(self)


class AttachmentWidget(QWidget):
    """Custom widget for an email attachment with checkbox and clickable filename."""

    def __init__(self, filename, size_str, attachment_data, parent_widget, is_excluded=False,
                 matched_rules=None, is_drawing=False, file_path=None, from_current_drawings=False):
        super().__init__()
        self.filename = filename
        self.size_str = size_str
        self.attachment_data = attachment_data  # For email attachments (bytes)
        self.file_path = file_path  # For dropped files (path string)
        self.parent_widget = parent_widget
        self.is_excluded = is_excluded
        self.words_visible = False
        self.word_labels = []

        # Secondary filing
        self.matched_rules = matched_rules or []
        self.is_drawing = is_drawing
        self.secondary_filing_enabled = is_drawing  # Auto-enable for drawings
        self.filing_chips = []

        # Track if file came from Current Drawings folder (skip secondary filing to same)
        self.from_current_drawings = from_current_drawings

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Main row with checkbox, filename, chips at end
        main_row = QHBoxLayout()
        main_row.setContentsMargins(0, 0, 0, 0)
        main_row.setSpacing(6)

        # Checkbox (only toggles when clicked directly)
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(not self.is_excluded)
        self.checkbox.setStyleSheet("QCheckBox { spacing: 0px; }")
        main_row.addWidget(self.checkbox)

        # Filename label (clickable to show/hide words) - allow word wrap for long names
        self.filename_label = QLabel(f"{self.filename} ({self.size_str})")
        self.filename_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.filename_label.setWordWrap(True)
        if self.is_excluded:
            self.filename_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        else:
            self.filename_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 12px;")
        self.filename_label.mousePressEvent = self.on_filename_clicked
        main_row.addWidget(self.filename_label, 1)  # stretch factor 1 to take available space

        # Secondary filing section - ALWAYS show for alignment consistency
        self._setup_secondary_filing_inline(main_row)

        layout.addLayout(main_row)

        # Words container (hidden by default)
        self.words_container = QWidget()
        self.words_container.setStyleSheet("margin-left: 20px;")
        self.words_layout = FlowLayout(self.words_container, margin=0, spacing=2)
        self.words_container.setVisible(False)
        layout.addWidget(self.words_container)

        # Populate words from filename
        self._populate_words()

    def _setup_secondary_filing_inline(self, row_layout):
        """Setup the secondary filing checkbox and chips inline at end of row.

        Uses fixed width container for alignment with buttons below.
        Limited to MAX_CHIPS chips, prioritized by: manual > high confidence > low confidence.
        """
        # Fixed-width container for entire secondary filing section (aligns with buttons)
        self.secondary_container = QWidget()
        self.secondary_container.setFixedWidth(SECONDARY_FILING_WIDTH)
        secondary_layout = QHBoxLayout(self.secondary_container)
        secondary_layout.setContentsMargins(0, 0, 0, 0)
        secondary_layout.setSpacing(4)

        # Secondary filing checkbox (no text - header has the label)
        self.secondary_checkbox = QCheckBox()
        self.secondary_checkbox.setChecked(self.secondary_filing_enabled)
        self.secondary_checkbox.setToolTip("Also file to secondary destinations")
        self.secondary_checkbox.stateChanged.connect(self._on_secondary_checkbox_changed)
        secondary_layout.addWidget(self.secondary_checkbox)

        # Chips container - horizontal, limited to MAX_CHIPS
        self.chips_container = QWidget()
        self.chips_container.setFixedHeight(24)
        self.chips_layout = QHBoxLayout(self.chips_container)
        self.chips_layout.setContentsMargins(0, 0, 0, 0)
        self.chips_layout.setSpacing(4)

        # Build list of chips to show (limited to MAX_CHIPS)
        # Priority: drawings first (auto-detected), then by confidence descending
        chips_to_add = []

        # Add Current Drawings chip first if it's a drawing (highest priority)
        if self.is_drawing:
            drawing_rule = {
                'keywords': [],
                'descriptors': [],
                'folder_location': '/XXXX_CURRENT-DRAWINGS',
                'folder_type': 'Current Drawings',
                'colour': '#f59e0b',
                'is_manual': False
            }
            chips_to_add.append(drawing_rule)

        # Add matched rules sorted by confidence (already sorted)
        for match in self.matched_rules:
            if len(chips_to_add) < MAX_CHIPS:
                chips_to_add.append(match['rule'])

        # Create chip widgets (up to MAX_CHIPS)
        for rule in chips_to_add[:MAX_CHIPS]:
            chip = FilingChip(rule, self, active=self.secondary_filing_enabled)
            self.chips_layout.addWidget(chip)
            self.filing_chips.append(chip)

        secondary_layout.addWidget(self.chips_container)

        # Add [+] button for adding more destinations (right after chips)
        self.add_chip_btn = QPushButton("+")
        self.add_chip_btn.setFixedSize(20, 20)
        self.add_chip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_chip_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg']};
                color: {COLORS['text_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['primary']};
                color: white;
                border-color: {COLORS['primary']};
            }}
        """)
        self.add_chip_btn.clicked.connect(self._on_add_chip_clicked)
        self.add_chip_btn.setVisible(self.secondary_filing_enabled)
        secondary_layout.addWidget(self.add_chip_btn)
        secondary_layout.addStretch()  # Push chips and + to the left

        row_layout.addWidget(self.secondary_container)

    def _on_secondary_checkbox_changed(self, state):
        """Handle secondary filing checkbox state change."""
        self.secondary_filing_enabled = state == Qt.CheckState.Checked.value
        # Update all chips
        for chip in self.filing_chips:
            chip.set_active(self.secondary_filing_enabled)
        # Show/hide add button
        if hasattr(self, 'add_chip_btn'):
            self.add_chip_btn.setVisible(self.secondary_filing_enabled)

    def _on_add_chip_clicked(self):
        """Handle click on [+] button to add more destinations."""
        if self.parent_widget:
            self.parent_widget.show_add_destination_menu(self)

    def on_chip_clicked(self, chip):
        """Handle click on a filing chip."""
        if self.parent_widget:
            self.parent_widget.show_chip_menu(self, chip)

    def remove_chip(self, chip):
        """Remove a filing chip."""
        if chip in self.filing_chips:
            self.filing_chips.remove(chip)
            self.chips_layout.removeWidget(chip)
            chip.deleteLater()
            # Show + button if now under limit
            if hasattr(self, 'add_chip_btn'):
                self.add_chip_btn.setVisible(len(self.filing_chips) < MAX_CHIPS and self.secondary_filing_enabled)

    def add_chip(self, rule, is_manual=True):
        """Add a new filing chip.

        Manual additions have highest priority and are inserted at the front.
        If at MAX_CHIPS, removes lowest priority chip to make room for manual additions.
        """
        # Check if rule already exists
        for chip in self.filing_chips:
            if chip.rule['folder_type'] == rule['folder_type']:
                return  # Already exists

        # Mark as manual if user-added
        rule_copy = dict(rule)
        rule_copy['is_manual'] = is_manual

        # If at max chips and this is manual, remove last (lowest priority) chip
        if len(self.filing_chips) >= MAX_CHIPS and is_manual:
            # Remove the last chip (lowest priority)
            last_chip = self.filing_chips.pop()
            self.chips_layout.removeWidget(last_chip)
            last_chip.deleteLater()

        # Only add if under limit
        if len(self.filing_chips) < MAX_CHIPS:
            chip = FilingChip(rule_copy, self, active=self.secondary_filing_enabled)
            if hasattr(self, 'chips_layout'):
                if is_manual:
                    # Insert at front for manual additions
                    self.chips_layout.insertWidget(0, chip)
                    self.filing_chips.insert(0, chip)
                else:
                    # Append at end for auto additions
                    self.chips_layout.addWidget(chip)
                    self.filing_chips.append(chip)

        # Hide + button if at max chips
        if hasattr(self, 'add_chip_btn'):
            self.add_chip_btn.setVisible(len(self.filing_chips) < MAX_CHIPS and self.secondary_filing_enabled)

    def set_secondary_enabled(self, enabled):
        """Set secondary filing enabled state (called by header tick-all)."""
        if hasattr(self, 'secondary_checkbox'):
            self.secondary_checkbox.setChecked(enabled)

    def get_secondary_destinations(self):
        """Get list of active secondary filing destinations."""
        if not self.secondary_filing_enabled:
            return []
        return [chip.rule for chip in self.filing_chips if chip.active]

    def _populate_words(self):
        """Extract and create word labels from filename."""
        # Remove extension and split into words
        name_without_ext = self.filename.rsplit('.', 1)[0] if '.' in self.filename else self.filename
        words = re.findall(r'\b[\w\-]+\b', name_without_ext)

        for i, word in enumerate(words):
            if len(word) > 1:  # Skip single characters
                label = ClickableWordLabel(word, self.parent_widget, i, word_group=f'filename_{id(self)}')
                self.words_layout.addWidget(label)
                self.word_labels.append(label)

    def on_filename_clicked(self, event):
        """Toggle visibility of clickable words."""
        self.words_visible = not self.words_visible
        self.words_container.setVisible(self.words_visible)

        # Update filename style to indicate expanded state
        if self.words_visible:
            if self.is_excluded:
                self.filename_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px; font-weight: bold;")
            else:
                self.filename_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 12px; font-weight: bold;")
        else:
            if self.is_excluded:
                self.filename_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
            else:
                self.filename_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 12px;")

    def isChecked(self):
        """Return checkbox state."""
        return self.checkbox.isChecked()

    def setChecked(self, checked):
        """Set checkbox state."""
        self.checkbox.setChecked(checked)


class DropZone(QFrame):
    """Drag and drop zone for files."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_widget = parent
        self.setAcceptDrops(True)
        self.setup_ui()

    def setup_ui(self):
        self.setMinimumHeight(200)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg']};
                border: 2px dashed {COLORS['border']};
                border-radius: 12px;
            }}
            QFrame:hover {{
                border-color: {COLORS['primary']};
                background-color: {COLORS['primary']}11;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = QLabel("📁")
        icon.setFont(QFont("Segoe UI", 48))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        text = QLabel("Drop files here")
        text.setFont(QFont("Segoe UI", 16, QFont.Weight.DemiBold))
        text.setStyleSheet(f"color: {COLORS['text_secondary']};")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(text)

        subtext = QLabel("or click to browse (supports .eml files)")
        subtext.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        subtext.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtext)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(f"""
                QFrame {{
                    background-color: {COLORS['primary']}22;
                    border: 2px dashed {COLORS['primary']};
                    border-radius: 12px;
                }}
            """)

    def dragLeaveEvent(self, event):
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg']};
                border: 2px dashed {COLORS['border']};
                border-radius: 12px;
            }}
        """)

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg']};
                border: 2px dashed {COLORS['border']};
                border-radius: 12px;
            }}
        """)

        files = []
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.exists(file_path):
                files.append(file_path)

        if files and self.parent_widget:
            self.parent_widget.on_files_dropped(files)

    def mousePressEvent(self, event):
        # Open file dialog on click
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Files to Import/Export",
            "",
            "All Files (*.*);;Email Files (*.eml)"
        )
        if files and self.parent_widget:
            self.parent_widget.on_files_dropped(files)
