"""
PDF generation and extraction functions for FileUzi.
"""

import os
import re
import base64
from io import BytesIO
from pathlib import Path
from datetime import datetime

from fileuzi.utils import get_file_ops_logger, safe_write_attachment

# Optional imports
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

HAS_PDF_RENDERER = HAS_WEASYPRINT or HAS_XHTML2PDF

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    try:
        from PyPDF2 import PdfReader
        HAS_PYPDF = True
    except ImportError:
        HAS_PYPDF = False


def is_junk_pdf_line(line):
    """
    Check if a line should be skipped when extracting PDF content.
    """
    line = line.strip()

    if len(line) < 5:
        return True

    if re.match(r'^page\s+\d+(\s+of\s+\d+)?$', line, re.IGNORECASE):
        return True

    if re.match(r'^[\d\s.,\-/]+$', line):
        return True

    date_patterns = [
        r'^\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}$',
        r'^\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2}$',
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
    """
    if not title or not title.strip():
        return False

    title = title.strip()

    if len(title) < 5:
        return False

    filename_base = filename.rsplit('.', 1)[0] if '.' in filename else filename
    if title.lower() == filename.lower() or title.lower() == filename_base.lower():
        return False

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
    """
    if not HAS_PYPDF:
        return None

    try:
        reader = PdfReader(BytesIO(pdf_data))
        if len(reader.pages) == 0:
            return None

        page = reader.pages[0]
        text = page.extract_text()
        if not text:
            return None

        lines = text.split('\n')
        meaningful_content = []
        total_chars = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if is_junk_pdf_line(line):
                continue

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


def convert_image_to_png(image_data):
    """
    Convert image data to PNG format.
    """
    if not HAS_PIL:
        return image_data

    try:
        img = Image.open(BytesIO(image_data))
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
    """
    if not subject:
        return 'untitled'

    cleaned = subject.strip()

    if ' - ' in cleaned:
        parts = cleaned.split(' - ', 1)
        first_part = parts[0].strip()

        if first_part.startswith(job_number):
            cleaned = parts[1] if len(parts) > 1 else first_part
        elif re.match(rf'^{job_number}\s+\w+', first_part):
            cleaned = parts[1] if len(parts) > 1 else first_part

    cleaned = re.sub(rf'^{job_number}\s*[-:]?\s*', '', cleaned)
    cleaned = re.sub(r'[<>:"/\\|?*]', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    if not cleaned:
        return 'untitled'

    return cleaned


def generate_email_pdf(email_data, embedded_images, job_number, projects_root):
    """
    Generate a PDF rendering of the full email with embedded images.
    """
    import html as html_module
    from .email_parser import extract_email_html_body

    logger = get_file_ops_logger(projects_root)

    if not HAS_PDF_RENDERER:
        logger.warning("EMAIL PDF SKIP | No PDF renderer installed (weasyprint or xhtml2pdf)")
        return (None, None)

    email_date = email_data.get('date', datetime.now())
    date_str = email_date.strftime('%Y-%m-%d')
    subject = email_data.get('subject', 'untitled')
    cleaned_subject = clean_subject_for_filename(subject, job_number)
    filename = f"{job_number}_email_{date_str}_{cleaned_subject}.pdf"

    from_addr = html_module.escape(email_data.get('from', ''))
    to_addr = html_module.escape(email_data.get('to', ''))
    cc_addr = html_module.escape(email_data.get('cc', ''))
    subject_escaped = html_module.escape(subject)

    html_body = None
    raw_msg = email_data.get('_raw_message')
    if raw_msg:
        html_body = extract_email_html_body(raw_msg)

    image_map = {}
    for img in embedded_images:
        cid = img.get('content_id', '')
        if cid:
            b64_data = base64.b64encode(img['data']).decode('utf-8')
            mime_type = img.get('content_type', 'image/png')
            image_map[cid] = f"data:{mime_type};base64,{b64_data}"

    if html_body:
        body_content = html_body
        for cid, data_url in image_map.items():
            body_content = body_content.replace(f'cid:{cid}', data_url)
            body_content = body_content.replace(f'CID:{cid}', data_url)

        body_match = re.search(r'<body[^>]*>(.*?)</body>', body_content, re.DOTALL | re.IGNORECASE)
        if body_match:
            body_html = body_match.group(1)
        else:
            body_html = body_content
    else:
        body_text = email_data.get('body', '')
        body_html = html_module.escape(body_text).replace('\n', '<br>')

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
        if HAS_WEASYPRINT:
            html_obj = HTML(string=html_content)
            pdf_data = html_obj.write_pdf()
        elif HAS_XHTML2PDF:
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
    """
    dest_folder = Path(dest_folder)
    if not (dest_folder / filename).exists():
        return filename

    base, ext = os.path.splitext(filename)
    for letter in 'bcdefghijklmnopqrstuvwxyz':
        new_filename = f"{base}_{letter}{ext}"
        if not (dest_folder / new_filename).exists():
            return new_filename

    timestamp = datetime.now().strftime('%H%M%S')
    return f"{base}_{timestamp}{ext}"


def should_capture_outbound_email(email_data, embedded_images):
    """
    Determine if an outbound email should trigger screenshot/PDF capture.
    """
    from .email_parser import is_my_email

    from_addr = email_data.get('from', '')
    if not is_my_email(from_addr):
        return False

    return len(embedded_images) > 0


def process_outbound_email_capture(msg, email_data, job_number, dest_folder, projects_root,
                                    secondary_paths=None, keystage_folder=None):
    """
    Process an outbound email for screenshot extraction and PDF generation.
    """
    from .email_parser import extract_embedded_images

    logger = get_file_ops_logger(projects_root)
    result = {'screenshots': [], 'pdf_filename': None, 'success': True}

    embedded_images = extract_embedded_images(msg)

    if not should_capture_outbound_email(email_data, embedded_images):
        return result

    logger.info(f"OUTBOUND EMAIL CAPTURE | Found {len(embedded_images)} embedded image(s) > 20KB")

    email_date = email_data.get('date', datetime.now())
    all_destinations = [dest_folder]
    if secondary_paths:
        all_destinations.extend(secondary_paths)
    if keystage_folder:
        all_destinations.append(keystage_folder)

    screenshot_filenames = generate_screenshot_filenames(job_number, email_date, len(embedded_images))

    for i, img in enumerate(embedded_images):
        filename = screenshot_filenames[i]
        png_data = convert_image_to_png(img['data'])

        for dest in all_destinations:
            dest_path = Path(dest) / filename
            try:
                if safe_write_attachment(dest_path, png_data, projects_root, f"screenshot:{filename}"):
                    if dest == dest_folder:
                        result['screenshots'].append(filename)
                    logger.info(f"SCREENSHOT SAVED | {filename} -> {dest}")
            except Exception as e:
                logger.error(f"SCREENSHOT FAILED | {filename} -> {dest}: {e}")
                result['success'] = False

    pdf_data, pdf_filename = generate_email_pdf(email_data, embedded_images, job_number, projects_root)

    if pdf_data and pdf_filename:
        for dest in all_destinations:
            unique_filename = check_unique_pdf_filename(dest, pdf_filename)
            dest_path = Path(dest) / unique_filename

            try:
                if safe_write_attachment(dest_path, pdf_data, projects_root, f"email_pdf:{unique_filename}"):
                    if dest == dest_folder:
                        result['pdf_filename'] = unique_filename
                    logger.info(f"EMAIL PDF SAVED | {unique_filename} -> {dest}")
            except Exception as e:
                logger.error(f"EMAIL PDF FAILED | {unique_filename} -> {dest}: {e}")
                result['success'] = False

    return result
