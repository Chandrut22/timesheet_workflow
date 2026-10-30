import json
from datetime import date

from app.mail.listener import process_new_mail
from app.mail.store import CURSOR_KEY, EMAIL_QUEUE, RedisStore
from tests.fakes import FakeRedis, FakeSource, make_email, settings


def queued(fr):
    return [json.loads(x) for x in reversed(fr.lists.get(EMAIL_QUEUE, []))]


def setup(**kw):
    fr, src = FakeRedis(), FakeSource()
    src.deliver(make_email("<old@abc>"))           # already in the inbox before we start
    return fr, RedisStore(fr), src, settings(**kw)


def test_first_run_only_watches_new_mail():
    fr, store, src, s = setup()
    assert process_new_mail(src, store, s) == 0
    assert fr.hashes[CURSOR_KEY] == {"uidvalidity": "1000", "last_uid": "1"}
    assert queued(fr) == []


def test_first_run_backfill_takes_existing_mail():
    fr, store, src, s = setup(start_from="backfill")
    assert process_new_mail(src, store, s, today=date(2026, 10, 10)) == 1
    assert queued(fr)[0]["message_id"] == "<old@abc>"


def test_new_mail_is_queued_once():
    fr, store, src, s = setup()
    process_new_mail(src, store, s)
    src.deliver(make_email("<new1@abc>"))
    src.deliver(make_email("<new2@abc>"))
    assert process_new_mail(src, store, s) == 2
    assert [e["imap_uid"] for e in queued(fr)] == [2, 3]
    assert process_new_mail(src, store, s) == 0   # nothing new: no repeats
    assert len(queued(fr)) == 2


def test_quirk_last_message_returned_for_n_star():
    fr, store, src, s = setup()
    process_new_mail(src, store, s)
    src.deliver(make_email("<n@abc>"))
    process_new_mail(src, store, s)
    src.next_uid += 1                      # UIDNEXT moved but the message was deleted
    assert process_new_mail(src, store, s) == 0
    assert len(queued(fr)) == 1


def test_ignored_senders_are_recorded_not_dropped():
    fr, store, src, s = setup()
    process_new_mail(src, store, s)
    src.deliver(make_email("<spam@x>", sender="offers@unknown.com"))
    src.deliver(make_email("<spoof@abc>", auth="spf=fail"))
    assert process_new_mail(src, store, s) == 0
    reasons = [e["ignore_reason"] for e in queued(fr)]
    assert reasons == ["Sender not on whitelist", "Sender failed SPF/DKIM/DMARC check"]


def test_duplicate_message_id_is_skipped():
    fr, store, src, s = setup()
    process_new_mail(src, store, s)
    src.deliver(make_email("<same@abc>"))
    src.deliver(make_email("<same@abc>"))  # e.g. copied back into the inbox
    assert process_new_mail(src, store, s) == 1


def test_uidvalidity_change_rescans_without_duplicates():
    fr, store, src, s = setup()
    process_new_mail(src, store, s)
    src.deliver(make_email("<before@abc>"))
    process_new_mail(src, store, s)
    src.validity = 2000                    # server renumbered the folder
    src.deliver(make_email("<after@abc>"))
    assert process_new_mail(src, store, s, today=date(2026, 10, 10)) == 2  # <old> and <after>
    ids = [e["message_id"] for e in queued(fr)]
    assert ids.count("<before@abc>") == 1
    assert fr.hashes[CURSOR_KEY]["uidvalidity"] == "2000"
