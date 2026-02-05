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
    """Dialog shown when a duplicate file is detected at the same location."""

    def __init__(self, parent, filename, duplicate_locations, projects_root,
                 destination_folder=None):
        super().__init__(parent)
        self.filename = filename
        self.duplicate_locations = duplicate_locations
        self.projects_root = projects_root
        self.destination_folder = destination_folder
        self.result_action = None
        self.new_filename = None
        self.replace_target = None  # Path of file to replace
        self.setWindowTitle("Duplicate File Detected")
        self.setModal(True)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Warning message
        warning_label = QLabel(f"File '{self.filename}' already exists:")
        warning_label.setStyleSheet(f"color: {COLORS['warning']}; font-size: 14px; font-weight: bold;")
        warning_label.setWordWrap(True)
        layout.addWidget(warning_label)

        # Show file details for first duplicate
        first_dup = self.duplicate_locations[0]
        try:
            from pathlib import Path
            dup_path = Path(first_dup)
            if dup_path.exists():
                stat = dup_path.stat()
                size_mb = stat.st_size / (1024 * 1024)
                from datetime import datetime
                modified = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
                details_text = (
                    f"  Location: {first_dup}\n"
                    f"  Size: {size_mb:.1f} MB\n"
                    f"  Modified: {modified}"
                )
            else:
                details_text = f"  Location: {first_dup}"
        except Exception:
            details_text = f"  Location: {first_dup}"

        if len(self.duplicate_locations) > 1:
            details_text += f"\n\n... and {len(self.duplicate_locations) - 1} more location(s)"

        details_label = QLabel(details_text)
        details_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 12px;")
        details_label.setWordWrap(True)
        layout.addWidget(details_label)

        # Options
        btn_skip = QPushButton("a) Skip - don't copy this file")
        btn_skip.setStyleSheet(self._button_style())
        btn_skip.clicked.connect(self.on_skip)
        layout.addWidget(btn_skip)

        btn_rename = QPushButton("b) Rename - add _v2 suffix")
        btn_rename.setStyleSheet(self._button_style())
        btn_rename.setDefault(True)
        btn_rename.clicked.connect(self.on_rename)
        layout.addWidget(btn_rename)

        # Determine Superseded folder name for display
        from pathlib import Path
        dup_parent = Path(first_dup).parent.name
        btn_replace = QPushButton(
            f"c) Replace (moves old to {dup_parent}/Superseded)"
        )
        btn_replace.setStyleSheet(self._button_style())
        btn_replace.clicked.connect(self.on_replace)
        layout.addWidget(btn_replace)

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
        logger = get_file_ops_logger(self.projects_root)
        logger.info(f"DUPLICATE SKIP | {self.filename} | Existing at: {self.duplicate_locations[0]}")
        self.accept()

    def on_rename(self):
        self.result_action = 'rename'
        # Generate new filename with _v2 suffix (or increment if _v2 exists)
        base, ext = os.path.splitext(self.filename)
        version_match = re.search(r'_v(\d+)$', base)
        if version_match:
            current_version = int(version_match.group(1))
            base = base[:version_match.start()]
            self.new_filename = f"{base}_v{current_version + 1}{ext}"
        else:
            self.new_filename = f"{base}_v2{ext}"
        logger = get_file_ops_logger(self.projects_root)
        logger.info(f"DUPLICATE RENAME | {self.filename} -> {self.new_filename}")
        self.accept()

    def on_replace(self):
        self.result_action = 'replace'
        self.replace_target = self.duplicate_locations[0]
        logger = get_file_ops_logger(self.projects_root)
        logger.info(
            f"DUPLICATE REPLACE | {self.filename} | "
            f"Superseding: {self.duplicate_locations[0]}"
        )
        self.accept()


class DifferentLocationDuplicateDialog(QDialog):
    """Dialog shown when a duplicate exists at a different location than the filing target."""

    def __init__(self, parent, filename, existing_path, new_destination,
                 projects_root):
        super().__init__(parent)
        self.filename = filename
        self.existing_path = existing_path
        self.new_destination = new_destination
        self.projects_root = projects_root
        self.result_action = None
        self.replace_target = None
        self.setWindowTitle("File Exists at Different Location")
        self.setModal(True)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Warning message
        warning_label = QLabel(f"File '{self.filename}' already exists at a different location:")
        warning_label.setStyleSheet(f"color: {COLORS['warning']}; font-size: 14px; font-weight: bold;")
        warning_label.setWordWrap(True)
        layout.addWidget(warning_label)

        # Show existing file details
        from pathlib import Path
        existing = Path(self.existing_path)
        try:
            if existing.exists():
                stat = existing.stat()
                size_mb = stat.st_size / (1024 * 1024)
                from datetime import datetime
                modified = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
                existing_text = (
                    f"  Location: {self.existing_path}\n"
                    f"  Size: {size_mb:.1f} MB\n"
                    f"  Modified: {modified}"
                )
            else:
                existing_text = f"  Location: {self.existing_path}"
        except Exception:
            existing_text = f"  Location: {self.existing_path}"

        existing_label = QLabel(existing_text)
        existing_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 12px;")
        existing_label.setWordWrap(True)
        layout.addWidget(existing_label)

        # Show target destination
        dest_label = QLabel(f"\nYou are filing to:\n  {self.new_destination}")
        dest_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 12px;")
        dest_label.setWordWrap(True)
        layout.addWidget(dest_label)

        info_label = QLabel("These are different locations. Choose action:")
        info_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        layout.addWidget(info_label)

        # Options
        existing_parent_name = existing.parent.name

        btn_skip = QPushButton("a) Skip - don't file anywhere")
        btn_skip.setStyleSheet(self._button_style())
        btn_skip.clicked.connect(self.on_skip)
        layout.addWidget(btn_skip)

        dest_name = Path(self.new_destination).name
        btn_file_new = QPushButton(
            f"b) File to {dest_name} - keep both files in different locations"
        )
        btn_file_new.setStyleSheet(self._button_style())
        btn_file_new.setDefault(True)
        btn_file_new.clicked.connect(self.on_file_new_location)
        layout.addWidget(btn_file_new)

        btn_replace = QPushButton(
            f"c) Replace {existing_parent_name} version - "
            f"moves old to {existing_parent_name}/Superseded, files new to {dest_name}"
        )
        btn_replace.setStyleSheet(self._button_style())
        btn_replace.clicked.connect(self.on_replace_existing)
        layout.addWidget(btn_replace)

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
        logger = get_file_ops_logger(self.projects_root)
        logger.info(
            f"DUPLICATE SKIP | {self.filename} | "
            f"Existing at: {self.existing_path}"
        )
        self.accept()

    def on_file_new_location(self):
        self.result_action = 'proceed'
        logger = get_file_ops_logger(self.projects_root)
        logger.info(
            f"DUPLICATE KEEP BOTH | {self.filename} | "
            f"Existing: {self.existing_path}, New: {self.new_destination}"
        )
        self.accept()

    def on_replace_existing(self):
        self.result_action = 'replace'
        self.replace_target = self.existing_path
        logger = get_file_ops_logger(self.projects_root)
        logger.info(
            f"DUPLICATE REPLACE DIFFERENT | {self.filename} | "
            f"Superseding: {self.existing_path}, Filing to: {self.new_destination}"
        )
        self.accept()
