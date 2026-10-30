from email.message import EmailMessage

from app.mail.parser import get_part, html_to_text, is_whitelisted, parse_message
from tests.fakes import make_email


def test_parse_full_email():
    e = parse_message(make_email("<a1@abc>", subject="=?utf-8?b?VGltZXNoZWV0IOKAkyB3ZWVrIDQx?="), 7, 1000, "INBOX")
    assert e.message_id == "<a1@abc>"
    assert e.imap_uid == 7 and e.uidvalidity == 1000
    assert e.from_email == "payroll@abcstaffing.com" and e.from_name == "Payroll"
    assert e.subject == "Timesheet – week 41"          # encoded subject decoded
    assert e.body_text == "Total 40 hours"
    assert e.has_html is True
    assert e.sender_auth_passed is True
    assert e.received_at.startswith("2026-10-09T10:02:00")
    assert len(e.attachments) == 1
    att = e.attachments[0]
    assert (att.filename, att.mime_type, att.is_inline) == ("timesheet.pdf", "application/pdf", False)
    assert att.size == len(b"%PDF-1.4 timesheet")


def test_attachment_can_be_found_again_by_part_index():
    msg = make_email("<a2@abc>")
    att = parse_message(msg, 1, 1, "INBOX").attachments[0]
    assert get_part(msg, att.part_index).get_payload(decode=True) == b"%PDF-1.4 timesheet"


def test_same_file_gives_same_hash():
    a = parse_message(make_email("<x@abc>"), 1, 1, "INBOX").attachments[0]
    b = parse_message(make_email("<y@abc>"), 2, 1, "INBOX").attachments[0]
    assert a.sha256 == b.sha256


def test_html_only_body_and_inline_logo():
    m = EmailMessage()
    m["From"] = "x@abcstaffing.com"
    m["Subject"] = "Hours"
    m.set_content("<style>p{}</style><p>Mon 10</p><p>Tue 8</p>", subtype="html")
    m.add_related(b"\x89PNG", maintype="image", subtype="png", cid="<logo>")
    e = parse_message(m, 1, 1, "INBOX")
    assert e.body_text == "Mon 10\nTue 8"
    assert e.attachments[0].is_inline is True
    assert e.message_id == "<uid-1-1@local>"   # fallback when Message-ID is missing


def test_auth_failure_and_helpers():
    e = parse_message(make_email("<f@abc>", auth="mx.google.com; spf=fail"), 1, 1, "INBOX")
    assert e.sender_auth_passed is False
    assert html_to_text("<p>A</p><p>B</p>") == "A\nB"
    assert is_whitelisted("R.Kumar@ABCStaffing.com", ["@abcstaffing.com"])
    assert not is_whitelisted("x@evil.com", ["@abcstaffing.com"])
    assert not is_whitelisted("a@abcstaffing.com", [])
