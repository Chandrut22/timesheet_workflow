"""Redis keys and the small amount of state the listener keeps."""
import json
from dataclasses import asdict

from app.mail.parser import ParsedEmail

EMAIL_QUEUE = "tsa:emails:incoming"     # input to the Read step
CURSOR_KEY = "tsa:imap:cursor"          # hash: uidvalidity, last_uid
SEEN_PREFIX = "tsa:imap:seen:"          # one key per Message-ID, stops duplicates
SEEN_TTL_SECONDS = 30 * 24 * 3600


class RedisStore:
    def __init__(self, redis_client):
        self.r = redis_client  # redis.Redis(..., decode_responses=True)

    def get_cursor(self) -> tuple[int | None, int]:
        data = self.r.hgetall(CURSOR_KEY)
        if not data:
            return None, 0
        return int(data["uidvalidity"]), int(data["last_uid"])

    def set_cursor(self, uidvalidity: int, last_uid: int) -> None:
        self.r.hset(CURSOR_KEY, mapping={"uidvalidity": uidvalidity, "last_uid": last_uid})

    def mark_seen(self, message_id: str) -> bool:
        """True if this Message-ID is new (and now marked), False if already handled."""
        return bool(self.r.set(SEEN_PREFIX + message_id, 1, nx=True, ex=SEEN_TTL_SECONDS))

    def unmark_seen(self, message_id: str) -> None:
        self.r.delete(SEEN_PREFIX + message_id)

    def push(self, email: ParsedEmail) -> None:
        self.r.lpush(EMAIL_QUEUE, json.dumps(asdict(email)))


# Worker queues
RESULT_QUEUE = "tsa:timesheets:results"   # one JSON result per processed email
DEAD_QUEUE = "tsa:emails:dead"            # emails that kept failing; inspect by hand
