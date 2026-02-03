#!/usr/bin/env python3
"""
Jaike_CRM Filing Widget - Standalone file import/export tool.

Drag files onto the widget to automatically file them into project folders.
Supports .eml files with automatic attachment extraction and direction detection.
"""
import sys
import os
import re
import csv
import shutil
import tempfile
import email
import sqlite3
import hashlib
import logging
import argparse
import base64
from io import BytesIO
from email import policy
from email.utils import parsedate_to_datetime, parseaddr
from pathlib import Path
from datetime import datetime, timezone
from difflib import SequenceMatcher
from html.parser import HTMLParser

# Optional imports for email PDF generation
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    from weasyprint import HTML, CSS
    HAS_WEASYPRINT = True
except ImportError:
    HAS_WEASYPRINT = False

try:
    from xhtml2pdf import pisa
    HAS_XHTML2PDF = True
except ImportError:
    HAS_XHTML2PDF = False

# Check if any PDF renderer is available
HAS_PDF_RENDERER = HAS_WEASYPRINT or HAS_XHTML2PDF

# Optional import for PDF metadata and content extraction
try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    try:
        from PyPDF2 import PdfReader
        HAS_PYPDF = True
    except ImportError:
        HAS_PYPDF = False

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QRadioButton, QButtonGroup,
    QFrame, QMessageBox, QFileDialog, QComboBox, QCheckBox,
    QScrollArea, QSizePolicy, QCompleter, QLayout, QDialog, QMenu
)
from PyQt6.QtCore import Qt, QMimeData, QUrl, QStringListModel, QRect, QSize, QPoint
from PyQt6.QtGui import QFont, QDragEnterEvent, QDropEvent, QDesktopServices, QPixmap

# Import configuration from fileuzi package
from fileuzi.config import (
    PROJECTS_ROOT,
    MY_EMAIL_ADDRESSES,
    MIN_ATTACHMENT_SIZE,
    MIN_EMBEDDED_IMAGE_SIZE,
    DOMAIN_SUFFIXES,
    COLORS,
    SECONDARY_FILING_WIDTH,
    MAX_CHIPS,
    MAX_CHIP_TEXT_LENGTH,
    MAX_HEADER_CHIP_LENGTH,
    FILING_WIDGET_TOOLS_FOLDER,
    DATABASE_FILENAME,
    DATABASE_BACKUP_FILENAME,
    FILING_RULES_FILENAME,
    PROJECT_MAPPING_FILENAME,
    OPERATIONS_LOG_FILENAME,
    CIRCUIT_BREAKER_LIMIT,
    SIGN_OFF_PATTERNS,
    DATABASE_SCHEMA,
    STAGE_HIERARCHY,
)

# Import utilities from fileuzi package
from fileuzi.utils import (
    PathJailViolation,
    CircuitBreakerTripped,
    FileOperationCounter,
    get_circuit_breaker,
    validate_path_jail,
    get_tools_folder_path,
    ensure_tools_folder,
    get_operations_log_path,
    get_file_ops_logger,
    safe_copy,
    safe_move,
    safe_write_attachment,
    HTMLTextExtractor,
)

# Import database functions from fileuzi package
from fileuzi.database import (
    get_database_path,
    get_database_backup_path,
    check_database_integrity,
    backup_database,
    init_database,
    check_database_exists,
    verify_database_schema,
    generate_email_hash,
    check_duplicate_email,
    update_filed_also,
    insert_email_record,
    get_contacts_from_database,
    get_contact_for_sender,
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
                 matched_rules=None, is_drawing=False, file_path=None):
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


