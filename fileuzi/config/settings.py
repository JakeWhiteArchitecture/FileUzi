"""
FileUzi Configuration Settings.

All configurable constants and settings for the filing widget.
"""

# ============================================================================
# USER CONFIGURATION - Adjust these settings as needed
# ============================================================================

# Root folder containing all project folders
PROJECTS_ROOT = "/home/jake/TEST SERVER ENVIRONMENT/JWA_PROJECTS"

# Email address(es) to detect IN/OUT direction
# If email is FROM this address = OUT (export), TO this address = IN (import)
MY_EMAIL_ADDRESSES = [
    "jw@jakewhitearchitecture.com",
    # Add more email addresses as needed
]

# Minimum attachment size to auto-select (bytes) - smaller files are likely signatures
MIN_ATTACHMENT_SIZE = 3 * 1024  # 3KB

# Minimum embedded image size for extraction (bytes) - filters out logos, icons, signatures
MIN_EMBEDDED_IMAGE_SIZE = 20 * 1024  # 20KB

# Domain suffixes to strip when extracting business name
DOMAIN_SUFFIXES = [
    '.com', '.co.uk', '.org', '.net', '.io', '.co',
    '.uk', '.org.uk', '.gov.uk', '.ac.uk'
]

# ============================================================================
# UI COLORS - Matching the main app theme
# ============================================================================

COLORS = {
    'primary': '#2563eb',
    'success': '#10b981',
    'warning': '#f59e0b',
    'danger': '#ef4444',
    'bg': '#f8fafc',
    'surface': '#ffffff',
    'border': '#e2e8f0',
    'text': '#0f172a',
    'text_secondary': '#64748b',
}

# ============================================================================
# LAYOUT CONSTANTS
# ============================================================================

# Secondary filing column width to align with buttons
SECONDARY_FILING_WIDTH = 280

# Maximum number of chips per attachment
MAX_CHIPS = 3

# Truncate chip text longer than this with ellipsis
MAX_CHIP_TEXT_LENGTH = 15

# Shorter truncation for header chips
MAX_HEADER_CHIP_LENGTH = 8

# ============================================================================
# FILE AND DATABASE CONSTANTS
# ============================================================================

# Special folder name for filing widget tools/database
FILING_WIDGET_TOOLS_FOLDER = '*FILING-WIDGET-TOOLS*'

# Database filenames
DATABASE_FILENAME = 'filing_widget.db'
DATABASE_BACKUP_FILENAME = 'filing_widget_backup.db'

# Configuration filenames
FILING_RULES_FILENAME = 'filing_rules.csv'
PROJECT_MAPPING_FILENAME = 'custom_project_number_mapping.csv'
OPERATIONS_LOG_FILENAME = 'filing_operations.log'

# ============================================================================
# SAFETY LIMITS
# ============================================================================

# Circuit breaker threshold - maximum file operations per "File Now" action
# Base limit - will be scaled by file count
CIRCUIT_BREAKER_LIMIT = 20

# ============================================================================
# EMAIL PARSING
# ============================================================================

# Sign-off patterns for email body parsing (order matters - longer first)
SIGN_OFF_PATTERNS = [
    'kind regards',
    'yours sincerely',
    'yours faithfully',
    'best wishes',
    'best regards',
    'warm regards',
    'with thanks',
    'many thanks',
    'cheers',
    'regards',
    'thanks',
]

# ============================================================================
# DATABASE SCHEMA
# ============================================================================

DATABASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS emails (
    message_id      TEXT PRIMARY KEY,
    hash_fallback   TEXT,

    sender_address  TEXT NOT NULL,
    sender_name     TEXT,
    recipient_to    TEXT,
    recipient_cc    TEXT,
    subject         TEXT NOT NULL,
    date_sent       TEXT NOT NULL,

    body_clean      TEXT,
    sign_off_type   TEXT,

    is_inbound      INTEGER DEFAULT 1,

    filed_to        TEXT NOT NULL,
    filed_also      TEXT,
    filed_at        TEXT DEFAULT (datetime('now')),
    tags            TEXT,

    has_attachments  INTEGER DEFAULT 0,
    attachment_names TEXT,
    submission_type  TEXT,

    source_path     TEXT,
    created_at      TEXT DEFAULT (datetime('now')),

    -- User-entered contact name (may differ from email sender)
    contact_name    TEXT,
    -- Job number for filtering contacts by project
    job_number      TEXT
);

