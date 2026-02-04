"""
Dialog components for FileUzi.
"""

import os
import re

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices

from fileuzi.config import COLORS
from fileuzi.database import get_database_path
from fileuzi.utils import get_file_ops_logger


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
        version_match = re.search(r'_v(\d+)$', base)
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