class SuccessDialog(QDialog):
    """Custom success dialog with clickable folder link."""

    def __init__(self, parent, message_or_count, dest_folder):
        super().__init__(parent)
        self.dest_folder = dest_folder
        self.setWindowTitle("Success")
        self.setModal(True)
        self.setup_ui(message_or_count)

    def setup_ui(self, message_or_count):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Success message - handle both string and int
        if isinstance(message_or_count, str):
            msg_text = message_or_count
        else:
            msg_text = f"Filed {message_or_count} item(s)"

        message = QLabel(f"{msg_text}\n\nPrimary location:")
        message.setStyleSheet("font-size: 14px;")
        layout.addWidget(message)

        # Clickable folder link
        folder_link = QLabel(f'<a href="file://{self.dest_folder}" style="color: #2563eb;">{self.dest_folder}</a>')
        folder_link.setStyleSheet("font-size: 12px;")
        folder_link.setWordWrap(True)
        folder_link.setOpenExternalLinks(False)
        folder_link.linkActivated.connect(self.on_link_clicked)
        folder_link.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(folder_link)

        # OK button
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        ok_btn = QPushButton("OK")
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 24px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
        """)
        ok_btn.clicked.connect(self.accept)
        button_layout.addWidget(ok_btn)

        layout.addLayout(button_layout)

        self.setMinimumWidth(400)

    def on_link_clicked(self, link):
        """Open folder and close dialog."""
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.dest_folder)))
        self.accept()


class DatabaseMissingDialog(QDialog):
    """Dialog shown when filing database is missing at the project root."""

    def __init__(self, parent, new_root_path, old_root_path=None):
        super().__init__(parent)
        self.new_root_path = new_root_path
        self.old_root_path = old_root_path
        self.result_action = None
        self.imported_db_path = None
        self.setWindowTitle("Filing Database Not Found")
        self.setModal(True)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Warning icon and message
        warning_label = QLabel(f"⚠ No filing database found at:\n\n{self.new_root_path}")
        warning_label.setStyleSheet(f"color: {COLORS['warning']}; font-size: 14px; font-weight: bold;")
        warning_label.setWordWrap(True)
        layout.addWidget(warning_label)

        info_label = QLabel("The filing database tracks previously filed emails to prevent duplicates.")
        info_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Options
        options_label = QLabel("Options:")
        options_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 13px; font-weight: bold;")
        layout.addWidget(options_label)

        # Option A - Create new
        btn_create = QPushButton("a) Create a new empty database here")
        btn_create.setStyleSheet(self._button_style())
        btn_create.clicked.connect(self.on_create_new)
        layout.addWidget(btn_create)

        # Option B - Import
        btn_import = QPushButton("b) Import existing database from another location...")
        btn_import.setStyleSheet(self._button_style())
        btn_import.clicked.connect(self.on_import)
        layout.addWidget(btn_import)

        # Option C - Copy from old (only if old path exists and has db)
        if self.old_root_path and self.old_root_path != self.new_root_path:
            old_db = get_database_path(self.old_root_path)
            if old_db.exists():
                btn_copy = QPushButton(f"c) Copy database from previous root:\n{self.old_root_path}")
                btn_copy.setStyleSheet(self._button_style())
                btn_copy.clicked.connect(self.on_copy_from_old)
                layout.addWidget(btn_copy)

        self.setMinimumWidth(500)

    def _button_style(self):
        return f"""
            QPushButton {{
                background-color: {COLORS['bg']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 12px 16px;
                text-align: left;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['primary']}11;
                border-color: {COLORS['primary']};
            }}
        """

    def on_create_new(self):
        self.result_action = 'create'
        self.accept()

    def on_import(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Filing Database",
            "",
            "SQLite Database (*.db);;All Files (*.*)"
        )
        if file_path:
            self.result_action = 'import'
            self.imported_db_path = file_path
            self.accept()

    def on_copy_from_old(self):
        self.result_action = 'copy'
        self.accept()


class DuplicateEmailDialog(QDialog):
    """Dialog shown when a duplicate email is detected."""

    def __init__(self, parent, filed_at, filed_to, filed_also=None):
        super().__init__(parent)
        self.filed_at = filed_at
        self.filed_to = filed_to
        self.filed_also = filed_also
        self.result_action = None
        self.setWindowTitle("Duplicate Email Detected")
        self.setModal(True)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Warning message
        warning_label = QLabel("This email was already filed:")
        warning_label.setStyleSheet(f"color: {COLORS['warning']}; font-size: 14px; font-weight: bold;")
        layout.addWidget(warning_label)

        # Filing details
        details = f"• Filed on: {self.filed_at}\n• Primary location: {self.filed_to}"
        if self.filed_also:
            details += f"\n• Also filed to: {self.filed_also}"
        details_label = QLabel(details)
        details_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 12px;")
        details_label.setWordWrap(True)
        layout.addWidget(details_label)

        # Options
        btn_file_again = QPushButton("a) File again to new destination (updates record)")
        btn_file_again.setStyleSheet(self._button_style())
        btn_file_again.clicked.connect(self.on_file_again)
        layout.addWidget(btn_file_again)

        btn_skip = QPushButton("b) Skip - don't file this email")
        btn_skip.setStyleSheet(self._button_style())
        btn_skip.clicked.connect(self.on_skip)
        layout.addWidget(btn_skip)

        self.setMinimumWidth(450)

    def _button_style(self):
        return f"""
            QPushButton {{
                background-color: {COLORS['bg']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 10px 16px;
                text-align: left;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['primary']}11;
                border-color: {COLORS['primary']};
            }}
        """

    def on_file_again(self):
        self.result_action = 'file_again'
        self.accept()

    def on_skip(self):
        self.result_action = 'skip'
        self.accept()


def scan_for_file_duplicates(project_path, filename):
    """
    Scan ALL subfolders of a project for files with the same name.

    Args:
        project_path: Path to the project folder
        filename: Name of the file to check for duplicates

    Returns:
        list: List of Path objects where duplicates exist
    """
    duplicates = []
    project_path = Path(project_path)

    if not project_path.exists():
        return duplicates

    # Walk through all subdirectories
    for item in project_path.rglob(filename):
        if item.is_file():
            duplicates.append(item)

    return duplicates


class FileDuplicateDialog(QDialog):
    """Dialog shown when a duplicate file is detected in the project."""

    def __init__(self, parent, filename, duplicate_locations, projects_root):
        super().__init__(parent)
        self.filename = filename
        self.duplicate_locations = duplicate_locations
        self.projects_root = projects_root
        self.result_action = None
        self.new_filename = None
        self.setWindowTitle("Duplicate File Detected")
        self.setModal(True)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Warning message
        warning_label = QLabel(f"File '{self.filename}' already exists in this project:")
        warning_label.setStyleSheet(f"color: {COLORS['warning']}; font-size: 14px; font-weight: bold;")
        warning_label.setWordWrap(True)
        layout.addWidget(warning_label)

        # List of duplicate locations
        locations_text = ""
        for loc in self.duplicate_locations[:5]:  # Show max 5 locations
            locations_text += f"• {loc}\n"
        if len(self.duplicate_locations) > 5:
            locations_text += f"... and {len(self.duplicate_locations) - 5} more"

        locations_label = QLabel(locations_text.strip())
        locations_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 12px;")
        locations_label.setWordWrap(True)
        layout.addWidget(locations_label)

        # Options
        btn_skip = QPushButton("a) Skip - don't copy this file")
        btn_skip.setStyleSheet(self._button_style())
        btn_skip.clicked.connect(self.on_skip)
        layout.addWidget(btn_skip)

        btn_rename = QPushButton("b) Rename - add _v2 suffix")
        btn_rename.setStyleSheet(self._button_style())
        btn_rename.clicked.connect(self.on_rename)
        layout.addWidget(btn_rename)

        btn_overwrite = QPushButton("c) Overwrite - replace existing file(s)")
        btn_overwrite.setStyleSheet(self._button_style())
        btn_overwrite.clicked.connect(self.on_overwrite)
        layout.addWidget(btn_overwrite)

        self.setMinimumWidth(500)

    def _button_style(self):
        return f"""
            QPushButton {{
                background-color: {COLORS['bg']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 10px 16px;
                text-align: left;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['primary']}11;
                border-color: {COLORS['primary']};
            }}
        """

    def on_skip(self):
        self.result_action = 'skip'
        # Log the decision
        logger = get_file_ops_logger(self.projects_root)
        logger.info(f"DUPLICATE SKIP | {self.filename} | Existing at: {self.duplicate_locations[0]}")
        self.accept()

    def on_rename(self):
        self.result_action = 'rename'
        # Generate new filename with _v2 suffix (or increment if _v2 exists)
        base, ext = os.path.splitext(self.filename)
        # Check for existing version suffix
        import re as regex
        version_match = regex.search(r'_v(\d+)$', base)
        if version_match:
            current_version = int(version_match.group(1))
            base = base[:version_match.start()]
            self.new_filename = f"{base}_v{current_version + 1}{ext}"
        else:
            self.new_filename = f"{base}_v2{ext}"
        # Log the decision
        logger = get_file_ops_logger(self.projects_root)
        logger.info(f"DUPLICATE RENAME | {self.filename} -> {self.new_filename}")
        self.accept()

    def on_overwrite(self):
        self.result_action = 'overwrite'
        # Log the decision
        logger = get_file_ops_logger(self.projects_root)
        logger.info(f"DUPLICATE OVERWRITE | {self.filename} | Replacing: {self.duplicate_locations[0]}")
        self.accept()


# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Try to import from database for settings, but work standalone too
try:
    from pyqt_app.database import get_session, Settings
    HAS_DATABASE = True
except ImportError:
    HAS_DATABASE = False

# ============================================================================
# EMAIL PARSING FUNCTIONS
# ============================================================================


def extract_email_body(msg):
    """
    Extract the text body from an email message.

    Handles multipart emails - prefers text/plain, falls back to stripped text/html.

    Returns:
        str: The email body text
    """
    body = ''

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = part.get_content_disposition()

            # Skip attachments
            if content_disposition == 'attachment':
                continue

            if content_type == 'text/plain':
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    try:
                        body = payload.decode(charset, errors='replace')
                        break  # Prefer plain text
                    except:
                        pass
            elif content_type == 'text/html' and not body:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    try:
                        html_content = payload.decode(charset, errors='replace')
                        extractor = HTMLTextExtractor()
                        extractor.feed(html_content)
                        body = extractor.get_text()
                    except:
                        pass
    else:
        content_type = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or 'utf-8'
            try:
                if content_type == 'text/html':
                    html_content = payload.decode(charset, errors='replace')
                    extractor = HTMLTextExtractor()
                    extractor.feed(html_content)
                    body = extractor.get_text()
                else:
                    body = payload.decode(charset, errors='replace')
            except:
                pass

    return body.strip()


def extract_email_html_body(msg):
    """
    Extract the HTML body from an email message for PDF rendering.

    Returns the raw HTML content with cid: image references intact.

    Returns:
        str or None: The HTML body content, or None if no HTML body found
    """
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = part.get_content_disposition()

            # Skip attachments
            if content_disposition == 'attachment':
                continue

            if content_type == 'text/html':
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    try:
                        return payload.decode(charset, errors='replace')
                    except:
                        pass
    else:
        content_type = msg.get_content_type()
        if content_type == 'text/html':
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or 'utf-8'
                try:
                    return payload.decode(charset, errors='replace')
                except:
                    pass

    return None


def parse_body_with_signoff(body_text):
    """
    Parse email body and detect sign-off.

    Returns:
        tuple: (body_clean, sign_off_type)
    """
    if not body_text:
        return ('', None)

    lines = body_text.split('\n')
    body_lines = []
    sign_off_type = None

    for i, line in enumerate(lines):
        line_lower = line.strip().lower()

        # Check for sign-off patterns
        for pattern in SIGN_OFF_PATTERNS:
            if line_lower.startswith(pattern) or line_lower == pattern:
                sign_off_type = pattern.title()
                # Return everything before this line
                body_clean = '\n'.join(body_lines).strip()
                return (body_clean, sign_off_type)

        body_lines.append(line)

    # No sign-off found
    return (body_text.strip(), None)

def scan_projects_folder(projects_root):
    """
    Scan the projects root folder for project directories.

    Looks for folders matching pattern: XXXX - Project Name or XXXXX - Project Name
    (4-5 digit job number followed by " - " and project name)

    Returns:
        list: List of tuples (job_number, project_name) sorted by job number descending
    """
    projects = []
    root_path = Path(projects_root)

    if not root_path.exists():
        return projects

    for item in root_path.iterdir():
        # Only process directories, ignore files
        if not item.is_dir():
            continue

        # Use existing parse_folder_name function to extract job number and name
        job_number, project_name = parse_folder_name(item.name)
        if job_number and project_name:
            projects.append((job_number, project_name))

    # Sort by job number descending (newest jobs first)
    projects.sort(key=lambda x: x[0], reverse=True)

    return projects


def parse_folder_name(folder_name):
    """
    Parse folder name in format: {job_number} - {project_name}

    Returns:
        tuple: (job_number, project_name) or (None, None) if invalid
    """
    match = re.match(r'^(\d{4,5})\s*[-–]\s*(.+)$', folder_name)
    if match:
        job_number = match.group(1)
        project_name = match.group(2).strip()
        return (job_number, project_name)
    return (None, None)


def extract_job_number_from_filename(filename, project_mapping=None):
    """
    Extract job number from filename in format: XXXX_... or XXXXX_... or custom prefix.

    Examples:
        2506_22_PROPOSED SECTIONS_C02.pdf -> 2506
        25061_DRAWING.pdf -> 25061
        B-012_01_DRAWING.pdf -> 2505 (if B-012 maps to 2505)

    Returns:
        str: job_number or None if not found
    """
    # Check custom project mappings FIRST (allows B-012 style prefixes)
    if project_mapping:
        for custom_no, local_no in project_mapping.items():
            # Check for patterns like B-012_... or B-012 - ...
            escaped = re.escape(custom_no)
            # Match prefix followed by underscore, space, or dash
            pattern = rf'^{escaped}[\s_\-]'
            if re.match(pattern, filename, re.IGNORECASE):
                return local_no

    # Then check standard numeric pattern
    match = re.match(r'^(\d{4,5})_', filename)
    if match:
        return match.group(1)
    return None


def find_job_number_from_path(file_path, project_mapping=None):
    """
    Find job number from file path - checks filename first, then folder structure.

    Returns:
        tuple: (job_number, project_name, project_folder_path) or (None, None, None)
    """
    path = Path(file_path)

    # First, check the filename itself for XXXX_ pattern or custom prefix
    filename = path.name
    job_number = extract_job_number_from_filename(filename, project_mapping)
    if job_number:
        return (job_number, None, None)

    # Walk up the directory tree looking for folder pattern
    for parent in path.parents:
        folder_name = parent.name
        job_number, project_name = parse_folder_name(folder_name)
        if job_number:
            return (job_number, project_name, str(parent))

    return (None, None, None)


def is_embedded_image(filename):
    """
    Check if filename looks like an embedded/inline image.
    These typically have names like 'image1769415576585.png' or 'image1769415576585'
    """
    name_lower = filename.lower()
    # Remove extension if present
    base_name = name_lower.rsplit('.', 1)[0] if '.' in name_lower else name_lower

    # Pattern: 'image' followed by digits (with or without extension)
    if re.match(r'^image\d+$', base_name):
        return True
    # Pattern: just a long number (with or without extension)
    if re.match(r'^\d{10,}$', base_name):
        return True
    # Pattern: UUID-like or hash-like names
    if re.match(r'^[a-f0-9\-]{20,}$', base_name):
        return True
    return False


# ============================================================================
# SECONDARY FILING - CSV Rules and Matching
# ============================================================================

def get_filing_rules_path(projects_root):
    """Get the path to the filing rules CSV in the tools folder."""
    return get_tools_folder_path(projects_root) / FILING_RULES_FILENAME


def get_project_mapping_path(projects_root):
    """Get the path to the custom project number mapping CSV in the tools folder."""
    return get_tools_folder_path(projects_root) / PROJECT_MAPPING_FILENAME


def load_project_mapping(projects_root):
    """
    Load custom project number mapping from CSV file.

    Maps external project numbers (e.g., client's drawing numbers) to local job numbers.
    If the file doesn't exist, returns empty dict (tool continues working normally).

    Returns:
        dict: Mapping of custom_project_no -> local_job_no (e.g., {'B-012': '2505'})
    """
    csv_path = get_project_mapping_path(projects_root)

    if not csv_path.exists():
        return {}

    mapping = {}
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                custom_no = row.get('Custom Project No:', '').strip()
                local_no = row.get('Local Project No:', '').strip()
                if custom_no and local_no:
                    # Store both original and uppercase for case-insensitive matching
                    mapping[custom_no] = local_no
                    mapping[custom_no.upper()] = local_no
    except Exception as e:
        print(f"Warning: Failed to load project mapping: {e}")
        return {}

    return mapping


def apply_project_mapping(filename, mapping):
    """
    Check if filename starts with a custom project number and return the local job number.

    Args:
        filename: The filename to check
        mapping: Dict of custom_project_no -> local_job_no

    Returns:
        str or None: The local job number if mapping found, None otherwise
    """
    if not mapping:
        return None

    # Check if filename starts with any custom project number
    filename_upper = filename.upper()
    for custom_no, local_no in mapping.items():
        if filename_upper.startswith(custom_no.upper()):
            return local_no

    return None


def detect_project_from_subject(subject, known_projects, project_mapping=None):
    """
    Detect project number from email subject line.

    Detection logic:
    1. Strip RE:/FW:/Fwd: prefixes
    2. Check mapping CSV for client references (e.g., B-013 -> 2507)
    3. Look for 4-digit job number
    4. Check if it matches a known project

    Args:
        subject: Email subject line
        known_projects: List of (project_number, project_name) tuples
        project_mapping: Dict mapping client references to local job numbers

    Returns:
        str or None: Detected job number, or None if not found
    """
    if not subject:
        return None

    # Strip common reply/forward prefixes
    cleaned = re.sub(r'^(RE:|FW:|FWD:|Re:|Fw:|Fwd:)\s*', '', subject, flags=re.IGNORECASE).strip()

    # Build set of known project numbers for quick lookup
    known_numbers = {proj[0] for proj in known_projects} if known_projects else set()

    # Check mapping CSV FIRST - client references like B-013 at start of subject
    if project_mapping:
        for custom_ref, local_job in project_mapping.items():
            # Check if subject starts with the custom reference (most common case)
            if cleaned.upper().startswith(custom_ref.upper()):
                return local_job
            # Also check if reference appears anywhere in subject
            if custom_ref.upper() in cleaned.upper():
                return local_job

    # Then look for 4-digit job numbers near the start
    search_text = cleaned[:50] if len(cleaned) > 50 else cleaned
    job_matches = re.findall(r'\b(\d{4})\b', search_text)

    # Check if any match a known project
    for job_num in job_matches:
        if job_num in known_numbers:
            return job_num

    # If no match in known projects, return first 4-digit number found (might be valid)
    if job_matches:
        return job_matches[0]

    return None


def load_filing_rules(projects_root):
    """
    Load filing rules from CSV file in FILING-WIDGET-TOOLS folder.

    Returns:
        list: List of rule dicts with keys: keywords, descriptors, folder_location,
              folder_type, subfolder_structure, colour
        Returns None if CSV is missing (caller should handle error)
    """
    csv_path = get_filing_rules_path(projects_root)

    if not csv_path.exists():
        return None

    rules = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Skip paused rules
                if row.get('Pause', '').strip().lower() == 'yes':
                    continue

                # Parse keywords and descriptors (comma-separated)
                keywords = [k.strip().lower() for k in row.get('Keywords', '').split(',') if k.strip()]
                descriptors = [d.strip().lower() for d in row.get('Interchangeable_Descriptors', '').split(',') if d.strip()]

                rules.append({
                    'keywords': keywords,
                    'descriptors': descriptors,
                    'folder_location': row.get('Folder_Location', '').strip(),
                    'folder_type': row.get('Folder_Type', '').strip(),
                    'subfolder_structure': row.get('Subfolder_Structure', '').strip(),
                    'colour': row.get('Colour', '#64748b').strip(),
                })
    except Exception as e:
        print(f"Error loading filing rules: {e}")
        return None

    return rules


def is_drawing_pdf(filename, job_number, project_mapping=None):
    """
    Check if a PDF file is a drawing based on naming convention.

    Patterns:
        - XXXX_NN_... (new convention) e.g., 2506_20_PROPOSED FLOOR PLANS_C01.pdf
        - XXXX_NN ... (space after number) e.g., B-013_11 PLANS & SECTION.pdf
        - XXXX - NNN - ... (old convention) e.g., 2502 - 104 - BUILDING REGULATIONS NOTES_P01.pdf
        - Also supports custom project prefixes via project_mapping (e.g., B-012_20_... -> 2505)

    Returns:
        bool: True if filename matches drawing pattern for the given job
    """
    if not filename.lower().endswith('.pdf'):
        return False

    # Build list of prefixes to check
    prefixes_to_check = []

    # Add job number if provided
    if job_number:
        prefixes_to_check.append(job_number)

    # Add ALL custom project numbers from mapping (check them directly)
    # This ensures we detect drawings even before job is selected
    if project_mapping:
        for custom_no, local_no in project_mapping.items():
            if custom_no not in prefixes_to_check:
                prefixes_to_check.append(custom_no)
            # Also add the local job number in case it's different
            if local_no not in prefixes_to_check:
                prefixes_to_check.append(local_no)

    # Check each prefix
    for prefix in prefixes_to_check:
        # Escape special regex characters in prefix (e.g., "B-012" has a hyphen)
        escaped_prefix = re.escape(prefix)

        # Pattern 1: PREFIX_NN followed by separator (underscore or space)
        # e.g., "2506_20_PLANS.pdf" or "B-013_11 PLANS.pdf"
        pattern1 = rf'^{escaped_prefix}_(\d{{2,3}})[\s_]'
        if re.match(pattern1, filename, re.IGNORECASE):
            return True

        # Pattern 2: PREFIX - NNN followed by separator (space, dash, or underscore)
        # e.g., "B-013 - 11 PLANS.pdf" or "2502 - 104 - BUILDING REGS.pdf"
        pattern2 = rf'^{escaped_prefix}\s*[-–]\s*(\d{{2,3}})[\s\-–_]'
        if re.match(pattern2, filename, re.IGNORECASE):
            return True

    return False


# ============================================================================
# DRAWING REVISION SUPERSEDING
# ============================================================================


def parse_drawing_filename_new(filename):
    """
    Parse a drawing filename in the new underscore format.

    Format: [job]_[drawing number]_[drawing name]_[stage prefix][revision number].pdf
    Example: 2506_22_PROPOSED SECTIONS_C02.pdf

    Returns:
        dict with keys: job, drawing_num, name, stage, revision, format
        None if parsing fails
    """
    if not filename.lower().endswith('.pdf'):
        return None

    # Remove .pdf extension
    base = filename[:-4]

    # Split by underscore and strip whitespace from parts
    parts = [p.strip() for p in base.split('_')]
    if len(parts) < 4:
        return None

    job = parts[0]
    drawing_num = parts[1]

    # Validate job and drawing number are digits
    if not job.isdigit() or not drawing_num.isdigit():
        return None

    # Last part should be stage prefix + revision number
    last_part = parts[-1]

    # Try to match stage prefix + revision number
    # Stage prefixes: F, PL, P, W, C followed by 2-digit number
    stage_match = re.match(r'^(F|PL|P|W|C)(\d{2})$', last_part, re.IGNORECASE)
    if not stage_match:
        return None

    stage = stage_match.group(1).upper()
    revision = int(stage_match.group(2))

    # Drawing name is everything between drawing number and stage/revision
    name = '_'.join(parts[2:-1])

    return {
        'job': job,
        'drawing_num': drawing_num,
        'name': name,
        'stage': stage,
        'revision': revision,
        'format': 'new'
    }


def parse_drawing_filename_old(filename):
    """
    Parse a drawing filename in the old space-dash-space format.

    Format: [job] - [drawing number][revision letter or nothing] - [drawing name].pdf
    Example: 2506 - 04A - PROPOSED PLANS AND ELEVATIONS.pdf
    Example: 2506 - 04 - PROPOSED PLANS AND ELEVATIONS.pdf (first issue, no letter)

    Returns:
        dict with keys: job, drawing_num, name, revision_letter, format
        None if parsing fails
    """
    if not filename.lower().endswith('.pdf'):
        return None

    # Remove .pdf extension
    base = filename[:-4]

    # Split by space-dash-space (handle both - and – dashes)
    parts = re.split(r'\s+[-–]\s+', base)
    if len(parts) < 3:
        return None

    job = parts[0].strip()
    drawing_part = parts[1].strip()
    name = ' - '.join(parts[2:]).strip()  # Join remaining parts as name

    # Validate job is digits
    if not job.isdigit():
        return None

    # Parse drawing number and optional revision letter
    # Drawing number is digits, revision letter (if any) follows immediately
    drawing_match = re.match(r'^(\d{2,3})([A-Z])?$', drawing_part, re.IGNORECASE)
    if not drawing_match:
        return None

    drawing_num = drawing_match.group(1)
    revision_letter = drawing_match.group(2).upper() if drawing_match.group(2) else ''

    return {
        'job': job,
        'drawing_num': drawing_num,
        'name': name,
        'revision_letter': revision_letter,
        'format': 'old'
    }


def parse_drawing_filename(filename):
    """
    Parse a drawing filename, auto-detecting the format.

    Returns:
        dict with parsed info, or None if not a recognized drawing format
    """
    # Try new format first (more specific pattern)
    result = parse_drawing_filename_new(filename)
    if result:
        return result

    # Try old format
    result = parse_drawing_filename_old(filename)
    if result:
        return result

    return None


def compare_drawing_revisions(parsed_a, parsed_b):
    """
    Compare two parsed drawing revisions.

    Returns:
        -1 if a < b (a is older)
         0 if a == b (same revision)
         1 if a > b (a is newer)
    """
    # Different formats: old system always < new system
    if parsed_a['format'] != parsed_b['format']:
        if parsed_a['format'] == 'old':
            return -1  # a is older
        else:
            return 1   # a is newer

    # Same format - compare within format
    if parsed_a['format'] == 'new':
        # Compare by stage first
        stage_a = STAGE_HIERARCHY.index(parsed_a['stage'])
        stage_b = STAGE_HIERARCHY.index(parsed_b['stage'])

        if stage_a != stage_b:
            return -1 if stage_a < stage_b else 1

        # Same stage - compare revision number
        rev_a = parsed_a['revision']
        rev_b = parsed_b['revision']

        if rev_a < rev_b:
            return -1
        elif rev_a > rev_b:
            return 1
        else:
            return 0

    else:  # old format
        # Compare revision letters: '' < 'A' < 'B' < 'C' < ...
        letter_a = parsed_a['revision_letter']
        letter_b = parsed_b['revision_letter']

        # Convert to comparable values ('' = -1, 'A' = 0, 'B' = 1, etc.)
        val_a = -1 if letter_a == '' else ord(letter_a) - ord('A')
        val_b = -1 if letter_b == '' else ord(letter_b) - ord('A')

        if val_a < val_b:
            return -1
        elif val_a > val_b:
            return 1
        else:
            return 0


def find_matching_drawings(current_drawings_folder, job_number, drawing_number):
    """
    Scan a folder for drawings with the same job and drawing number.

    Args:
        current_drawings_folder: Path to Current Drawings folder
        job_number: Job number to match
        drawing_number: Drawing number to match

    Returns:
        list of tuples: [(filepath, parsed_info), ...]
    """
    matches = []
    folder = Path(current_drawings_folder)

    if not folder.exists():
        return matches

    for item in folder.iterdir():
        if not item.is_file():
            continue

        parsed = parse_drawing_filename(item.name)
        if parsed is None:
            continue

        # Check if job and drawing number match
        if parsed['job'] == str(job_number) and parsed['drawing_num'] == str(drawing_number):
            matches.append((item, parsed))

    return matches


def supersede_drawings(current_drawings_folder, new_file_path, projects_root, circuit_breaker=None):
    """
    Handle drawing revision superseding when a new drawing arrives.

    If older revisions of the same drawing exist, move them to Superseded subfolder.

    Args:
        current_drawings_folder: Path to Current Drawings folder
        new_file_path: Path to the newly filed drawing
        projects_root: Project root for path jail validation
        circuit_breaker: Optional FileOperationCounter instance

    Returns:
        tuple: (success, message, superseded_count)
    """
    logger = get_file_ops_logger(projects_root)
    new_file = Path(new_file_path)

    # Parse the new file
    new_parsed = parse_drawing_filename(new_file.name)
    if new_parsed is None:
        # Can't parse - log warning and skip superseding
        logger.warning(f"SUPERSEDE SKIP | Could not parse revision info from: {new_file.name}")
        return (True, f"⚠ Could not parse revision info from: \"{new_file.name}\"\nFiled without superseding check. Manual review recommended.", 0)

    # Find all matching drawings in the folder
    matches = find_matching_drawings(
        current_drawings_folder,
        new_parsed['job'],
        new_parsed['drawing_num']
    )

    # Filter out the new file itself from matches
    matches = [(path, parsed) for path, parsed in matches if path != new_file]

    if not matches:
        # No existing revisions found
        return (True, None, 0)

    # Determine which files need to be superseded
    to_supersede = []
    for match_path, match_parsed in matches:
        comparison = compare_drawing_revisions(match_parsed, new_parsed)
        if comparison < 0:
            # match is older than new file - supersede it
            to_supersede.append((match_path, match_parsed))
        elif comparison > 0:
            # match is newer than new file - this shouldn't happen normally
            # Log warning but don't block the filing
            logger.warning(
                f"SUPERSEDE ANOMALY | New file {new_file.name} appears OLDER than existing {match_path.name}"
            )

    if not to_supersede:
        return (True, None, 0)

    # Create Superseded folder if needed (this is the ONE auto-create exception)
    superseded_folder = Path(current_drawings_folder) / 'Superseded'
    if not superseded_folder.exists():
        try:
            superseded_folder.mkdir(parents=True, exist_ok=True)
            logger.info(f"MKDIR | Created Superseded folder: {superseded_folder}")
        except Exception as e:
            logger.error(f"SUPERSEDE FAILED | Could not create Superseded folder: {e}")
            return (False, f"Could not create Superseded folder: {e}", 0)

    # Move old revisions to Superseded
    superseded_count = 0
    cb = circuit_breaker or get_circuit_breaker()

    for old_path, old_parsed in to_supersede:
        dest_path = superseded_folder / old_path.name

        try:
            # Path jail validation
            validate_path_jail(dest_path, projects_root)

            # Circuit breaker
            cb.record("SUPERSEDE", old_path, dest_path)

            # Safe move: copy -> verify -> delete
            # First copy
            shutil.copy2(str(old_path), str(dest_path))

            # Verify the copy exists and has same size
            if dest_path.exists() and dest_path.stat().st_size == old_path.stat().st_size:
                # Delete source
                old_path.unlink()
                logger.info(f"SUPERSEDE | {old_path.name} -> Superseded/")
                superseded_count += 1
            else:
                # Copy verification failed - don't delete source
                logger.error(f"SUPERSEDE VERIFY FAILED | {old_path.name} - copy verification failed, source retained")
                if dest_path.exists():
                    dest_path.unlink()  # Clean up failed copy

        except PathJailViolation as e:
            logger.error(f"SUPERSEDE BLOCKED | Path jail violation: {e}")
            raise
        except CircuitBreakerTripped:
            raise
        except Exception as e:
            logger.error(f"SUPERSEDE FAILED | {old_path.name}: {e}")

    if superseded_count > 0:
        msg = f"Superseded {superseded_count} older revision(s) → Superseded/"
        return (True, msg, superseded_count)

    return (True, None, 0)


def is_current_drawings_folder(folder_path):
    """
    Check if a folder is a Current Drawings folder (where superseding applies).

    Returns True if folder name contains both "CURRENT" and "DRAWING" (case insensitive).
    """
    folder_name = Path(folder_path).name.upper()
    return 'CURRENT' in folder_name and 'DRAWING' in folder_name


def match_filing_rules(filename, rules, fuzzy_threshold=0.85):
    """
    Match a filename against filing rules.

    IMPORTANT: Only matches against the filename string, NOT file contents.

    Rules:
        - Keywords alone can trigger a match
        - Keyword + Descriptor together increases confidence
        - Descriptors alone do NOT trigger a match
        - Fuzzy matching only for words >= 5 chars and similarity >= 85%

    Returns:
        list: List of matching rules with confidence scores, sorted by confidence desc
              Each item is dict with: rule, confidence
    """
    if not rules:
        return []

    filename_lower = filename.lower()
    # Remove extension for matching
    name_without_ext = filename_lower.rsplit('.', 1)[0] if '.' in filename_lower else filename_lower
    # Split into words for matching (only words 3+ chars)
    filename_words = set(w for w in re.findall(r'\b[\w\-]+\b', name_without_ext) if len(w) >= 3)

    matches = []

    for rule in rules:
        best_confidence = 0
        matched_keyword = None

        # Check each keyword
        for keyword in rule['keywords']:
            keyword_lower = keyword.lower()
            keyword_words = keyword_lower.split()

            # Exact phrase match (highest confidence)
            if keyword_lower in name_without_ext:
                confidence = 1.0
                if confidence > best_confidence:
                    best_confidence = confidence
                    matched_keyword = keyword
                continue

            # Word-by-word match for multi-word keywords
            if len(keyword_words) > 1:
                all_words_found = all(w in filename_words for w in keyword_words)
                if all_words_found:
                    confidence = 0.95
                    if confidence > best_confidence:
                        best_confidence = confidence
                        matched_keyword = keyword
                    continue

            # Single word exact match
            if keyword_lower in filename_words:
                confidence = 0.9
                if confidence > best_confidence:
                    best_confidence = confidence
                    matched_keyword = keyword
                continue

            # Acronym match - keyword with separators vs filename without (e.g., "BR PD", "BR-PD", "BR_PD" vs "BRPD")
            keyword_no_seps = keyword_lower.replace(' ', '').replace('-', '').replace('_', '')
            if len(keyword_no_seps) >= 3 and keyword_no_seps in filename_words:
                confidence = 0.95
                if confidence > best_confidence:
                    best_confidence = confidence
                    matched_keyword = keyword
                continue

            # Also check if filename word without common separators matches keyword
            for word in filename_words:
                word_cleaned = word.replace('-', '').replace('_', '')
                if word_cleaned == keyword_no_seps and len(word_cleaned) >= 3:
                    confidence = 0.95
                    if confidence > best_confidence:
                        best_confidence = confidence
                        matched_keyword = keyword
                    break

            # Fuzzy match - only for keywords >= 5 chars to avoid false positives
            if len(keyword_lower) >= 5:
                for word in filename_words:
                    # Only fuzzy match words of similar length (within 3 chars)
                    if len(word) >= 5 and abs(len(word) - len(keyword_lower)) <= 3:
                        ratio = SequenceMatcher(None, keyword_lower, word).ratio()
                        if ratio >= fuzzy_threshold:
                            if ratio > best_confidence:
                                best_confidence = ratio
                                matched_keyword = keyword

        # If we found a keyword match, check for descriptor bonus
        if best_confidence > 0 and matched_keyword:
            for descriptor in rule['descriptors']:
                descriptor_lower = descriptor.lower()
                if descriptor_lower in name_without_ext or descriptor_lower in filename_words:
                    # Descriptor found - boost confidence slightly
                    best_confidence = min(1.0, best_confidence + 0.05)
                    break

            matches.append({
                'rule': rule,
                'confidence': best_confidence,
                'matched_keyword': matched_keyword
            })

    # Sort by confidence descending
    matches.sort(key=lambda x: x['confidence'], reverse=True)

    return matches


# ============================================================================
# KEYWORD MATCHING CASCADE
# ============================================================================

def is_junk_pdf_line(line):
    """
    Check if a line should be skipped when extracting PDF content.

    Skip:
        - Lines matching "Page X" or "Page X of Y" patterns
        - Lines that are just numbers
        - Lines that are just dates
        - Lines under 5 characters
    """
    line = line.strip()

    # Skip empty or very short lines
    if len(line) < 5:
        return True

    # Skip "Page X" or "Page X of Y" patterns
    if re.match(r'^page\s+\d+(\s+of\s+\d+)?$', line, re.IGNORECASE):
        return True

    # Skip lines that are just numbers (with optional punctuation)
    if re.match(r'^[\d\s.,\-/]+$', line):
        return True

    # Skip date patterns (various formats)
    date_patterns = [
        r'^\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}$',  # DD/MM/YYYY, MM-DD-YY, etc.
        r'^\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2}$',    # YYYY-MM-DD
        r'^(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s+\d{4}$',
        r'^\d{1,2}\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}$',
    ]
    for pattern in date_patterns:
        if re.match(pattern, line, re.IGNORECASE):
            return True

    return False


def is_valid_pdf_title(title, filename):
    """
    Check if a PDF metadata Title field is valid for matching.

    Invalid if:
        - Empty or blank
        - Same as filename (some software copies filename to Title)
        - Generic junk like "untitled", "Document1", "Microsoft Word - ..."
        - Under 5 characters
    """
    if not title or not title.strip():
        return False

    title = title.strip()

    # Too short
    if len(title) < 5:
        return False

    # Same as filename (case-insensitive, with or without extension)
    filename_base = filename.rsplit('.', 1)[0] if '.' in filename else filename
    if title.lower() == filename.lower() or title.lower() == filename_base.lower():
        return False

    # Generic junk patterns
    junk_patterns = [
        r'^untitled(\s+document)?$',
        r'^document\s*\d*$',
        r'^microsoft\s+word\s*[-–]\s*',
        r'^microsoft\s+excel\s*[-–]\s*',
        r'^microsoft\s+powerpoint\s*[-–]\s*',
        r'^adobe\s+(acrobat|reader)',
        r'^new\s+document',
        r'^temp\d*$',
        r'^file\d*$',
    ]
    for pattern in junk_patterns:
        if re.match(pattern, title, re.IGNORECASE):
            return False

    return True


def extract_pdf_metadata_title(pdf_data):
    """
    Extract the Title field from PDF metadata.

    Args:
        pdf_data: Binary PDF data

    Returns:
        str or None: The Title field if present, otherwise None
    """
    if not HAS_PYPDF:
        return None

    try:
        reader = PdfReader(BytesIO(pdf_data))
        metadata = reader.metadata
        if metadata and metadata.title:
            return metadata.title
    except Exception:
        pass

    return None


def extract_pdf_first_content(pdf_data, char_limit=40):
    """
    Extract the first meaningful characters from page 1 of a PDF.

    Skips junk lines (page numbers, dates, very short lines) before
    starting the character count.

    Args:
        pdf_data: Binary PDF data
        char_limit: Number of characters to extract (default 40)

    Returns:
        str or None: First meaningful content, or None if extraction fails
    """
    if not HAS_PYPDF:
        return None

    try:
        reader = PdfReader(BytesIO(pdf_data))
        if len(reader.pages) == 0:
            return None

        # Extract text from first page only
        page = reader.pages[0]
        text = page.extract_text()
        if not text:
            return None

        # Process line by line, skipping junk
        lines = text.split('\n')
        meaningful_content = []
        total_chars = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Skip junk lines
            if is_junk_pdf_line(line):
                continue

            # Add to content until we reach char_limit
            meaningful_content.append(line)
            total_chars += len(line)
            if total_chars >= char_limit:
                break

        if meaningful_content:
            result = ' '.join(meaningful_content)
            return result[:char_limit]

    except Exception:
        pass

    return None


def match_filing_rules_cascade(filename, rules, attachment_data=None, job_number=None, project_mapping=None):
    """
    Match an attachment against filing rules using a cascade approach.

    The cascade prioritizes structured, reliable sources over email subjects:
        1. Skip entirely if this is a JWA drawing (filename contains all info)
        2. Match attachment filename against keywords
        3. If PDF and no match, check PDF metadata Title field
        4. If PDF and no match, extract first 40 meaningful chars of content
        5. No fallback to email subject - return empty if no matches

    Args:
        filename: The attachment filename
        rules: List of filing rule dicts
        attachment_data: Binary data of the attachment (optional, for PDF processing)
        job_number: Current job number (for drawing detection)
        project_mapping: Dict mapping custom project numbers to local job numbers

    Returns:
        list: List of matching rules with confidence scores, sorted by confidence desc
              Each item is dict with: rule, confidence, matched_keyword, match_source
    """
    # Skip condition: If this is a JWA drawing, return empty (drawing filename has all info)
    if job_number and is_drawing_pdf(filename, job_number, project_mapping):
        return []

    # Step 1: Match against attachment filename
    matches = match_filing_rules(filename, rules)
    if matches:
        # Add source info
        for m in matches:
            m['match_source'] = 'filename'
        return matches

    # Only continue with PDF-specific steps if this is a PDF with data
    if not attachment_data or not filename.lower().endswith('.pdf'):
        return []

    # Step 2: Check PDF metadata Title field
    title = extract_pdf_metadata_title(attachment_data)
    if title and is_valid_pdf_title(title, filename):
        matches = match_filing_rules(title, rules)
        if matches:
            for m in matches:
                m['match_source'] = 'pdf_title'
            return matches

    # Step 3: Extract first 40 meaningful characters of PDF content
    content = extract_pdf_first_content(attachment_data, char_limit=40)
    if content:
        matches = match_filing_rules(content, rules)
        if matches:
            for m in matches:
                m['match_source'] = 'pdf_content'
            return matches

    # Step 4: No matches found - return empty (do NOT fall back to email subject)
    return []


def extract_business_from_domain(email_addr):
    """
    Extract business name from email domain.

    Examples:
        john@smitharchitects.co.uk -> smitharchitects
        info@acme-construction.com -> acme-construction
    """
    _, addr = parseaddr(email_addr)
    if not addr or '@' not in addr:
        return None

    domain = addr.split('@')[1].lower()

    # Remove common suffixes
    for suffix in sorted(DOMAIN_SUFFIXES, key=len, reverse=True):
        if domain.endswith(suffix):
            domain = domain[:-len(suffix)]
            break

    # Clean up the business name
    business = domain.replace('.', '-').replace('_', '-')

    # Skip generic/personal email domains
    generic_domains = [
        'gmail', 'googlemail', 'yahoo', 'hotmail', 'outlook', 'icloud', 'aol',
        'mail', 'email', 'live', 'msn', 'btinternet', 'sky', 'virginmedia',
        'protonmail', 'zoho', 'ymail', 'rocketmail', 'fastmail', 'tutanota',
        'gmx', 'web', 'mail', 'me', 'mac', 'pm', 'proton'
    ]
    if business in generic_domains:
        return None

    return business


def parse_eml_file(eml_path):
    """
    Parse an .eml file and extract metadata, body, and attachments.

    Returns:
        dict: {
            'from': str,
            'to': str,
            'cc': str,
            'subject': str,
            'date': datetime,
            'date_iso': str (ISO 8601),
            'message_id': str,
            'body': str (full body text),
            'body_clean': str (body above sign-off),
            'sign_off_type': str or None,
            'attachments': list of {'filename': str, 'data': bytes, 'size': int}
        }
    """
    with open(eml_path, 'rb') as f:
        msg = email.message_from_binary_file(f, policy=policy.default)

    # Extract headers
    from_addr = msg.get('From', '')
    to_addr = msg.get('To', '')
    cc_addr = msg.get('Cc', '')
    subject = msg.get('Subject', '(No Subject)')
    date_str = msg.get('Date', '')
    message_id = msg.get('Message-ID', '')

    # Clean up message_id
    if message_id:
        message_id = message_id.strip().strip('<>').strip()

    # Parse date
    email_date = None
    if date_str:
        try:
            email_date = parsedate_to_datetime(date_str)
        except:
            pass
    if not email_date:
        email_date = datetime.now()

    # Convert to ISO 8601
    date_iso = email_date.isoformat()

    # Extract body
    body = extract_email_body(msg)
    body_clean, sign_off_type = parse_body_with_signoff(body)

    # Extract attachments (excluding embedded images which are handled separately)
    attachments = []
    for part in msg.walk():
        content_disposition = part.get_content_disposition()
        content_type = part.get_content_type()
        content_id = part.get('Content-ID', '')

        # Skip embedded images (inline images with Content-ID that are referenced in body)
        # These are extracted separately via extract_embedded_images() and renamed
        is_embedded_inline = (
            content_disposition == 'inline' and
            content_type.startswith('image/') and
            content_id  # Has Content-ID means it's embedded in HTML body
        )

        if is_embedded_inline:
            continue  # Skip - will be handled by extract_embedded_images

        if content_disposition == 'attachment' or (content_disposition == 'inline' and part.get_filename()):
            filename = part.get_filename()
            if filename:
                data = part.get_payload(decode=True)
                if data:
                    attachments.append({
                        'filename': filename,
                        'data': data,
                        'size': len(data)
                    })

    return {
        'from': from_addr,
        'to': to_addr,
        'cc': cc_addr,
        'subject': subject,
        'date': email_date,
        'date_iso': date_iso,
        'message_id': message_id,
        'body': body,
        'body_clean': body_clean,
        'sign_off_type': sign_off_type,
        'attachments': attachments,
        '_raw_message': msg  # Raw email.message.Message for advanced processing
    }


def is_my_email(email_str):
    """Check if an email address matches one of our configured addresses."""
    _, addr = parseaddr(email_str)
    addr_lower = addr.lower()
    return any(my_addr.lower() in addr_lower for my_addr in MY_EMAIL_ADDRESSES)


def detect_email_direction(email_data):
    """
    Detect if email is IN (import) or OUT (export) based on From/To.

    Returns:
        str: 'IN' if email is to us, 'OUT' if email is from us
    """
    from_addr = email_data.get('from', '')
    to_addr = email_data.get('to', '')

    # If FROM matches our email, it's outgoing (OUT/export)
    if is_my_email(from_addr):
        return 'OUT'

    # If TO matches our email, it's incoming (IN/import)
    if is_my_email(to_addr):
        return 'IN'

    # Default to IN if we can't determine
    return 'IN'


# ============================================================================
# OUTBOUND EMAIL SCREENSHOT & PDF CAPTURE
# ============================================================================

def extract_embedded_images(msg, min_size=MIN_EMBEDDED_IMAGE_SIZE):
    """
    Extract embedded images from an email message.

    Only extracts images that exceed the minimum size threshold.
    Filters out images from quoted reply sections.

    Args:
        msg: email.message.Message object
        min_size: Minimum image size in bytes (default 20KB)

    Returns:
        list of dicts: [{content_id, data, content_type, size}, ...]
    """
    embedded_images = []

    for part in msg.walk():
        content_type = part.get_content_type()
        content_disposition = part.get_content_disposition()

        # Embedded images are typically inline with a Content-ID
        if content_type.startswith('image/') and content_disposition == 'inline':
            content_id = part.get('Content-ID', '')
            # Clean up Content-ID (remove < > brackets)
            if content_id:
                content_id = content_id.strip('<>').strip()

            data = part.get_payload(decode=True)
            if data and len(data) >= min_size:
                embedded_images.append({
                    'content_id': content_id,
                    'data': data,
                    'content_type': content_type,
                    'size': len(data)
                })

    return embedded_images


def convert_image_to_png(image_data):
    """
    Convert image data to PNG format.

    Args:
        image_data: Binary image data

    Returns:
        bytes: PNG image data, or original data if conversion fails
    """
    if not HAS_PIL:
        return image_data

    try:
        img = Image.open(BytesIO(image_data))
        # Convert to RGB if necessary (for RGBA or palette images)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        output = BytesIO()
        img.save(output, format='PNG')
        return output.getvalue()
    except Exception:
        return image_data


def clean_subject_for_filename(subject, job_number):
    """
    Clean email subject for use as filename.

    Removes job number prefix and everything before first ' - ' separator.
    Strips invalid filename characters.

    Args:
        subject: Email subject line
        job_number: Current job number

    Returns:
        str: Cleaned subject suitable for filename
    """
    if not subject:
        return 'untitled'

    cleaned = subject.strip()

    # Remove job number prefix patterns
    # Pattern: "XXXX Smith Extension - Actual Subject"
    # or: "XXXX - Smith Extension - Actual Subject"
    if ' - ' in cleaned:
        # Find the first ' - ' and check if what's before it looks like a project header
        parts = cleaned.split(' - ', 1)
        first_part = parts[0].strip()

        # If the first part starts with the job number, strip it
        if first_part.startswith(job_number):
            cleaned = parts[1] if len(parts) > 1 else first_part
        # Also check if it's just a job number with letters after
        elif re.match(rf'^{job_number}\s+\w+', first_part):
            cleaned = parts[1] if len(parts) > 1 else first_part

    # Remove leading job number if still present
    cleaned = re.sub(rf'^{job_number}\s*[-:]?\s*', '', cleaned)

    # Remove invalid filename characters
    cleaned = re.sub(r'[<>:"/\\|?*]', '', cleaned)

    # Collapse multiple spaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    if not cleaned:
        return 'untitled'

    return cleaned


def generate_email_pdf(email_data, embedded_images, job_number, projects_root):
    """
    Generate a PDF rendering of the full email with embedded images.

    Args:
        email_data: Parsed email data dict
        embedded_images: List of embedded image dicts
        job_number: Job number for filename
        projects_root: Project root for logging

    Returns:
        tuple: (pdf_data, filename) or (None, None) if generation fails
    """
    import html as html_module  # For escaping - renamed to avoid conflicts

    logger = get_file_ops_logger(projects_root)

    if not HAS_PDF_RENDERER:
        logger.warning("EMAIL PDF SKIP | No PDF renderer installed (weasyprint or xhtml2pdf)")
        return (None, None)

    # Build filename
    email_date = email_data.get('date', datetime.now())
    date_str = email_date.strftime('%Y-%m-%d')
    subject = email_data.get('subject', 'untitled')
    cleaned_subject = clean_subject_for_filename(subject, job_number)
    filename = f"{job_number}_email_{date_str}_{cleaned_subject}.pdf"

    # Get email metadata and ESCAPE for HTML safety
    # Email addresses often contain < > which break HTML
    from_addr = html_module.escape(email_data.get('from', ''))
    to_addr = html_module.escape(email_data.get('to', ''))
    cc_addr = html_module.escape(email_data.get('cc', ''))
    subject_escaped = html_module.escape(subject)

    # Try to get HTML body first (preserves cid: image references)
    html_body = None
    raw_msg = email_data.get('_raw_message')
    if raw_msg:
        html_body = extract_email_html_body(raw_msg)

    # Create image map for Content-ID references
    image_map = {}
    for img in embedded_images:
        cid = img.get('content_id', '')
        if cid:
            # Convert to base64 for embedding in HTML
            b64_data = base64.b64encode(img['data']).decode('utf-8')
            mime_type = img.get('content_type', 'image/png')
            image_map[cid] = f"data:{mime_type};base64,{b64_data}"

    if html_body:
        # Use the original HTML body with cid: references replaced
        body_content = html_body
        for cid, data_url in image_map.items():
            # Replace both cid:xxx and CID:xxx formats
            body_content = body_content.replace(f'cid:{cid}', data_url)
            body_content = body_content.replace(f'CID:{cid}', data_url)

        # Extract just the body content from the HTML (if it has full structure)
        body_match = re.search(r'<body[^>]*>(.*?)</body>', body_content, re.DOTALL | re.IGNORECASE)
        if body_match:
            body_html = body_match.group(1)
        else:
            body_html = body_content
    else:
        # Fallback to plain text body
        body_text = email_data.get('body', '')
        # Escape HTML entities and preserve formatting
        body_html = html_module.escape(body_text).replace('\n', '<br>')

    # Build complete HTML document with header and body
    # Using escaped values for all header fields
    cc_row = f"<div class='header-row'><span class='header-label'>CC:</span> {cc_addr}</div>" if cc_addr else ""

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: Arial, sans-serif; font-size: 11pt; line-height: 1.4; margin: 15px 20px; }}
        .header {{ background-color: #f5f5f5; padding: 15px; margin-bottom: 20px; border-radius: 4px; }}
        .header-row {{ margin-bottom: 5px; }}
        .header-label {{ font-weight: bold; color: #555; min-width: 60px; display: inline-block; }}
        .subject {{ font-size: 14pt; font-weight: bold; margin-top: 10px; }}
        .email-body {{ }}
        img {{ max-width: 100%; height: auto; }}
    </style>
</head>
<body>
    <div class="header">
        <div class="header-row"><span class="header-label">From:</span> {from_addr}</div>
        <div class="header-row"><span class="header-label">To:</span> {to_addr}</div>
        {cc_row}
        <div class="header-row"><span class="header-label">Date:</span> {email_date.strftime('%Y-%m-%d %H:%M')}</div>
        <div class="subject">{subject_escaped}</div>
    </div>
    <div class="email-body">{body_html}</div>
</body>
</html>"""

    try:
        # Generate PDF - prefer weasyprint, fallback to xhtml2pdf
        if HAS_WEASYPRINT:
            html_obj = HTML(string=html_content)
            pdf_data = html_obj.write_pdf()
        elif HAS_XHTML2PDF:
            from io import BytesIO
            pdf_buffer = BytesIO()
            pisa_status = pisa.CreatePDF(html_content, dest=pdf_buffer)
            if pisa_status.err:
                logger.error(f"EMAIL PDF FAILED | xhtml2pdf error count: {pisa_status.err}")
                return (None, None)
            pdf_data = pdf_buffer.getvalue()
        else:
            return (None, None)

        if not pdf_data or len(pdf_data) == 0:
            logger.error("EMAIL PDF FAILED | Generated PDF is empty")
            return (None, None)

        logger.info(f"EMAIL PDF OK | Generated {len(pdf_data)} bytes for {filename}")
        return (pdf_data, filename)
    except Exception as e:
        import traceback
        logger.error(f"EMAIL PDF FAILED | {e}\n{traceback.format_exc()}")
        return (None, None)


def generate_screenshot_filenames(job_number, email_date, count):
    """
    Generate filenames for extracted screenshots.

    Args:
        job_number: Job number
        email_date: Email date (datetime object)
        count: Number of filenames to generate

    Returns:
        list of filenames
    """
    date_str = email_date.strftime('%Y-%m-%d')
    filenames = []
    for i in range(count):
        seq = str(i + 1).zfill(3)
        filenames.append(f"{job_number}_email_screenshot_{date_str}_{seq}.png")
    return filenames


def check_unique_pdf_filename(dest_folder, filename):
    """
    Ensure PDF filename is unique, adding letter suffix if needed.

    Args:
        dest_folder: Destination folder path
        filename: Proposed filename

    Returns:
        str: Unique filename (may have _b, _c, etc. suffix)
    """
    dest_folder = Path(dest_folder)
    if not (dest_folder / filename).exists():
        return filename

    # Add letter suffix
    base, ext = os.path.splitext(filename)
    for letter in 'bcdefghijklmnopqrstuvwxyz':
        new_filename = f"{base}_{letter}{ext}"
        if not (dest_folder / new_filename).exists():
            return new_filename

    # Fallback: add timestamp
    timestamp = datetime.now().strftime('%H%M%S')
    return f"{base}_{timestamp}{ext}"


def should_capture_outbound_email(email_data, embedded_images):
    """
    Determine if an outbound email should trigger screenshot/PDF capture.

    Conditions:
    - Email is outbound (from address matches user's configured addresses)
    - Email contains embedded images > 20KB

    Args:
        email_data: Parsed email data
        embedded_images: List of embedded images

    Returns:
        bool: True if capture should be triggered
    """
    # Check if outbound
    from_addr = email_data.get('from', '')
    if not is_my_email(from_addr):
        return False

    # Check if has large embedded images
    return len(embedded_images) > 0


def process_outbound_email_capture(msg, email_data, job_number, dest_folder, projects_root,
                                    secondary_paths=None, keystage_folder=None):
    """
    Process an outbound email for screenshot extraction and PDF generation.

    Args:
        msg: Original email.message.Message object
        email_data: Parsed email data dict
        job_number: Job number
        dest_folder: Primary destination folder
        projects_root: Projects root for logging/path jail
        secondary_paths: List of secondary filing paths (optional)
        keystage_folder: Key Stage Archive folder path (optional)

    Returns:
        dict: {
            'screenshots': list of generated screenshot filenames,
            'pdf_filename': generated PDF filename or None,
            'success': bool
        }
    """
    logger = get_file_ops_logger(projects_root)
    result = {'screenshots': [], 'pdf_filename': None, 'success': True}

    # Extract embedded images
    embedded_images = extract_embedded_images(msg)

    # Check if capture should be triggered
    if not should_capture_outbound_email(email_data, embedded_images):
        return result

    logger.info(f"OUTBOUND EMAIL CAPTURE | Found {len(embedded_images)} embedded image(s) > 20KB")

    email_date = email_data.get('date', datetime.now())
    all_destinations = [dest_folder]
    if secondary_paths:
        all_destinations.extend(secondary_paths)
    if keystage_folder:
        all_destinations.append(keystage_folder)

    # Generate screenshot filenames
    screenshot_filenames = generate_screenshot_filenames(job_number, email_date, len(embedded_images))

    # Save screenshots to all destinations
    for i, img in enumerate(embedded_images):
        filename = screenshot_filenames[i]

        # Convert to PNG
        png_data = convert_image_to_png(img['data'])

        for dest in all_destinations:
            dest_path = Path(dest) / filename
            try:
                if safe_write_attachment(dest_path, png_data, projects_root, f"screenshot:{filename}"):
                    if dest == dest_folder:  # Only record once
                        result['screenshots'].append(filename)
                    logger.info(f"SCREENSHOT SAVED | {filename} -> {dest}")
            except Exception as e:
                logger.error(f"SCREENSHOT FAILED | {filename} -> {dest}: {e}")
                result['success'] = False

    # Generate and save email PDF
    pdf_data, pdf_filename = generate_email_pdf(email_data, embedded_images, job_number, projects_root)

    if pdf_data and pdf_filename:
        for dest in all_destinations:
            # Ensure unique filename for this destination
            unique_filename = check_unique_pdf_filename(dest, pdf_filename)
            dest_path = Path(dest) / unique_filename

            try:
                if safe_write_attachment(dest_path, pdf_data, projects_root, f"email_pdf:{unique_filename}"):
                    if dest == dest_folder:  # Only record once
                        result['pdf_filename'] = unique_filename
                    logger.info(f"EMAIL PDF SAVED | {unique_filename} -> {dest}")
            except Exception as e:
                logger.error(f"EMAIL PDF FAILED | {unique_filename} -> {dest}: {e}")
                result['success'] = False

    return result


def get_sender_name_and_business(email_data, direction):
    """
    Get the sender (for IN) or recipient (for OUT) name and business from email.

    Returns:
        tuple: (name, business_name) - business_name may be None
    """
    if direction == 'IN':
        email_addr = email_data.get('from', '')
    else:
        email_addr = email_data.get('to', '')

    name, addr = parseaddr(email_addr)
    business = extract_business_from_domain(email_addr)

    # If no name, use the email address part before @
    if not name and addr:
        name = addr.split('@')[0].replace('.', ' ').replace('_', ' ').title()

    return (name, business)


def parse_import_export_folder(folder_name):
    """
    Parse an import/export folder name to extract the contact name.

    Format: {job}_{IN/OUT}_{date}_{contact}_{description}
    Example: 2508_IN_2024-01-15_SMITH-ARCHITECTS_DRAWINGS

    Returns:
        str: contact name or None
    """
    parts = folder_name.split('_')
    if len(parts) >= 4:
        # Contact is the 4th part (index 3)
        return parts[3]
    return None


def find_previous_contacts(project_folder, job_number):
    """
    Search IMPORTS-EXPORTS folder for previously used contact names.

    Returns:
        list: List of unique contact names found
    """
    contacts = set()
    project_path = Path(project_folder)

    if not project_path.exists():
        return []

    # Find IMPORTS-EXPORTS folder
    imports_exports_folder = None
    for item in project_path.iterdir():
        if item.is_dir():
            name_upper = item.name.upper()
            if 'IMPORT' in name_upper and 'EXPORT' in name_upper:
                imports_exports_folder = item
                break
            if job_number in item.name and ('IMPORT' in name_upper or 'EXPORT' in name_upper):
                imports_exports_folder = item
                break

    if not imports_exports_folder:
        return []

    # Scan folders for contact names
    for item in imports_exports_folder.iterdir():
        if item.is_dir():
            contact = parse_import_export_folder(item.name)
            if contact and len(contact) > 1:
                # Convert from folder format back to readable
                readable = contact.replace('-', ' ').title()
                contacts.add(readable)

    return sorted(list(contacts))


def fuzzy_match_contact(input_text, contacts, threshold=0.6):
    """
    Find contacts that fuzzy match the input text.

    Returns:
        list: Matching contacts sorted by similarity
    """
    if not input_text or not contacts:
        return contacts

    input_lower = input_text.lower()
    matches = []

    for contact in contacts:
        contact_lower = contact.lower()

        # Check if input is substring
        if input_lower in contact_lower:
            matches.append((contact, 1.0))
            continue

        # Calculate similarity
        ratio = SequenceMatcher(None, input_lower, contact_lower).ratio()
        if ratio >= threshold:
            matches.append((contact, ratio))

    # Sort by similarity descending
    matches.sort(key=lambda x: x[1], reverse=True)
    return [m[0] for m in matches]


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


class FilingWidget(QMainWindow):
    """Main filing widget window."""

    def __init__(self):
        super().__init__()
        self.dropped_files = []
        self.job_number = None
        self.project_name = None
        self.projects_root = None
        self.previous_projects_root = None  # Track previous root for db copy option
        self.db_path = None  # Path to filing database
        self.projects = []  # List of (job_number, project_name) tuples
        self.filing_rules = []  # Filing rules from CSV
        self.email_data = None  # Stores parsed email data
        self.email_date = None  # Date to use for folder name
        self.email_source_path = None  # Source path of the dropped .eml file
        self.email_message_id = None  # Message-ID from email headers
        self.email_hash_fallback = None  # Hash fallback if no Message-ID
        self.email_is_duplicate = False  # Whether this email was already filed
        self.attachment_checkboxes = []  # Track attachment checkboxes (email)
        self.file_widgets = []  # Track file widgets (dropped files)
        self.previous_contacts = []  # Contacts from previous filings
        self.last_job_number = None  # Remember last job for consecutive filings
        self.last_project_name = None

        self.setWindowTitle("FileUZI")
        self.setMinimumSize(550, 750)
        self.setStyleSheet(f"background-color: {COLORS['surface']};")

        if not self.load_projects_root():
            return  # Exit if CSV missing
        if not self.ensure_database():
            return  # Exit if database setup failed
        self.setup_ui()

    def load_projects_root(self):
        """Load projects root, scan for project folders, and load filing rules."""
        self.projects_root = PROJECTS_ROOT
        self.projects = scan_projects_folder(self.projects_root)

        # Ensure tools folder exists
        ensure_tools_folder(self.projects_root)

        # Load filing rules from CSV
        self.filing_rules = load_filing_rules(self.projects_root)
        if self.filing_rules is None:
            tools_folder = get_tools_folder_path(self.projects_root)
            QMessageBox.critical(
                None,
                "Filing Rules Missing",
                f"Could not find {FILING_RULES_FILENAME} in:\n\n{tools_folder}\n\n"
                "This file is required for the filing widget to work.\n"
                "Please create the CSV file and restart the application."
            )
            sys.exit(1)

        # Load custom project number mapping (optional - doesn't fail if missing)
        self.project_mapping = load_project_mapping(self.projects_root)

        return True

    def ensure_database(self):
        """Ensure the filing database exists and is valid."""
        self.db_path = get_database_path(self.projects_root)

        if not self.db_path.exists():
            # Database missing - show dialog
            dialog = DatabaseMissingDialog(None, self.projects_root, self.previous_projects_root)
            result = dialog.exec()

            if result != QDialog.DialogCode.Accepted:
                sys.exit(0)  # User closed dialog without choosing

            if dialog.result_action == 'create':
                init_database(self.db_path)
            elif dialog.result_action == 'import':
                # Copy the imported database
                safe_copy(dialog.imported_db_path, self.db_path, self.projects_root)
            elif dialog.result_action == 'copy':
                # Copy from previous root
                old_db = get_database_path(self.previous_projects_root)
                safe_copy(old_db, self.db_path, self.projects_root)
        else:
            # Database exists - verify schema
            if not verify_database_schema(self.db_path):
                reply = QMessageBox.warning(
                    None,
                    "Database Schema Invalid",
                    f"The filing database at:\n\n{self.db_path}\n\n"
                    "appears to be corrupted or has an outdated schema.\n\n"
                    "Create a fresh database? (The old file will be renamed)",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    # Rename old file
                    backup_path = self.db_path.with_suffix('.db.backup')
                    self.db_path.rename(backup_path)
                    init_database(self.db_path)
                else:
                    sys.exit(0)

        return True

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Header with logo
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        header = QLabel("FileUzi - Architectural Filing Widget")
        header.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {COLORS['text']};")
        header_layout.addWidget(header)

        header_layout.addStretch()

        # Logo in top right
        logo_label = QLabel()
        logo_path = Path(__file__).parent / "assets" / "fileuzi_logo.png"
        if logo_path.exists():
            pixmap = QPixmap(str(logo_path))
            # Scale to 120px height (50% larger than 80px)
            scaled_pixmap = pixmap.scaledToHeight(120, Qt.TransformationMode.SmoothTransformation)
            logo_label.setPixmap(scaled_pixmap)
        header_layout.addWidget(logo_label)

        layout.addLayout(header_layout)

        # Project selection dropdown
        project_label = QLabel("Select Project")
        project_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-weight: bold; font-size: 12px;")
        layout.addWidget(project_label)

        self.project_combo = QComboBox()
        self.project_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 10px 12px;
                font-size: 14px;
                min-height: 20px;
            }}
            QComboBox:focus {{
                border-color: {COLORS['primary']};
            }}
            QComboBox::drop-down {{
                border: none;
                padding-right: 10px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                selection-background-color: {COLORS['primary']}22;
            }}
        """)
        self.project_combo.addItem("-- Select a project --", None)
        for job_num, proj_name in self.projects:
            self.project_combo.addItem(f"{job_num} - {proj_name}", (job_num, proj_name))
        self.project_combo.currentIndexChanged.connect(self.on_project_selected)
        layout.addWidget(self.project_combo)

        # Drop zone
        self.drop_zone = DropZone(self)
        layout.addWidget(self.drop_zone)

        # Files display (hidden until files dropped)
        self.files_frame = QFrame()
        self.files_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
            }}
        """)
        self.files_frame.setVisible(False)

        files_layout = QVBoxLayout(self.files_frame)
        files_layout.setContentsMargins(12, 12, 12, 12)
        files_layout.setSpacing(8)

        # Files header with "Also file to" column
        files_header_row = QHBoxLayout()
        files_header_row.setContentsMargins(0, 0, 0, 4)

        self.files_label = QLabel("Files:")
        self.files_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-weight: bold; font-size: 12px; border: none;")
        files_header_row.addWidget(self.files_label)

        files_header_row.addStretch()

        # "Also file to" column header - fixed width to align with buttons
        # Vertical layout: label above, checkbox+button row below, left-aligned
        files_also_file_to_header = QWidget()
        files_also_file_to_header.setFixedWidth(SECONDARY_FILING_WIDTH)
        files_also_file_to_header_layout = QVBoxLayout(files_also_file_to_header)
        files_also_file_to_header_layout.setContentsMargins(0, 0, 0, 0)
        files_also_file_to_header_layout.setSpacing(2)

        self.files_also_file_to_label = QLabel("Also file to:")
        self.files_also_file_to_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px; border: none;")
        files_also_file_to_header_layout.addWidget(self.files_also_file_to_label)

        # Horizontal row for tick-all checkbox and global add button
        files_tick_all_row = QHBoxLayout()
        files_tick_all_row.setContentsMargins(0, 0, 0, 0)
        files_tick_all_row.setSpacing(4)

        self.files_tick_all_checkbox = QCheckBox()
        self.files_tick_all_checkbox.setToolTip("Enable/disable secondary filing for all files")
        self.files_tick_all_checkbox.stateChanged.connect(self._on_files_tick_all_changed)
        files_tick_all_row.addWidget(self.files_tick_all_checkbox)

        # Container for global chips in files header
        self.files_global_chips_container = QWidget()
        self.files_global_chips_container.setFixedHeight(24)  # Match individual attachment chips
        self.files_global_chips_container.setStyleSheet("border: none;")
        self.files_global_chips_layout = QHBoxLayout(self.files_global_chips_container)
        self.files_global_chips_layout.setContentsMargins(4, 0, 0, 0)
        self.files_global_chips_layout.setSpacing(4)
        self.files_global_chips = []  # Track global chips for files
        files_tick_all_row.addWidget(self.files_global_chips_container)

        # Global add chip button for files (after chips)
        self.files_global_add_chip_btn = QPushButton("+")
        self.files_global_add_chip_btn.setFixedSize(18, 18)
        self.files_global_add_chip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.files_global_add_chip_btn.setToolTip("Add destination to all ticked files")
        self.files_global_add_chip_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg']};
                color: {COLORS['text_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 9px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['primary']};
                color: white;
                border-color: {COLORS['primary']};
            }}
        """)
        self.files_global_add_chip_btn.clicked.connect(self._on_files_global_add_chip_clicked)
        files_tick_all_row.addWidget(self.files_global_add_chip_btn)
        files_tick_all_row.addStretch()  # Push everything to the left

        files_also_file_to_header_layout.addLayout(files_tick_all_row)

        files_header_row.addWidget(files_also_file_to_header)

        files_layout.addLayout(files_header_row)

        # Container for file widgets (like attachments)
        self.files_container = QWidget()
        self.files_container.setStyleSheet("border: none;")
        self.files_container_layout = QVBoxLayout(self.files_container)
        self.files_container_layout.setContentsMargins(0, 0, 0, 0)
        self.files_container_layout.setSpacing(4)
        files_layout.addWidget(self.files_container)

        # Key Stage Archive toggle for files (same as in email frame)
        files_keystage_layout = QHBoxLayout()
        files_keystage_layout.setContentsMargins(0, 8, 0, 0)

        self.files_keystage_toggle = QCheckBox("Key Stage Archive")
        self.files_keystage_toggle.setStyleSheet(f"""
            QCheckBox {{
                color: {COLORS['text']};
                font-size: 12px;
                spacing: 6px;
            }}
            QCheckBox::indicator {{
                width: 14px;
                height: 14px;
                border-radius: 3px;
                border: 2px solid #a855f7;
            }}
            QCheckBox::indicator:unchecked {{
                background-color: transparent;
            }}
            QCheckBox::indicator:checked {{
                background-color: #a855f7;
                border-color: #a855f7;
            }}
            QCheckBox::indicator:hover {{
                border-color: #9333ea;
            }}
        """)
        self.files_keystage_toggle.setChecked(False)
        self.files_keystage_toggle.toggled.connect(self._on_keystage_toggled)
        files_keystage_layout.addWidget(self.files_keystage_toggle)
        files_keystage_layout.addStretch()
        files_layout.addLayout(files_keystage_layout)

        layout.addWidget(self.files_frame)

        # Email info frame (hidden until .eml dropped)
        self.email_frame = QFrame()
        self.email_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
            }}
        """)
        self.email_frame.setVisible(False)

        email_layout = QVBoxLayout(self.email_frame)
        email_layout.setContentsMargins(12, 12, 12, 12)
        email_layout.setSpacing(8)

        # Email header info
        email_header_label = QLabel("📧 Email Details")
        email_header_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        email_header_label.setStyleSheet(f"color: {COLORS['text']}; border: none;")
        email_layout.addWidget(email_header_label)

        self.email_from_label = QLabel()
        self.email_from_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px; border: none;")
        self.email_from_label.setWordWrap(True)
        email_layout.addWidget(self.email_from_label)

        self.email_to_label = QLabel()
        self.email_to_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px; border: none;")
        self.email_to_label.setWordWrap(True)
        email_layout.addWidget(self.email_to_label)

        self.email_date_label = QLabel()
        self.email_date_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px; border: none;")
        email_layout.addWidget(self.email_date_label)

        # Subject label (static text)
        subject_header = QLabel("Subject:")
        subject_header.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px; border: none; margin-top: 4px;")
        email_layout.addWidget(subject_header)

        # Subject words container (clickable words)
        self.subject_container = QWidget()
        self.subject_container.setStyleSheet("border: none;")
        self.subject_layout = FlowLayout(self.subject_container, margin=0, spacing=2)
        email_layout.addWidget(self.subject_container)

        # Hint for clicking words
        self.subject_hint = QLabel("💡 Click words to add to description")
        self.subject_hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 10px; border: none;")
        email_layout.addWidget(self.subject_hint)

        # Track subject word labels and drag selection
        self.subject_word_labels = []
        self.is_dragging = False
        self.drag_start_index = -1
        self.drag_select_state = True  # True = selecting, False = deselecting

        # Attachments section header row
        attachments_header_row = QHBoxLayout()
        attachments_header_row.setContentsMargins(0, 8, 0, 4)

        self.attachments_label = QLabel("Attachments:")
        self.attachments_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-weight: bold; font-size: 12px; border: none;")
        attachments_header_row.addWidget(self.attachments_label)

        attachments_header_row.addStretch()

        # "Also file to" column header - fixed width to align with buttons
        # Vertical layout: label above, checkbox below, left-aligned
        also_file_to_header = QWidget()
        also_file_to_header.setFixedWidth(SECONDARY_FILING_WIDTH)
        also_file_to_header_layout = QVBoxLayout(also_file_to_header)
        also_file_to_header_layout.setContentsMargins(0, 0, 0, 0)
        also_file_to_header_layout.setSpacing(2)

        self.also_file_to_label = QLabel("Also file to:")
        self.also_file_to_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px; border: none;")
        also_file_to_header_layout.addWidget(self.also_file_to_label)

        # Horizontal row for tick-all checkbox and global add button
        tick_all_row = QHBoxLayout()
        tick_all_row.setContentsMargins(0, 0, 0, 0)
        tick_all_row.setSpacing(4)

        self.tick_all_checkbox = QCheckBox()
        self.tick_all_checkbox.setToolTip("Enable/disable secondary filing for all attachments")
        self.tick_all_checkbox.stateChanged.connect(self._on_tick_all_changed)
        tick_all_row.addWidget(self.tick_all_checkbox)

        # Container for global chips in header
        self.global_chips_container = QWidget()
        self.global_chips_container.setFixedHeight(24)  # Match individual attachment chips
        self.global_chips_container.setStyleSheet("border: none;")
        self.global_chips_layout = QHBoxLayout(self.global_chips_container)
        self.global_chips_layout.setContentsMargins(4, 0, 0, 0)
        self.global_chips_layout.setSpacing(4)
        self.global_chips = []  # Track global chips
        tick_all_row.addWidget(self.global_chips_container)

        # Global add chip button - adds chip to header and all attachments (after chips)
        self.global_add_chip_btn = QPushButton("+")
        self.global_add_chip_btn.setFixedSize(18, 18)
        self.global_add_chip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.global_add_chip_btn.setToolTip("Add destination to all ticked attachments")
        self.global_add_chip_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg']};
                color: {COLORS['text_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 9px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['primary']};
                color: white;
                border-color: {COLORS['primary']};
            }}
        """)
        self.global_add_chip_btn.clicked.connect(self._on_global_add_chip_clicked)
        tick_all_row.addWidget(self.global_add_chip_btn)
        tick_all_row.addStretch()  # Push everything to the left

        also_file_to_header_layout.addLayout(tick_all_row)

        attachments_header_row.addWidget(also_file_to_header)

        email_layout.addLayout(attachments_header_row)

        # Container for selected attachments
        self.attachments_container = QWidget()
        self.attachments_container.setStyleSheet("border: none;")
        self.attachments_layout = QVBoxLayout(self.attachments_container)
        self.attachments_layout.setContentsMargins(0, 0, 0, 0)
        self.attachments_layout.setSpacing(4)
        email_layout.addWidget(self.attachments_container)

        # Show more/less button for excluded attachments
        self.show_excluded_btn = QPushButton("Show more...")
        self.show_excluded_btn.setStyleSheet(f"""
            QPushButton {{
                background: none;
                border: none;
                color: {COLORS['primary']};
                font-size: 11px;
                text-align: left;
                padding: 4px 0;
            }}
            QPushButton:hover {{
                text-decoration: underline;
            }}
        """)
        self.show_excluded_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_excluded_btn.clicked.connect(self.toggle_excluded_attachments)
        self.show_excluded_btn.setVisible(False)
        email_layout.addWidget(self.show_excluded_btn)

        # Container for excluded attachments (hidden by default)
        self.excluded_container = QWidget()
        self.excluded_container.setStyleSheet("border: none;")
        self.excluded_layout = QVBoxLayout(self.excluded_container)
        self.excluded_layout.setContentsMargins(0, 0, 0, 0)
        self.excluded_layout.setSpacing(4)
        self.excluded_container.setVisible(False)
        email_layout.addWidget(self.excluded_container)

        # Key Stage Archive toggle and Print Email to PDF toggle (at bottom of email frame)
        toggles_layout = QHBoxLayout()
        toggles_layout.setContentsMargins(0, 8, 0, 0)

        self.keystage_toggle = QCheckBox("Key Stage Archive")
        self.keystage_toggle.setStyleSheet(f"""
            QCheckBox {{
                color: {COLORS['text']};
                font-size: 12px;
                spacing: 6px;
            }}
        """)
        self.keystage_toggle.setChecked(False)
        self.keystage_toggle.toggled.connect(self._on_keystage_toggled)
        toggles_layout.addWidget(self.keystage_toggle)

        # Print Email to PDF toggle (only visible when embedded images > 20KB detected)
        self.print_pdf_toggle = QCheckBox("Print Email to PDF")
        self.print_pdf_toggle.setStyleSheet(f"""
            QCheckBox {{
                color: {COLORS['text']};
                font-size: 12px;
                spacing: 6px;
            }}
            QCheckBox:disabled {{
                color: {COLORS['text_secondary']};
            }}
        """)
        self.print_pdf_toggle.setChecked(True)  # Default ON when visible
        self.print_pdf_toggle.setVisible(False)  # Hidden until embedded images detected
        self.print_pdf_toggle.toggled.connect(self._on_print_pdf_toggled)
        if not HAS_PDF_RENDERER:
            self.print_pdf_toggle.setEnabled(False)
            self.print_pdf_toggle.setToolTip("PDF printing requires weasyprint — run: pip install weasyprint")
        toggles_layout.addWidget(self.print_pdf_toggle)
        self.pdf_placeholder_widget = None  # Track PDF placeholder in attachments

        toggles_layout.addStretch()
        email_layout.addLayout(toggles_layout)

        layout.addWidget(self.email_frame)

        # Form section
        form_layout = QVBoxLayout()
        form_layout.setSpacing(16)

        # Import/Export selection
        direction_label = QLabel("Direction")
        direction_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-weight: bold; font-size: 12px;")
        form_layout.addWidget(direction_label)

        direction_row = QHBoxLayout()
        self.direction_group = QButtonGroup(self)

        self.import_radio = QRadioButton("Import (IN)")
        self.import_radio.setChecked(True)
        self.import_radio.toggled.connect(self.on_direction_changed)
        self.direction_group.addButton(self.import_radio)
        direction_row.addWidget(self.import_radio)

        self.export_radio = QRadioButton("Export (OUT)")
        self.direction_group.addButton(self.export_radio)
        direction_row.addWidget(self.export_radio)

        direction_row.addStretch()
        form_layout.addLayout(direction_row)

        # Sender/Recipient
        self.contact_label = QLabel("Sender")
        self.contact_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-weight: bold; font-size: 12px;")
        form_layout.addWidget(self.contact_label)

        self.contact_input = QLineEdit()
        self.contact_input.setPlaceholderText("Enter sender name...")
        self.contact_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 10px 12px;
                font-size: 14px;
            }}
            QLineEdit:focus {{
                border-color: {COLORS['primary']};
            }}
        """)

        # Setup completer for contact suggestions
        self.contact_completer = QCompleter()
        self.contact_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.contact_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.contact_input.setCompleter(self.contact_completer)

        form_layout.addWidget(self.contact_input)

        # Description
        desc_label = QLabel("Description")
        desc_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-weight: bold; font-size: 12px;")
        form_layout.addWidget(desc_label)

        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("Brief description of files...")
        self.desc_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 10px 12px;
                font-size: 14px;
            }}
            QLineEdit:focus {{
                border-color: {COLORS['primary']};
            }}
        """)
        form_layout.addWidget(self.desc_input)

        # Preview
        preview_label = QLabel("Folder Preview")
        preview_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-weight: bold; font-size: 12px;")
        form_layout.addWidget(preview_label)

        self.preview_label = QLabel()
        self.preview_label.setStyleSheet(f"""
            background-color: {COLORS['bg']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            padding: 10px 12px;
            font-family: monospace;
            font-size: 13px;
        """)
        self.preview_label.setWordWrap(True)
        form_layout.addWidget(self.preview_label)

        # Connect inputs to preview update
        self.contact_input.textChanged.connect(self.update_preview)
        self.desc_input.textChanged.connect(self.update_preview)

        # Connect Enter key to file documents
        self.contact_input.returnPressed.connect(self.file_documents)
        self.desc_input.returnPressed.connect(self.file_documents)

        layout.addLayout(form_layout)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 16, 0, 0)

        button_layout.addStretch()

        cancel_btn = QPushButton("Reset")
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 10px 24px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {COLORS['bg']};
            }}
        """)
        cancel_btn.clicked.connect(self.reset_form)
        button_layout.addWidget(cancel_btn)

        self.file_btn = QPushButton("File Documents")
        self.file_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['primary']};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 24px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: #1d4ed8;
            }}
        """)
        self.file_btn.clicked.connect(self.file_documents)
        button_layout.addWidget(self.file_btn)

        layout.addLayout(button_layout)

        layout.addStretch()

        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)

    def on_project_selected(self, index):
        """Handle project selection from dropdown."""
        data = self.project_combo.currentData()
        if data:
            self.job_number, self.project_name = data
            self.update_preview()
            self.load_previous_contacts()
        else:
            self.job_number = None
            self.project_name = None
            self.previous_contacts = []

    def load_previous_contacts(self):
        """Load previous contacts from project folders and database for current project only."""
        contacts = set()

        # Only load contacts if a project is selected
        if not self.job_number:
            self.previous_contacts = []
            model = QStringListModel([])
            self.contact_completer.setModel(model)
            return

        # Get contacts from project's IMPORTS-EXPORTS folder
        project_folder = self.find_project_folder()
        if project_folder:
            folder_contacts = find_previous_contacts(project_folder, self.job_number)
            contacts.update(folder_contacts)

        # Get contacts from database (filtered by job number)
        if hasattr(self, 'db_path') and self.db_path:
            db_contacts = get_contacts_from_database(self.db_path, self.job_number)
            contacts.update(db_contacts)

        self.previous_contacts = sorted(list(contacts))

        # Update completer with combined contacts for auto-complete
        model = QStringListModel(self.previous_contacts)
        self.contact_completer.setModel(model)

    def on_direction_changed(self):
        """Update label when direction changes."""
        if self.import_radio.isChecked():
            self.contact_label.setText("Sender")
            self.contact_input.setPlaceholderText("Enter sender name...")
        else:
            self.contact_label.setText("Recipient")
            self.contact_input.setPlaceholderText("Enter recipient name...")
        self.update_preview()

    def toggle_excluded_attachments(self):
        """Toggle visibility of excluded attachments."""
        is_visible = self.excluded_container.isVisible()
        self.excluded_container.setVisible(not is_visible)
        self.show_excluded_btn.setText("Show less..." if not is_visible else "Show more...")

    def _on_tick_all_changed(self, state):
        """Handle tick-all checkbox state change - toggle all secondary filing checkboxes."""
        enabled = state == Qt.CheckState.Checked.value
        for att_widget, _ in self.attachment_checkboxes:
            att_widget.set_secondary_enabled(enabled)

    def _on_files_tick_all_changed(self, state):
        """Handle files tick-all checkbox state change - toggle all secondary filing checkboxes."""
        enabled = state == Qt.CheckState.Checked.value
        for att_widget, _ in self.file_widgets:
            att_widget.set_secondary_enabled(enabled)

    def _on_global_add_chip_clicked(self):
        """Handle click on global + button - add chip to header and attachments."""
        self._show_global_add_menu(
            checkbox_list=self.attachment_checkboxes,
            tick_all_checked=self.tick_all_checkbox.isChecked(),
            button=self.global_add_chip_btn,
            header_chips_layout=self.global_chips_layout,
            header_chips_list=self.global_chips,
            is_files=False
        )

    def _on_files_global_add_chip_clicked(self):
        """Handle click on files global + button - add chip to header and files."""
        self._show_global_add_menu(
            checkbox_list=self.file_widgets,
            tick_all_checked=self.files_tick_all_checkbox.isChecked(),
            button=self.files_global_add_chip_btn,
            header_chips_layout=self.files_global_chips_layout,
            header_chips_list=self.files_global_chips,
            is_files=True
        )

    def _show_global_add_menu(self, checkbox_list, tick_all_checked, button,
                               header_chips_layout, header_chips_list, is_files):
        """Show menu to add a chip to header and attachments/files.

        Args:
            checkbox_list: List of (widget, data) tuples
            tick_all_checked: If True, add to ALL items; if False, add only to checked items
            button: The button widget (for positioning the menu)
            header_chips_layout: Layout for header chips
            header_chips_list: List to track header chips
            is_files: True if this is for files, False for attachments
        """
        # Determine target widgets
        if tick_all_checked:
            target_widgets = [widget for widget, _ in checkbox_list]
        else:
            target_widgets = [widget for widget, _ in checkbox_list if widget.isChecked()]

        if not target_widgets:
            return

        menu = QMenu(self)

        # Add all available filing rules
        for rule in self.filing_rules:
            action = menu.addAction(rule['folder_type'])
            action.triggered.connect(
                lambda checked, r=rule, targets=target_widgets, layout=header_chips_layout,
                       chips=header_chips_list, files=is_files:
                    self._add_global_chip(targets, r, layout, chips, files)
            )

        # Add Current Drawings option
        drawing_rule = {
            'keywords': [],
            'descriptors': [],
            'folder_location': '/XXXX_CURRENT-DRAWINGS',
            'folder_type': 'Current Drawings',
            'colour': '#f59e0b'
        }
        action = menu.addAction('Current Drawings')
        action.triggered.connect(
            lambda checked, r=drawing_rule, targets=target_widgets, layout=header_chips_layout,
                   chips=header_chips_list, files=is_files:
                self._add_global_chip(targets, r, layout, chips, files)
        )

        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _add_global_chip(self, target_widgets, rule, header_chips_layout, header_chips_list, is_files):
        """Add a chip to the header and to all target widgets."""
        folder_type = rule['folder_type']

        # Check if already in header
        for chip in header_chips_list:
            if chip.rule['folder_type'] == folder_type:
                return  # Already exists in header

        # Add to all target widgets first
        for widget in target_widgets:
            widget.add_chip(rule)

        # Add chip to header
        # Mark it as a header chip with metadata for click handling
        header_chip = FilingChip(rule, self, active=True)
        header_chip.is_header_chip = True
        header_chip.header_chips_layout = header_chips_layout
        header_chip.header_chips_list = header_chips_list
        header_chip.is_files = is_files
        header_chips_layout.addWidget(header_chip)
        header_chips_list.append(header_chip)

        self._update_global_add_btn_visibility()

    def on_chip_clicked(self, chip):
        """Handle click on a header chip - show menu to remove from all."""
        # This is called when a header chip (with self as parent) is clicked
        if not getattr(chip, 'is_header_chip', False):
            return

        menu = QMenu(self)
        chip_color = chip.rule.get('colour', COLORS['primary'])
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: white;
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 4px;
            }}
            QMenu::item {{
                color: {COLORS['text']};
                padding: 6px 12px;
                border-radius: 3px;
            }}
            QMenu::item:selected {{
                background-color: {chip_color};
                color: white;
            }}
        """)
        folder_type = chip.rule['folder_type']
        header_chips_layout = chip.header_chips_layout
        header_chips_list = chip.header_chips_list
        is_files = chip.is_files

        # Count how many attachments/files have this chip
        if is_files:
            widgets_with_chip = [w for w, _ in self.file_widgets
                                 if any(c.rule['folder_type'] == folder_type for c in w.filing_chips)]
        else:
            widgets_with_chip = [w for w, _ in self.attachment_checkboxes
                                 if any(c.rule['folder_type'] == folder_type for c in w.filing_chips)]

        remove_action = menu.addAction(f"✕ Remove from all ({len(widgets_with_chip)})")
        remove_action.triggered.connect(
            lambda: self._remove_global_chip(chip, header_chips_layout, header_chips_list,
                                              widgets_with_chip, folder_type)
        )

        menu.exec(self.cursor().pos())

    def _remove_global_chip(self, header_chip, header_chips_layout, header_chips_list,
                            widgets, folder_type):
        """Remove a global chip from header and all widgets."""
        # Remove from all widgets
        for widget in widgets:
            chip_to_remove = None
            for chip in widget.filing_chips:
                if chip.rule['folder_type'] == folder_type:
                    chip_to_remove = chip
                    break
            if chip_to_remove:
                widget.remove_chip(chip_to_remove)

        # Remove from header
        if header_chip in header_chips_list:
            header_chips_list.remove(header_chip)
            header_chips_layout.removeWidget(header_chip)
            header_chip.deleteLater()

        self._update_global_add_btn_visibility()

    def _add_chip_to_widgets(self, widgets, rule):
        """Add a chip to multiple attachment/file widgets."""
        for widget in widgets:
            widget.add_chip(rule)
        self._update_global_add_btn_visibility()

    def _update_global_add_btn_visibility(self):
        """Hide global + buttons if any attachment has MAX_CHIPS."""
        # Check attachments
        any_attachment_full = any(
            len(widget.filing_chips) >= MAX_CHIPS
            for widget, _ in self.attachment_checkboxes
        )
        if hasattr(self, 'global_add_chip_btn'):
            self.global_add_chip_btn.setVisible(not any_attachment_full)

        # Check files
        any_file_full = any(
            len(widget.filing_chips) >= MAX_CHIPS
            for widget, _ in self.file_widgets
        )
        if hasattr(self, 'files_global_add_chip_btn'):
            self.files_global_add_chip_btn.setVisible(not any_file_full)

    def show_chip_menu(self, attachment_widget, chip):
        """Show context menu for a filing chip (reassign or remove)."""
        menu = QMenu(self)
        chip_color = chip.rule.get('colour', COLORS['primary'])
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: white;
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 4px;
            }}
            QMenu::item {{
                color: {COLORS['text']};
                padding: 6px 12px;
                border-radius: 3px;
            }}
            QMenu::item:selected {{
                background-color: {chip_color};
                color: white;
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {COLORS['border']};
                margin: 4px 8px;
            }}
        """)

        # Add "Remove" action
        remove_action = menu.addAction("✕ Remove")
        remove_action.triggered.connect(lambda: self._remove_chip_and_update(attachment_widget, chip))

        # Check if same chip exists on other widgets - offer "Remove from all"
        folder_type = chip.rule['folder_type']
        other_widgets_with_chip = []

        # Check attachments
        for widget, _ in self.attachment_checkboxes:
            if widget != attachment_widget:
                for other_chip in widget.filing_chips:
                    if other_chip.rule['folder_type'] == folder_type:
                        other_widgets_with_chip.append(widget)
                        break

        # Check files
        for widget, _ in self.file_widgets:
            if widget != attachment_widget:
                for other_chip in widget.filing_chips:
                    if other_chip.rule['folder_type'] == folder_type:
                        other_widgets_with_chip.append(widget)
                        break

        if other_widgets_with_chip:
            all_widgets = [attachment_widget] + other_widgets_with_chip
            remove_all_action = menu.addAction(f"✕ Remove from all ({len(all_widgets)})")
            remove_all_action.triggered.connect(
                lambda checked, widgets=all_widgets, ft=folder_type: self._remove_chip_from_all(widgets, ft)
            )

        menu.addSeparator()

        # Add "Reassign to..." submenu with all available folders
        reassign_menu = menu.addMenu("Reassign to...")

        # Add all filing rules as options
        for rule in self.filing_rules:
            if rule['folder_type'] != chip.rule['folder_type']:
                action = reassign_menu.addAction(rule['folder_type'])
                action.triggered.connect(lambda checked, r=rule: self._reassign_chip(attachment_widget, chip, r))

        # Add Current Drawings option if not already this chip
        if chip.rule['folder_type'] != 'Current Drawings':
            drawing_rule = {
                'keywords': [],
                'descriptors': [],
                'folder_location': '/XXXX_CURRENT-DRAWINGS',
                'folder_type': 'Current Drawings',
                'colour': '#f59e0b'
            }
            action = reassign_menu.addAction('Current Drawings')
            action.triggered.connect(lambda checked, r=drawing_rule: self._reassign_chip(attachment_widget, chip, r))

        # Show menu at cursor position
        menu.exec(self.cursor().pos())

    def _reassign_chip(self, attachment_widget, old_chip, new_rule):
        """Reassign a chip to a new destination."""
        attachment_widget.remove_chip(old_chip)
        attachment_widget.add_chip(new_rule)
        self._update_global_add_btn_visibility()

    def _remove_chip_and_update(self, attachment_widget, chip):
        """Remove a chip and update global + button visibility."""
        attachment_widget.remove_chip(chip)
        self._update_global_add_btn_visibility()

    def _remove_chip_from_all(self, widgets, folder_type):
        """Remove a chip with the given folder_type from all specified widgets."""
        for widget in widgets:
            # Find and remove the chip with matching folder_type
            chip_to_remove = None
            for chip in widget.filing_chips:
                if chip.rule['folder_type'] == folder_type:
                    chip_to_remove = chip
                    break
            if chip_to_remove:
                widget.remove_chip(chip_to_remove)
        self._update_global_add_btn_visibility()

    def show_add_destination_menu(self, attachment_widget):
        """Show menu to add a new filing destination."""
        menu = QMenu(self)

        # Get existing chip folder types
        existing_types = {chip.rule['folder_type'] for chip in attachment_widget.filing_chips}

        # Add all available filing rules
        for rule in self.filing_rules:
            if rule['folder_type'] not in existing_types:
                action = menu.addAction(rule['folder_type'])
                action.triggered.connect(lambda checked, r=rule: attachment_widget.add_chip(r))

        # Add Current Drawings if not already present
        if 'Current Drawings' not in existing_types:
            drawing_rule = {
                'keywords': [],
                'descriptors': [],
                'folder_location': '/XXXX_CURRENT-DRAWINGS',
                'folder_type': 'Current Drawings',
                'colour': '#f59e0b'
            }
            action = menu.addAction('Current Drawings')
            action.triggered.connect(lambda checked, r=drawing_rule: attachment_widget.add_chip(r))

        if menu.isEmpty():
            action = menu.addAction("(All destinations added)")
            action.setEnabled(False)

        menu.exec(self.cursor().pos())

    def on_subject_word_clicked(self, word, selected):
        """Handle clicking on a word in the email subject."""
        current_desc = self.desc_input.text().strip()

        if selected:
            # Add word to description
            if current_desc:
                new_desc = f"{current_desc} {word}"
            else:
                new_desc = word
            self.desc_input.setText(new_desc)
        else:
            # Remove word from description
            words = current_desc.split()
            # Remove the last occurrence of the word
            for i in range(len(words) - 1, -1, -1):
                if words[i].lower() == word.lower():
                    words.pop(i)
                    break
            self.desc_input.setText(' '.join(words))

    def start_drag_select(self, index):
        """Start drag selection from given index."""
        self.is_dragging = True
        self.drag_start_index = index
        # Determine if we're selecting or deselecting based on the clicked word's state
        if index < len(self.subject_word_labels):
            # We toggle on click, so the NEW state will be opposite of current
            self.drag_select_state = not self.subject_word_labels[index].selected

    def drag_select_to(self, index):
        """Extend drag selection to given index."""
        if not self.is_dragging or self.drag_start_index < 0:
            return

        # Get range of indices to select
        start = min(self.drag_start_index, index)
        end = max(self.drag_start_index, index)

        # Select/deselect all words in range
        for i in range(start, end + 1):
            if i < len(self.subject_word_labels):
                label = self.subject_word_labels[i]
                if label.selected != self.drag_select_state:
                    label.set_selected(self.drag_select_state)

    def end_drag_select(self):
        """End drag selection."""
        self.is_dragging = False
        self.drag_start_index = -1

    def preload_file(self, file_path):
        """Preload a file into the widget (for file watcher integration)."""
        if os.path.exists(file_path):
            self.on_files_dropped([file_path])

    def on_files_dropped(self, files):
        """Handle dropped files."""
        self.dropped_files = files
        self.email_data = None
        self.email_date = None

        if files:
            # Check if first file is an .eml
            first_file = files[0]
            if first_file.lower().endswith('.eml'):
                self.handle_eml_file(first_file)
            else:
                self.handle_regular_files(files)

    def handle_eml_file(self, eml_path):
        """Handle an .eml email file."""
        try:
            self.email_data = parse_eml_file(eml_path)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to parse email file:\n\n{str(e)}")
            return

        # Store source path for database record
        self.email_source_path = str(eml_path)

        # Extract Message-ID or generate hash fallback
        self.email_message_id = self.email_data.get('message_id')
        sender_name, sender_addr = parseaddr(self.email_data['from'])
        self.email_hash_fallback = generate_email_hash(
            sender_addr,
            self.email_data['subject'],
            self.email_data['date_iso']
        )

        # Check for duplicate
        self.email_is_duplicate = False
        if self.db_path and self.db_path.exists():
            existing = check_duplicate_email(
                self.db_path,
                self.email_message_id,
                self.email_hash_fallback
            )
            if existing:
                dialog = DuplicateEmailDialog(
                    self,
                    existing['filed_at'],
                    existing['filed_to'],
                    existing.get('filed_also')
                )
                result = dialog.exec()

                if result != QDialog.DialogCode.Accepted or dialog.result_action == 'skip':
                    # User chose to skip - reset and return
                    self.reset_form()
                    return

                # User chose to file again - mark as duplicate for later
                self.email_is_duplicate = True

        # Show email info
        self.email_from_label.setText(f"From: {self.email_data['from']}")
        self.email_to_label.setText(f"To: {self.email_data['to']}")
        self.email_date_label.setText(f"Date: {self.email_data['date'].strftime('%Y-%m-%d %H:%M')}")

        # Create clickable word labels for subject
        self.subject_word_labels = []
        while self.subject_layout.count():
            child = self.subject_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        subject = self.email_data.get('subject', '')
        # Split into words, keeping meaningful chunks
        words = re.findall(r'\b[\w\-]+\b', subject)
        index = 0
        for word in words:
            if len(word) > 1:  # Skip single characters
                label = ClickableWordLabel(word, self, index)
                self.subject_layout.addWidget(label)
                self.subject_word_labels.append(label)
                index += 1

        # Store email date for folder name
        self.email_date = self.email_data['date']

        # Extract embedded images (>20KB) and show/hide PDF toggle
        self.embedded_images = []
        if '_raw_message' in self.email_data:
            self.embedded_images = extract_embedded_images(
                self.email_data['_raw_message'],
                min_size=MIN_EMBEDDED_IMAGE_SIZE
            )

        # Show PDF toggle only if qualifying embedded images exist
        has_qualifying_images = len(self.embedded_images) > 0
        self.print_pdf_toggle.setVisible(has_qualifying_images)
        if has_qualifying_images:
            self.print_pdf_toggle.setChecked(True)  # Default ON when visible

        # Clear existing attachment checkboxes
        self.attachment_checkboxes = []
        while self.attachments_layout.count():
            child = self.attachments_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        while self.excluded_layout.count():
            child = self.excluded_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # Add attachment widgets - separate selected from excluded
        attachments = self.email_data.get('attachments', [])
        selected_count = 0
        excluded_count = 0

        # Try to detect job number from attachment filenames FIRST (for B-013 style prefixes)
        if attachments and not self.job_number:
            for att in attachments:
                detected_job = extract_job_number_from_filename(att['filename'], self.project_mapping)
                if detected_job:
                    self.try_select_job(detected_job)
                    break  # Use first match

        if attachments:
            for att in attachments:
                size_kb = att['size'] / 1024
                size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{att['size']/1024/1024:.1f} MB"

                filename = att['filename']
                is_image = filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp'))
                is_small = att['size'] < MIN_ATTACHMENT_SIZE
                is_embedded = is_embedded_image(filename)

                # Auto-exclude: small images, embedded images
                is_excluded = (is_image and is_small) or is_embedded

                # Check if this is a drawing PDF (use job number if available, but always check custom prefixes)
                job_for_drawing = self.job_number or self.last_job_number or ''
                is_drawing = is_drawing_pdf(filename, job_for_drawing, self.project_mapping)

                # Match filing rules using cascade (filename -> PDF metadata -> PDF content)
                matched_rules = match_filing_rules_cascade(
                    filename=filename,
                    rules=self.filing_rules,
                    attachment_data=att.get('data'),
                    job_number=job_for_drawing,
                    project_mapping=self.project_mapping
                )

                # Create custom attachment widget
                att_widget = AttachmentWidget(
                    filename=filename,
                    size_str=size_str,
                    attachment_data=att,
                    parent_widget=self,
                    is_excluded=is_excluded,
                    matched_rules=matched_rules,
                    is_drawing=is_drawing
                )

                if is_excluded:
                    self.excluded_layout.addWidget(att_widget)
                    excluded_count += 1
                else:
                    self.attachments_layout.addWidget(att_widget)
                    selected_count += 1

                self.attachment_checkboxes.append((att_widget, att))

            self.attachments_label.setText(f"Attachments ({selected_count}):")

            # Show/hide the "show more" button based on excluded count
            if excluded_count > 0:
                self.show_excluded_btn.setText(f"Show {excluded_count} hidden...")
                self.show_excluded_btn.setVisible(True)
                self.excluded_container.setVisible(False)
            else:
                self.show_excluded_btn.setVisible(False)
        else:
            self.attachments_label.setText("Attachments: None")
            self.show_excluded_btn.setVisible(False)

        # Show email frame, hide drop zone
        self.email_frame.setVisible(True)
        self.files_frame.setVisible(False)
        self.drop_zone.setVisible(False)

        # Auto-detect direction based on email addresses
        direction = detect_email_direction(self.email_data)
        if direction == 'OUT':
            self.export_radio.setChecked(True)
        else:
            self.import_radio.setChecked(True)

        # Try to auto-detect job number from email subject FIRST
        # This ensures contact lookup can use the correct job number
        # Detection handles: RE:/FW: prefixes, known projects, and mapping CSV
        subject = self.email_data.get('subject', '')
        detected_job = detect_project_from_subject(
            subject,
            self.projects,
            self.project_mapping
        )
        if detected_job:
            self.try_select_job(detected_job)
        elif self.last_job_number:
            # No job in subject, keep last job
            self.try_select_job(self.last_job_number, prompt_if_different=False)

        # Auto-fill sender/recipient with business name
        name, business = get_sender_name_and_business(self.email_data, direction)

        # Get the email address for database lookup
        if direction == 'IN':
            sender_addr = parseaddr(self.email_data.get('from', ''))[1]
        else:
            sender_addr = parseaddr(self.email_data.get('to', ''))[1]

        # First, check if we have a previously used contact name for this sender
        contact_text = None
        if hasattr(self, 'db_path') and self.db_path and sender_addr:
            # Try job-specific first, then any job
            contact_text = get_contact_for_sender(self.db_path, sender_addr, self.job_number)
            if not contact_text:
                contact_text = get_contact_for_sender(self.db_path, sender_addr)

        # Fall back to name/business extraction if no previous contact found
        if not contact_text:
            if business:
                contact_text = f"{name} ({business})" if name else business
            else:
                contact_text = name or ""

            # Check if we have a fuzzy match in previous contacts
            if self.previous_contacts and business:
                matches = fuzzy_match_contact(business, self.previous_contacts)
                if matches:
                    # Use the best match from previous filings
                    contact_text = matches[0]

        self.contact_input.setText(contact_text)

        # Add PDF placeholder if toggle is visible and checked
        if (hasattr(self, 'print_pdf_toggle') and
            self.print_pdf_toggle.isVisible() and
            self.print_pdf_toggle.isChecked() and
            HAS_PDF_RENDERER):
            self._add_pdf_placeholder()

        self.update_preview()

    def handle_regular_files(self, files):
        """Handle regular (non-email) files with secondary filing support."""
        # Clear existing file widgets
        self.file_widgets = []
        while self.files_container_layout.count():
            child = self.files_container_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # Update header label
        self.files_label.setText(f"Files ({len(files)}):")

        # Try to detect job number from file path FIRST, before processing files
        # This ensures drawing detection uses the correct job number
        if files:
            detected_job, detected_name, _ = find_job_number_from_path(files[0], self.project_mapping)
            if detected_job:
                self.try_select_job(detected_job)
            elif self.last_job_number and not self.job_number:
                # No job in path, use last job number as fallback
                self.try_select_job(self.last_job_number, prompt_if_different=False)

        # Get job number for drawing detection (now should be set from path detection)
        job_for_drawing = self.job_number or self.last_job_number or ''

        # Track if any JWA drawings detected
        has_drawings = False

        # Create AttachmentWidget for each file
        for file_path in files:
            src = Path(file_path)
            filename = src.name

            # Get file size
            try:
                size_bytes = src.stat().st_size
                size_kb = size_bytes / 1024
                size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_bytes/1024/1024:.1f} MB"
            except:
                size_str = "? KB"

            # Check if this is a drawing PDF
            is_drawing = is_drawing_pdf(filename, job_for_drawing, self.project_mapping) if job_for_drawing else False
            if is_drawing:
                has_drawings = True

            # Match filing rules using cascade (filename -> PDF metadata -> PDF content)
            # For dropped files, read PDF content from file if it's a PDF
            file_data = None
            if filename.lower().endswith('.pdf') and src.exists():
                try:
                    file_data = src.read_bytes()
                except Exception:
                    pass

            matched_rules = match_filing_rules_cascade(
                filename=filename,
                rules=self.filing_rules,
                attachment_data=file_data,
                job_number=job_for_drawing,
                project_mapping=self.project_mapping
            )

            # Create widget
            file_widget = AttachmentWidget(
                filename=filename,
                size_str=size_str,
                attachment_data=None,  # No attachment data for dropped files
                parent_widget=self,
                is_excluded=False,
                matched_rules=matched_rules,
                is_drawing=is_drawing,
                file_path=str(src)  # Store full path for copying
            )

            self.files_container_layout.addWidget(file_widget)
            self.file_widgets.append((file_widget, str(src)))

        # Show files frame, hide email frame
        self.files_frame.setVisible(True)
        self.email_frame.setVisible(False)
        self.drop_zone.setVisible(False)

        # Auto-switch to Export mode if JWA drawings detected
        if has_drawings:
            self.export_radio.setChecked(True)

        self.update_preview()

    def auto_select_project_from_path(self, file_path):
        """Auto-select project if job number is detected in file path."""
        detected_job, detected_name, _ = find_job_number_from_path(file_path, self.project_mapping)

        if detected_job:
            self.try_select_job(detected_job)
        elif self.last_job_number:
            # No job detected, keep last job
            self.try_select_job(self.last_job_number, prompt_if_different=False)

    def try_select_job(self, detected_job, prompt_if_different=True):
        """
        Try to select a job, prompting if different from current.

        Args:
            detected_job: Job number to select
            prompt_if_different: If True, prompt user when job differs from current
        """
        # Check if detected job is in our known projects list
        detected_project_name = None
        for proj_num, proj_name in self.projects:
            if proj_num == detected_job:
                detected_project_name = proj_name
                break

        # If not a known job, keep current selection
        if not detected_project_name:
            if self.last_job_number and not self.job_number:
                self.select_job_in_dropdown(self.last_job_number)
            return

        # Get current job
        current_job = self.job_number or self.last_job_number

        # If same as current job, just select it
        if detected_job == current_job:
            self.select_job_in_dropdown(detected_job)
            return

        # Different job detected
        if current_job and prompt_if_different:
            current_name = self.project_name or self.last_project_name or current_job
            reply = QMessageBox.question(
                self,
                "Different Job Detected",
                f"Detected job {detected_job} - {detected_project_name}\n\n"
                f"Currently working on: {current_job} - {current_name}\n\n"
                f"Switch to {detected_job}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )

            if reply == QMessageBox.StandardButton.No:
                # Keep current job selected
                self.select_job_in_dropdown(current_job)
                return

        # Select the detected job
        self.select_job_in_dropdown(detected_job)

    def select_job_in_dropdown(self, job_number):
        """Select a job in the dropdown by job number."""
        for i in range(self.project_combo.count()):
            data = self.project_combo.itemData(i)
            if data and data[0] == job_number:
                self.project_combo.setCurrentIndex(i)
                return

    def update_preview(self):
        """Update the folder name preview."""
        if not self.job_number:
            self.preview_label.setText("Select a project first...")
            return

        direction = "IN" if self.import_radio.isChecked() else "OUT"

        # Use email date if available, otherwise today's date
        if self.email_date:
            date_str = self.email_date.strftime("%Y-%m-%d")
        else:
            date_str = datetime.now().strftime("%Y-%m-%d")

        contact = self.contact_input.text().strip().upper().replace(" ", "-") or "SENDER"
        desc = self.desc_input.text().strip().upper().replace(" ", "-") or "DESCRIPTION"

        # Sanitize for folder name
        contact = re.sub(r'[^\w\-]', '', contact)
        desc = re.sub(r'[^\w\-]', '', desc)

        folder_name = f"{self.job_number}_{direction}_{date_str}_{contact}_{desc}"
        self.preview_label.setText(folder_name)

    def file_documents(self):
        """Create folder and move files, including secondary filing destinations."""
        if not self.job_number:
            QMessageBox.warning(self, "Error", "Please select a project first.")
            return

        # Check if we have files to file
        has_files = False
        if self.email_data:
            # Check if any attachments are selected
            has_files = any(cb.isChecked() for cb, _ in self.attachment_checkboxes)
        else:
            # Check if any dropped files are selected
            has_files = any(fw.isChecked() for fw, _ in self.file_widgets)

        if not has_files:
            QMessageBox.warning(self, "Error", "Please select some files/attachments to file.")
            return

        contact = self.contact_input.text().strip()
        desc = self.desc_input.text().strip()

        if not contact:
            QMessageBox.warning(self, "Missing Information", "Please enter a sender/recipient.")
            return

        if not desc:
            QMessageBox.warning(self, "Missing Information", "Please enter a description.")
            return

        # Find project folder
        try:
            project_folder = self.find_project_folder()
        except FileNotFoundError as e:
            # Hard stop - project root doesn't exist
            QMessageBox.critical(
                self,
                "Project Root Not Found",
                f"⚠ {str(e)}\n\n"
                "No files have been moved."
            )
            return

        if not project_folder:
            QMessageBox.warning(
                self,
                "Project Folder Not Found",
                f"Could not find folder for project {self.job_number} - {self.project_name}\n\n"
                "Please configure the projects root directory in settings."
            )
            return

        # Build folder name
        direction = "IN" if self.import_radio.isChecked() else "OUT"

        # Use email date if available
        if self.email_date:
            date_str = self.email_date.strftime("%Y-%m-%d")
        else:
            date_str = datetime.now().strftime("%Y-%m-%d")

        contact_safe = re.sub(r'[^\w\-]', '', contact.upper().replace(" ", "-"))
        desc_safe = re.sub(r'[^\w\-]', '', desc.upper().replace(" ", "-"))

        folder_name = f"{self.job_number}_{direction}_{date_str}_{contact_safe}_{desc_safe}"

        # Find or create IMPORTS-EXPORTS folder
        imports_exports_folder = None
        project_path = Path(project_folder)

        # Look for existing IMPORTS-EXPORTS folder (case insensitive)
        for item in project_path.iterdir():
            if item.is_dir() and 'IMPORT' in item.name.upper() and 'EXPORT' in item.name.upper():
                imports_exports_folder = item
                break

        # Also check for folder with job number prefix
        if not imports_exports_folder:
            for item in project_path.iterdir():
                if item.is_dir() and self.job_number in item.name and ('IMPORT' in item.name.upper() or 'EXPORT' in item.name.upper()):
                    imports_exports_folder = item
                    break

        # Create if not found
        if not imports_exports_folder:
            imports_exports_folder = project_path / f"{self.job_number}_IMPORTS-EXPORTS"
            imports_exports_folder.mkdir(exist_ok=True)

        # Create the destination folder
        dest_folder = imports_exports_folder / folder_name

        # Key Stage Archive folder confirmation - prompt BEFORE filing if enabled
        keystage_confirmed_name = None
        if self._is_keystage_enabled():
            # Find the Key-stage rule to compute default folder name
            keystage_rule = None
            for rule in self.filing_rules:
                if rule.get('folder_type', '').lower() == 'key-stage':
                    keystage_rule = rule
                    break

            if keystage_rule:
                subfolder_structure = keystage_rule.get('subfolder_structure', '').strip()
                if subfolder_structure:
                    # Compute default name using the structure
                    default_name = subfolder_structure.replace('XXXX', self.job_number)
                    default_name = default_name.replace('DESCRIPTION', desc_safe)
                    default_name = default_name.lstrip('/')
                else:
                    # No structure - just use description
                    default_name = f"{self.job_number}_KEYSTAGE_{desc_safe}"

                # Show confirmation dialog
                from PyQt6.QtWidgets import QInputDialog
                confirmed_name, ok = QInputDialog.getText(
                    self,
                    "Key Stage Archive",
                    "Confirm or edit the Key Stage folder name:",
                    text=default_name
                )
                if not ok:
                    return  # User cancelled
                keystage_confirmed_name = confirmed_name.strip() if confirmed_name else default_name

        try:
            # Pre-calculate expected files per destination for circuit breaker
            destination_limits = {}
            destination_limits[str(dest_folder)] = 0  # Primary destination

            if self.email_data:
                for att_widget, att in self.attachment_checkboxes:
                    if att_widget.isChecked():
                        # Count for primary destination
                        destination_limits[str(dest_folder)] += 1

                        # Count for each secondary destination
                        secondary_dests = att_widget.get_secondary_destinations()
                        for rule in secondary_dests:
                            secondary_path = self._resolve_secondary_path(project_path, rule)
                            if secondary_path:
                                path_str = str(secondary_path)
                                destination_limits[path_str] = destination_limits.get(path_str, 0) + 1
            else:
                for file_widget, file_path in self.file_widgets:
                    if file_widget.isChecked():
                        # Count for primary destination
                        destination_limits[str(dest_folder)] += 1

                        # Count for each secondary destination
                        secondary_dests = file_widget.get_secondary_destinations()
                        for rule in secondary_dests:
                            secondary_path = self._resolve_secondary_path(project_path, rule)
                            if secondary_path:
                                path_str = str(secondary_path)
                                destination_limits[path_str] = destination_limits.get(path_str, 0) + 1

            # Reset circuit breaker with per-destination limits
            get_circuit_breaker().reset(destination_limits=destination_limits)

            dest_folder.mkdir(exist_ok=True)

            copied_count = 0
            secondary_copies = 0
            actual_secondary_destinations = []  # Track ONLY destinations where files were actually copied
            supersede_messages = []  # Track drawing superseding actions

            if self.email_data:
                # Save selected email attachments
                for att_widget, att in self.attachment_checkboxes:
                    if att_widget.isChecked():
                        # Skip PDF placeholder - it's handled separately below
                        if att.get('is_pdf_placeholder', False):
                            continue

                        filename = att['filename']

                        # Check for duplicates in project
                        action, final_filename = self._check_file_duplicate(project_path, filename)

                        if action == 'skip':
                            continue  # Skip this file

                        # Primary filing to IMPORTS-EXPORTS
                        dst = dest_folder / final_filename
                        if safe_write_attachment(dst, att['data'], self.projects_root, final_filename):
                            copied_count += 1

                        # Secondary filing to additional destinations
                        secondary_dests = att_widget.get_secondary_destinations()
                        for rule in secondary_dests:
                            secondary_path = self._resolve_secondary_path(project_path, rule)
                            if secondary_path:
                                sec_dst = secondary_path / final_filename
                                if safe_write_attachment(sec_dst, att['data'], self.projects_root, final_filename):
                                    secondary_copies += 1
                                    # Record ACTUAL destination where file was copied
                                    folder_type = rule.get('folder_type', '')
                                    if folder_type and folder_type not in actual_secondary_destinations:
                                        actual_secondary_destinations.append(folder_type)

                                    # Check for drawing superseding in Current Drawings folder
                                    if is_current_drawings_folder(secondary_path):
                                        success, msg, count = supersede_drawings(
                                            secondary_path, sec_dst, self.projects_root
                                        )
                                        if msg:  # Include both supersede info and warnings
                                            supersede_messages.append(msg)

                # File embedded images with structured naming (only renamed version, not original)
                if hasattr(self, 'embedded_images') and self.embedded_images:
                    email_date = self.email_data.get('date', datetime.now())
                    screenshot_filenames = generate_screenshot_filenames(
                        self.job_number, email_date, len(self.embedded_images)
                    )
                    for i, img in enumerate(self.embedded_images):
                        # Convert to PNG and save with structured filename only
                        png_data = convert_image_to_png(img['data'])
                        screenshot_dst = dest_folder / screenshot_filenames[i]
                        if safe_write_attachment(screenshot_dst, png_data, self.projects_root, screenshot_filenames[i]):
                            copied_count += 1

                # Generate and file email PDF if toggle is ON
                if (hasattr(self, 'print_pdf_toggle') and
                    self.print_pdf_toggle.isVisible() and
                    self.print_pdf_toggle.isChecked() and
                    HAS_PDF_RENDERER):
                    pdf_data, pdf_filename = generate_email_pdf(
                        self.email_data,
                        self.embedded_images if hasattr(self, 'embedded_images') else [],
                        self.job_number,
                        self.projects_root
                    )
                    if pdf_data and pdf_filename:
                        # Check for duplicates and get final filename
                        action, final_pdf_filename = self._check_file_duplicate(project_path, pdf_filename)

                        if action != 'skip':
                            # Primary filing to IMPORTS-EXPORTS
                            pdf_dst = dest_folder / final_pdf_filename
                            if safe_write_attachment(pdf_dst, pdf_data, self.projects_root, final_pdf_filename):
                                copied_count += 1

                            # Secondary filing from PDF placeholder widget settings
                            if self.pdf_placeholder_widget is not None:
                                secondary_dests = self.pdf_placeholder_widget.get_secondary_destinations()
                                for rule in secondary_dests:
                                    secondary_path = self._resolve_secondary_path(project_path, rule)
                                    if secondary_path:
                                        sec_dst = secondary_path / final_pdf_filename
                                        if safe_write_attachment(sec_dst, pdf_data, self.projects_root, final_pdf_filename):
                                            secondary_copies += 1
                                            folder_type = rule.get('folder_type', '')
                                            if folder_type and folder_type not in actual_secondary_destinations:
                                                actual_secondary_destinations.append(folder_type)

            else:
                # Copy regular files with secondary filing support
                for file_widget, file_path in self.file_widgets:
                    if file_widget.isChecked():
                        src = Path(file_path)
                        filename = src.name

                        # Check for duplicates in project
                        action, final_filename = self._check_file_duplicate(project_path, filename)

                        if action == 'skip':
                            continue  # Skip this file

                        dst = dest_folder / final_filename

                        if src.is_file():
                            if safe_copy(src, dst, self.projects_root):
                                copied_count += 1

                            # Secondary filing to additional destinations
                            secondary_dests = file_widget.get_secondary_destinations()
                            for rule in secondary_dests:
                                secondary_path = self._resolve_secondary_path(project_path, rule)
                                if secondary_path:
                                    sec_dst = secondary_path / final_filename
                                    if safe_copy(src, sec_dst, self.projects_root):
                                        secondary_copies += 1
                                        # Record ACTUAL destination where file was copied
                                        folder_type = rule.get('folder_type', '')
                                        if folder_type and folder_type not in actual_secondary_destinations:
                                            actual_secondary_destinations.append(folder_type)

                                        # Check for drawing superseding in Current Drawings folder
                                        if is_current_drawings_folder(secondary_path):
                                            success, msg, count = supersede_drawings(
                                                secondary_path, sec_dst, self.projects_root
                                            )
                                            if msg:  # Include both supersede info and warnings
                                                supersede_messages.append(msg)
                        elif src.is_dir():
                            if safe_copy(src, dst, self.projects_root):
                                copied_count += 1

            # Key Stage Archive - copy all filed items to KEYSTAGE folder using CSV rules
            keystage_copies = 0
            if self._is_keystage_enabled() and keystage_confirmed_name:
                # Find the Key-stage rule in filing rules
                keystage_rule = None
                for rule in self.filing_rules:
                    if rule.get('folder_type', '').lower() == 'key-stage':
                        keystage_rule = rule
                        break

                if keystage_rule:
                    # Resolve the folder location (e.g., /XXXX_KEY_STAGE_ARCHIVE_PDF)
                    folder_location = keystage_rule['folder_location'].replace('XXXX', self.job_number)
                    keystage_base = project_path / folder_location.lstrip('/')

                    # Use the user-confirmed folder name
                    keystage_folder = keystage_base / keystage_confirmed_name.lstrip('/')

                    # Create folder if needed
                    keystage_folder.mkdir(parents=True, exist_ok=True)

                    # Log keystage archiving
                    logger = get_file_ops_logger(self.projects_root)
                    logger.info(f"KEYSTAGE ARCHIVE | Creating: {keystage_folder}")

                    # Copy all files from dest_folder to keystage_folder
                    if self.email_data:
                        for att_widget, att in self.attachment_checkboxes:
                            if att_widget.isChecked():
                                keystage_dst = keystage_folder / att['filename']
                                if safe_write_attachment(keystage_dst, att['data'], self.projects_root, f"KEYSTAGE:{att['filename']}"):
                                    keystage_copies += 1
                    else:
                        for file_widget, file_path in self.file_widgets:
                            if file_widget.isChecked():
                                src = Path(file_path)
                                keystage_dst = keystage_folder / src.name
                                if src.is_file():
                                    if safe_copy(src, keystage_dst, self.projects_root):
                                        keystage_copies += 1
                                elif src.is_dir():
                                    if safe_copy(src, keystage_dst, self.projects_root):
                                        keystage_copies += 1

            # Outbound email screenshot & PDF capture
            captured_files = {'screenshots': [], 'pdf_filename': None}
            if self.email_data and direction == 'OUT':
                # Get the raw message object for embedded image extraction
                raw_msg = self.email_data.get('_raw_message')
                if raw_msg:
                    # Collect secondary paths used for this filing
                    secondary_paths_used = []
                    for att_widget, _ in self.attachment_checkboxes:
                        for rule in att_widget.get_secondary_destinations():
                            sec_path = self._resolve_secondary_path(project_path, rule)
                            if sec_path and sec_path not in secondary_paths_used:
                                secondary_paths_used.append(sec_path)

                    # Get keystage folder if active
                    ks_folder = keystage_folder if (self._is_keystage_enabled() and keystage_rule) else None

                    captured_files = process_outbound_email_capture(
                        msg=raw_msg,
                        email_data=self.email_data,
                        job_number=self.job_number,
                        dest_folder=dest_folder,
                        projects_root=self.projects_root,
                        secondary_paths=secondary_paths_used,
                        keystage_folder=ks_folder
                    )

            # Write to database
            if self.db_path and self.db_path.exists():
                if self.email_data:
                    self._write_email_to_database(
                        dest_folder=str(dest_folder),
                        direction=direction,
                        actual_secondary_destinations=actual_secondary_destinations,
                        captured_screenshots=captured_files.get('screenshots', []),
                        captured_pdf=captured_files.get('pdf_filename'),
                        contact=contact
                    )
                else:
                    # Record file filing (no email) - just store contact for autocomplete
                    self._write_file_filing_to_database(
                        dest_folder=str(dest_folder),
                        contact=contact
                    )

            # Build success message (simple counts only, no detailed log)
            success_msg = f"Filed {copied_count} item(s)"
            if secondary_copies > 0:
                success_msg += f"\n+ {secondary_copies} secondary copies"
            if keystage_copies > 0:
                success_msg += f"\n+ {keystage_copies} Key Stage Archive copies"
            if captured_files.get('screenshots') or captured_files.get('pdf_filename'):
                capture_count = len(captured_files.get('screenshots', []))
                if captured_files.get('pdf_filename'):
                    capture_count += 1
                success_msg += f"\n+ {capture_count} email capture file(s)"
            if supersede_messages:
                success_msg += f"\n+ {len(supersede_messages)} drawing(s) superseded"

            # Show success dialog with clickable link
            dialog = SuccessDialog(self, success_msg, dest_folder)
            dialog.exec()

            self.reset_form()

        except PathJailViolation as e:
            # Path jail violation - log and show clear warning
            logger = get_file_ops_logger(self.projects_root)
            logger.error(f"PATH JAIL VIOLATION | {str(e)}")
            QMessageBox.critical(
                self,
                "Security: Path Violation",
                f"⚠ BLOCKED: A file operation attempted to access a path outside the project root.\n\n"
                f"{str(e)}\n\n"
                "No files have been moved or copied. This may indicate a configuration error in the filing rules CSV."
            )

        except CircuitBreakerTripped as e:
            # Circuit breaker tripped - log all operations and show warning
            logger = get_file_ops_logger(self.projects_root)
            cb = get_circuit_breaker()
            ops_log = "\n".join([f"  {op[0]}: {op[1]} -> {op[2]}" for op in cb.get_summary()])
            logger.error(f"CIRCUIT BREAKER TRIPPED | {cb.count} operations\n{ops_log}")
            QMessageBox.critical(
                self,
                "Safety Stop: Too Many Operations",
                f"⚠ STOPPED: Too many file operations in a single filing action.\n\n"
                f"{str(e)}\n\n"
                "The filing action was stopped to prevent potential runaway operations. "
                "Some files may have been copied before the stop. "
                "Check the filing_operations.log for details."
            )

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to file documents:\n\n{str(e)}")

    def _write_email_to_database(self, dest_folder, direction, actual_secondary_destinations,
                                   captured_screenshots=None, captured_pdf=None, contact=None):
        """Write email record to the filing database.

        Args:
            dest_folder: Primary destination folder path
            direction: 'IN' or 'OUT'
            actual_secondary_destinations: List of folder_type names where files were ACTUALLY copied
                                          (not suggestions, only explicit user choices that resulted in copies)
            captured_screenshots: List of generated screenshot filenames (optional)
            captured_pdf: Generated PDF filename (optional)
            contact: User-entered contact name at time of filing
        """
        try:
            # Extract sender info
            sender_name, sender_addr = parseaddr(self.email_data['from'])

            # Get recipient info
            _, to_addr = parseaddr(self.email_data['to'])
            cc_addr = self.email_data.get('cc', '')

            # Determine is_inbound
            is_inbound = 1 if direction == 'IN' else 0

            # For contact lookup, we need to store the relevant address:
            # - For IN (import): use sender address (from)
            # - For OUT (export): use recipient address (to)
            contact_lookup_addr = sender_addr if direction == 'IN' else to_addr

            # Get attachment names - include regular attachments and captured files
            selected_attachments = [
                att['filename'] for att_widget, att in self.attachment_checkboxes
                if att_widget.isChecked()
            ]

            # Add captured screenshots and PDF to attachment list
            if captured_screenshots:
                selected_attachments.extend(captured_screenshots)
            if captured_pdf:
                selected_attachments.append(captured_pdf)

            attachment_names = ','.join(selected_attachments) if selected_attachments else None

            # filed_also and tags come ONLY from actual copies made (not suggestions)
            # If user ticked nothing, these are null. If user ticked 2 boxes, those 2 go in.
            filed_also = ','.join(actual_secondary_destinations) if actual_secondary_destinations else None
            tags = filed_also  # Tags match the actual destinations

            email_record = {
                'message_id': self.email_message_id,
                'hash_fallback': self.email_hash_fallback,
                'sender_address': contact_lookup_addr,  # Store the relevant party for contact lookup
                'sender_name': sender_name,
                'recipient_to': to_addr,
                'recipient_cc': cc_addr,
                'subject': self.email_data.get('subject', ''),
                'date_sent': self.email_data.get('date_iso', ''),
                'body_clean': self.email_data.get('body_clean', ''),
                'sign_off_type': self.email_data.get('sign_off_type'),
                'is_inbound': is_inbound,
                'filed_to': dest_folder,
                'filed_also': filed_also,
                'tags': tags,
                'has_attachments': 1 if selected_attachments else 0,
                'attachment_names': attachment_names,
                'source_path': self.email_source_path,
                'contact_name': contact,  # User-entered contact at time of filing
                'job_number': self.job_number,
            }

            if self.email_is_duplicate:
                # Update existing record with new destination
                update_filed_also(
                    self.db_path,
                    self.email_message_id,
                    self.email_hash_fallback,
                    dest_folder,
                    self.projects_root
                )
            else:
                # Insert new record
                insert_email_record(self.db_path, email_record, self.projects_root)

        except Exception as e:
            # Don't fail the filing if database write fails - just log
            print(f"Warning: Failed to write email to database: {e}")

    def _write_file_filing_to_database(self, dest_folder, contact):
        """Write file filing record to database for contact autocomplete.

        This is for dropped files (not emails) - we store minimal info
        just to track the contact name used for autocomplete.
        """
        try:
            import uuid
            # Generate unique ID for this file filing
            file_id = f"FILE_{uuid.uuid4().hex[:16]}"

            file_record = {
                'message_id': file_id,
                'hash_fallback': None,
                'sender_address': 'file_filing',  # Placeholder
                'sender_name': None,
                'recipient_to': None,
                'recipient_cc': None,
                'subject': f"File filing: {contact}",  # Placeholder
                'date_sent': datetime.now().isoformat(),
                'body_clean': None,
                'sign_off_type': None,
                'is_inbound': 0 if self.export_radio.isChecked() else 1,
                'filed_to': dest_folder,
                'filed_also': None,
                'tags': None,
                'has_attachments': 0,
                'attachment_names': None,
                'source_path': None,
                'contact_name': contact,
                'job_number': self.job_number,
            }

            insert_email_record(self.db_path, file_record, self.projects_root)

        except Exception as e:
            # Don't fail the filing if database write fails - just log
            print(f"Warning: Failed to write file filing to database: {e}")

    def _check_file_duplicate(self, project_path, filename):
        """
        Check if a file with the same name exists anywhere in the project.

        Args:
            project_path: Path to the project folder
            filename: Name of the file to check

        Returns:
            tuple: (action, new_filename) where action is 'proceed', 'skip', 'rename', or 'overwrite'
                   new_filename is only set if action is 'rename'
        """
        duplicates = scan_for_file_duplicates(project_path, filename)

        if not duplicates:
            return ('proceed', filename)

        # Show dialog
        dialog = FileDuplicateDialog(self, filename, duplicates, self.projects_root)
        result = dialog.exec()

        if result != QDialog.DialogCode.Accepted:
            return ('skip', filename)

        if dialog.result_action == 'skip':
            return ('skip', filename)
        elif dialog.result_action == 'rename':
            return ('rename', dialog.new_filename)
        elif dialog.result_action == 'overwrite':
            return ('overwrite', filename)

        return ('proceed', filename)

    def _resolve_secondary_path(self, project_path, rule, description=None):
        """
        Resolve a secondary filing path from a rule.

        Replaces XXXX with job number and DESCRIPTION with description.
        If rule has subfolder_structure defined, creates that subfolder.

        Args:
            project_path: Path to the project folder
            rule: Filing rule dict with folder_location and optional subfolder_structure
            description: Optional description to replace DESCRIPTION placeholder

        Returns:
            Path object if successful, None if user cancelled
        """
        folder_location = rule['folder_location']

        # Replace XXXX with job number
        resolved_path = folder_location.replace('XXXX', self.job_number)

        # Build full path (folder_location starts with /)
        full_path = project_path / resolved_path.lstrip('/')

        # Check if rule has subfolder_structure defined
        subfolder_structure = rule.get('subfolder_structure', '').strip()
        if subfolder_structure:
            # Get description from form if not provided
            if description is None:
                description = self.desc_input.text().strip()
            desc_safe = re.sub(r'[^\w\-]', '', description.upper().replace(" ", "-"))

            # Replace placeholders in subfolder structure
            subfolder_name = subfolder_structure.replace('XXXX', self.job_number)
            subfolder_name = subfolder_name.replace('DESCRIPTION', desc_safe)

            # Append subfolder to full path
            full_path = full_path / subfolder_name.lstrip('/')

        # Check if folder exists - show existing folders and let user decide
        if not full_path.exists():
            parent_path = full_path.parent
            folder_name = full_path.name

            # Check if parent exists - if not, warn about deeper missing path
            if not parent_path.exists():
                # Find the first existing ancestor
                existing_ancestor = parent_path
                while not existing_ancestor.exists() and existing_ancestor != project_path:
                    existing_ancestor = existing_ancestor.parent

                QMessageBox.warning(
                    self,
                    "Destination Folder Not Found",
                    f"⚠ Destination folder not found:\n\n{full_path}\n\n"
                    f"The parent folder also doesn't exist:\n{parent_path}\n\n"
                    f"Closest existing folder: {existing_ancestor}\n\n"
                    "This may indicate a configuration error in the filing rules CSV. "
                    "This secondary filing will be skipped."
                )
                return None

            # Parent exists - list existing folders to help user spot typos
            existing_folders = sorted([
                f.name for f in parent_path.iterdir()
                if f.is_dir()
            ])

            if existing_folders:
                folders_list = "\n".join([f"  • {f}" for f in existing_folders[:15]])
                if len(existing_folders) > 15:
                    folders_list += f"\n  ... and {len(existing_folders) - 15} more"
            else:
                folders_list = "  (no folders exist here yet)"

            msg = QMessageBox(self)
            msg.setWindowTitle("Destination Folder Not Found")
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setText(f"⚠ Destination folder not found:\n\n{full_path}")
            msg.setInformativeText(
                f"Existing folders in {parent_path.name}/:\n{folders_list}\n\n"
                "What would you like to do?"
            )
            msg.addButton(f"Create \"{folder_name}\"", QMessageBox.ButtonRole.AcceptRole)
            cancel_btn = msg.addButton("Skip this filing", QMessageBox.ButtonRole.RejectRole)
            msg.setDefaultButton(cancel_btn)

            msg.exec()

            if msg.clickedButton() == cancel_btn:
                return None

            # User chose to create
            try:
                full_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to create folder:\n\n{str(e)}")
                return None

        return full_path

    def find_project_folder(self):
        """
        Find the project folder based on job number.

        Returns:
            str: Path to project folder if found
            None: Project folder not found (but root exists)

        Raises:
            FileNotFoundError: If projects_root doesn't exist (hard stop condition)
        """
        if not self.projects_root or not self.job_number:
            return None

        projects_root = Path(self.projects_root)
        if not projects_root.exists():
            # Hard stop - project root doesn't exist
            raise FileNotFoundError(
                f"Project root not found: {self.projects_root}\n\n"
                "This path does not exist. Check the project root setting."
            )

        # Look for folder matching pattern: {job_number} - {name}
        for item in projects_root.iterdir():
            if item.is_dir():
                job_num, proj_name = parse_folder_name(item.name)
                if job_num == self.job_number:
                    return str(item)

        return None

    def _is_keystage_enabled(self):
        """Check if Key Stage Archive is enabled (either toggle)."""
        email_checked = hasattr(self, 'keystage_toggle') and self.keystage_toggle.isChecked()
        files_checked = hasattr(self, 'files_keystage_toggle') and self.files_keystage_toggle.isChecked()
        return email_checked or files_checked

    def _on_keystage_toggled(self, checked):
        """Handle Key Stage Archive toggle state change."""
        logger = get_file_ops_logger(self.projects_root)
        if checked:
            logger.info("KEYSTAGE TOGGLE | Enabled")
        else:
            logger.info("KEYSTAGE TOGGLE | Disabled")

    def _on_print_pdf_toggled(self, checked):
        """Handle Print Email to PDF toggle state change - add/remove PDF placeholder in attachments."""
        if not self.email_data:
            return

        if checked and HAS_PDF_RENDERER:
            # Add PDF placeholder to attachments list
            self._add_pdf_placeholder()
        else:
            # Remove PDF placeholder
            self._remove_pdf_placeholder()

    def _get_pdf_filename(self):
        """Generate the PDF filename for the current email."""
        if not self.email_data:
            return None
        job = self.job_number or 'XXXX'
        email_date = self.email_data.get('date', datetime.now())
        date_str = email_date.strftime('%Y-%m-%d')
        subject = self.email_data.get('subject', 'untitled')
        cleaned_subject = clean_subject_for_filename(subject, job)
        return f"{job}_email_{date_str}_{cleaned_subject}.pdf"

    def _add_pdf_placeholder(self):
        """Add a PDF placeholder widget to the attachments list."""
        if self.pdf_placeholder_widget is not None:
            return  # Already added

        pdf_filename = self._get_pdf_filename()
        if not pdf_filename:
            return

        # Create placeholder attachment widget (no actual data yet)
        self.pdf_placeholder_widget = AttachmentWidget(
            filename=pdf_filename,
            size_str="(PDF)",
            attachment_data={'filename': pdf_filename, 'data': None, 'size': 0, 'is_pdf_placeholder': True},
            parent_widget=self,
            is_excluded=False,
            matched_rules=[],
            is_drawing=False
        )
        self.pdf_placeholder_widget.setChecked(True)

        # Add to attachments layout
        self.attachments_layout.addWidget(self.pdf_placeholder_widget)
        self.attachment_checkboxes.append((self.pdf_placeholder_widget, {'filename': pdf_filename, 'data': None, 'size': 0, 'is_pdf_placeholder': True}))

        # Update count
        current_text = self.attachments_label.text()
        if 'None' in current_text:
            self.attachments_label.setText("Attachments (1):")
        else:
            import re as regex
            match = regex.search(r'\((\d+)\)', current_text)
            if match:
                count = int(match.group(1)) + 1
                self.attachments_label.setText(f"Attachments ({count}):")

    def _remove_pdf_placeholder(self):
        """Remove the PDF placeholder widget from attachments list."""
        if self.pdf_placeholder_widget is None:
            return

        # Remove from layout
        self.attachments_layout.removeWidget(self.pdf_placeholder_widget)
        self.pdf_placeholder_widget.deleteLater()

        # Remove from checkboxes list
        self.attachment_checkboxes = [(w, a) for w, a in self.attachment_checkboxes
                                       if not a.get('is_pdf_placeholder', False)]

        self.pdf_placeholder_widget = None

        # Update count
        current_text = self.attachments_label.text()
        import re as regex
        match = regex.search(r'\((\d+)\)', current_text)
        if match:
            count = max(0, int(match.group(1)) - 1)
            if count == 0:
                self.attachments_label.setText("Attachments: None")
            else:
                self.attachments_label.setText(f"Attachments ({count}):")

    def reset_form(self, clear_job=False):
        """Reset the form to initial state, optionally keeping the job selected."""
        # Remember current job for next filing
        if self.job_number:
            self.last_job_number = self.job_number
            self.last_project_name = self.project_name

        self.dropped_files = []
        self.email_data = None
        self.email_date = None
        self.embedded_images = []
        self.attachment_checkboxes = []

        # Reset and hide Print Email to PDF toggle
        if hasattr(self, 'print_pdf_toggle'):
            self.print_pdf_toggle.setVisible(False)
            self.print_pdf_toggle.setChecked(True)  # Reset to default ON for next email
        self.pdf_placeholder_widget = None
        self.file_widgets = []
        self.subject_word_labels = []

        # Clear attachment checkboxes
        while self.attachments_layout.count():
            child = self.attachments_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        while self.excluded_layout.count():
            child = self.excluded_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # Clear file widgets
        while self.files_container_layout.count():
            child = self.files_container_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # Clear subject word labels
        while self.subject_layout.count():
            child = self.subject_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # Reset tick-all checkboxes
        self.tick_all_checkbox.setChecked(False)
        self.files_tick_all_checkbox.setChecked(False)

        # Clear global chips from headers
        for chip in self.global_chips[:]:
            self.global_chips_layout.removeWidget(chip)
            chip.deleteLater()
        self.global_chips.clear()

        for chip in self.files_global_chips[:]:
            self.files_global_chips_layout.removeWidget(chip)
            chip.deleteLater()
        self.files_global_chips.clear()

        # Reset global + button visibility
        if hasattr(self, 'global_add_chip_btn'):
            self.global_add_chip_btn.setVisible(True)
        if hasattr(self, 'files_global_add_chip_btn'):
            self.files_global_add_chip_btn.setVisible(True)

        self.show_excluded_btn.setVisible(False)
        self.excluded_container.setVisible(False)

        self.files_frame.setVisible(False)
        self.email_frame.setVisible(False)
        self.drop_zone.setVisible(True)

        # Reset Key Stage Archive toggles
        if hasattr(self, 'keystage_toggle'):
            self.keystage_toggle.setChecked(False)
        if hasattr(self, 'files_keystage_toggle'):
            self.files_keystage_toggle.setChecked(False)

        self.contact_input.clear()
        self.desc_input.clear()
        self.import_radio.setChecked(True)

        if clear_job:
            # Full reset - clear job selection
            self.project_combo.setCurrentIndex(0)
            self.job_number = None
            self.project_name = None
        else:
            # Keep the last job selected for consecutive filings
            if self.last_job_number:
                # Find and select the last job in dropdown
                for i in range(self.project_combo.count()):
                    data = self.project_combo.itemData(i)
                    if data and data[0] == self.last_job_number:
                        self.project_combo.setCurrentIndex(i)
                        break
        self.update_preview()


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Jaike_CRM Filing Widget')
    parser.add_argument(
        '--file', '-f',
        type=str,
        help='File to preload into the widget'
    )
    args, qt_args = parser.parse_known_args()

    # Qt needs sys.argv-like list
    app = QApplication([sys.argv[0]] + qt_args)
    app.setApplicationName("FileUZI")

    # Set default font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    window = FilingWidget()
    window.show()

    # Preload file if specified
    if args.file and os.path.exists(args.file):
        # Simulate a file drop
        window.preload_file(args.file)

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
