"""Worker: take queued emails, extract and validate every timesheet, save the results.

    uv run python -m app.run_worker

You can run more than one worker to process emails in parallel; each email is taken
by exactly one worker (Redis BRPOP).
"""
import json
import logging
import re
import time
from dataclasses import asdict
from pathlib import Path

import redis

from app.config import Settings, load_settings
from app.mail.store import DEAD_QUEUE, EMAIL_QUEUE, RESULT_QUEUE
from app.pipeline import ReadTools, process_email

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("worker")


def build_tools(settings: Settings) -> ReadTools:
    # Imported here: Docling and LangChain are slow to load.
    from app.extraction.document_extraction import extract_document_bytes, get_converter
    from app.extraction.rules import build_validation_report
    from app.extraction.timesheet_extractor import extract_timesheet_fields
    from app.mail.imap_source import ImapSource

    def fetch_message(job: dict):
        with ImapSource(settings) as source:
            return source.fetch_message(job["imap_uid"], job["uidvalidity"], job["message_id"])

    log.info("Loading Docling OCR models (first start can take a minute)...")
    get_converter()
    return ReadTools(
        fetch_message=fetch_message,
        document_to_text=extract_document_bytes,
        extract_fields=extract_timesheet_fields,
        validate=build_validation_report,
    )


def save_result(r: redis.Redis, out_dir: Path, result) -> Path:
    data = asdict(result)
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    safe_subject = re.sub(r"[^A-Za-z0-9_-]+", "_", result.subject or "no_subject")[:40]
    path = out_dir / f"{result.uidvalidity}-{result.imap_uid}_{safe_subject}.json"
    path.write_text(payload, encoding="utf-8")
    r.lpush(RESULT_QUEUE, json.dumps(data, ensure_ascii=False))
    return path


def main() -> None:
    settings = load_settings()
    r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    out_dir = Path(settings.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tools = build_tools(settings)
    log.info("Worker waiting for emails on %s", EMAIL_QUEUE)

    while True:
        try:
            item = r.brpop(EMAIL_QUEUE, timeout=30)
        except KeyboardInterrupt:
            log.info("Stopped")
            return
        if item is None:
            continue

        job = json.loads(item[1])
        label = f"UID {job.get('imap_uid')} {job.get('subject')!r}"
        started = time.monotonic()
        try:
            result = process_email(job, tools)
        except Exception:
            job["_attempts"] = job.get("_attempts", 0) + 1
            log.exception("Failed to process %s (attempt %d)", label, job["_attempts"])
            if job["_attempts"] >= settings.max_attempts:
                r.lpush(DEAD_QUEUE, json.dumps(job))
                log.error("Gave up on %s; moved to %s", label, DEAD_QUEUE)
            else:
                time.sleep(2 ** job["_attempts"])
                r.rpush(EMAIL_QUEUE, json.dumps(job))  # retried next
            continue

        path = save_result(r, out_dir, result)
        log.info("%s -> %s, %d timesheet(s), %d skipped, %d failed in %.1fs (%s)",
                 label, result.state, len(result.timesheets), len(result.skipped),
                 len(result.failures), time.monotonic() - started, path.name)


if __name__ == "__main__":
    main()
