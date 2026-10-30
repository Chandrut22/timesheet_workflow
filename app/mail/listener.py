"""Core logic: find mail that arrived since the last check and queue it.

No third-party imports, so it can be tested with a fake mailbox and a fake Redis.
"""
import logging
from datetime import date, timedelta
from email.message import Message
from typing import Iterator, Protocol

from app.config import Settings
from app.mail.parser import is_whitelisted, parse_message
from app.mail.store import RedisStore

log = logging.getLogger("imap.listener")


class MailSource(Protocol):
    def status(self) -> tuple[int, int]: ...                         # (UIDVALIDITY, UIDNEXT)
    def fetch_from_uid(self, start_uid: int) -> Iterator[tuple[int, Message]]: ...
    def fetch_since(self, day: date) -> Iterator[tuple[int, Message]]: ...
    def wait(self, timeout: int) -> bool: ...                        # IDLE; True if server pushed something


def ignore_reason_for(email, settings: Settings) -> str | None:
    if not is_whitelisted(email.from_email, settings.sender_whitelist):
        return "Sender not on whitelist"
    if settings.require_sender_auth and not email.sender_auth_passed:
        return "Sender failed SPF/DKIM/DMARC check"
    return None


def process_new_mail(source: MailSource, store: RedisStore, settings: Settings,
                     today: date | None = None) -> int:
    """Queue every message that arrived since the stored cursor. Returns how many were queued.

    Ignored emails are queued too (with ignore_reason set) so the next step can save
    them with state = ignored, as the logging rules require.
    """
    today = today or date.today()
    validity, uidnext = source.status()
    saved_validity, last_uid = store.get_cursor()

    if saved_validity is None:
        if settings.start_from == "new":
            store.set_cursor(validity, uidnext - 1)
            log.info("First run: watching for mail with UID >= %s", uidnext)
            return 0
        log.info("First run: back-filling the last %s day(s)", settings.backfill_days)
        messages = source.fetch_since(today - timedelta(days=settings.backfill_days))
        resync = True
    elif saved_validity != validity:
        # The server renumbered the folder; old UIDs mean nothing now.
        log.warning("UIDVALIDITY changed (%s -> %s); re-scanning recent mail", saved_validity, validity)
        messages = source.fetch_since(today - timedelta(days=2))
        resync = True
    else:
        if uidnext - 1 <= last_uid:
            return 0  # nothing new
        messages = source.fetch_from_uid(last_uid + 1)
        resync = False

    queued = 0
    highest = 0 if resync else last_uid
    for uid, msg in messages:
        if not resync and uid <= last_uid:
            continue  # IMAP returns the last message for "n:*" even when nothing is newer
        email = parse_message(msg, uid, validity, settings.imap_folder)
        if store.mark_seen(email.message_id):
            email.ignore_reason = ignore_reason_for(email, settings)
            try:
                store.push(email)
            except Exception:
                store.unmark_seen(email.message_id)
                raise
            if email.ignore_reason:
                log.info("Ignored UID %s from %s: %s", uid, email.from_email, email.ignore_reason)
            else:
                queued += 1
                log.info("New mail UID %s from %s: %r (%d attachment(s))",
                         uid, email.from_email, email.subject, len(email.attachments))
        highest = max(highest, uid)
        if not resync:
            store.set_cursor(validity, highest)  # move forward after each message

    if resync:
        store.set_cursor(validity, max(highest, uidnext - 1))
    return queued
