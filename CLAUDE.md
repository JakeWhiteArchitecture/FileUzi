# CLAUDE.md - AI Assistant Guide for FileUzi

## Project Overview

**FileUzi** is a PyQt6-based document filing widget designed for architectural practices. It streamlines the process of filing emails, attachments, and documents into structured project folders with features like automatic job number detection, drawing management, and duplicate handling.

**Repository:** JakeWhiteArchitecture/FileUzi
**License:** MIT (2024 Jake White & Claude AI)
**Tech Stack:** Python 3.9+, PyQt6
**Status:** Early development stage

---

## Quick Reference

### Common Commands

```bash
# Git operations
git status                    # Check current state
git add <files>               # Stage changes
git commit -m "message"       # Commit with message
git push -u origin <branch>   # Push to remote

# Python operations (when set up)
python -m venv venv           # Create virtual environment
source venv/bin/activate      # Activate venv (Linux/Mac)
pip install -r requirements.txt  # Install dependencies
python main.py                # Run the application

# Branch naming convention
# Development branches should follow: claude/<description>-<session-id>
```

### Key Paths

| Path | Description |
|------|-------------|
| `/` | Repository root |
| `/README.md` | Full project documentation with features and workflows |
| `/LICENSE` | MIT License file |
| `/CLAUDE.md` | This file - AI assistant guide |
| `/src/` | [Planned] Source code directory |
| `/tests/` | [Planned] Test files |

---

## Codebase Structure

```
FileUzi/
├── LICENSE                  # MIT License (2024 Jake White & Claude AI)
├── README.md                # Full project documentation
├── CLAUDE.md                # AI assistant guidelines (this file)
├── requirements.txt         # [Planned] Python dependencies
├── main.py                  # [Planned] Application entry point
├── src/                     # [Planned] Source code directory
│   ├── __init__.py
│   ├── widgets/             # PyQt6 UI widgets
│   │   ├── __init__.py
│   │   └── filing_widget.py # Main filing widget
│   ├── services/            # Business logic
│   │   ├── __init__.py
│   │   ├── email_parser.py  # Email parsing (.eml files)
│   │   ├── job_detector.py  # Job number detection
│   │   ├── file_manager.py  # File operations
│   │   └── pdf_generator.py # Email to PDF conversion
│   ├── utils/               # Utility functions
│   │   ├── __init__.py
│   │   └── helpers.py
│   └── config/              # Configuration
│       ├── __init__.py
│       └── settings.py      # Email addresses, paths, etc.
├── tests/                   # [Planned] Test files
│   ├── __init__.py
│   ├── test_email_parser.py
│   ├── test_job_detector.py
│   └── test_file_manager.py
├── data/                    # [Planned] Data files
│   └── project_mapping.csv  # Custom project reference mappings
└── docs/                    # [Planned] Additional documentation
```

> **Note:** Directories marked [Planned] do not exist yet. Create them as needed following the structure above.

---

## Development Guidelines

### Code Conventions

When adding code to this project, follow these conventions:

1. **File Naming**
   - Use snake_case for Python files: `email_parser.py`, `file_manager.py`
   - Use snake_case for functions and variables: `parse_email()`, `job_number`
   - Use PascalCase for classes: `FilingWidget`, `EmailParser`
   - Test files should mirror source: `test_email_parser.py`

2. **Code Style**
   - Follow PEP 8 style guidelines
   - Use type hints for function signatures
   - Use meaningful, descriptive variable and function names
   - Keep functions focused and single-purpose
   - Add docstrings for public functions and classes
   - Add comments only where logic isn't self-evident

3. **Architecture Principles**
   - Separate concerns: UI (widgets), business logic (services), utilities
   - Keep widgets focused on display and user interaction
   - Put business logic in services, not in UI code
   - Use signals/slots for PyQt6 communication patterns
   - Follow SOLID principles

### Git Workflow

1. **Branch Naming**
   - Feature branches: `feature/<description>`
   - Bug fixes: `fix/<description>`
   - AI assistant branches: `claude/<description>-<session-id>`

2. **Commit Messages**
   - Use imperative mood: "Add feature" not "Added feature"
   - Keep first line under 72 characters
   - Reference issues when applicable: "Fix #123"

3. **Push Protocol**
   - Always use: `git push -u origin <branch-name>`
   - On network failures, retry up to 4 times with exponential backoff (2s, 4s, 8s, 16s)

---

## Domain Context

### What is FileUzi?

FileUzi is designed for **architectural practices** to streamline document filing:

- **Email Processing**: Parse .eml files, extract metadata, detect IN/OUT direction
- **Attachment Management**: List attachments with size filtering (skip small signature images)
- **Job Number Detection**: Auto-detect from filenames, subjects, or custom mappings
- **Drawing Management**: File to Current Drawings, auto-supersede old revisions
- **Email to PDF**: Generate PDFs from emails with embedded images preserved
- **Duplicate Handling**: Project-wide scanning with skip/rename/overwrite options
- **Secondary Filing**: File to multiple destinations with rule-based routing

