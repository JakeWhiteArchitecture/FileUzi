"""Services module for FileUzi."""

from .email_parser import (
    extract_email_body,
    extract_email_html_body,
    parse_body_with_signoff,
    parse_eml_file,
    is_my_email,
    detect_email_direction,
    extract_embedded_images,
    extract_business_from_domain,
    get_sender_name_and_business,
)

from .job_detector import (
    scan_projects_folder,
    parse_folder_name,
    extract_job_number_from_filename,
    find_job_number_from_path,
    is_embedded_image,
    detect_project_from_subject,
)

from .filing_rules import (
    get_filing_rules_path,
    get_project_mapping_path,
    load_project_mapping,
    apply_project_mapping,
    load_filing_rules,
    match_filing_rules,
    match_filing_rules_cascade,
)

from .drawing_manager import (
    is_drawing_pdf,
    parse_drawing_filename_new,
    parse_drawing_filename_old,
    parse_drawing_filename,
    compare_drawing_revisions,
    find_matching_drawings,
    supersede_drawings,
    is_current_drawings_folder,
)

from .pdf_generator import (
    is_junk_pdf_line,
    is_valid_pdf_title,
    extract_pdf_metadata_title,
    extract_pdf_first_content,
    convert_image_to_png,
    clean_subject_for_filename,
    generate_email_pdf,
    generate_screenshot_filenames,
    check_unique_pdf_filename,
    should_capture_outbound_email,
    process_outbound_email_capture,
)

from .duplicate_scanner import scan_for_file_duplicates

from .filing_operations import replace_with_supersede

from .contact_utils import (
    parse_import_export_folder,
    find_previous_contacts,
    fuzzy_match_contact,
)

from .email_composer import (
    detect_os_info,
    EmailClientDetector,
    generate_email_subject,
    extract_first_name,
    generate_email_body,
    load_email_signature,
    detect_email_clients,
    save_email_client_preference,
    load_email_client_preference,
    get_email_client_path,
    launch_email_compose,
    detect_superseding_candidates,
)

__all__ = [
    # Email parser
    'extract_email_body',
    'extract_email_html_body',
    'parse_body_with_signoff',
    'parse_eml_file',
    'is_my_email',
    'detect_email_direction',
    'extract_embedded_images',
    'extract_business_from_domain',
    'get_sender_name_and_business',
    # Job detector
    'scan_projects_folder',
    'parse_folder_name',
    'extract_job_number_from_filename',
    'find_job_number_from_path',
    'is_embedded_image',
    'detect_project_from_subject',
    # Filing rules
    'get_filing_rules_path',
    'get_project_mapping_path',
    'load_project_mapping',
    'apply_project_mapping',
    'load_filing_rules',
    'match_filing_rules',
    'match_filing_rules_cascade',
    # Drawing manager
    'is_drawing_pdf',
    'parse_drawing_filename_new',
    'parse_drawing_filename_old',
    'parse_drawing_filename',
    'compare_drawing_revisions',
    'find_matching_drawings',
    'supersede_drawings',
    'is_current_drawings_folder',
    # PDF generator
    'is_junk_pdf_line',
    'is_valid_pdf_title',
    'extract_pdf_metadata_title',
    'extract_pdf_first_content',
    'convert_image_to_png',
    'clean_subject_for_filename',
    'generate_email_pdf',
    'generate_screenshot_filenames',
    'check_unique_pdf_filename',
    'should_capture_outbound_email',
    'process_outbound_email_capture',
    # Duplicate scanner
    'scan_for_file_duplicates',
    # Filing operations
    'replace_with_supersede',
    # Contact utils
    'parse_import_export_folder',
    'find_previous_contacts',
    'fuzzy_match_contact',
    # Email composer
    'detect_os_info',
    'EmailClientDetector',
    'generate_email_subject',
    'extract_first_name',
    'generate_email_body',
    'load_email_signature',
    'detect_email_clients',
    'save_email_client_preference',
    'load_email_client_preference',
    'get_email_client_path',
    'launch_email_compose',
    'detect_superseding_candidates',
]
