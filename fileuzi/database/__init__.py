"""Database module for FileUzi."""

from .connection import (
    get_database_path,
    get_database_backup_path,
    check_database_integrity,
    backup_database,
    init_database,
    check_database_exists,
    verify_database_schema,
)
from .email_records import (
    generate_email_hash,
    check_duplicate_email,
    update_filed_also,
    insert_email_record,
)
from .contacts import (
    get_contacts_from_database,
    get_contact_for_sender,
)

__all__ = [
    'get_database_path',
    'get_database_backup_path',
    'check_database_integrity',
    'backup_database',
    'init_database',
    'check_database_exists',
    'verify_database_schema',
    'generate_email_hash',
    'check_duplicate_email',
    'update_filed_also',
    'insert_email_record',
    'get_contacts_from_database',
    'get_contact_for_sender',
]
