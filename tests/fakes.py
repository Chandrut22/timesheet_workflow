from email.message import EmailMessage

from app.config import Settings


def settings(**overrides) -> Settings:
    base = dict(imap_host="imap.test", imap_port=993, imap_user="ts@genworx.ai", imap_password="x",
                imap_folder="INBOX", redis_url="redis://", sender_whitelist=["@abcstaffing.com"], output_dir="output",
                require_sender_auth=True, idle_timeout=300, start_from="new", backfill_days=2)
    base.update(overrides)
    return Settings(**base)


def make_email(msg_id: str, sender: str = "payroll@abcstaffing.com", subject: str = "Timesheet",
               body: str = "Total 40 hours", auth: str = "mx.google.com; dkim=pass; spf=pass; dmarc=pass",
               pdf: bytes | None = b"%PDF-1.4 timesheet") -> EmailMessage:
    m = EmailMessage()
    m["Received"] = "from mail.abcstaffing.com by mx.google.com; Fri, 09 Oct 2026 10:02:00 +0530"
    m["Authentication-Results"] = auth
    m["From"] = f"Payroll <{sender}>"
    m["To"] = "ts@genworx.ai"
    m["Subject"] = subject
    m["Message-ID"] = msg_id
    m["Date"] = "Fri, 09 Oct 2026 10:01:55 +0530"
    m.set_content(body)
    m.add_alternative(f"<p>{body}</p>", subtype="html")
    if pdf is not None:
        m.add_attachment(pdf, maintype="application", subtype="pdf", filename="timesheet.pdf")
    return m


class FakeRedis:
    def __init__(self):
        self.kv, self.hashes, self.lists = {}, {}, {}

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update({k: str(v) for k, v in mapping.items()})

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        return True

    def delete(self, key):
        self.kv.pop(key, None)

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)


class FakeSource:
    """In-memory mailbox that behaves like IMAP, including the 'n:*' quirk."""

    def __init__(self, validity=1000):
        self.validity = validity
        self.messages: list[tuple[int, EmailMessage]] = []
        self.next_uid = 1

    def deliver(self, msg):
        self.messages.append((self.next_uid, msg))
        self.next_uid += 1

    def status(self):
        return self.validity, self.next_uid

    def fetch_from_uid(self, start_uid):
        hits = [(u, m) for u, m in self.messages if u >= start_uid]
        if not hits and self.messages:
            hits = [self.messages[-1]]  # real IMAP servers do this for "n:*"
        return iter(hits)

    def fetch_since(self, day):
        return iter(list(self.messages))

    def wait(self, timeout):
        return False