CREATE INDEX IF NOT EXISTS idx_message_id ON emails(message_id);
CREATE INDEX IF NOT EXISTS idx_hash_fallback ON emails(hash_fallback);
CREATE INDEX IF NOT EXISTS idx_filed_to ON emails(filed_to);
CREATE INDEX IF NOT EXISTS idx_submission_type ON emails(submission_type);
CREATE INDEX IF NOT EXISTS idx_job_number ON emails(job_number);
CREATE INDEX IF NOT EXISTS idx_sender ON emails(sender_address);
CREATE INDEX IF NOT EXISTS idx_date_sent ON emails(date_sent);
"""

# ============================================================================
# DRAWING MANAGEMENT
# ============================================================================

# Stage prefix hierarchy for new naming system (lower index = older/lower priority)
STAGE_HIERARCHY = ['F', 'PL', 'P', 'W', 'C']

# ============================================================================
# FILING RULE PARAMETERS (moved from module-level constants)
# ----------------------------------------------------------------------------
# The dictionaries below expose every value that used to be hard-coded
# throughout the service modules. They are read at runtime so the Settings
# panel (fileuzi/ui/settings_panel.py) can edit them without code changes.
# ============================================================================

# PDF extraction rules -------------------------------------------------------
PDF_EXTRACTION_RULES = {
    'min_line_length': 5,
    'char_limit_first_page': 40,
    'min_title_length': 5,
    'skip_page_footer_pattern': r'^page\s+\d+(\s+of\s+\d+)?$',
    'skip_numbers_only_pattern': r'^[\d\s.,\-/]+$',
    'date_patterns': [
        r'^\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}$',
        r'^\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2}$',
        r'^(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s+\d{4}$',
        r'^\d{1,2}\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}$',
    ],
    'junk_title_patterns': [
        r'^untitled(\s+document)?$',
        r'^document\s*\d*$',
        r'^microsoft\s+word\s*[-–]\s*',
        r'^microsoft\s+excel\s*[-–]\s*',
        r'^microsoft\s+powerpoint\s*[-–]\s*',
        r'^adobe\s+(acrobat|reader)',
        r'^new\s+document',
        r'^temp\d*$',
        r'^file\d*$',
    ],
}

# Job number pattern rules ---------------------------------------------------
JOB_NUMBER_PATTERNS = {
    'digit_range_min': 4,
    'digit_range_max': 5,
    'folder_format_dash': r'^(\d{4,5})\s*[-–]\s*(.+)$',
    'folder_format_underscore': r'^(\d{4,5})_(.+)$',
    'filename_prefix_underscore': r'^(\d{4,5})_',
    'filename_prefix_dash': r'^(\d{4,5})\s*[-–]\s*',
    'subject_prefix_pattern': r'^(\d{4,5})\s*[-–]?\s*',
    'subject_anywhere_pattern': r'\b(\d{4,5})\b',
    'custom_prefix_separator_class': r'[\s_\-]',
}

# Drawing number pattern rules ----------------------------------------------
# {prefix} placeholder is replaced at runtime with an escaped job/custom prefix.
# {stages} placeholder is replaced at runtime with STAGE_HIERARCHY joined by |.
DRAWING_NUMBER_PATTERNS = {
    'old_format_min_digits': 2,
    'old_format_max_digits': 3,
    'new_format_pattern': r'^{prefix}_(\d{{2,3}})[\s_]',
    'old_format_pattern': r'^{prefix}\s*[-–]\s*(\d{{2,3}})[\s\-–_]',
    'old_delimiter_pattern': r'\s+[-–]\s+',
    'old_drawing_number_pattern': r'^(\d{2,3})([A-Z])?$',
    'revision_pattern': r'^({stages})(\d{{2}})$',
}

# Project mapping CSV column keywords ---------------------------------------
PROJECT_MAPPING_COLUMNS = {
    'their_project_number_primary': ['custom', 'client', 'external'],
    'their_project_number_fallback': ['reference', 'ref', 'project no', 'project number'],
    'our_job_number_primary': ['local', 'jwa', 'internal'],
    'our_job_number_fallback': ['job no', 'job number', 'job'],
}

# Filing rules engine parameters --------------------------------------------
FILING_RULES_ENGINE = {
    'pause_trigger_value': 'yes',
    'keyword_separator_pattern': '[|,]',
    'default_chip_color': '#64748b',
    'fuzzy_threshold': 0.85,
    'min_word_length_filename': 3,
    'min_keyword_length': 2,
    'min_multiword_component_length': 2,
    'confidence_long_word_threshold': 4,
    'confidence_long_word_score': 1.0,
    'confidence_short_word_score': 0.9,
    'min_acronym_length': 3,
    'min_fuzzy_keyword_length': 5,
    'max_fuzzy_char_difference': 3,
    'descriptor_match_bonus': 0.05,
}

# Email parsing rules --------------------------------------------------------
EMAIL_PARSING_RULES = {
    'direction_fallback': 'IN',
    'subject_prefix_pattern': r'^(RE|FW|Fwd):\s*',
    'generic_email_domains': [
        'gmail',
        'googlemail',
        'yahoo',
        'hotmail',
        'outlook',
        'icloud',
        'aol',
        'mail',
        'email',
        'live',
        'msn',
        'btinternet',
        'sky',
        'virginmedia',
        'protonmail',
        'zoho',
        'ymail',
        'rocketmail',
        'fastmail',
        'tutanota',
        'gmx',
        'web',
        'me',
        'mac',
        'pm',
        'proton',
    ],
}

# Attachment filtering rules -------------------------------------------------
ATTACHMENT_FILTERING = {
    'image_extensions': ['.png', '.jpg', '.jpeg', '.gif', '.bmp'],
    'excluded_contact_names': ['sender', 'recipient'],
    'embedded_image_patterns': {
        'simple_image': r'^image\d+$',
        'timestamp': r'^\d{10,}$',
        'hash': r'^[a-f0-9\-]{20,}$',
    },
}

# Contact management rules --------------------------------------------------
CONTACT_MANAGEMENT = {
    'fuzzy_match_threshold': 0.6,
    'folder_name_contact_index': 3,
    'min_contact_name_length': 1,
    'imports_exports_keywords': ['IMPORT', 'EXPORT'],
}

# Folder keywords -----------------------------------------------------------
FOLDER_KEYWORDS = {
    'current_drawings': ['CURRENT', 'DRAWING'],
    'imports_exports': ['IMPORT', 'EXPORT'],
}

# Operation limits ----------------------------------------------------------
OPERATION_LIMITS = {
    'max_email_attachment_size': 26214400,
    'max_command_line_length': 30000,
    'email_signature_folder': '*EMAIL_SIGNATURE*',
    'email_signature_filename': 'email_signature.html',
    'circuit_breaker_overhead': 2,
}


# ============================================================================
# RUNTIME HELPERS - compile dynamic regex fragments from the dicts above
# ============================================================================

def build_drawing_revision_pattern(stage_hierarchy=None):
    """Return the revision regex with STAGE_HIERARCHY baked in (case-insensitive)."""
    stages = stage_hierarchy if stage_hierarchy is not None else STAGE_HIERARCHY
    stages_alt = '|'.join(stages)
    return DRAWING_NUMBER_PATTERNS['revision_pattern'].format(stages=stages_alt)


def build_drawing_prefix_pattern(prefix, new_format=True):
    """Return the drawing-match regex with an escaped prefix injected."""
    import re as _re
    escaped = _re.escape(prefix)
    template_key = 'new_format_pattern' if new_format else 'old_format_pattern'
    return DRAWING_NUMBER_PATTERNS[template_key].format(prefix=escaped)
