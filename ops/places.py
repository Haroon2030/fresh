"""Smart place search for Saudi map picker."""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

logger = logging.getLogger(__name__)

BIAS_LAT = 24.7136
BIAS_LNG = 46.6753
SA_VIEWBOX = "34.5,32.2,55.7,16.0"
USER_AGENT = "FarshOperations/1.0 (place-search; contact=ops@farsh.local)"

# Fallback landmarks when external APIs fail (common Saudi spots)
SA_LANDMARKS = [
    {"title": "الرياض", "subtitle": "مدينة", "label": "الرياض، المملكة العربية السعودية", "lat": 24.7136, "lng": 46.6753},
    {"title": "حي العليا", "subtitle": "الرياض", "label": "حي العليا، الرياض", "lat": 24.6931, "lng": 46.6855},
    {"title": "حي السليمانية", "subtitle": "الرياض", "label": "حي السليمانية، الرياض", "lat": 24.6980, "lng": 46.7010},
    {"title": "حي الملز", "subtitle": "الرياض", "label": "حي الملز، الرياض", "lat": 24.6620, "lng": 46.7350},
    {"title": "حي النسيم", "subtitle": "الرياض", "label": "حي النسيم، الرياض", "lat": 24.7400, "lng": 46.8200},
    {"title": "حي الياسمين", "subtitle": "الرياض", "label": "حي الياسمين، الرياض", "lat": 24.8200, "lng": 46.6400},
    {"title": "طريق الملك فهد", "subtitle": "الرياض", "label": "طريق الملك فهد، الرياض", "lat": 24.7130, "lng": 46.6750},
    {"title": "بوليفارد رياض سيتي", "subtitle": "الرياض", "label": "بوليفارد رياض سيتي، الرياض", "lat": 24.7675, "lng": 46.6710},
    {"title": "الرياض بارك", "subtitle": "الرياض", "label": "الرياض بارك، الرياض", "lat": 24.7705, "lng": 46.6430},
    {"title": "نخيل مول", "subtitle": "الرياض", "label": "نخيل مول، الرياض", "lat": 24.7430, "lng": 46.6620},
    {"title": "العثيم مول", "subtitle": "الرياض", "label": "العثيم مول، الرياض", "lat": 24.7800, "lng": 46.7000},
    {"title": "بانوراما مول", "subtitle": "الرياض", "label": "بانوراما مول، الرياض", "lat": 24.6920, "lng": 46.6700},
    {"title": "جدة", "subtitle": "مدينة", "label": "جدة، المملكة العربية السعودية", "lat": 21.4858, "lng": 39.1925},
    {"title": "حي الحمراء", "subtitle": "جدة", "label": "حي الحمراء، جدة", "lat": 21.5433, "lng": 39.1728},
    {"title": "البلد", "subtitle": "جدة", "label": "البلد التاريخية، جدة", "lat": 21.4850, "lng": 39.1870},
    {"title": "مكة المكرمة", "subtitle": "مدينة", "label": "مكة المكرمة، المملكة العربية السعودية", "lat": 21.3891, "lng": 39.8579},
    {"title": "المدينة المنورة", "subtitle": "مدينة", "label": "المدينة المنورة، المملكة العربية السعودية", "lat": 24.5247, "lng": 39.5692},
    {"title": "الدمام", "subtitle": "مدينة", "label": "الدمام، المملكة العربية السعودية", "lat": 26.4207, "lng": 50.0888},
    {"title": "الخبر", "subtitle": "مدينة", "label": "الخبر، المملكة العربية السعودية", "lat": 26.2172, "lng": 50.1971},
    {"title": "الطائف", "subtitle": "مدينة", "label": "الطائف، المملكة العربية السعودية", "lat": 21.2703, "lng": 40.4158},
    {"title": "أبها", "subtitle": "مدينة", "label": "أبها، المملكة العربية السعودية", "lat": 18.2164, "lng": 42.5053},
    {"title": "تبوك", "subtitle": "مدينة", "label": "تبوك، المملكة العربية السعودية", "lat": 28.3838, "lng": 36.5550},
]


def _headers():
    return {"User-Agent": USER_AGENT, "Accept": "application/json"}


def _norm_key(lat, lng, label: str) -> str:
    try:
        return f"{round(float(lat), 4)}|{round(float(lng), 4)}|{label[:40]}"
    except (TypeError, ValueError):
        return label[:60]


