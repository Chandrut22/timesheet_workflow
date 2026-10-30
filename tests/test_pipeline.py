"""Pipeline tests with fake Docling / LLM / rules, so they run without those installed."""
from dataclasses import asdict
from email.message import EmailMessage

import pytest

from app.extraction.document_extraction import NoTextError
from app.mail.parser import parse_message
from app.pipeline import ReadTools, process_email
from tests.fakes import make_email


class FakeTimesheet:
    def __init__(self, name=None, days=(), total=None):
        self.employee_name = name
        self.daily_entries = list(days)
        self.reported_total_hours = total

    def model_dump(self, mode="json"):
        return {"employee_name": self.employee_name, "reported_total_hours": self.reported_total_hours}


def fake_extract(source_text: str):
    """Pretend LLM: reads 'NAME:' / 'TOTAL:' markers from the text."""
    if "BROKEN-LLM" in source_text:
        raise ValueError("Model did not return valid TimesheetData")
    attachment = source_text.split("--- SOURCE SEPARATOR ---")[0]
    for line in attachment.splitlines():
        if line.startswith("NAME:"):
            return FakeTimesheet(name=line[5:].strip(), days=["Mon"], total=40)
    if "Total 40" in source_text and "EMAIL BODY" in attachment:
        return FakeTimesheet(name="John", total=40)
    return FakeTimesheet()  # not a timesheet


def fake_document_to_text(name: str, data: bytes) -> str:
    if data.startswith(b"CORRUPT"):
        raise RuntimeError("PdfiumError: Failed to load document")
    if not data.strip():
        raise NoTextError(f"No text extracted from {name}")
    return data.decode()


def fake_validate(ts):
    violations = [] if ts.reported_total_hours == 40 else [{"severity": "medium", "message": "x"}]
    return {"status": "human_review_required" if violations else "passed", "violations": violations}


def tools_for(msg):
    return ReadTools(fetch_message=lambda job: msg, document_to_text=fake_document_to_text,
                     extract_fields=fake_extract, validate=fake_validate)


def email_with(files: list[tuple[str, str, bytes]], body="Please find attached.", sender="payroll@abcstaffing.com"):
    m = make_email("<t@abc>", sender=sender, body=body, pdf=None)
    for filename, mime, data in files:
        maintype, subtype = mime.split("/")
        m.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return m


def run(msg, ignore_reason=None):
    job = asdict(parse_message(msg, 5, 1000, "INBOX"))
    job["ignore_reason"] = ignore_reason
    return process_email(job, tools_for(msg))


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_one_timesheet_is_extracted_and_validated():
    r = run(email_with([("Priya_Nair.xlsx", XLSX, b"NAME: Priya Nair")]))
    assert r.state == "matching"
    assert [t.source for t in r.timesheets] == ["Priya_Nair.xlsx"]
    assert r.timesheets[0].timesheet["employee_name"] == "Priya Nair"
    assert r.timesheets[0].validation["status"] == "passed"
    assert r.timesheets[0].sha256  # kept for duplicate checks
    assert [s.step for s in r.steps] == ["fetch", "read", "extract", "rule_check"]


def test_three_files_give_three_timesheets():
    r = run(email_with([("Fatima.xlsx", XLSX, b"NAME: Fatima Zahra"),
                        ("Marcus.xlsx", XLSX, b"NAME: Marcus Allen"),
                        ("Oliver.pdf", "application/pdf", b"NAME: Oliver Grant")]))
    assert [t.timesheet["employee_name"] for t in r.timesheets] == ["Fatima Zahra", "Marcus Allen", "Oliver Grant"]


def test_invoice_and_logo_are_skipped_timesheet_kept():
    m = email_with([("Daniel_Okafor.pdf", "application/pdf", b"NAME: Daniel Okafor"),
                    ("Vendor_Invoice.pdf", "application/pdf", b"INVOICE 4471 amount due"),
                    ("notes.zip", "application/zip", b"PK..")])
    m.get_body(("html",)).add_related(b"\x89PNG", maintype="image", subtype="png", cid="<logo>")
    r = run(m)
    assert r.state == "matching"
    assert [t.source for t in r.timesheets] == ["Daniel_Okafor.pdf"]
    reasons = {s["file"]: s["reason"] for s in r.skipped}
    assert reasons["Vendor_Invoice.pdf"] == "Not a timesheet"
    assert reasons["notes.zip"].startswith("Unsupported file type")
    assert reasons["(unnamed)"] == "Inline image (logo or signature)"


def test_corrupted_file_fails_with_plain_message():
    r = run(email_with([("week41_batch.xlsx", XLSX, b"CORRUPT\x00\x01")], body="Batch attached."))
    assert r.state == "failed"
    assert "could not be opened" in r.reason and "week41_batch.xlsx" in r.reason
    read = [s for s in r.steps if s.step == "read"][0]
    assert read.result == "error" and "PdfiumError" in read.error_details  # technical detail kept


def test_corrupted_file_does_not_block_good_one():
    r = run(email_with([("bad.pdf", "application/pdf", b"CORRUPT"),
                        ("Grace.xlsx", XLSX, b"NAME: Grace Okoye")]))
    assert r.state == "matching"
    assert len(r.timesheets) == 1 and len(r.failures) == 1


def test_timesheet_in_email_body_only():
    r = run(email_with([], body="Mon to Fri 8 hours each day. Total 40. - John"))
    assert r.state == "matching"
    assert r.timesheets[0].source == "email body"
    assert r.timesheets[0].part_index is None


def test_email_with_no_timesheet_is_ignored():
    r = run(email_with([("Q4_Safety_Briefing.pdf", "application/pdf", b"Safety notice")], body="FYI"))
    assert r.state == "ignored"
    assert r.reason == "No timesheet found in the email"


def test_llm_failure_is_reported():
    r = run(email_with([("x.pdf", "application/pdf", b"BROKEN-LLM")], body=""))
    assert r.state == "failed"
    assert "AI model" in r.reason


def test_listener_ignored_email_is_not_fetched():
    msg = email_with([("Priya.xlsx", XLSX, b"NAME: Priya")], sender="offers@unknown.com")
    job = asdict(parse_message(msg, 5, 1000, "INBOX"))
    job["ignore_reason"] = "Sender not on whitelist"

    def must_not_fetch(job):
        raise AssertionError("should not download an ignored email")

    r = process_email(job, ReadTools(must_not_fetch, fake_document_to_text, fake_extract, fake_validate))
    assert (r.state, r.reason) == ("ignored", "Sender not on whitelist")


def test_email_deleted_from_mailbox():
    msg = email_with([("Priya.xlsx", XLSX, b"NAME: Priya")])
    job = asdict(parse_message(msg, 5, 1000, "INBOX"))
    r = process_email(job, ReadTools(lambda j: None, fake_document_to_text, fake_extract, fake_validate))
    assert r.state == "failed" and "no longer in the mailbox" in r.reason


def test_mailbox_down_raises_so_worker_retries():
    msg = email_with([("Priya.xlsx", XLSX, b"NAME: Priya")])
    job = asdict(parse_message(msg, 5, 1000, "INBOX"))

    def down(job):
        raise ConnectionError("imap.gmail.com unreachable")

    with pytest.raises(ConnectionError):
        process_email(job, ReadTools(down, fake_document_to_text, fake_extract, fake_validate))
