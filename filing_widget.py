#!/usr/bin/env python3
"""
Jaike_CRM Filing Widget - Standalone file import/export tool.

Drag files onto the widget to automatically file them into project folders.
Supports .eml files with automatic attachment extraction and direction detection.
"""
import sys
import os
import re
import argparse
from email.utils import parseaddr
from pathlib import Path
from datetime import datetime

# Optional imports for PDF generation capability check
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

HAS_PDF_RENDERER = HAS_WEASYPRINT or HAS_XHTML2PDF

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QRadioButton, QButtonGroup,
    QFrame, QMessageBox, QComboBox, QCheckBox,
    QScrollArea, QSizePolicy, QCompleter, QMenu, QDialog
)
from PyQt6.QtCore import Qt, QStringListModel, QEvent
from PyQt6.QtGui import QFont, QPixmap

# Import configuration from fileuzi package
from fileuzi.config import (
    PROJECTS_ROOT,
    MIN_ATTACHMENT_SIZE,
    MIN_EMBEDDED_IMAGE_SIZE,
    COLORS,
    SECONDARY_FILING_WIDTH,
    MAX_CHIPS,
    FILING_RULES_FILENAME,
)

# Import utilities from fileuzi package
from fileuzi.utils import (
    PathJailViolation,
    CircuitBreakerTripped,
    get_circuit_breaker,
    get_tools_folder_path,
    ensure_tools_folder,
    get_file_ops_logger,
    safe_copy,
    safe_write_attachment,
)

# Import database functions from fileuzi package
from fileuzi.database import (
    get_database_path,
    init_database,
    verify_database_schema,
    generate_email_hash,
    check_duplicate_email,
    update_filed_also,
    insert_email_record,
    get_contacts_from_database,
    get_contact_for_sender,
)

# Import services from fileuzi package
from fileuzi.services import (
    parse_eml_file,
    detect_email_direction,
    extract_embedded_images,
    get_sender_name_and_business,
    scan_projects_folder,
    parse_folder_name,
    extract_job_number_from_filename,
    find_job_number_from_path,
    is_embedded_image,
    detect_project_from_subject,
    load_project_mapping,
    load_filing_rules,
    match_filing_rules_cascade,
    is_drawing_pdf,
    supersede_drawings,
    is_current_drawings_folder,
    convert_image_to_png,
    clean_subject_for_filename,
    generate_email_pdf,
    generate_screenshot_filenames,
    process_outbound_email_capture,
    scan_for_file_duplicates,
    find_previous_contacts,
    fuzzy_match_contact,
)

# Import UI components from fileuzi package
from fileuzi.ui import (
    FlowLayout,
    ClickableWordLabel,
    FilingChip,
    AttachmentWidget,
    DropZone,
    DroppableFilesFrame,
    SuccessDialog,
    DatabaseMissingDialog,
    DuplicateEmailDialog,
    FileDuplicateDialog,
    DifferentLocationDuplicateDialog,
)

