import re
from datetime import UTC, date, datetime
from urllib.parse import urlparse

from .flyers import MAX_PDF_BYTES, FlyerInfo
from .sources import SourceError
from .web_sources import client, get

LIDL_URL = "https://www.lidl.de/c/online-prospekte/s10005610/"


def discover_lidl_flyer(on: date | None = None):
    with client() as c:
        html = get(c, LIDL_URL).text
        matches = set(
            re.findall(r"aktionsprospekt-(\d{2}-\d{2}-\d{4})-(\d{2}-\d{2}-\d{4})-([a-z0-9]+)", html)
        )
        today = on or datetime.now(UTC).date()
        candidates = []
        for start, end, suffix in matches:
            first, last = [datetime.strptime(v, "%d-%m-%Y").date() for v in [start, end]]
            if first <= today <= last:
                candidates.append((first, last, f"aktionsprospekt-{start}-{end}-{suffix}"))
        if not candidates:
            raise SourceError("No currently valid Lidl action flyer found")
        first, last, slug = sorted(candidates)[-1]
        data = get(
            c,
            "https://endpoints.leaflets.schwarz/v4/flyer?"
            f"flyer_identifier={slug}&region_id=0&region_code=0",
        ).json()["flyer"]
        if date.fromisoformat(data["offerStartDate"]) != first or (
            date.fromisoformat(data["offerEndDate"]) != last
        ):
            raise SourceError("Lidl viewer and offer dates disagree")
        url = data["pdfUrl"]
        if urlparse(url).scheme != "https" or urlparse(url).hostname != "assets.leaflets.schwarz":
            raise SourceError("Unexpected Lidl PDF host")
    info = FlyerInfo(
        title=f"Lidl Aktionsprospekt {data['title']} (Standardansicht, Region 0)",
        retailer="lidl",
        source_url=url,
        valid_from=first,
        valid_until=last,
        scope="chain_advertised",
        region_label="Standardprospekt; Filialgeltung nicht bestätigt",
    )
    return info


def download_lidl_pdf(url: str):
    if urlparse(url).scheme != "https" or urlparse(url).hostname != "assets.leaflets.schwarz":
        raise SourceError("Unexpected Lidl PDF host")
    try:
        with client() as c, c.stream("GET", url) as pdf:
            pdf.raise_for_status()
            content = bytearray()
            for chunk in pdf.iter_bytes(1024 * 1024):
                content.extend(chunk)
                if len(content) > MAX_PDF_BYTES:
                    raise SourceError("Lidl PDF exceeds 80 MiB")
        return bytes(content)
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError("Lidl PDF download failed") from exc


def fetch_lidl_flyer():
    info = discover_lidl_flyer()
    return info, download_lidl_pdf(str(info.source_url))
