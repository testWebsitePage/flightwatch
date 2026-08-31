"""两个数据源。stdlib only — GitHub Actions 上不用装任何东西。"""
import json, os, time, urllib.parse, urllib.request, urllib.error

UA = "flightwatch/1.0"


def _get(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# =====================================================================
#  广度层 — Travelpayouts (免费, 缓存数据, 一次拿整月)
# =====================================================================

TP_BASE = "https://api.travelpayouts.com"


def tp_month_matrix(origin, dest, month, currency="usd", token=None, retries=3):
    """一次调用返回该月每一天的最低价。month 格式 'YYYY-MM-01'。"""
    token = token or os.environ.get("TP_TOKEN", "")
    if not token:
        return []
    qs = urllib.parse.urlencode({
        "currency": currency, "origin": origin, "destination": dest,
        "month": month, "show_to_affiliates": "true", "token": token})
    url = "%s/v2/prices/month-matrix?%s" % (TP_BASE, qs)
    for k in range(retries):
        try:
            d = _get(url)
            out = []
            for row in (d.get("data") or []):
                if not row.get("depart_date") or not row.get("value"):
                    continue
                out.append({"depart_date": row["depart_date"][:10],
                            "price": float(row["value"]),
                            "changes": row.get("number_of_changes"),
                            "found_at": row.get("found_at")})
            return out
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                time.sleep(2 + 3 * k); continue
            return []
        except Exception:
            time.sleep(1 + 2 * k)
    return []


# =====================================================================
#  精度层 — SerpApi Google Flights (250/月, 一次一个日期组合)
# =====================================================================

SERP_BASE = "https://serpapi.com/search.json"


def serp_account(api_key=None):
    """SerpApi 官方的剩余额度。查这个不消耗搜索次数 —— 它是配额的权威来源，
    比我们本地账本可靠（免费档按注册日循环，不是自然月）。"""
    api_key = api_key or os.environ.get("SERPAPI_KEY", "")
    if not api_key:
        return None
    try:
        url = "https://serpapi.com/account?" + urllib.parse.urlencode({"api_key": api_key})
        return _get(url, timeout=30)
    except Exception:
        return None


def serp_multicity(legs, adults=1, travel_class=1, currency="USD", api_key=None, retries=3):
    """legs = [(from, to, 'YYYY-MM-DD'), ...]  from/to 可以是 'WUH,CSX' 这种多机场。"""
    api_key = api_key or os.environ.get("SERPAPI_KEY", "")
    if not api_key:
        raise RuntimeError("SERPAPI_KEY 未设置")
    mcj = [{"departure_id": a, "arrival_id": b, "date": d} for a, b, d in legs]
    qs = urllib.parse.urlencode({
        "engine": "google_flights", "type": "3",
        "multi_city_json": json.dumps(mcj, separators=(",", ":")),
        "adults": str(adults), "travel_class": str(travel_class),
        "currency": currency, "hl": "en", "gl": "us",
        "deep_search": "true", "api_key": api_key})
    url = "%s?%s" % (SERP_BASE, qs)
    last = None
    for k in range(retries):
        try:
            return _get(url, timeout=90)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode()[:300]
            except Exception:
                pass
            last = "HTTP %s %s" % (e.code, body)
            if e.code in (429, 503):
                time.sleep(5 + 5 * k); continue
            break
        except Exception as e:
            last = str(e); time.sleep(3 + 3 * k)
    raise RuntimeError("SerpApi 调用失败: %s" % last)


def parse_serp(d):
    """把 SerpApi 响应压成我们要存的字段。"""
    flights = (d.get("best_flights") or []) + (d.get("other_flights") or [])
    if not flights:
        return None
    flights = [f for f in flights if f.get("price")]
    if not flights:
        return None
    best = min(flights, key=lambda f: f["price"])

    airlines, stops = [], []
    for seg in best.get("flights", []):
        a = seg.get("airline")
        if a and a not in airlines:
            airlines.append(a)
    for lay in best.get("layovers", []):
        if lay.get("id"):
            stops.append(lay["id"])

    pi = d.get("price_insights") or {}
    tr = pi.get("typical_price_range") or [None, None]

    return {
        "price": float(best["price"]),
        "airlines": " / ".join(airlines[:4]),
        "duration_min": best.get("total_duration"),
        "stops": ",".join(stops),
        "price_level": pi.get("price_level"),
        "typical_low": tr[0], "typical_high": tr[1],
        "booking_url": (d.get("search_metadata") or {}).get("google_flights_url"),
        "raw": {"best": best, "price_insights": pi},
    }