from fileuzi.services.filing_operations import replace_with_supersede
from fileuzi.services.email_composer import (
    generate_email_subject,
    generate_email_body,
    load_email_signature,
    get_email_client_path,
    launch_email_compose,
    detect_superseding_candidates,
)


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
        else:
            # Fallback styled text logo
            logo_label.setText("FU")
            logo_label.setFixedSize(48, 48)
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo_label.setStyleSheet(
                f"background-color: {COLORS['primary']}; color: #ffffff; "
                f"font-size: 20px; font-weight: bold; border-radius: 10px;"
            )
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
        # Uses DroppableFilesFrame to allow dropping additional files
        self.files_frame = DroppableFilesFrame(self)
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

        # Create Email toggle (only visible for non-.eml exports)
        self.create_email_toggle = QCheckBox("Create Email")
        self.create_email_toggle.setStyleSheet(f"""
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
        self.create_email_toggle.setChecked(False)
        self.create_email_toggle.setVisible(False)
        files_keystage_layout.addWidget(self.create_email_toggle)

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

        # Install event filter to handle Down arrow showing all completions
        self.contact_input.installEventFilter(self)

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

        # Connect Enter key to file documents (desc_input only - contact_input
        # is handled in eventFilter to avoid filing when selecting from autocomplete)
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

        # Normalize to uppercase and filter out invalid entries like 'sender'/'recipient'
        invalid_entries = {'sender', 'recipient'}
        normalized_contacts = set()
        for contact in contacts:
            upper_contact = contact.upper()
            if upper_contact.lower() not in invalid_entries:
                normalized_contacts.add(upper_contact)

        self.previous_contacts = sorted(list(normalized_contacts))

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
        self._update_create_email_visibility()
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

        # Hide Create Email toggle for .eml files
        self.create_email_toggle.setVisible(False)
        self.create_email_toggle.setChecked(False)

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
                # Drawings are assumed to be from Current Drawings (prevents re-filing there)
                att_widget = AttachmentWidget(
                    filename=filename,
                    size_str=size_str,
                    attachment_data=att,
                    parent_widget=self,
                    is_excluded=is_excluded,
                    matched_rules=matched_rules,
                    is_drawing=is_drawing,
                    from_current_drawings=is_drawing
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
        """Handle regular (non-email) files with secondary filing support.

        Supports multiple drag-and-drop batches - new files are appended to existing list.
        Detects files from Current Drawings folders and marks them to skip secondary filing
        back to Current Drawings (to avoid overwriting themselves).
        """
        # Get existing filenames to avoid duplicates when appending
        existing_filenames = {Path(fp).name for _, fp in self.file_widgets}

        # Try to detect job number from file path FIRST, before processing files
        # This ensures drawing detection uses the correct job number
        if files:
            detected_job = find_job_number_from_path(files[0], self.project_mapping)
            if detected_job:
                self.try_select_job(detected_job)
            elif self.last_job_number and not self.job_number:
                # No job in path, use last job number as fallback
                self.try_select_job(self.last_job_number, prompt_if_different=False)

        # Get job number for drawing detection (now should be set from path detection)
        job_for_drawing = self.job_number or self.last_job_number or ''

        # Track if any JWA drawings detected (in this batch or existing)
        has_drawings = any(w.is_drawing for w, _ in self.file_widgets)

        # Count new files added
        new_files_added = 0

        # Create AttachmentWidget for each file
        for file_path in files:
            src = Path(file_path)
            filename = src.name

            # Skip if this filename already exists in the list
            if filename in existing_filenames:
                continue

            # Get file size
            try:
                size_bytes = src.stat().st_size
                size_kb = size_bytes / 1024
                size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_bytes/1024/1024:.1f} MB"
            except:
                size_str = "? KB"

            # Check if this is a drawing PDF (project_mapping can identify
            # drawings by custom prefix even without a job number)
            is_drawing = is_drawing_pdf(filename, job_for_drawing, self.project_mapping)
            if is_drawing:
                has_drawings = True

            # Check if file is coming from a Current Drawings folder OR is a drawing
            # (drawings with custom prefixes like B-012 are assumed to be from Current Drawings)
            from_current_drawings = is_current_drawings_folder(src.parent) or is_drawing

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
                file_path=str(src),  # Store full path for copying
                from_current_drawings=from_current_drawings
            )

            self.files_container_layout.addWidget(file_widget)
            self.file_widgets.append((file_widget, str(src)))
            existing_filenames.add(filename)
            new_files_added += 1

        # Update header label with total count
        total_files = len(self.file_widgets)
        self.files_label.setText(f"Files ({total_files}):")

        # Show files frame, hide email frame
        self.files_frame.setVisible(True)
        self.email_frame.setVisible(False)
        self.drop_zone.setVisible(False)

        # Auto-switch to Export mode if JWA drawings detected
        if has_drawings:
            self.export_radio.setChecked(True)

        # Update Create Email toggle visibility
        self._update_create_email_visibility()

        self.update_preview()

    def auto_select_project_from_path(self, file_path):
        """Auto-select project if job number is detected in file path."""
        detected_job = find_job_number_from_path(file_path, self.project_mapping)

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

    def eventFilter(self, obj, event):
        """Handle events for contact input field."""
        if obj == self.contact_input and event.type() == QEvent.Type.KeyPress:
            from PyQt6.QtCore import Qt as QtCore_Qt
            key = event.key()

            # Down arrow: show all completions if popup not visible
            if key == QtCore_Qt.Key.Key_Down:
                if not self.contact_completer.popup().isVisible():
                    # Show all completions
                    self.contact_completer.setCompletionPrefix("")
                    self.contact_completer.complete()
                    return True

            # Enter key: file documents only if completer popup is NOT visible
            if key in (QtCore_Qt.Key.Key_Return, QtCore_Qt.Key.Key_Enter):
                if self.contact_completer.popup().isVisible():
                    # Let the completer handle the selection
                    return False
                else:
                    # No popup - proceed with filing
                    self.file_documents()
                    return True

        return super().eventFilter(obj, event)

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

        # Superseding confirmation: check BEFORE filing if any drawings will be superseded
        superseding_files = []
        if not self.email_data:
            for file_widget, file_path in self.file_widgets:
                if file_widget.isChecked():
                    secondary_dests = file_widget.get_secondary_destinations()
                    for rule in secondary_dests:
                        secondary_path = self._resolve_secondary_path(project_path, rule)
                        if secondary_path and is_current_drawings_folder(secondary_path):
                            candidates = detect_superseding_candidates(
                                file_path, secondary_path
                            )
                            if candidates:
                                superseding_files.extend(candidates)

        if superseding_files:
            msg = (
                f"The following {len(superseding_files)} drawing(s) will be "
                f"superseded and moved to Superseded/:\n\n"
            )
            for name in superseding_files:
                msg += f"  - {name}\n"
            msg += "\nDo you want to proceed?"

            reply = QMessageBox.question(
                self,
                "Superseding Confirmation",
                msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

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
            filed_paths = []  # Track actual destination paths for email attachments

            if self.email_data:
                # Save selected email attachments
                # (No duplicate check - email duplicate dialog already handles this)
                for att_widget, att in self.attachment_checkboxes:
                    if att_widget.isChecked():
                        # Skip PDF placeholder - it's handled separately below
                        if att.get('is_pdf_placeholder', False):
                            continue

                        filename = att['filename']

                        # Primary filing to IMPORTS-EXPORTS
                        dst = dest_folder / filename
                        if safe_write_attachment(dst, att['data'], self.projects_root, filename):
                            copied_count += 1
                            filed_paths.append(dst)

                        # Secondary filing to additional destinations
                        secondary_dests = att_widget.get_secondary_destinations()
                        for rule in secondary_dests:
                            secondary_path = self._resolve_secondary_path(project_path, rule)
                            if secondary_path:
                                sec_dst = secondary_path / filename
                                if safe_write_attachment(sec_dst, att['data'], self.projects_root, filename):
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
                        # Primary filing to IMPORTS-EXPORTS
                        # (No duplicate check - email duplicate dialog already handles this)
                        pdf_dst = dest_folder / pdf_filename
                        if safe_write_attachment(pdf_dst, pdf_data, self.projects_root, pdf_filename):
                            copied_count += 1

                        # Secondary filing from PDF placeholder widget settings
                        if self.pdf_placeholder_widget is not None:
                            secondary_dests = self.pdf_placeholder_widget.get_secondary_destinations()
                            for rule in secondary_dests:
                                secondary_path = self._resolve_secondary_path(project_path, rule)
                                if secondary_path:
                                    sec_dst = secondary_path / pdf_filename
                                    if safe_write_attachment(sec_dst, pdf_data, self.projects_root, pdf_filename):
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
                        action, final_filename, replace_target = self._check_file_duplicate(
                            project_path, filename, dest_folder
                        )

                        if action == 'skip':
                            continue  # Skip this file

                        if action == 'replace' and replace_target:
                            try:
                                superseded = replace_with_supersede(
                                    old_path=replace_target,
                                    project_root=self.projects_root,
                                    new_file_source=src,
                                )
                                if superseded:
                                    supersede_messages.append(
                                        f"Old version backed up to: {superseded}"
                                    )
                                copied_count += 1
                                filed_paths.append(replace_target)
                                continue
                            except (ValueError, OSError) as e:
                                QMessageBox.warning(
                                    self, "Replace Failed",
                                    f"Replace operation failed: {e}\n"
                                    f"Original file has been preserved."
                                )
                                continue

                        dst = dest_folder / final_filename

                        if src.is_file():
                            if safe_copy(src, dst, self.projects_root):
                                copied_count += 1
                                filed_paths.append(dst)

                            # Secondary filing to additional destinations
                            secondary_dests = file_widget.get_secondary_destinations()
                            for rule in secondary_dests:
                                secondary_path = self._resolve_secondary_path(project_path, rule)
                                if secondary_path:
                                    # Skip filing to Current Drawings if file came from there
                                    # (to avoid overwriting itself unnecessarily)
                                    if file_widget.from_current_drawings and is_current_drawings_folder(secondary_path):
                                        continue

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

            # Launch email composition if Create Email toggle is checked
            if (hasattr(self, 'create_email_toggle') and
                self.create_email_toggle.isVisible() and
                self.create_email_toggle.isChecked()):
                self._launch_email_after_filing(
                    filed_paths, project_path, contact, desc
                )

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
                'contact_name': contact.upper(),  # Normalize to uppercase for consistency
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
                'contact_name': contact.upper(),
                'job_number': self.job_number,
            }

            insert_email_record(self.db_path, file_record, self.projects_root)

        except Exception as e:
            # Don't fail the filing if database write fails - just log
            print(f"Warning: Failed to write file filing to database: {e}")

    def _check_file_duplicate(self, project_path, filename, destination_folder=None):
        """
        Check if a file with the same name exists anywhere in the project.

        Detects whether duplicates are in the same location or a different one
        and shows the appropriate dialog.

        Args:
            project_path: Path to the project folder
            filename: Name of the file to check
            destination_folder: Where the file is being filed to

        Returns:
            tuple: (action, new_filename, replace_target) where:
                   action is 'proceed', 'skip', 'rename', or 'replace'
                   new_filename is only set if action is 'rename'
                   replace_target is the Path to supersede if action is 'replace'
        """
        duplicates = scan_for_file_duplicates(project_path, filename)

        if not duplicates:
            return ('proceed', filename, None)

        # Determine if any duplicates are at a different location than destination
        if destination_folder:
            dest_folder = Path(destination_folder)
            same_location = [d for d in duplicates if Path(d).parent == dest_folder]
            diff_location = [d for d in duplicates if Path(d).parent != dest_folder]

            # If all duplicates are at different locations, just proceed
            # (email duplicate detection handles most cases, no need for dialog)
            if diff_location and not same_location:
                return ('proceed', filename, None)

        # Same-location or mixed: show standard dialog
        dialog = FileDuplicateDialog(
            self, filename, duplicates, self.projects_root,
            destination_folder=destination_folder
        )
        result = dialog.exec()

        if result != QDialog.DialogCode.Accepted:
            return ('skip', filename, None)

        if dialog.result_action == 'skip':
            return ('skip', filename, None)
        elif dialog.result_action == 'rename':
            return ('rename', dialog.new_filename, None)
        elif dialog.result_action == 'replace':
            return ('replace', filename, dialog.replace_target)

        return ('proceed', filename, None)

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

    def _update_create_email_visibility(self):
        """Show/hide Create Email toggle based on direction and file type."""
        is_export = self.export_radio.isChecked()
        is_regular_files = not self.email_data and bool(self.file_widgets)
        self.create_email_toggle.setVisible(is_export and is_regular_files)
        if not (is_export and is_regular_files):
            self.create_email_toggle.setChecked(False)

    def _launch_email_after_filing(self, filed_paths, project_path, contact, desc):
        """Launch email client with filed documents as attachments after filing.

        Args:
            filed_paths: List of Path objects to actually-filed documents
            project_path: Path to the project folder
            contact: Recipient name from UI
            desc: Description from UI
        """
        import logging
        log = logging.getLogger('fileuzi.services.email_composer')
        log.info("_launch_email_after_filing: %d filed paths, project=%s",
                 len(filed_paths), project_path)
        try:
            # Get email client path
            client_path = get_email_client_path(self.db_path)
            log.info("  client_path resolved to: %s", client_path)

            # Generate subject from project folder name and description
            project_folder_name = project_path.name
            subject = generate_email_subject(project_folder_name, desc)
            log.info("  subject: %s", subject)

            # Load email signature
            try:
                signature_html = load_email_signature(self.projects_root)
            except FileNotFoundError:
                signature_html = ""
                log.info("  No email signature file found, using empty")

            # Generate email body
            body_html = generate_email_body(contact, signature_html)

            # Use the actual filed paths (only files that exist)
            attachment_paths = [p for p in filed_paths if Path(p).is_file()]
            for p in attachment_paths:
                log.info("  attachment: %s", p)

            if not attachment_paths:
                log.warning("  No filed paths available — skipping email")
                return

            # Launch email client
            launch_email_compose(subject, attachment_paths, body_html, client_path)

        except FileNotFoundError as e:
            log.error("  FileNotFoundError: %s", e)
            QMessageBox.warning(
                self, "Email Client Not Found",
                str(e)
            )
        except ValueError as e:
            log.error("  ValueError: %s", e)
            QMessageBox.warning(
                self, "Email Error",
                str(e)
            )
        except RuntimeError as e:
            log.error("  RuntimeError: %s", e)
            QMessageBox.warning(
                self, "Email Error",
                str(e)
            )
        except Exception as e:
            log.error("  Unexpected error: %s", e, exc_info=True)
            QMessageBox.warning(
                self, "Email Error",
                f"Unexpected error launching email:\n\n{e}"
            )

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

        # Reset and hide Create Email toggle
        if hasattr(self, 'create_email_toggle'):
            self.create_email_toggle.setVisible(False)
            self.create_email_toggle.setChecked(False)
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
    import logging as _logging

    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Jaike_CRM Filing Widget')
    parser.add_argument(
        '--file', '-f',
        type=str,
        help='File to preload into the widget'
    )
    parser.add_argument(
        '--debug-email',
        action='store_true',
        help='Enable debug logging for email client detection and launch'
    )
    args, qt_args = parser.parse_known_args()

    # Set up logging
    if args.debug_email:
        _logging.basicConfig(
            level=_logging.DEBUG,
            format='%(asctime)s %(name)s %(levelname)s: %(message)s',
            datefmt='%H:%M:%S',
        )
        _logging.getLogger('fileuzi.services.email_composer').setLevel(_logging.DEBUG)
    else:
        # Default: email INFO to stderr so detection results are visible
        _logging.basicConfig(
            level=_logging.WARNING,
            format='%(name)s %(levelname)s: %(message)s',
        )
        _logging.getLogger('fileuzi.services.email_composer').setLevel(_logging.INFO)

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
