"""Turn a raw email (email.message.Message) into a clean record. Standard library only."""
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser


@dataclass
class AttachmentMeta:
    part_index: int      # position in msg.walk(); the Read step uses it to find the file again
    filename: str
    mime_type: str
    size: int
    sha256: str          # finds the same file sent twice (case 6)
    is_inline: bool      # logos / signature images


@dataclass
class ParsedEmail:
    message_id: str
    imap_uid: int
    uidvalidity: int
    folder: str
    from_name: str
    from_email: str
    to: str
    subject: str
    received_at: str     # ISO 8601
    body_text: str
    has_html: bool
    sender_auth_passed: bool
    attachments: list[AttachmentMeta] = field(default_factory=list)
    ignore_reason: str | None = None


# ---------------- helpers ----------------
def decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:
        return str(value).strip()


def _decode_text(part: Message) -> str:
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


class _HTMLToText(HTMLParser):
    BLOCK = {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "table"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag in ("td", "th"):
            self.parts.append("\t")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _HTMLToText()
    parser.feed(html)
    return re.sub(r"\n\s*\n+", "\n\n", "".join(parser.parts)).strip()


def _received_at(msg: Message) -> datetime:
    """Time the mail server received it: the newest Received header, else the Date header."""
    received = msg.get_all("Received") or []
    candidates = [received[0].rsplit(";", 1)[-1]] if received else []
    candidates.append(msg.get("Date", ""))
    for value in candidates:
        try:
            dt = parsedate_to_datetime(value.strip())
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError, IndexError):
            continue
    return datetime.now(timezone.utc)


def sender_auth_passed(msg: Message) -> bool:
    """True if the receiving server recorded DMARC pass, or both SPF and DKIM pass."""
    results = " ".join(msg.get_all("Authentication-Results") or []).lower()
    return "dmarc=pass" in results or ("spf=pass" in results and "dkim=pass" in results)


def is_whitelisted(sender: str, whitelist: list[str]) -> bool:
    """Match full addresses or '@domain' entries. Empty whitelist = allow nobody."""
    sender = sender.strip().lower()
    if "@" not in sender:
        return False
    domain = "@" + sender.rsplit("@", 1)[1]
    allowed = {w.strip().lower() for w in whitelist}
    return sender in allowed or domain in allowed


def get_part(msg: Message, part_index: int) -> Message:
    """Used by the Read step: return the attachment part saved as part_index."""
    for index, part in enumerate(msg.walk()):
        if index == part_index:
            return part
    raise IndexError(f"No MIME part {part_index}")


# ---------------- main entry ----------------
def parse_message(msg: Message, uid: int, uidvalidity: int, folder: str) -> ParsedEmail:
    texts: list[str] = []
    htmls: list[str] = []
    attachments: list[AttachmentMeta] = []

    for index, part in enumerate(msg.walk()):
        if part.is_multipart():
            continue
        mime = part.get_content_type()
        disposition = (part.get("Content-Disposition") or "").lower()
        filename = decode_mime_header(part.get_filename())
        inline_image = mime.startswith("image/") and part.get("Content-ID") is not None

        if filename or disposition.startswith("attachment") or inline_image:
            payload = part.get_payload(decode=True) or b""
            attachments.append(AttachmentMeta(
                part_index=index,
                filename=filename or "(unnamed)",
                mime_type=mime,
                size=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                is_inline=disposition.startswith("inline") or (inline_image and not disposition),
            ))
        elif mime == "text/plain":
            texts.append(_decode_text(part))
        elif mime == "text/html":
            htmls.append(_decode_text(part))

    body_text = "\n".join(texts).strip() or (html_to_text("\n".join(htmls)) if htmls else "")
    from_name, from_email = parseaddr(decode_mime_header(msg.get("From")))
    message_id = (msg.get("Message-ID") or "").strip() or f"<uid-{uidvalidity}-{uid}@local>"

    return ParsedEmail(
        message_id=message_id,
        imap_uid=uid,
        uidvalidity=uidvalidity,
        folder=folder,
        from_name=from_name,
        from_email=from_email.lower(),
        to=decode_mime_header(msg.get("To")),
        subject=decode_mime_header(msg.get("Subject")),
        received_at=_received_at(msg).isoformat(),
        body_text=body_text,
        has_html=bool(htmls),
        sender_auth_passed=sender_auth_passed(msg),
        attachments=attachments,
    )
