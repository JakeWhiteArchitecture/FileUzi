"""
Email parsing functions for FileUzi.
"""

import re
import email
from email import policy
from email.utils import parsedate_to_datetime, parseaddr
from datetime import datetime

from fileuzi.config import MY_EMAIL_ADDRESSES, SIGN_OFF_PATTERNS, DOMAIN_SUFFIXES
from fileuzi.utils import HTMLTextExtractor


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
        line_stripped = line.strip()
        line_lower = line_stripped.lower()

        # Check for sign-off patterns
        for pattern in SIGN_OFF_PATTERNS:
            if line_lower.startswith(pattern) or line_lower == pattern:
                # Capture the actual text as it appeared in the email (case-preserving)
                sign_off_type = line_stripped[:len(pattern)]
                # Return everything before this line
                body_clean = '\n'.join(body_lines).strip()
                return (body_clean, sign_off_type)

        body_lines.append(line)

    # No sign-off found
    return (body_text.strip(), None)


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


def extract_embedded_images(msg, min_size=None):
    """
    Extract embedded images from an email message.

    Only extracts images that exceed the minimum size threshold.
    Filters out images from quoted reply sections.

    Args:
        msg: email.message.Message object
        min_size: Minimum image size in bytes (default from config)

    Returns:
        list of dicts: [{content_id, data, content_type, size}, ...]
    """
    from fileuzi.config import MIN_EMBEDDED_IMAGE_SIZE
    if min_size is None:
        min_size = MIN_EMBEDDED_IMAGE_SIZE

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


def get_sender_name_and_business(email_data, direction):
    """
    Extract sender name and business for folder naming.

    Args:
        email_data: Parsed email data dict
        direction: 'IN' or 'OUT'

    Returns:
        tuple: (contact_name, business_name) - either may be None
    """
    if direction == 'OUT':
        # For outbound, we want the recipient's info
        addr_field = email_data.get('to', '')
    else:
        # For inbound, we want the sender's info
        addr_field = email_data.get('from', '')

    # Parse the address to get name and email
    name, email_addr = parseaddr(addr_field)

    # Clean up the name
    if name:
        # Remove quotes if present
        name = name.strip('"\'')

    # Extract business from domain
    business = extract_business_from_domain(email_addr)

    return (name if name else None, business)
