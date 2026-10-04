import json

import httpx
import pytest

from pricewatch_api.conditional_fetch import ConditionalFetcher, SourceCooldown


def test_revalidation_reuses_body_but_error_does_not_refresh_cache(tmp_path):
    calls = []
    statuses = iter([200, 304, 503])

    def handler(request):
        calls.append(request)
        return httpx.Response(next(statuses), text="fresh", headers={"ETag": "v1"})

    fetcher = ConditionalFetcher(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert fetcher.fetch(client, "https://example.org/prices") == ("fresh", 200)
        assert fetcher.fetch(client, "https://example.org/prices") == ("fresh", 304)
        assert calls[1].headers["If-None-Match"] == "v1"
        cache = next(tmp_path.glob("*.json"))
        before = cache.read_text()
        with pytest.raises(httpx.HTTPStatusError):
            fetcher.fetch(client, "https://example.org/prices")
        assert cache.read_text() == before


def test_cooldown_survives_next_process(tmp_path):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(429, headers={"Retry-After": "3600"})
        )
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            ConditionalFetcher(tmp_path).fetch(client, "https://example.org/prices")
        with pytest.raises(SourceCooldown):
            ConditionalFetcher(tmp_path).fetch(client, "https://example.org/prices")
    assert "checked_at" not in json.loads(next(tmp_path.glob("*.json")).read_text())


def test_unconditional_304_is_not_evidence(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(304))) as client:
        with pytest.raises(ValueError):
            ConditionalFetcher(tmp_path).fetch(client, "https://example.org/prices")
