# AGENTS.md

This file provides guidance to Codex (claude.ai/code) when working with code in this repository.

## Common Commands

### Development
- Install dependencies: `uv sync`
- Run the listener (collects emails): `uv run python -m app.run_listener`
- Run the worker (processes emails): `uv run python -m app.run_worker`
- Process a single local file via CLI: `uv run python main.py --file <path>`
- Run all tests: `uv run pytest`

### Infrastructure
- Start Redis (required): `docker run -d -p 6379:6379 redis:7`

## Architecture

The system is an asynchronous pipeline for extracting timesheet data from emails.

### High-Level Flow
`Mailbox` $\rightarrow$ `Listener` $\rightarrow$ `Redis Queue (tsa:emails:incoming)` $\rightarrow$ `Worker` $\rightarrow$ `JSON Output / Redis (tsa:timesheets:results)`

### Components
- **Listener (`app/mail/`)**: Monitors a mailbox via IMAP IDLE. It filters emails based on a whitelist and queues the UIDs of valid emails into Redis.
- **Worker (`app/run_worker.py` & `app/pipeline.py`)**: 
    - Consumes UIDs from Redis.
    - Downloads attachments and utilizes **Docling** for document conversion (OCR for scans/photos) to Markdown.
    - Uses an **LLM** to extract structured `TimesheetData` from the Markdown and email body.
    - Applies deterministic **rule checks** (`app/extraction/rules.py`) to validate extracted data (e.g., total hours, missing IDs).
- **Extraction (`app/extraction/`)**: Handles the core logic of converting raw documents to structured data and validating them against business rules.
- **CLI (`main.py`)**: Provides a synchronous path to run the extraction pipeline on a single local file for testing purposes.

### Data Models
- `TimesheetData` and `DailyEntry` are defined in `app/extraction/models.py` and serve as the primary schema for extracted information.
