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
