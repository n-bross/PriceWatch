from __future__ import annotations

import datetime
import hashlib
import json
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from .barcodes import valid_ean
from .observations import cents


def _iso_date_from_str(date_str: str) -> str | None:
    cleaned = date_str.strip().replace("/", ".").replace("-", ".")
    match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", cleaned)
    if not match:
        return None
    d, m, y = match.groups()
    try:
        dt = datetime.date(int(y), int(m), int(d))
        return dt.isoformat()
    except ValueError:
        return None


def _parse_iso_datetime(dt_str: str) -> datetime.datetime | None:
    if not dt_str:
        return None
    s = dt_str.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.datetime.fromisoformat(s)
    except Exception:
        return None


def _dedup_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    result: list[dict[str, Any]] = []
    for obs in observations:
        key = (
            obs.get("source"),
            obs.get("retailer"),
            obs.get("source_product_id"),
            obs.get("price_cents"),
            obs.get("valid_from"),
            obs.get("valid_until"),
            obs.get("requires_membership"),
            obs.get("conditions_text"),
        )
        if key not in seen:
            seen.add(key)
            result.append(obs)
    return result


def parse_bio_company(
    html: str,
    url: str,
    price_date: str,
    region: str | None = None,
) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")

    valid_from: str | None = None
    valid_until: str | None = None
    page_text = soup.get_text(" ", strip=True)
    date_match = re.search(
        r"Gültig\s+von\s+(\d{1,2}\.\d{1,2}\.\d{4})\s+bis\s+(\d{1,2}\.\d{1,2}\.\d{4})",
        page_text,
        re.IGNORECASE,
    )
    if date_match:
        valid_from = _iso_date_from_str(date_match.group(1))
        valid_until = _iso_date_from_str(date_match.group(2))

    observations: list[dict[str, Any]] = []
    cards = soup.select(".dealscard")
    for card in cards:
        headline_el = card.select_one(".dealscardHeadline")
        name = headline_el.get_text(strip=True) if headline_el else ""
        if not name:
            continue

        brand_el = card.select_one(".dealscardOverline")
        brand = brand_el.get_text(strip=True) if brand_el else None
        if brand == "":
            brand = None

        info_strong = card.select_one(".info strong")
        package_label = info_strong.get_text(strip=True) if info_strong else None
        if package_label == "":
            package_label = None

        euro_el = card.select_one(".dealsprice .euro")
        cent_el = card.select_one(".dealsprice .cent")
        if not euro_el or not cent_el:
            continue

        euro_text = re.sub(r"[^\d]", "", euro_el.get_text())
        cent_text = re.sub(r"[^\d]", "", cent_el.get_text())
        if not euro_text or not cent_text:
            continue
        if len(cent_text) != 2:
            continue

        try:
            price_val = cents(f"{euro_text}.{cent_text}")
        except Exception:
            continue

        if price_val <= 0:
            continue

        hash_payload = f"{brand or ''}|{name}|{package_label or ''}".strip()
        source_product_id = hashlib.sha256(hash_payload.encode("utf-8")).hexdigest()[:16]

        conditions: list[str] = []
        if region:
            conditions.append(f"Region: {region}")

        obs: dict[str, Any] = {
            "source": "bio_company_website",
            "retailer": "Bio Company",
            "source_product_id": source_product_id,
            "name": name,
            "price_cents": price_val,
            "ean": None,
            "price_date": price_date,
            "source_url": url,
            "scope": "unknown",
            "kind": "offer",
            "valid_from": valid_from,
            "valid_until": valid_until,
            "requires_membership": False,
            "conditions_text": "; ".join(conditions) if conditions else None,
            "package_label": package_label,
            "brand": brand,
        }
        observations.append(obs)

    return _dedup_observations(observations)


