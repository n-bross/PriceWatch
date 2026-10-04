"""Disk-backed conditional requests; cached bodies require live revalidation."""

import hashlib
import json
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path


class SourceCooldown(Exception):
    pass


def atomic_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def retry_seconds(value):
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            seconds = 300
    return max(60, min(86400, seconds))


class ConditionalFetcher:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def fetch(self, client, url):
        path = self.directory / (hashlib.sha256(url.encode()).hexdigest() + ".json")
        cached = json.loads(path.read_text()) if path.exists() else {}
        if cached.get("retry_after_epoch", 0) > time.time():
            raise SourceCooldown("Source is still in cooldown")
        headers = {}
        if "body" in cached:
            if cached.get("etag"):
                headers["If-None-Match"] = cached["etag"]
            if cached.get("last_modified"):
                headers["If-Modified-Since"] = cached["last_modified"]
        response = client.get(url, headers=headers)
        if response.status_code in (403, 429):
            cached["retry_after_epoch"] = time.time() + retry_seconds(
                response.headers.get("Retry-After")
            )
            atomic_json(path, cached)
            response.raise_for_status()
        if response.status_code == 304:
            if not headers or "body" not in cached:
                raise ValueError("304 without a validated cached representation")
            body = cached["body"]
        else:
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError(f"Unexpected HTTP status {response.status_code}")
            body = response.text
            cached = {"body": body}
        cached.update(
            etag=response.headers.get("ETag", cached.get("etag")),
            last_modified=response.headers.get("Last-Modified", cached.get("last_modified")),
            checked_at=datetime.now(UTC).isoformat(),
            retry_after_epoch=0,
        )
        atomic_json(path, cached)
        return body, response.status_code
