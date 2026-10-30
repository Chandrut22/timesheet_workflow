"""Listen for new mail with IMAP IDLE and push each email to Redis.

    python -m app.run_listener        (run exactly one instance)
"""
import logging
import time

import redis
from imap_tools.errors import MailboxLoginError

from app.config import load_settings
from app.mail.imap_source import ImapSource
from app.mail.listener import process_new_mail
from app.mail.store import RedisStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("imap.listener")


def main() -> None:
    settings = load_settings()
    store = RedisStore(redis.Redis.from_url(settings.redis_url, decode_responses=True))
    backoff = 5

    while True:
        try:
            with ImapSource(settings) as source:
                log.info("Connected to %s as %s, folder %s", settings.imap_host,
                         settings.imap_user, settings.imap_folder)
                backoff = 5
                process_new_mail(source, store, settings)          # catch up after (re)connect
                while True:
                    pushed = source.wait(settings.idle_timeout)    # blocks in IDLE
                    if pushed:
                        log.info("Server reported a mailbox change")
                    process_new_mail(source, store, settings)      # also runs on timeout, as a safety net
        except KeyboardInterrupt:
            log.info("Stopped")
            return
        except MailboxLoginError:
            log.error("Login failed. Check IMAP_USER and IMAP_PASSWORD (Gmail needs an App Password).")
        except Exception:
            log.exception("Connection lost")
        log.info("Reconnecting in %s s", backoff)
        time.sleep(backoff)
        backoff = min(backoff * 2, 300)


if __name__ == "__main__":
    main()
