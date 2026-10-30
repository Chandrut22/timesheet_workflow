# Timesheet Processing Assistant - workflow

Email in -> timesheets extracted and checked, automatically.

```
Mailbox ──IMAP IDLE──▶ LISTENER ──▶ Redis tsa:emails:incoming ──▶ WORKER ──▶ output/*.json
                       (Collect)                                   (Read + Validate)  + Redis tsa:timesheets:results
```

| Process | Command | Job |
|---|---|---|
| Listener | `uv run python -m app.run_listener` | Waits for new mail (IMAP IDLE), parses it, checks the sender, queues it |
| Worker | `uv run python -m app.run_worker` | Downloads each queued email's attachments, Docling -> LLM -> rule checks, saves the result |
| CLI | `uv run python main.py --file <path>` | Same extraction on one local file, for testing |

## Project layout
```
main.py                          CLI for one file / email body
app/
  config.py                      settings from .env
  run_listener.py                listener process
  run_worker.py                  worker process
  pipeline.py                    Read step for one email (attachments -> timesheets)
  mail/
    imap_source.py               IMAP connection: IDLE, fetch new, fetch one again
    listener.py                  what is new since last time, whitelist, cursor
    parser.py                    raw email -> clean record
    store.py                     Redis keys and queues
  extraction/
    document_extraction.py       Docling: file or bytes -> Markdown
    timesheet_extractor.py       LLM: Markdown -> TimesheetData (JSON, validated, retried)
    models.py                    TimesheetData / DailyEntry
    rules.py                     deterministic checks (missing ID, >16 h/day, totals...)
tests/                           23 tests, run with fakes (no mailbox, Docling or LLM needed)
attachments/                     sample timesheets TC-01..TC-20
```

## Setup
1. Install: `uv sync`
2. `cp .env.example .env` and fill in the LLM key, mailbox and app password, whitelist.
   Gmail needs 2-Step Verification and an **App Password** (Google Account -> Security -> App passwords).
3. Start Redis: `docker run -d -p 6379:6379 redis:7`

## Run (two terminals)
```bash
uv run python -m app.run_listener
uv run python -m app.run_worker
```
Send a timesheet to the mailbox from a whitelisted sender. Within seconds:
```
listener  New mail UID 1234 from payroll@abcstaffing.com: 'Timesheet' (1 attachment(s))
worker    UID 1234 'Timesheet' -> matching, 1 timesheet(s), 0 skipped, 0 failed in 18.4s (...json)
```
The result is in `output/` and on Redis: `redis-cli LRANGE tsa:timesheets:results 0 0`

Tests: `uv run pytest`

## What the worker does with each email
1. Listener already ignored it (whitelist / SPF-DKIM-DMARC)? -> state `ignored`, nothing downloaded.
2. Downloads the email again by UID (attachments are never stored on disk).
3. For each attachment:
   - inline logos and unsupported types (.zip, .txt ...) -> skipped, with the reason
   - Docling reads it (OCR for scans/photos) -> the LLM extracts the fields, with the email body
     included so it can note conflicts -> rule checks
   - no name, no days, no total -> "Not a timesheet" (invoices, notices, logos)
   - unreadable / corrupted -> plain error message, the other attachments still run
4. No timesheet in any attachment? Tries the email body on its own.
5. Result state: `matching` (timesheets found; the Match step is next), `failed` (nothing
   extracted and something broke) or `ignored` (no timesheet in the email).
6. If the mailbox is unreachable, the email goes back on the queue and is retried
   (MAX_ATTEMPTS, then `tsa:emails:dead`).

Each result has a `steps` list (fetch / read / extract / rule_check, with result, message,
technical detail and time taken) ready to be saved as `processing_steps` rows.

## Speed
OCR + LLM take roughly 10-60 s per attachment, depending on the model. To process faster,
run more workers: each email is taken by exactly one worker.
