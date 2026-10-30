"""Read step: turn one queued email into extracted, validated timesheets.

For each email the listener queued:
  1. skip it if the listener already marked it ignored (whitelist / SPF-DKIM-DMARC)
  2. download the email again from the mailbox (attachments are never stored)
  3. for every attachment that could be a timesheet:
       Docling -> Markdown text -> LLM -> TimesheetData -> rule checks
  4. if no attachment held a timesheet, try the email body on its own
  5. return one result with every timesheet, every skipped file and a step-by-step log

The heavy tools (IMAP, Docling, LLM, rules) are passed in through ReadTools, so this
module can be tested without any of them installed.
"""
import logging
import time
from dataclasses import dataclass, field
from email.message import Message
from typing import Any, Callable

from app.extraction.document_extraction import (
    SUPPORTED_EXTENSIONS,
    NoTextError,
    file_extension,
    format_source_text,
)
from app.mail.parser import get_part

log = logging.getLogger("pipeline")


@dataclass
class ReadTools:
    fetch_message: Callable[[dict], Message | None]   # queued email -> raw message (None if gone)
    document_to_text: Callable[[str, bytes], str]     # (file name, bytes) -> Markdown
    extract_fields: Callable[[str], Any]              # source text -> TimesheetData
    validate: Callable[[Any], dict]                   # TimesheetData -> validation report


@dataclass
class StepLog:
    step: str              # fetch | read | extract | rule_check
    result: str            # success | warning | error
    message: str           # plain language for users
    source: str | None = None
    error_details: str | None = None
    duration_ms: int = 0


@dataclass
class TimesheetResult:
    source: str            # attachment file name, or "email body"
    part_index: int | None
    sha256: str | None
    timesheet: dict
    validation: dict


@dataclass
class EmailResult:
    message_id: str
    imap_uid: int
    uidvalidity: int
    from_email: str
    subject: str
    received_at: str
    state: str = "reading"     # ignored | failed | matching (Read finished, Match is next)
    reason: str | None = None
    timesheets: list[TimesheetResult] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)    # {file, reason}
    failures: list[dict] = field(default_factory=list)   # {file, message}
    steps: list[StepLog] = field(default_factory=list)


def looks_like_timesheet(ts: Any) -> bool:
    """An invoice, notice or logo comes back with no name, no days and no total."""
    return bool(
        getattr(ts, "employee_name", None)
        or getattr(ts, "daily_entries", None)
        or getattr(ts, "reported_total_hours", None) is not None
    )


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _read_error_message(name: str, exc: Exception) -> str:
    if isinstance(exc, NoTextError):
        return f"No text could be read from {name}. It may be blank or an unreadable scan."
    return (f"{name} could not be opened. It may be corrupted or password-protected. "
            "Ask the sender to resend it.")


def _extract_and_check(result: EmailResult, tools: ReadTools, source_label: str,
                       source_text: str, part_index: int | None, sha256: str | None) -> bool:
    """LLM extraction + rules for one source. True if a timesheet was added."""
    start = time.monotonic()
    try:
        ts = tools.extract_fields(source_text)
    except Exception as exc:
        message = (f"Could not extract timesheet details from {source_label}: "
                   "the AI model did not return valid data.")
        result.steps.append(StepLog("extract", "error", message, source_label, repr(exc)[:800], _ms(start)))
        result.failures.append({"file": source_label, "message": message})
        return False

    if not looks_like_timesheet(ts):
        result.steps.append(StepLog("extract", "warning", f"{source_label} is not a timesheet",
                                    source_label, None, _ms(start)))
        result.skipped.append({"file": source_label, "reason": "Not a timesheet"})
        return False

    result.steps.append(StepLog("extract", "success",
                                f"Extracted timesheet for {getattr(ts, 'employee_name', None) or 'unknown employee'}",
                                source_label, None, _ms(start)))

    start = time.monotonic()
    report = tools.validate(ts)
    problems = len(report.get("violations", []))
    result.steps.append(StepLog("rule_check", "warning" if problems else "success",
                                f"{problems} rule violation(s)" if problems else "All rule checks passed",
                                source_label, None, _ms(start)))
    result.timesheets.append(TimesheetResult(source_label, part_index, sha256,
                                             ts.model_dump(mode="json"), report))
    return True


def process_email(job: dict, tools: ReadTools) -> EmailResult:
    result = EmailResult(
        message_id=job["message_id"], imap_uid=job["imap_uid"], uidvalidity=job["uidvalidity"],
        from_email=job["from_email"], subject=job.get("subject", ""), received_at=job["received_at"],
    )

    # 1. Already rejected by the listener
    if job.get("ignore_reason"):
        result.state, result.reason = "ignored", job["ignore_reason"]
        return result

    # 2. Download the email again to get the attachment bytes
    start = time.monotonic()
    try:
        msg = tools.fetch_message(job)
    except Exception as exc:
        result.steps.append(StepLog("fetch", "error", "Could not download the email from the mailbox",
                                    None, repr(exc)[:800], _ms(start)))
        raise  # temporary problem (network, login): the worker retries the whole email
    if msg is None:
        result.state, result.reason = "failed", "The email is no longer in the mailbox"
        result.steps.append(StepLog("fetch", "error", result.reason, None, None, _ms(start)))
        return result
    result.steps.append(StepLog("fetch", "success", "Email downloaded", None, None, _ms(start)))

    body = job.get("body_text") or ""

    # 3. Each attachment that could be a timesheet
    for att in job.get("attachments", []):
        name = att["filename"]
        extension = file_extension(name, att.get("mime_type"))

        if att.get("is_inline"):
            result.skipped.append({"file": name, "reason": "Inline image (logo or signature)"})
            continue
        if extension not in SUPPORTED_EXTENSIONS:
            result.skipped.append({"file": name, "reason": f"Unsupported file type {extension or att.get('mime_type')}"})
            continue

        start = time.monotonic()
        try:
            data = get_part(msg, att["part_index"]).get_payload(decode=True) or b""
            doc_name = name if name.lower().endswith(extension) else name + extension
            text = tools.document_to_text(doc_name, data)
        except Exception as exc:
            message = _read_error_message(name, exc)
            result.steps.append(StepLog("read", "error", message, name, repr(exc)[:800], _ms(start)))
            result.failures.append({"file": name, "message": message})
            continue
        result.steps.append(StepLog("read", "success", f"Read {name}", name, None, _ms(start)))

        # The body goes along with each file so the LLM can note conflicts (e.g. email says 40, file says 38)
        _extract_and_check(result, tools, name, format_source_text(name, text, body),
                           att["part_index"], att.get("sha256"))

    # 4. Timesheet written in the email body only
    if not result.timesheets and body.strip():
        _extract_and_check(result, tools, "email body", format_source_text(email_body=body), None, None)

    # 5. Final state for this email
    if result.timesheets:
        result.state = "matching"
    elif result.failures:
        result.state, result.reason = "failed", result.failures[0]["message"]
    else:
        result.state, result.reason = "ignored", "No timesheet found in the email"
    return result
