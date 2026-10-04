import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import String, and_, case, cast, func, literal, or_, select

from .barcodes import barcode_scope, valid_ean
from .catalog import articles, products
from .database import Database, area_stores, normalize, prices
from .observations import observations

RETAILERS_FILE = Path(__file__).resolve().parent / "retailers.json"

EXACT_ALIASES: dict[str, set[str]] = {
    "aldi_nord": {"aldi_nord", "aldi-nord", "aldi nord"},
    "aldi_sued": {"aldi_sued", "aldi-sued", "aldi sued", "aldi süd"},
    "rewe": {"rewe"},
    "netto": {
        "netto_marken_discount",
        "netto-marken-discount",
        "netto marken-discount",
        "netto-online",
    },
    "netto_dog": {
        "netto_dog",
        "netto mit hund",
        "netto-mit-hund",
        "netto schwarz-gelb",
        "netto (mit hund)",
    },
    "lidl": {"lidl"},
    "edeka": {"edeka"},
    "penny": {"penny"},
    "kaufland": {"kaufland"},
    "norma": {"norma"},
    "globus": {"globus"},
    "tegut": {"tegut", "tegut..."},
    "hit": {"hit"},
    "combi": {"combi"},
    "mytime": {"mytime", "mytime.de"},
    "nahkauf": {"nahkauf"},
    "alnatura": {"alnatura"},
    "bio_company": {"bio_company", "bio company"},
    "cap": {"cap", "cap-markt"},
    "denns": {"denns", "denns biomarkt"},
    "diska": {"diska"},
    "famila_nordost": {"famila_nordost", "famila nordost"},
    "famila_nordwest": {"famila_nordwest", "famila nordwest"},
    "feneberg": {"feneberg"},
    "klaus_kock": {"klaus_kock", "k+k", "k+k klaas & kock"},
    "marktkauf": {"marktkauf"},
    "mix_markt": {"mix_markt", "mix markt"},
    "v_markt": {"v_markt", "v-markt"},
    "wasgau": {"wasgau"},
    "markant": {"markant"},
    "konsum_dresden": {"konsum_dresden", "konsum dresden"},
    "konsum_leipzig": {"konsum_leipzig", "konsum leipzig"},
    "lpg": {"lpg", "lpg biomarkt"},
    "dm": {"dm", "dm-drogerie markt"},
    "rossmann": {"rossmann"},
}

AMBIGUOUS_RETAILERS = {"aldi", "netto", "famila"}


