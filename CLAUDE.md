# CLAUDE.md - AI Assistant Guide for FileUzi

## Project Overview

**FileUzi** is an architectural filing widget designed to improve accuracy when storing key documents and make the process much quicker. This project is owned by JakeWhiteArchitecture and licensed under the MIT License.

**Repository:** JakeWhiteArchitecture/FileUzi
**License:** MIT (2026)
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

# Branch naming convention
# Development branches should follow: claude/<description>-<session-id>
```

### Key Paths

| Path | Description |
|------|-------------|
| `/` | Repository root |
| `/README.md` | Project description |
| `/LICENSE` | MIT License file |
| `/CLAUDE.md` | This file - AI assistant guide |

---

## Codebase Structure

```
FileUzi/
├── LICENSE              # MIT License (2026 JakeWhiteArchitecture)
├── README.md            # Project overview and description
├── CLAUDE.md            # AI assistant guidelines (this file)
├── src/                 # [Planned] Source code directory
│   ├── components/      # [Planned] UI components
│   ├── services/        # [Planned] Business logic and services
│   ├── utils/           # [Planned] Utility functions
│   └── types/           # [Planned] Type definitions
├── tests/               # [Planned] Test files
├── docs/                # [Planned] Documentation
└── config/              # [Planned] Configuration files
```

> **Note:** Directories marked [Planned] do not exist yet. Create them as needed following the structure above.

---

## Development Guidelines

### Code Conventions

When adding code to this project, follow these conventions:

1. **File Naming**
   - Use kebab-case for file names: `file-processor.ts`, `document-viewer.tsx`
   - Use PascalCase for component files if using React: `DocumentCard.tsx`
   - Test files should mirror source: `file-processor.test.ts`

2. **Code Style**
   - Prefer TypeScript over JavaScript for type safety
   - Use meaningful, descriptive variable and function names
   - Keep functions focused and single-purpose
   - Add comments only where logic isn't self-evident

3. **Architecture Principles**
   - Separate concerns: UI, business logic, and data access
   - Keep components small and reusable
   - Use dependency injection where appropriate
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

FileUzi is designed for **architectural firms** to:
- Store and organize key documents (drawings, specifications, contracts, etc.)
- Improve filing accuracy through intelligent categorization
- Speed up the document storage and retrieval process
- Provide a user-friendly widget interface

### Target Users

- Architects and architectural firms
- Project managers handling architectural documentation
- Administrative staff managing project files

### Key Terminology

| Term | Definition |
|------|------------|
| Filing Widget | The main UI component for document organization |
| Document | Any file being stored (drawings, specs, contracts) |
| Category | A classification for organizing documents |
| Project | A container for related documents |

---

## AI Assistant Instructions

### When Working on This Codebase

1. **Before Making Changes**
   - Read existing code before modifying it
   - Understand the context and purpose of files
   - Check for related tests and documentation

2. **Making Changes**
   - Keep changes focused and minimal
   - Don't over-engineer solutions
   - Avoid introducing security vulnerabilities
   - Follow existing patterns and conventions

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

- Never commit sensitive data (API keys, credentials)
- Validate user input at system boundaries
- Be cautious with file system operations
- Follow OWASP guidelines for web applications

---

## Testing Guidelines

When tests are implemented, follow these practices:

1. **Test Structure**
   - Place tests in `/tests/` directory mirroring `/src/`
   - Name test files with `.test.ts` or `.spec.ts` suffix
   - Group related tests with `describe` blocks

2. **Test Coverage**
   - Write tests for new features and bug fixes
   - Cover edge cases and error conditions
   - Aim for meaningful coverage, not just percentage

3. **Running Tests**
   ```bash
   # Commands to be defined when testing framework is set up
   npm test           # Run all tests
   npm test -- <file> # Run specific test file
   ```

---

## Build and Deployment

> **Note:** Build and deployment workflows are not yet configured. This section will be updated as the project evolves.

### Planned Setup

```bash
# Install dependencies (when package.json exists)
npm install

# Development server
npm run dev

# Build for production
npm run build

# Run linting
npm run lint
```

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

---

## Changelog

### 2026-02-03
- Initial repository creation
- Added README.md and LICENSE
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
