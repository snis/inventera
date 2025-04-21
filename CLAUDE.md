# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run Commands
- Run app: `python app.py`
- Create test database: `python create_test_db.py`
- Docker build: `docker build -t inventera .`
- Docker run: `docker run -p 5000:5000 -d inventera`

## Code Style Guidelines
- Follow PEP 8 conventions (snake_case for functions/variables, CamelCase for classes)
- 4-space indentation
- Import order: standard library first, third-party packages second, local modules last
- String literals: use single quotes
- Max line length: ~80-100 characters
- Error handling: use try-except blocks with appropriate logging and user-friendly responses
- All code and comments should be written in English
- Comments are encouraged for clarity

## Project Structure
- Flask application with SQLite/SQLAlchemy
- HTML templates in `/templates`
- CSS in `/static`
- Database stored in `/instance`
- SQLAlchemy models defined in app.py
- AJAX for asynchronous updates
- Frontend UI text and database content are in Swedish

## Data Validation
- Always validate numeric inputs before conversion (using isdigit() for positive integers)
- Check for None and empty values
- Log errors with app.logger.error/warning
- Return appropriate error responses based on request type (JSON for AJAX, redirect for standard)

## Communication Guidelines
- Ask follow-up questions if user intentions are unclear
- Do not assume understanding of ambiguous requests
- Seek clarification when requirements are not specific enough