def _load_retailers_registry() -> list[dict[str, Any]]:
    if RETAILERS_FILE.exists():
        try:
            return json.loads(RETAILERS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _load_coverage_data() -> tuple[str, dict[str, dict[str, Any]]]:
    pkg_dir = Path(__file__).resolve().parent
    candidates = [
        pkg_dir / "retailer_coverage.json",
        pkg_dir.parent / "data" / "retailer_coverage.json",
        pkg_dir.parent / "data" / "retailer-audit" / "retailer_coverage.json",
        pkg_dir.parent / "retailer_coverage.json",
        pkg_dir.parent.parent / "data" / "retailer_coverage.json",
        pkg_dir.parent.parent / "data" / "retailer-audit" / "retailer_coverage.json",
        pkg_dir.parent.parent / "api" / "data" / "retailer_coverage.json",
        pkg_dir.parent.parent / "api" / "data" / "retailer-audit" / "retailer_coverage.json",
        Path("retailer_coverage.json"),
        Path("data/retailer_coverage.json"),
        Path("api/data/retailer_coverage.json"),
        Path("api/pricewatch_api/retailer_coverage.json"),
    ]
    raw = None
    for p in candidates:
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                break
            except Exception:
                continue

    if not raw:
        return datetime.now(UTC).isoformat(), {}

    checked_at = raw.get("checked_at") if isinstance(raw, dict) else None
    if not checked_at:
        checked_at = datetime.now(UTC).isoformat()

    retailers_raw = raw.get("retailers") if isinstance(raw, dict) else raw
    coverage_map: dict[str, dict[str, Any]] = {}

    if isinstance(retailers_raw, dict):
        for rid, val in retailers_raw.items():
            if isinstance(val, dict):
                coverage_map[rid] = val
    elif isinstance(retailers_raw, list):
        for item in retailers_raw:
            if isinstance(item, dict):
                rid = item.get("id") or item.get("retailer_id")
                if rid:
                    coverage_map[rid] = item

    return checked_at, coverage_map


def _resolve_retailer_id(retailer_input: str | None) -> str | None:
    if not retailer_input:
        return None
    norm = retailer_input.strip().lower()
    if norm in AMBIGUOUS_RETAILERS:
        raise HTTPException(
            status_code=422,
            detail=f"Ambiguous generic retailer '{retailer_input}'. Specify exact subchain.",
        )
    for canon_id, aliases in EXACT_ALIASES.items():
        if norm == canon_id or norm in aliases:
            return canon_id
    raise HTTPException(status_code=422, detail=f"Unknown retailer '{retailer_input}'")


def sql_canonical_retailer(col, *, native=False):
    lowered = func.replace(func.lower(func.trim(col)), "Ü", "ü")
    whens = []
    if not native:
        whens.append((lowered.in_(list(AMBIGUOUS_RETAILERS)), literal("ambiguous:") + lowered))
    else:
        whens.append((lowered == "netto", literal("netto")))
    for canon_id, aliases in EXACT_ALIASES.items():
        all_aliases = {canon_id.lower()} | {a.lower() for a in aliases}
        all_aliases -= AMBIGUOUS_RETAILERS
        whens.append((lowered.in_(list(all_aliases)), literal(canon_id)))
    return case(*whens, else_=lowered)


def _json_extract_field(dialect_name: str, col, field: str):
    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import JSONB

        return cast(col, JSONB)[field].astext
    return func.json_extract(col, f"$.{field}")


def _compute_price_status(
    *,
    valid_from: str | None,
    valid_until: str | None,
    price_date: str | None,
    observed_at: datetime | None,
    today_str: str,
    now_utc: datetime,
) -> str:
    if valid_until and valid_until < today_str:
        return "expired"
    if valid_from and valid_from > today_str:
        return "upcoming"
    if not valid_from and price_date and price_date > today_str:
        return "upcoming"
    stale_date_str = (date.fromisoformat(today_str) - timedelta(days=7)).isoformat()
    if observed_at and observed_at < now_utc - timedelta(days=7):
        return "stale"
    if price_date and price_date < stale_date_str:
        return "stale"
    if valid_from and valid_until and valid_from <= today_str <= valid_until:
        return "currently_advertised"
    if price_date and price_date == today_str:
        return "observed_today"
    if observed_at and observed_at.date().isoformat() == today_str:
        return "observed_today"
    if price_date and price_date < today_str:
        return "recently_observed"
    if observed_at and observed_at.date().isoformat() < today_str:
        return "recently_observed"
    return "undated"


def _is_restricted_ean_expr(ean_col):
    return or_(
        and_(func.length(ean_col) == 8, or_(ean_col.like("0%"), ean_col.like("2%"))),
        and_(func.length(ean_col) == 13, or_(ean_col.like("2%"), ean_col.like("02%"))),
        and_(func.length(ean_col) == 14, or_(ean_col.like("_2%"), ean_col.like("_02%"))),
    )


def register_comparison_routes(app: FastAPI, db: Database) -> None:
    dialect_name = db.engine.dialect.name

    @app.get("/v1/compare")
    def compare_prices(
        q: str | None = Query(default=None),
        ean: str | None = Query(default=None),
        postal_code: str | None = Query(default=None, pattern=r"^\d{5}$"),
        retailer: str | None = Query(default=None),
        include_history: bool = Query(default=False),
        include_membership: bool = Query(default=False),
        limit: int = Query(default=20, ge=1, le=50),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        today = datetime.now(ZoneInfo("Europe/Berlin")).date()
        today_str = today.isoformat()
        now_utc = datetime.now(UTC)
        stale_cutoff = now_utc - timedelta(days=7)

        resolved_retailer = _resolve_retailer_id(retailer)
        target_ean: str | None = None
        q_term: str | None = None

        if ean is not None:
            cleaned_ean = ean.strip()
            if not valid_ean(cleaned_ean):
                raise HTTPException(status_code=422, detail="Invalid EAN checksum or format")
            if barcode_scope(cleaned_ean) == "restricted_circulation" and not resolved_retailer:
                raise HTTPException(
                    status_code=422,
                    detail="Restricted circulation barcode requires explicit retailer",
                )
            target_ean = cleaned_ean
        elif q and q.strip():
            cleaned_q = q.strip()
            if valid_ean(cleaned_q):
                if barcode_scope(cleaned_q) == "restricted_circulation" and not resolved_retailer:
                    raise HTTPException(
                        status_code=422,
                        detail="Restricted circulation barcode requires explicit retailer",
                    )
                target_ean = cleaned_q
            else:
                q_term = normalize(cleaned_q)

        # Scoped unique article identity mapping: count(distinct ean) == 1
        article_map = (
            select(
                func.lower(articles.c.retailer).label("retailer"),
                articles.c.source_product_id.label("source_product_id"),
                articles.c.store_id.label("store_id"),
                func.min(articles.c.ean).label("ean"),
            )
            .group_by(
                func.lower(articles.c.retailer),
                articles.c.source_product_id,
                articles.c.store_id,
            )
            .having(func.count(func.distinct(articles.c.ean)) == 1)
            .cte("article_map")
        )
        store_art = article_map.alias("store_art")
        chain_art = article_map.alias("chain_art")

        store_join = and_(
            or_(prices.c.ean.is_(None), prices.c.ean == ""),
            prices.c.scope == "store",
            store_art.c.retailer == func.lower(prices.c.retailer),
            store_art.c.source_product_id == prices.c.source_product_id,
            store_art.c.store_id == func.coalesce(prices.c.store_id, ""),
        )
        chain_join = and_(
            or_(prices.c.ean.is_(None), prices.c.ean == ""),
            chain_art.c.retailer == func.lower(prices.c.retailer),
            chain_art.c.source_product_id == prices.c.source_product_id,
            chain_art.c.store_id == "",
        )

        resolved_native_ean = func.coalesce(
            func.nullif(prices.c.ean, ""),
            store_art.c.ean,
            chain_art.c.ean,
        )

        native_conditions = []
        p_canon = func.lower(prices.c.retailer)
        if resolved_retailer:
            native_conditions.append(p_canon == resolved_retailer)
        if not include_membership:
            native_conditions.append(prices.c.requires_membership.is_(False))
        if not include_history:
            native_conditions.append(prices.c.is_listed.is_(True))
            native_conditions.append(prices.c.valid_from <= today)
            native_conditions.append(prices.c.valid_until >= today)
            native_conditions.append(prices.c.observed_at >= stale_cutoff)
        if postal_code:
            nearby_stores = (
                select(area_stores.c.store_id)
                .where(
                    or_(
                        area_stores.c.area_postal_code == postal_code,
                        area_stores.c.postal_code == postal_code,
                    ),
                    func.lower(area_stores.c.retailer) == func.lower(prices.c.retailer),
                )
                .correlate(prices)
            )
            native_conditions.append(
                or_(
                    prices.c.scope.in_(["chain_advertised", "online", "unknown", "global"]),
                    and_(
                        prices.c.scope == "postal_code",
                        or_(prices.c.postal_code == postal_code, prices.c.postal_code.is_(None)),
                    ),
                    and_(
                        prices.c.scope == "store",
                        or_(
                            prices.c.postal_code == postal_code,
                            prices.c.store_id.in_(nearby_stores),
                        ),
                    ),
                )
            )

        is_restricted_native = _is_restricted_ean_expr(resolved_native_ean)
        native_key = case(
            (
                and_(resolved_native_ean.isnot(None), resolved_native_ean != ""),
                case(
                    (
                        is_restricted_native,
                        literal("rcn:") + p_canon + ":" + resolved_native_ean,
                    ),
                    else_=literal("ean:") + resolved_native_ean,
                ),
            ),
            else_=literal("article:") + p_canon + ":" + prices.c.source_product_id,
        )
        native_itype = case(
            (
                and_(resolved_native_ean.isnot(None), resolved_native_ean != ""),
                case(
                    (is_restricted_native, literal("restricted_circulation")),
                    else_=literal("global_ean"),
                ),
            ),
            else_=literal("retailer_article"),
        )

        obs_canon_retailer = sql_canonical_retailer(observations.c.retailer)
        obs_source_product_id = func.coalesce(
            _json_extract_field(dialect_name, observations.c.payload_json, "source_product_id"),
            _json_extract_field(dialect_name, observations.c.payload_json, "article_id"),
            _json_extract_field(dialect_name, observations.c.payload_json, "product_id"),
        )
        obs_mem = _json_extract_field(
            dialect_name, observations.c.payload_json, "requires_membership"
        )
        obs_valid_from = _json_extract_field(
            dialect_name, observations.c.payload_json, "valid_from"
        )
        obs_valid_until = _json_extract_field(
            dialect_name, observations.c.payload_json, "valid_until"
        )

        obs_conditions = []
        if resolved_retailer:
            obs_conditions.append(obs_canon_retailer == resolved_retailer)
        if not include_membership:
            obs_conditions.append(
                or_(
                    obs_mem.is_(None),
                    and_(
                        obs_mem != 1,
                        obs_mem != "1",
                        obs_mem != "true",
                        func.lower(cast(obs_mem, String)) != "true",
                    ),
                )
            )
        if not include_history:
            obs_conditions.append(
                or_(
                    and_(
                        observations.c.price_date.isnot(None),
                        observations.c.price_date >= (today - timedelta(days=7)).isoformat(),
                        observations.c.price_date <= today_str,
                    ),
                    and_(
                        obs_valid_from.isnot(None),
                        obs_valid_from <= today_str,
                        obs_valid_until.isnot(None),
                        obs_valid_until >= today_str,
                        or_(
                            observations.c.price_date.is_(None),
                            observations.c.price_date >= (today - timedelta(days=7)).isoformat(),
                        ),
                    ),
                )
            )
        if not include_history:
            obs_conditions.extend(
                [
                    or_(obs_valid_from.is_(None), obs_valid_from <= today_str),
                    or_(obs_valid_until.is_(None), obs_valid_until >= today_str),
                ]
            )
        if postal_code:
            obs_conditions.append(
                or_(
                    observations.c.postal_code == postal_code,
                    observations.c.postal_code.is_(None),
                    observations.c.postal_code == "",
                )
            )

        is_restricted_obs = _is_restricted_ean_expr(observations.c.ean)
        obs_key = case(
            (
                and_(observations.c.ean.isnot(None), observations.c.ean != ""),
                case(
                    (
                        is_restricted_obs,
                        literal("rcn:") + obs_canon_retailer + ":" + observations.c.ean,
                    ),
                    else_=literal("ean:") + observations.c.ean,
                ),
            ),
            (
                and_(obs_source_product_id.isnot(None), obs_source_product_id != ""),
                literal("article:") + obs_canon_retailer + ":" + obs_source_product_id,
            ),
            else_=literal("obs:") + observations.c.id,
        )
        obs_itype = case(
            (
                and_(observations.c.ean.isnot(None), observations.c.ean != ""),
                case(
                    (is_restricted_obs, literal("restricted_circulation")),
                    else_=literal("global_ean"),
                ),
            ),
            else_=literal("retailer_article"),
        )

        target_key: str | None = None
        if target_ean:
            if barcode_scope(target_ean) == "restricted_circulation":
                target_key = f"rcn:{resolved_retailer}:{target_ean}"
            else:
                target_key = f"ean:{target_ean}"

        native_keyed_select = [
            prices.c.id.label("price_id"),
            native_key.label("item_key"),
            native_itype.label("identity_type"),
            resolved_native_ean.label("resolved_ean"),
            prices.c.name.label("name"),
            prices.c.normalized_name.label("normalized_name"),
            prices.c.price_cents.label("price_cents"),
        ]
        obs_keyed_select = [
            observations.c.id.label("obs_id"),
            obs_key.label("item_key"),
            obs_itype.label("identity_type"),
            observations.c.ean.label("resolved_ean"),
            observations.c.name.label("name"),
            observations.c.normalized_name.label("normalized_name"),
            observations.c.price_cents.label("price_cents"),
        ]

        pr_cand = None
        if target_ean:
            native_where = and_(
                *native_conditions,
                or_(
                    prices.c.ean == target_ean,
                    store_art.c.ean == target_ean,
                    chain_art.c.ean == target_ean,
                ),
                native_key == target_key,
            )
            obs_where = and_(
                *obs_conditions,
                observations.c.ean == target_ean,
                obs_key == target_key,
            )
            if not resolved_retailer:
                is_restricted_prod = _is_restricted_ean_expr(products.c.ean)
                prod_key = case(
                    (is_restricted_prod, literal("rcn:catalog:") + products.c.ean),
                    else_=literal("ean:") + products.c.ean,
                )
                prod_itype = case(
                    (is_restricted_prod, literal("restricted_circulation")),
                    else_=literal("global_ean"),
                )
                pr_cand = select(
                    prod_key.label("item_key"),
                    prod_itype.label("identity_type"),
                    products.c.ean.label("ean"),
                    products.c.name.label("name"),
                    literal(2147483647).label("min_price"),
                ).where(products.c.ean == target_ean)
        elif q_term:
            cand_ean_selects = []
            if not resolved_retailer:
                cand_ean_selects.append(
                    select(products.c.ean.label("ean")).where(
                        products.c.normalized_name.contains(q_term, autoescape=True),
                        products.c.ean.isnot(None),
                        products.c.ean != "",
                    )
                )
            cand_ean_selects.append(
                select(resolved_native_ean.label("ean"))
                .select_from(
                    prices.outerjoin(store_art, store_join).outerjoin(chain_art, chain_join)
                )
                .where(
                    *native_conditions,
                    prices.c.normalized_name.contains(q_term, autoescape=True),
                    resolved_native_ean.isnot(None),
                    resolved_native_ean != "",
                )
            )
            cand_ean_selects.append(
                select(observations.c.ean.label("ean")).where(
                    *obs_conditions,
                    observations.c.normalized_name.contains(q_term, autoescape=True),
                    observations.c.ean.isnot(None),
                    observations.c.ean != "",
                )
            )
            cand_eans_cte = (
                cand_ean_selects[0].union(*cand_ean_selects[1:]).cte("cand_eans")
                if len(cand_ean_selects) > 1
                else cand_ean_selects[0].cte("cand_eans")
            )

            cand_art_keys_cte = (
                select(native_key.label("item_key"))
                .select_from(
                    prices.outerjoin(store_art, store_join).outerjoin(chain_art, chain_join)
                )
                .where(
                    *native_conditions,
                    prices.c.normalized_name.contains(q_term, autoescape=True),
                    or_(resolved_native_ean.is_(None), resolved_native_ean == ""),
                )
                .union(
                    select(obs_key.label("item_key")).where(
                        *obs_conditions,
                        observations.c.normalized_name.contains(q_term, autoescape=True),
                        or_(observations.c.ean.is_(None), observations.c.ean == ""),
                    )
                )
                .cte("cand_art_keys")
            )

            native_where = and_(
                *native_conditions,
                or_(
                    prices.c.ean.in_(select(cand_eans_cte.c.ean)),
                    store_art.c.ean.in_(select(cand_eans_cte.c.ean)),
                    chain_art.c.ean.in_(select(cand_eans_cte.c.ean)),
                    native_key.in_(select(cand_art_keys_cte.c.item_key)),
                ),
            )
            obs_where = and_(
                *obs_conditions,
                or_(
                    observations.c.ean.in_(select(cand_eans_cte.c.ean)),
                    obs_key.in_(select(cand_art_keys_cte.c.item_key)),
                ),
            )
            if not resolved_retailer:
                is_restricted_prod = _is_restricted_ean_expr(products.c.ean)
                prod_key = case(
                    (is_restricted_prod, literal("rcn:catalog:") + products.c.ean),
                    else_=literal("ean:") + products.c.ean,
                )
                prod_itype = case(
                    (is_restricted_prod, literal("restricted_circulation")),
                    else_=literal("global_ean"),
                )
                pr_cand = select(
                    prod_key.label("item_key"),
                    prod_itype.label("identity_type"),
                    products.c.ean.label("ean"),
                    products.c.name.label("name"),
                    literal(2147483647).label("min_price"),
                ).where(products.c.normalized_name.contains(q_term, autoescape=True))
        else:
            native_where = and_(*native_conditions)
            obs_where = and_(*obs_conditions)

        native_keyed = (
            select(*native_keyed_select)
            .select_from(prices.outerjoin(store_art, store_join).outerjoin(chain_art, chain_join))
            .where(native_where)
            .cte("native_keyed")
            .prefix_with("MATERIALIZED")
        )
        obs_keyed = (
            select(*obs_keyed_select).where(obs_where).cte("obs_keyed").prefix_with("MATERIALIZED")
        )

        p_cand = select(
            native_keyed.c.item_key.label("item_key"),
            native_keyed.c.identity_type.label("identity_type"),
            native_keyed.c.resolved_ean.label("ean"),
            func.min(native_keyed.c.name).label("name"),
            func.min(native_keyed.c.price_cents).label("min_price"),
        ).group_by(
            native_keyed.c.item_key,
            native_keyed.c.identity_type,
            native_keyed.c.resolved_ean,
        )

        o_cand = select(
            obs_keyed.c.item_key.label("item_key"),
            obs_keyed.c.identity_type.label("identity_type"),
            obs_keyed.c.resolved_ean.label("ean"),
            func.min(obs_keyed.c.name).label("name"),
            func.min(obs_keyed.c.price_cents).label("min_price"),
        ).group_by(
            obs_keyed.c.item_key,
            obs_keyed.c.identity_type,
            obs_keyed.c.resolved_ean,
        )

        union_parts = [p_cand, o_cand]
        if pr_cand is not None:
            union_parts.append(pr_cand)

        cand_union = union_parts[0].union_all(*union_parts[1:]).subquery("cand_union")
        cand_grouped = (
            select(
                cand_union.c.item_key,
                func.min(cand_union.c.identity_type).label("identity_type"),
                func.min(cand_union.c.ean).label("ean"),
                func.min(cand_union.c.name).label("name"),
                func.min(cand_union.c.min_price).label("min_price"),
            )
            .group_by(cand_union.c.item_key)
            .cte("cand_grouped")
        )

        with db.engine.connect() as conn:
            page_query = (
                select(
                    cand_grouped.c.item_key,
                    cand_grouped.c.identity_type,
                    cand_grouped.c.ean,
                    cand_grouped.c.name,
                    cand_grouped.c.min_price,
                    func.count().over().label("full_count"),
                )
                .order_by(
                    cand_grouped.c.min_price.asc(),
                    func.lower(cand_grouped.c.name).asc(),
                    cand_grouped.c.item_key.asc(),
                )
                .limit(limit)
                .offset(offset)
            )
            page_rows = conn.execute(page_query).mappings().all()

            if not page_rows:
                if offset == 0:
                    return {"items": [], "total": 0, "limit": limit, "offset": offset}
                total = conn.scalar(select(func.count()).select_from(cand_grouped)) or 0
                return {"items": [], "total": total, "limit": limit, "offset": offset}

            total = int(page_rows[0]["full_count"])
            selected_page_keys = [r["item_key"] for r in page_rows]

            # Fetch selected identities without repeating the name candidate search.
            native_keyed = (
                select(*native_keyed_select)
                .select_from(
                    prices.outerjoin(store_art, store_join).outerjoin(chain_art, chain_join)
                )
                .where(*native_conditions)
                .cte("native_selected_lookup")
            )
            obs_keyed = select(*obs_keyed_select).where(*obs_conditions).cte("obs_selected_lookup")

            native_price_rows = (
                conn.execute(
                    select(
                        native_keyed.c.item_key,
                        prices.c.retailer,
                        prices.c.name,
                        prices.c.brand,
                        prices.c.package_label,
                        prices.c.price_cents,
                        prices.c.currency,
                        prices.c.source,
                        prices.c.source_url,
                        prices.c.scope,
                        prices.c.postal_code,
                        prices.c.store_id,
                        prices.c.kind,
                        prices.c.valid_from,
                        prices.c.valid_until,
                        prices.c.observed_at,
                        prices.c.requires_membership,
                        prices.c.conditions,
                    )
                    .select_from(native_keyed.join(prices, prices.c.id == native_keyed.c.price_id))
                    .where(native_keyed.c.item_key.in_(selected_page_keys))
                )
                .mappings()
                .all()
            )

            obs_price_rows = (
                conn.execute(
                    select(
                        obs_keyed.c.item_key,
                        observations.c.retailer,
                        observations.c.price_cents,
                        observations.c.price_date,
                        observations.c.postal_code,
                        observations.c.store_id,
                        observations.c.source,
                        observations.c.payload_json,
                    )
                    .select_from(
                        obs_keyed.join(observations, observations.c.id == obs_keyed.c.obs_id)
                    )
                    .where(obs_keyed.c.item_key.in_(selected_page_keys))
                )
                .mappings()
                .all()
            )

            page_eans = [r["ean"] for r in page_rows if r["ean"]]
            cat_metadata: dict[str, dict[str, Any]] = {}
            if page_eans:
                cat_meta_rows = (
                    conn.execute(
                        select(
                            products.c.ean,
                            products.c.name,
                            products.c.brand,
                            products.c.package_label,
                        ).where(products.c.ean.in_(page_eans))
                    )
                    .mappings()
                    .all()
                )
                for cr in cat_meta_rows:
                    cat_metadata[cr["ean"]] = dict(cr)

        items_map: dict[str, dict[str, Any]] = {}
        for r in page_rows:
            key = r["item_key"]
            item_ean = r["ean"]
            meta = cat_metadata.get(item_ean, {}) if item_ean else {}
            items_map[key] = {
                "key": key,
                "ean": item_ean,
                "name": r["name"],
                "brand": meta.get("brand"),
                "package_label": meta.get("package_label"),
                "identity": r["identity_type"],
                "prices": [],
            }

        for row in native_price_rows:
            key = row["item_key"]
            if key not in items_map:
                continue
            vf_str = row["valid_from"].isoformat() if row["valid_from"] else None
            vu_str = row["valid_until"].isoformat() if row["valid_until"] else None
            pd_str = row["observed_at"].date().isoformat() if row["observed_at"] else None
            obs_dt = (
                row["observed_at"].astimezone(UTC)
                if row["observed_at"] and row["observed_at"].tzinfo
                else row["observed_at"].replace(tzinfo=UTC)
                if row["observed_at"]
                else None
            )

            status = _compute_price_status(
                valid_from=vf_str,
                valid_until=vu_str,
                price_date=pd_str,
                observed_at=obs_dt,
                today_str=today_str,
                now_utc=now_utc,
            )
            if not include_history and status in ("historical", "expired", "stale", "upcoming"):
                continue

            scope = row["scope"]
            channel = (
                "online"
                if scope == "online"
                else "instore"
                if scope == "store"
                else "leaflet"
                if scope == "chain_advertised"
                else "app"
                if scope == "app"
                else None
            )
            if not items_map[key]["brand"] and row["brand"]:
                items_map[key]["brand"] = row["brand"]
            if not items_map[key]["package_label"] and row["package_label"]:
                items_map[key]["package_label"] = row["package_label"]

            items_map[key]["prices"].append(
                {
                    "retailer": row["retailer"],
                    "price_cents": row["price_cents"],
                    "currency": row["currency"] or "EUR",
                    "source": row["source"],
                    "source_url": row["source_url"],
                    "scope": scope,
                    "postal_code": row["postal_code"],
                    "store_id": row["store_id"],
                    "channel": channel,
                    "kind": row["kind"],
                    "valid_from": vf_str,
                    "valid_until": vu_str,
                    "price_date": pd_str,
                    "requires_membership": bool(row["requires_membership"]),
                    "conditions": row["conditions"],
                    "bonus_credit_cents": None,
                    "bonus_credit_percent": None,
                    "status": status,
                }
            )

        for row in obs_price_rows:
            key = row["item_key"]
            if key not in items_map:
                continue
            try:
                payload = json.loads(row["payload_json"])
            except Exception:
                payload = {}

            mem_flag = payload.get("requires_membership")
            if not include_membership and mem_flag in (True, 1, "true", "1"):
                continue

            vf_str = payload.get("valid_from")
            vu_str = payload.get("valid_until")
            pd_str = row["price_date"] or payload.get("price_date")

            status = _compute_price_status(
                valid_from=vf_str,
                valid_until=vu_str,
                price_date=pd_str,
                observed_at=None,
                today_str=today_str,
                now_utc=now_utc,
            )
            if not include_history and status in (
                "historical",
                "expired",
                "stale",
                "upcoming",
                "undated",
            ):
                continue

            scope = payload.get("scope") or "unknown"
            channel = payload.get("channel") or (
                "online"
                if scope == "online"
                else "instore"
                if scope == "store"
                else "app"
                if scope == "app"
                else None
            )
            if not items_map[key]["brand"] and payload.get("brand"):
                items_map[key]["brand"] = payload.get("brand")
            if not items_map[key]["package_label"] and payload.get("package_label"):
                items_map[key]["package_label"] = payload.get("package_label")

            conditions = payload.get("conditions") or payload.get("conditions_text")
            items_map[key]["prices"].append(
                {
                    "retailer": row["retailer"],
                    "price_cents": row["price_cents"],
                    "currency": payload.get("currency") or "EUR",
                    "price_qualifier": payload.get("price_qualifier"),
                    "source": row["source"],
                    "source_url": payload.get("source_url") or "",
                    "scope": scope,
                    "postal_code": row["postal_code"] or payload.get("postal_code"),
                    "store_id": row["store_id"] or payload.get("store_id"),
                    "channel": channel,
                    "kind": payload.get("kind") or "unknown",
                    "valid_from": vf_str,
                    "valid_until": vu_str,
                    "price_date": pd_str,
                    "requires_membership": bool(mem_flag in (True, 1, "true", "1")),
                    "conditions": conditions,
                    "bonus_credit_cents": payload.get("bonus_credit_cents"),
                    "bonus_credit_percent": payload.get("bonus_credit_percent"),
                    "status": status,
                }
            )

        page_items = []
        for r in page_rows:
            item = items_map[r["item_key"]]
            browser_prices = {}
            cleaned_prices = []
            for price in item["prices"]:
                canonical = next(
                    (
                        rid
                        for rid, aliases in EXACT_ALIASES.items()
                        if price["retailer"].casefold() in aliases or price["retailer"] == rid
                    ),
                    None,
                )
                if price["source"] != "rewe_browser":
                    cleaned_prices.append(price)
                    continue
                if price["scope"] == "store_channel":
                    price["scope"] = "store"
                dedup = (canonical,) + tuple(
                    price.get(k)
                    for k in (
                        "price_cents",
                        "store_id",
                        "postal_code",
                        "valid_from",
                        "valid_until",
                        "requires_membership",
                        "kind",
                    )
                )
                previous = browser_prices.get(dedup)
                if previous:
                    for field in ("conditions", "bonus_credit_cents", "bonus_credit_percent"):
                        if price.get(field) is not None:
                            previous[field] = price[field]
                else:
                    browser_prices[dedup] = price
                    cleaned_prices.append(price)
            if not include_history:
                # Daily imports accumulate snapshots. Keep the newest date for
                # each price context, and preserve same-day conflicting reports.
                latest_dates: dict[tuple, str] = {}

                def snapshot_context(price):
                    return tuple(
                        str(price.get(field) or "")
                        for field in (
                            "retailer",
                            "source",
                            "source_url",
                            "scope",
                            "postal_code",
                            "store_id",
                            "channel",
                            "kind",
                            "requires_membership",
                            "conditions",
                            "valid_from",
                            "valid_until",
                            "price_qualifier",
                            "bonus_credit_cents",
                            "bonus_credit_percent",
                        )
                    )

                for price in cleaned_prices:
                    context = snapshot_context(price)
                    latest_dates[context] = max(
                        latest_dates.get(context, ""), price.get("price_date") or ""
                    )
                cleaned_prices = [
                    price
                    for price in cleaned_prices
                    if (price.get("price_date") or "") == latest_dates[snapshot_context(price)]
                ]
            item["prices"] = cleaned_prices
            item["prices"].sort(key=lambda p: (p["price_cents"], p["retailer"]))
            page_items.append(item)

        return {
            "items": page_items,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @app.get("/v1/coverage")
    def get_coverage() -> dict[str, Any]:
        checked_at, coverage_map = _load_coverage_data()
        registry = _load_retailers_registry()

        p_canon = func.lower(prices.c.retailer)
        o_canon = sql_canonical_retailer(observations.c.retailer)

        db_counts: dict[str, dict[str, int]] = {}
        with db.engine.connect() as conn:
            for row in conn.execute(
                select(p_canon.label("retailer"), func.count().label("cnt")).group_by(p_canon)
            ).mappings():
                ret = row["retailer"]
                if not ret.startswith("ambiguous:"):
                    db_counts.setdefault(ret, {"price_count": 0, "ean_count": 0})
                    db_counts[ret]["price_count"] += row["cnt"]

            for row in conn.execute(
                select(
                    p_canon.label("retailer"),
                    func.count(func.distinct(prices.c.ean)).label("ean_cnt"),
                )
                .where(prices.c.ean.isnot(None), prices.c.ean != "")
                .group_by(p_canon)
            ).mappings():
                ret = row["retailer"]
                if not ret.startswith("ambiguous:"):
                    db_counts.setdefault(ret, {"price_count": 0, "ean_count": 0})
                    db_counts[ret]["ean_count"] += row["ean_cnt"]

            for row in conn.execute(
                select(o_canon.label("retailer"), func.count().label("cnt")).group_by(o_canon)
            ).mappings():
                ret = row["retailer"]
                if not ret.startswith("ambiguous:"):
                    db_counts.setdefault(ret, {"price_count": 0, "ean_count": 0})
                    db_counts[ret]["price_count"] += row["cnt"]

            for row in conn.execute(
                select(
                    o_canon.label("retailer"),
                    func.count(func.distinct(observations.c.ean)).label("ean_cnt"),
                )
                .where(observations.c.ean.isnot(None), observations.c.ean != "")
                .group_by(o_canon)
            ).mappings():
                ret = row["retailer"]
                if not ret.startswith("ambiguous:"):
                    db_counts.setdefault(ret, {"price_count": 0, "ean_count": 0})
                    db_counts[ret]["ean_count"] += row["ean_cnt"]

        retailer_rows: list[dict[str, Any]] = []
        for entry in registry:
            rid = entry["id"]
            rname = entry["name"]

            stats = db_counts.get(rid, {"price_count": 0, "ean_count": 0})
            total_prices = stats["price_count"]
            total_eans = stats["ean_count"]

            cov_entry = coverage_map.get(rid)
            if cov_entry:
                full_price_list_downloaded = cov_entry.get("full_price_list_downloaded", False)
                price_status = cov_entry.get("price_status", "unknown")
                reason = cov_entry.get("reason", "unknown")
                attempts = cov_entry.get("attempts", [])
                downloaded_pdfs = cov_entry.get("downloaded_pdfs", [])
            else:
                full_price_list_downloaded = False
                price_status = "unknown"
                reason = "No audit coverage data available"
                attempts = []
                downloaded_pdfs = []

            retailer_rows.append(
                {
                    "id": rid,
                    "name": rname,
                    "full_price_list_downloaded": full_price_list_downloaded,
                    "price_status": price_status,
                    "reason": reason,
                    "attempts": attempts,
                    "downloaded_pdfs": downloaded_pdfs,
                    "price_count": total_prices,
                    "ean_count": total_eans,
                }
            )

        return {
            "checked_at": checked_at,
            "retailers": retailer_rows,
        }
