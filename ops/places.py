"""Smart place search for Saudi map picker (Photon + Nominatim)."""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

logger = logging.getLogger(__name__)

# Center bias: Riyadh
BIAS_LAT = 24.7136
BIAS_LNG = 46.6753
# Rough Saudi bounding box for Nominatim viewbox (left, top, right, bottom)
SA_VIEWBOX = "34.5,32.2,55.7,16.0"

USER_AGENT = "FarshOperations/1.0 (place-search)"


def _headers():
    return {"User-Agent": USER_AGENT, "Accept": "application/json"}


def _norm_key(lat, lng, label: str) -> str:
    try:
        return f"{round(float(lat), 4)}|{round(float(lng), 4)}|{label[:40]}"
    except (TypeError, ValueError):
        return label[:60]


def _score_item(q: str, label: str, city: str = "", kind: str = "") -> int:
    """Higher = better match for what the user typed."""
    qn = re.sub(r"\s+", " ", (q or "").strip().lower())
    ln = re.sub(r"\s+", " ", (label or "").strip().lower())
    cn = (city or "").strip().lower()
    score = 0
    if not qn or not ln:
        return 0
    if ln == qn:
        score += 100
    if ln.startswith(qn):
        score += 50
    if qn in ln:
        score += 30
    # token overlap
    q_tokens = [t for t in qn.split() if len(t) > 1]
    for t in q_tokens:
        if t in ln:
            score += 12
        if t in cn:
            score += 6
    # Prefer shops / amenity / suburb for branch lookups
    kind_l = (kind or "").lower()
    if any(k in kind_l for k in ("shop", "retail", "mall", "suburb", "neighbourhood", "commercial")):
        score += 8
    if "saudi" in ln or "السعودية" in ln or "الرياض" in ln or "riyadh" in ln:
        score += 5
    return score


def _from_photon(q: str, limit: int = 8) -> list[dict]:
    url = "https://photon.komoot.io/api/"
    params = {
        "q": q,
        "lang": "ar",
        "limit": limit,
        "lat": BIAS_LAT,
        "lon": BIAS_LNG,
    }
    try:
        r = requests.get(url, params=params, headers=_headers(), timeout=8)
        if r.status_code != 200:
            return []
        features = (r.json() or {}).get("features") or []
    except requests.RequestException:
        logger.exception("Photon search failed")
        return []

    out = []
    for f in features:
        props = f.get("properties") or {}
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        lng, lat = coords[0], coords[1]
        # Prefer Saudi / nearby Gulf; soft filter
        country = (props.get("country") or props.get("countrycode") or "").lower()
        if country and country not in ("saudi arabia", "sa", "السعودية") and "arab" not in country:
            # still allow if close to bias (within ~8 deg)
            if abs(float(lat) - BIAS_LAT) > 8 or abs(float(lng) - BIAS_LNG) > 10:
                continue
        name = props.get("name") or props.get("street") or ""
        city = props.get("city") or props.get("town") or props.get("state") or ""
        parts = [p for p in [name, props.get("street"), city, props.get("state"), props.get("country")] if p]
        # unique preserve order
        seen = set()
        uniq = []
        for p in parts:
            if p not in seen:
                seen.add(p)
                uniq.append(p)
        label = "، ".join(uniq) if uniq else name
        if not label:
            continue
        kind = props.get("osm_value") or props.get("type") or props.get("osm_key") or ""
        out.append(
            {
                "lat": float(lat),
                "lng": float(lng),
                "label": label[:255],
                "title": (name or label)[:120],
                "subtitle": "، ".join([p for p in [city, props.get("state")] if p])[:160],
                "source": "photon",
                "kind": kind,
                "score": _score_item(q, label, city, kind),
            }
        )
    return out


def _from_nominatim(q: str, limit: int = 6) -> list[dict]:
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "format": "jsonv2",
        "q": q,
        "countrycodes": "sa",
        "limit": limit,
        "addressdetails": 1,
        "accept-language": "ar",
        "viewbox": SA_VIEWBOX,
        "bounded": 0,
    }
    try:
        r = requests.get(url, params=params, headers=_headers(), timeout=8)
        if r.status_code != 200:
            return []
        rows = r.json() or []
    except requests.RequestException:
        logger.exception("Nominatim search failed")
        return []

    out = []
    for item in rows:
        lat = item.get("lat")
        lon = item.get("lon")
        if lat is None or lon is None:
            continue
        addr = item.get("address") or {}
        title = (
            item.get("name")
            or addr.get("shop")
            or addr.get("amenity")
            or addr.get("building")
            or addr.get("road")
            or (item.get("display_name") or "").split(",")[0]
        )
        city = addr.get("city") or addr.get("town") or addr.get("suburb") or addr.get("state") or ""
        label = item.get("display_name") or title
        kind = item.get("type") or item.get("class") or ""
        out.append(
            {
                "lat": float(lat),
                "lng": float(lon),
                "label": str(label)[:255],
                "title": str(title)[:120],
                "subtitle": str(city)[:160],
                "source": "nominatim",
                "kind": kind,
                "score": _score_item(q, label, city, kind),
            }
        )
    return out


def search_places(query: str, *, limit: int = 10) -> list[dict]:
    """
    Smart multi-source place search biased to Saudi Arabia.
    Returns ranked list: title, subtitle, label, lat, lng.
    """
    q = (query or "").strip()
    if len(q) < 2:
        return []

    variants = [q]
    # Enrich Arabic/local queries
    if "سعود" not in q and "saudi" not in q.lower():
        variants.append(f"{q} السعودية")
    if "رياض" not in q and "riyadh" not in q.lower():
        variants.append(f"{q} الرياض")
    if "فرع" in q or "مول" in q or "سوق" in q or "هايبر" in q:
        variants.append(f"{q} متجر")
        variants.append(f"{q} الرياض")
    # Common mall shorthand
    if "نخيل" in q and "مول" not in q:
        variants.append("نخيل مول الرياض")
    if "بوليفارد" in q or "boulevard" in q.lower():
        variants.append("بوليفارد الرياض")

    # Deduplicate variants
    seen_v = []
    for v in variants:
        if v not in seen_v:
            seen_v.append(v)
    variants = seen_v[:3]

    pooled: list[dict] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = []
        for v in variants:
            futures.append(pool.submit(_from_photon, v, 8))
            futures.append(pool.submit(_from_nominatim, v, 5))
        for fut in as_completed(futures):
            try:
                pooled.extend(fut.result() or [])
            except Exception:
                logger.exception("place search worker failed")

    # Merge by approximate coordinates + label
    best: dict[str, dict] = {}
    for item in pooled:
        key = _norm_key(item["lat"], item["lng"], item.get("title") or item.get("label") or "")
        prev = best.get(key)
        if not prev or item.get("score", 0) > prev.get("score", 0):
            best[key] = item

    ranked = sorted(best.values(), key=lambda x: (-x.get("score", 0), x.get("title") or ""))
    return ranked[:limit]