def parse_denns(
    data: Any,
    url: str,
    price_date: str,
) -> list[dict[str, Any]]:
    if isinstance(data, (str, bytes)):
        try:
            data = json.loads(data)
        except Exception:
            return []

    observations: list[dict[str, Any]] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            if "_id" in node and "title" in node:
                _process_denns_item(node)
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    def _process_denns_item(item: dict[str, Any]) -> None:
        if item.get("hidden") is True:
            return
        if str(item.get("land", "de")).strip().lower() != "de":
            return
        if item.get("bmvOnly") is True:
            return

        name = (item.get("title") or "").strip()
        if not name:
            return

        source_product_id = str(item.get("_id")).strip()
        if not source_product_id:
            return

        brand = (item.get("brand") or "").strip() or None
        package_label = (item.get("subtitle") or "").strip() or None

        explicit_ean: str | None = None
        for key in ("ean", "gtin"):
            candidate = item.get(key)
            if candidate and valid_ean(str(candidate).strip()):
                explicit_ean = str(candidate).strip()
                break

        base_conditions: list[str] = []
        if item.get("shordesc"):
            base_conditions.append(str(item["shordesc"]).strip())
        if item.get("priceAb"):
            base_conditions.append("Ab-Preis (Preis ab angegebenem Wert)")
        if item.get("priceCa"):
            base_conditions.append("Ca-Preis (ungefähre Angabe / Circa-Preis)")

        market_id_list = item.get("marketIdList")
        if isinstance(market_id_list, dict) and market_id_list.get("marketIds"):
            count = len(market_id_list["marketIds"])
            base_conditions.append(f"Verfügbar in {count} teilnehmenden Märkten")
        elif isinstance(market_id_list, list) and market_id_list:
            base_conditions.append(f"Verfügbar in {len(market_id_list)} teilnehmenden Märkten")

        valid_from = str(item.get("validfrom") or "").strip() or None
        valid_until = str(item.get("validto") or "").strip() or None

        raw_price = item.get("price")
        if raw_price is not None and str(raw_price).strip() != "":
            try:
                price_val = cents(raw_price)
                if price_val > 0:
                    cond_text = "; ".join(base_conditions) if base_conditions else None
                    observations.append(
                        {
                            "source": "denns_website",
                            "retailer": "Denns BioMarkt",
                            "source_product_id": source_product_id,
                            "name": name,
                            "price_cents": price_val,
                            "price_qualifier": "from" if item.get("priceAb") else None,
                            "ean": explicit_ean,
                            "price_date": price_date,
                            "source_url": url,
                            "scope": "unknown",
                            "kind": "offer",
                            "valid_from": valid_from,
                            "valid_until": valid_until,
                            "requires_membership": False,
                            "conditions_text": cond_text,
                            "package_label": package_label,
                            "brand": brand,
                        }
                    )
            except Exception:
                pass

        raw_app_price = item.get("priceApp")
        app_from = str(item.get("appValidfrom") or "").strip() or None
        app_until = str(item.get("appValidto") or "").strip() or None

        if raw_app_price is not None and str(raw_app_price).strip() != "":
            if app_from and app_until:
                try:
                    price_app_val = cents(raw_app_price)
                    if price_app_val > 0:
                        app_cond = list(base_conditions)
                        app_cond.append("App-Coupon / Denns App erforderlich")
                        observations.append(
                            {
                                "source": "denns_website",
                                "retailer": "Denns BioMarkt",
                                "source_product_id": source_product_id,
                                "name": name,
                                "price_cents": price_app_val,
                                "ean": explicit_ean,
                                "price_date": price_date,
                                "source_url": url,
                                "scope": "unknown",
                                "kind": "offer",
                                "valid_from": app_from,
                                "valid_until": app_until,
                                "requires_membership": True,
                                "conditions_text": "; ".join(app_cond),
                                "package_label": package_label,
                                "brand": brand,
                            }
                        )
                except Exception:
                    pass

    _walk(data)
    return _dedup_observations(observations)