def _score_item(q: str, label: str, city: str = "", kind: str = "") -> int:
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
        score += 35
    q_tokens = [t for t in qn.split() if len(t) > 1]
    for t in q_tokens:
        if t in ln:
            score += 14
        if t in cn:
            score += 8
    kind_l = (kind or "").lower()
    if any(k in kind_l for k in ("shop", "retail", "mall", "suburb", "neighbourhood", "commercial")):
        score += 8
    if any(x in ln for x in ("سعود", "رياض", "جدة", "مكة", "riyadh", "jeddah")):
        score += 5
    return score


def _from_landmarks(q: str) -> list[dict]:
    qn = (q or "").strip().lower()
    out = []
    for item in SA_LANDMARKS:
        blob = f"{item['title']} {item['subtitle']} {item['label']}".lower()
        score = _score_item(qn, blob, item["subtitle"], "landmark")
        if score < 12 and qn not in blob:
            continue
        out.append(
            {
                **item,
                "source": "local",
                "kind": "landmark",
                "score": score + 20,
            }
        )
    return out


def _from_nominatim(q: str, limit: int = 8) -> list[dict]:
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
        r = requests.get(url, params=params, headers=_headers(), timeout=12)
        if r.status_code != 200:
            logger.warning("Nominatim HTTP %s", r.status_code)
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
            or addr.get("suburb")
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


def _from_photon(q: str, limit: int = 8) -> list[dict]:
    url = "https://photon.komoot.io/api/"
    params = {"q": q, "lang": "ar", "limit": limit, "lat": BIAS_LAT, "lon": BIAS_LNG}
    try:
        r = requests.get(url, params=params, headers=_headers(), timeout=8)
        if r.status_code != 200:
            return []
        features = (r.json() or {}).get("features") or []
    except requests.RequestException:
        return []

    out = []
    for f in features:
        props = f.get("properties") or {}
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        lng, lat = coords[0], coords[1]
        country = (props.get("country") or props.get("countrycode") or "").lower()
        if country and country not in ("saudi arabia", "sa", "السعودية") and "arab" not in country:
            if abs(float(lat) - BIAS_LAT) > 8 or abs(float(lng) - BIAS_LNG) > 10:
                continue
        name = props.get("name") or props.get("street") or ""
        city = props.get("city") or props.get("town") or props.get("state") or ""
        parts = [p for p in [name, props.get("street"), city, props.get("state"), props.get("country")] if p]
        seen, uniq = set(), []
        for p in parts:
            if p not in seen:
                seen.add(p)
                uniq.append(p)
        label = "، ".join(uniq) if uniq else name
        if not label:
            continue
        kind = props.get("osm_value") or props.get("type") or ""
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


def search_places(query: str, *, limit: int = 10) -> list[dict]:
    q = (query or "").strip()
    if len(q) < 2:
        return []

    variants = [q]
    if "سعود" not in q and "saudi" not in q.lower():
        variants.append(f"{q} السعودية")
    if "رياض" not in q and "riyadh" not in q.lower() and "جدة" not in q:
        variants.append(f"{q} الرياض")
    if any(x in q for x in ("فرع", "مول", "سوق", "هايبر")):
        variants.append(f"{q} متجر")
        variants.append(f"{q} الرياض")
    if "نخيل" in q and "مول" not in q:
        variants.append("نخيل مول الرياض")
    if "بوليفارد" in q or "boulevard" in q.lower():
        variants.append("بوليفارد الرياض")

    seen_v, uniq_v = set(), []
    for v in variants:
        if v not in seen_v:
            seen_v.add(v)
            uniq_v.append(v)
    variants = uniq_v[:3]

    pooled: list[dict] = []
    # Free sources only: local landmarks + OpenStreetMap Nominatim + Photon
    pooled.extend(_from_landmarks(q))

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = []
        for v in variants:
            futures.append(pool.submit(_from_nominatim, v, 6))
            futures.append(pool.submit(_from_photon, v, 6))
        for fut in as_completed(futures):
            try:
                pooled.extend(fut.result() or [])
            except Exception:
                logger.exception("place search worker failed")

    best: dict[str, dict] = {}
    for item in pooled:
        key = _norm_key(item["lat"], item["lng"], item.get("title") or item.get("label") or "")
        prev = best.get(key)
        if not prev or item.get("score", 0) > prev.get("score", 0):
            best[key] = item

    ranked = sorted(best.values(), key=lambda x: (-x.get("score", 0), x.get("title") or ""))
    return ranked[:limit]
