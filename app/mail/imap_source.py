"""Real mailbox connection using imap-tools (IMAP over SSL + IDLE)."""
from datetime import date
from email.message import Message
from typing import Iterator

from imap_tools import AND, H, U, MailBox

from app.config import Settings


class ImapSource:
    def __init__(self, settings: Settings):
        self.s = settings
        self.mailbox: MailBox | None = None

    def __enter__(self) -> "ImapSource":
        self.mailbox = MailBox(self.s.imap_host, self.s.imap_port).login(
            self.s.imap_user, self.s.imap_password, initial_folder=self.s.imap_folder
        )
        return self

    def __exit__(self, *exc) -> None:
        try:
            self.mailbox.logout()
        except Exception:
            pass

    def status(self) -> tuple[int, int]:
        st = self.mailbox.folder.status(self.s.imap_folder, ["UIDVALIDITY", "UIDNEXT"])
        return int(st["UIDVALIDITY"]), int(st["UIDNEXT"])

    def fetch_from_uid(self, start_uid: int) -> Iterator[tuple[int, Message]]:
        # mark_seen=False: reading here must not change what people see in the mailbox
        for msg in self.mailbox.fetch(AND(uid=U(start_uid, "*")), mark_seen=False):
            yield int(msg.uid), msg.obj

    def fetch_since(self, day: date) -> Iterator[tuple[int, Message]]:
        for msg in self.mailbox.fetch(AND(date_gte=day), mark_seen=False):
            yield int(msg.uid), msg.obj

    def fetch_message(self, uid: int, uidvalidity: int, message_id: str) -> Message | None:
        """Get one email again (the worker needs its attachments). None if it is gone."""
        current_validity, _ = self.status()
        if current_validity == uidvalidity:
            for msg in self.mailbox.fetch(AND(uid=str(uid)), mark_seen=False):
                return msg.obj
        # Folder renumbered or message moved: look it up by Message-ID instead
        if message_id and not message_id.startswith("<uid-"):
            for msg in self.mailbox.fetch(AND(header=H("Message-ID", message_id)), mark_seen=False):
                return msg.obj
        return None

    def wait(self, timeout: int) -> bool:
        """Enter IMAP IDLE until the server reports a change or the timeout passes."""
        return bool(self.mailbox.idle.wait(timeout=timeout))