def parse_netto_dog(
    html: str,
    url: str,
    price_date: str,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    soup = BeautifulSoup(html, "html.parser")

    dom_valid_from: str | None = None
    dom_valid_until: str | None = None
    page_text = soup.get_text(" ", strip=True)
    date_match = re.search(
        r"Angebote\s+vom:?\s*(\d{1,2}[.-]\d{1,2}[.-]\d{4})\s+bis\s+(\d{1,2}[.-]\d{1,2}[.-]\d{4})",
        page_text,
        re.IGNORECASE,
    )
    if date_match:
        dom_valid_from = _iso_date_from_str(date_match.group(1))
        dom_valid_until = _iso_date_from_str(date_match.group(2))

    if dom_valid_from and dom_valid_until:
        cards = soup.select("div[aria-label^='product-']")
        for card in cards:
            h4 = card.select_one("h4")
            name = h4.get_text(" ", strip=True) if h4 else ""
            if not name:
                continue

            desc_el = card.select_one("p")
            desc_text = desc_el.get_text(" ", strip=True) if desc_el else ""

            h3 = card.select_one("h3")
            if not h3:
                continue

            price_raw = h3.get_text(strip=True).replace("<!-- -->", "").strip()
            match = re.search(r"(\d+)[.,](\d{2})", price_raw)
            if not match:
                continue
            euro_part, cent_part = match.groups()
            try:
                price_val = cents(f"{euro_part}.{cent_part}")
            except Exception:
                continue

            if price_val <= 0:
                continue

            card_all_text = card.get_text(" ", strip=True)
            requires_membership = bool(
                re.search(r"Nur\s+mit.*(?:App|Netto\+)", card_all_text, re.IGNORECASE)
                or "Netto-App" in card_all_text
                or "App-Preis" in card_all_text
            )

            source_product_id = hashlib.sha256(f"{name}|{desc_text}".encode("utf-8")).hexdigest()[
                :16
            ]

            conditions: list[str] = []
            conditions.append(card_all_text)
            if requires_membership:
                conditions.append("Nur mit Netto-App")

            observations.append(
                {
                    "source": "netto_dog_website",
                    "retailer": "Netto mit Hund",
                    "source_product_id": source_product_id,
                    "name": name,
                    "price_cents": price_val,
                    "ean": None,
                    "price_date": price_date,
                    "source_url": url,
                    "scope": "unknown",
                    "kind": "offer",
                    "valid_from": dom_valid_from,
                    "valid_until": dom_valid_until,
                    "requires_membership": requires_membership,
                    "conditions_text": "; ".join(conditions) if conditions else None,
                    "package_label": desc_text or None,
                    "brand": None,
                }
            )

    # Decode self.__next_f.push RSC payloads
    push_matches = re.findall(r"self\.__next_f\.push\s*\(\s*(\[.*?\])\s*\)[\s;]*", html, re.DOTALL)
    for raw_push in push_matches:
        try:
            push_data = json.loads(raw_push)
        except Exception:
            continue
        if not isinstance(push_data, list) or len(push_data) < 2:
            continue

        payload_str = push_data[1]
        if not isinstance(payload_str, str):
            continue

        for line in payload_str.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            hex_split = re.match(r"^[0-9a-fA-F]+:(.*)$", line_str)
            candidate_json = hex_split.group(1).strip() if hex_split else line_str

            if candidate_json.startswith(("{", "[")):
                try:
                    parsed_node = json.loads(candidate_json)
                    _extract_netto_json_items(parsed_node, url, price_date, observations)
                except Exception:
                    pass

    return _dedup_observations(observations)


def _extract_netto_json_items(
    node: Any,
    url: str,
    price_date: str,
    out: list[dict[str, Any]],
) -> None:
    if isinstance(node, dict):
        if (
            "id" in node
            and "title" in node
            and "price" in node
            and "startTime" in node
            and "endTime" in node
        ):
            _parse_netto_json_dict(node, url, price_date, out)
        for v in node.values():
            _extract_netto_json_items(v, url, price_date, out)
    elif isinstance(node, list):
        for item in node:
            _extract_netto_json_items(item, url, price_date, out)


def _parse_netto_json_dict(
    item: dict[str, Any],
    url: str,
    price_date: str,
    out: list[dict[str, Any]],
) -> None:
    if item.get("hidePrice") is True or item.get("personalizedOffer") is True:
        return
    if item.get("currency") != "EUR":
        return

    name = str(item.get("title") or "").strip()
    if not name:
        return

    source_product_id = str(item.get("id")).strip()
    if not source_product_id:
        return

    raw_price = item.get("price")
    if raw_price is None or str(raw_price).strip() == "":
        return
    try:
        price_val = cents(raw_price)
    except Exception:
        return
    if price_val <= 0:
        return

    start_raw = str(item.get("startTime") or "").strip()
    end_raw = str(item.get("endTime") or "").strip()

    start_dt = _parse_iso_datetime(start_raw)
    end_dt = _parse_iso_datetime(end_raw)

    valid_from = start_dt.date().isoformat() if start_dt else None
    valid_until = None
    if end_dt:
        if end_dt.hour < 6:
            conservative_date = end_dt.date() - datetime.timedelta(days=1)
            valid_until = conservative_date.isoformat()
        else:
            valid_until = end_dt.date().isoformat()

    ean: str | None = None
    if item.get("type") == "singlebuy":
        candidate_ean = str(item.get("sales_EAN") or item.get("ean") or "").strip()
        if candidate_ean and valid_ean(candidate_ean):
            ean = candidate_ean

    requires_membership = bool(
        item.get("membershipOffer")
        or item.get("memberOnly")
        or item.get("isAppOnly")
        or item.get("requiresApp")
        or "app" in str(item.get("promotionType") or "").lower()
    )

    conditions: list[str] = []
    if start_raw or end_raw:
        conditions.append(f"Angebotszeitraum: {start_raw} bis {end_raw}")
    if item.get("description"):
        conditions.append(str(item["description"]).strip())
    if requires_membership:
        conditions.append("Netto+ App erforderlich")
    if item.get("maximumQuantity"):
        conditions.append(f"Höchstens {item['maximumQuantity']} Stück")
    if item.get("discountValue"):
        conditions.append(f"Rabatt: {item['discountValue']}")

    package_label = str(item.get("description") or "").strip() or None
    brand = None  # The feed's brand='netto' identifies the retailer, not the product brand.

    out.append(
        {
            "source": "netto_dog_website",
            "retailer": "Netto mit Hund",
            "source_product_id": source_product_id,
            "name": name,
            "price_cents": price_val,
            "ean": ean,
            "price_date": price_date,
            "source_url": url,
            "scope": "unknown",
            "kind": "offer",
            "valid_from": valid_from,
            "valid_until": valid_until,
            "requires_membership": requires_membership,
            "conditions_text": "; ".join(conditions) if conditions else None,
            "package_label": package_label,
            "brand": brand,
        }
    )


def parse_alnatura(
    html: str,
    url: str,
    price_date: str,
) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    observations: list[dict[str, Any]] = []

    price_slots = soup.select("[id^='price-slot-']")
    for price_slot in price_slots:
        slot_id = price_slot.get("id", "")
        prod_id = slot_id.replace("price-slot-", "").strip()
        if not prod_id:
            continue

        slot_text = price_slot.get_text(" ", strip=True)
        if "Wählen Sie Ihren Alnatura Markt" in slot_text or "Markt auswählen" in slot_text:
            continue

        match = re.search(r"(\d+[,.]\d{2})\s*€|€\s*(\d+[,.]\d{2})", slot_text)
        if not match:
            continue

        price_str = match.group(1) or match.group(2)
        try:
            price_val = cents(price_str.replace(",", "."))
        except Exception:
            continue
        if price_val <= 0:
            continue

        title_el = soup.select_one(f"#product-title-{prod_id}")
        name = title_el.get_text(" ", strip=True) if title_el else ""
        if not name:
            parent_card = price_slot.find_parent("article") or price_slot.find_parent(
                "div", class_=re.compile(r"product|card", re.I)
            )
            if parent_card:
                fallback_title = parent_card.select_one("h2, h3, h4")
                if fallback_title:
                    name = fallback_title.get_text(" ", strip=True)
        if not name:
            continue

        brand_el = soup.select_one(f"#brand-slot-{prod_id}")
        brand = brand_el.get_text(" ", strip=True) if brand_el else None
        if brand == "":
            brand = None

        weight_el = soup.select_one(f"#weight-slot-{prod_id}")
        package_label = weight_el.get_text(" ", strip=True) if weight_el else None
        if package_label == "":
            package_label = None

        valid_from: str | None = None
        valid_until: str | None = None
        flag = soup.find(id=f"flag-slot-{prod_id}")
        is_dauerpreis = bool(flag and "dauerpreis" in flag.get_text().lower())

        for ancestor in price_slot.parents:
            if not isinstance(ancestor, Tag):
                continue
            ancestor_text = ancestor.get_text(" ", strip=True)
            d_match = re.search(
                r"vom\s+(\d{1,2}\.\d{1,2}\.\d{4})\s*(?:-|–|bis)\s*(\d{1,2}\.\d{1,2}\.\d{4})",
                ancestor_text,
                re.IGNORECASE,
            )
            if d_match:
                valid_from = _iso_date_from_str(d_match.group(1))
                valid_until = _iso_date_from_str(d_match.group(2))
                break

        if is_dauerpreis:
            kind = "regular"
            valid_from = None
            valid_until = None
        elif valid_from and valid_until:
            kind = "offer"
        else:
            continue

        conditions_text = "Standard-Marktkonditionen; Preise können je nach Filiale variieren."

        observations.append(
            {
                "source": "alnatura_website",
                "retailer": "Alnatura",
                "source_product_id": prod_id,
                "name": name,
                "price_cents": price_val,
                "ean": None,
                "price_date": price_date,
                "source_url": url,
                "scope": "unknown",
                "kind": kind,
                "valid_from": valid_from,
                "valid_until": valid_until,
                "requires_membership": False,
                "conditions_text": conditions_text,
                "package_label": package_label,
                "brand": brand,
            }
        )

    return _dedup_observations(observations)