### Target Users

- Architects and architectural firms
- Project managers handling architectural documentation
- Administrative staff managing project files

### Key Terminology

| Term | Definition |
|------|------------|
| Filing Widget | The main PyQt6 UI component for document organization |
| Job Number | Project identifier (e.g., `2505`) used for folder navigation |
| Project Mapping | CSV file mapping client references to internal job numbers |
| Direction | IN (received) or OUT (sent) email classification |
| Current Drawings | Folder containing latest drawing revisions |
| Superseded | Folder for older drawing revisions |
| Import/Export Folder | Dated folders for incoming/outgoing documents |
| Secondary Destination | Additional filing location beyond primary destination |

### Key Workflows

1. **Filing Incoming Email**: Drag .eml → auto-detect job → select attachments → file to import folder
2. **Filing Outbound Email**: Drag .eml → detect OUT direction → optionally generate PDF → file to export folder
3. **Filing Drawings**: Drag drawing → add Current Drawings as secondary → old revision auto-superseded
4. **Custom Project Mapping**: Configure CSV → drag file with client reference → resolves to job number

---

## AI Assistant Instructions

### When Working on This Codebase

1. **Before Making Changes**
   - Read existing code before modifying it
   - Understand the context and purpose of files
   - Check for related tests and documentation
   - Review README.md for feature specifications

2. **Making Changes**
   - Keep changes focused and minimal
   - Don't over-engineer solutions
   - Avoid introducing security vulnerabilities
   - Follow existing patterns and conventions
   - Use PyQt6 idioms (signals/slots, etc.)

3. **After Making Changes**
   - Verify changes work as expected
   - Update relevant documentation
   - Create clear, descriptive commit messages

### Things to Avoid

- Don't add features beyond what was requested
- Don't refactor unrelated code
- Don't create unnecessary abstractions
- Don't add excessive comments or documentation
- Don't guess file contents - always read first

### Security Considerations

- Never commit sensitive data (API keys, credentials, email addresses)
- Validate file paths to prevent directory traversal
- Be cautious with file system operations (use safe write patterns)
- Sanitize filenames before writing
- Follow OWASP guidelines

---

## Testing Guidelines

When tests are implemented, follow these practices:

1. **Test Structure**
   - Place tests in `/tests/` directory mirroring `/src/`
   - Name test files with `test_` prefix: `test_email_parser.py`
   - Use pytest as the testing framework
   - Group related tests in classes or with descriptive function names

2. **Test Coverage**
   - Write tests for new features and bug fixes
   - Cover edge cases and error conditions
   - Mock file system operations where appropriate
   - Test PyQt6 widgets with pytest-qt

3. **Running Tests**
   ```bash
   # Run all tests
   pytest

   # Run specific test file
   pytest tests/test_email_parser.py

   # Run with coverage
   pytest --cov=src
   ```

---

## Dependencies

### Required
- Python 3.9+
- PyQt6

### Optional (for PDF generation)
- `weasyprint` (preferred)
- `xhtml2pdf` (fallback)

### Development
- pytest
- pytest-qt
- pytest-cov

---

## Build and Deployment

> **Note:** Build and deployment workflows are not yet configured. This section will be updated as the project evolves.

### Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Run application
python main.py
```

### Packaging (Planned)

```bash
# Build standalone executable with PyInstaller
pyinstaller --onefile --windowed main.py
```

---

## Configuration

### Email Addresses
Configure in `src/config/settings.py`:
```python
MY_EMAIL_ADDRESSES = [
    "you@yourcompany.com",
]
```

### Project Mapping
Create `data/project_mapping.csv`:
```csv
custom_reference,local_job
CLIENT-001,2505
B-013,2507
```

### Minimum Attachment Size
Default 3KB threshold to skip signature images.

---

## Contributing

1. Create a feature branch from main
2. Make focused, incremental changes
3. Write or update tests as needed
4. Ensure all tests pass
5. Submit a pull request with clear description

---

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| Git push fails with 403 | Ensure branch name follows correct pattern |
| Network errors on push | Retry with exponential backoff (2s, 4s, 8s, 16s) |
| PyQt6 import error | Ensure virtual environment is activated |
| PDF generation fails | Install weasyprint or xhtml2pdf |

---

## Changelog

### 2026-02-03
- Initial repository creation
- Added README.md with full project documentation
- Added LICENSE (MIT)
- Created CLAUDE.md for AI assistant guidance

---

## Updating This File

This CLAUDE.md should be updated when:
- New directories or files are added to the structure
- New conventions or patterns are established
- Build/test workflows are implemented
- New dependencies are introduced
- Domain terminology changes

Keep this file accurate and current to help AI assistants work effectively with the codebase.
