"""Settings from environment variables / the .env file.

The LLM settings (MODEL_NAME, MODEL_PROVIDER, BASE_URL, API_KEY) are read directly
by app/extraction/timesheet_extractor.py.
"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    imap_host: str
    imap_port: int
    imap_user: str
    imap_password: str
    imap_folder: str
    redis_url: str
    sender_whitelist: list[str]
    require_sender_auth: bool
    idle_timeout: int
    start_from: str
    backfill_days: int
    output_dir: str = "output"
    max_attempts: int = 3


def load_settings() -> Settings:
    from dotenv import load_dotenv

    load_dotenv()
    env = os.environ
    return Settings(
        imap_host=env["IMAP_HOST"],
        imap_port=int(env.get("IMAP_PORT", "993")),
        imap_user=env["IMAP_USER"],
        imap_password=env["IMAP_PASSWORD"].replace(" ", ""),
        imap_folder=env.get("IMAP_FOLDER", "INBOX"),
        redis_url=env.get("REDIS_URL", "redis://localhost:6379/0"),
        sender_whitelist=[w.strip() for w in env.get("SENDER_WHITELIST", "").split(",") if w.strip()],
        require_sender_auth=env.get("REQUIRE_SENDER_AUTH", "true").lower() == "true",
        idle_timeout=int(env.get("IDLE_TIMEOUT", "300")),
        start_from=env.get("START_FROM", "new"),
        backfill_days=int(env.get("BACKFILL_DAYS", "2")),
        output_dir=env.get("OUTPUT_DIR", "output"),
        max_attempts=int(env.get("MAX_ATTEMPTS", "3")),
    )
