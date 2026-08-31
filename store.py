"""SQLite storage. Every observation is kept forever — the price history IS the product."""
import sqlite3, os, json, datetime

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flights.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS leg_price (          -- 广度层：Travelpayouts 缓存价，按天
  origin TEXT, dest TEXT, depart_date TEXT,
  price REAL, changes INTEGER, found_at TEXT,
  scanned_at TEXT,
  PRIMARY KEY (origin, dest, depart_date, scanned_at)
);
CREATE INDEX IF NOT EXISTS ix_leg ON leg_price(origin, dest, depart_date);

CREATE TABLE IF NOT EXISTS quote (              -- 精度层：SerpApi 实际联程报价
  combo_id TEXT, quoted_at TEXT,
  dep1 TEXT, dep2 TEXT, dep3 TEXT,
  stop2 TEXT, stop1_nights INT, stop2_nights INT, total_nights INT,
  price REAL, airlines TEXT, duration_min INT, stops TEXT,
  price_level TEXT, typical_low REAL, typical_high REAL,
  booking_url TEXT, raw TEXT,
  PRIMARY KEY (combo_id, quoted_at)
);
CREATE INDEX IF NOT EXISTS ix_quote ON quote(combo_id, quoted_at);

CREATE TABLE IF NOT EXISTS api_usage (          -- SerpApi 配额账本
  day TEXT, month TEXT, n INTEGER,
  PRIMARY KEY (day)
);

CREATE TABLE IF NOT EXISTS alert_sent (
  combo_id TEXT, sent_at TEXT, price REAL,
  PRIMARY KEY (combo_id, sent_at)
);
"""


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def today():
    return datetime.date.today().isoformat()


# ---------- 广度层 ----------

def save_leg_prices(c, origin, dest, rows):
    ts = now()
    c.executemany(
        "INSERT OR REPLACE INTO leg_price VALUES (?,?,?,?,?,?,?)",
        [(origin, dest, r["depart_date"], r["price"], r.get("changes"),
          r.get("found_at"), ts) for r in rows])
    c.commit()


def latest_leg_map(c, origin, dest):
    """date -> cheapest price, using the most recent scan for each date."""
    q = c.execute(
        "SELECT depart_date, price FROM leg_price WHERE origin=? AND dest=? "
        "AND scanned_at = (SELECT MAX(scanned_at) FROM leg_price lp2 "
        "  WHERE lp2.origin=leg_price.origin AND lp2.dest=leg_price.dest "
        "  AND lp2.depart_date=leg_price.depart_date)", (origin, dest))
    return {r["depart_date"]: r["price"] for r in q}


# ---------- 精度层 ----------

def save_quote(c, q):
    c.execute(
        "INSERT OR REPLACE INTO quote VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (q["combo_id"], now(), q["dep1"], q["dep2"], q["dep3"], q["stop2"],
         q["stop1_nights"], q["stop2_nights"], q["total_nights"], q["price"],
         q.get("airlines"), q.get("duration_min"), q.get("stops"),
         q.get("price_level"), q.get("typical_low"), q.get("typical_high"),
         q.get("booking_url"), json.dumps(q.get("raw", {}))[:200000]))
    c.commit()


def all_prices(c):
    """Every quote price ever seen, for the cross-combo percentile baseline."""
    return [r["price"] for r in c.execute("SELECT price FROM quote WHERE price > 0")]


def combo_history(c, combo_id):
    return [(r["quoted_at"], r["price"]) for r in c.execute(
        "SELECT quoted_at, price FROM quote WHERE combo_id=? ORDER BY quoted_at", (combo_id,))]


def quoted_months(c):
    """已经拿到过真实报价的月份集合，用来决定下一次搜索该补哪个月。"""
    return {r["m"] for r in c.execute(
        "SELECT DISTINCT substr(dep1,1,7) AS m FROM quote WHERE price > 0")}


def month_best(c):
    """每个月最便宜的一条真实报价。"""
    return list(c.execute(
        "SELECT substr(dep1,1,7) AS m, MIN(price) AS price, dep1, stop2, "
        "       stop1_nights, stop2_nights, airlines "
        "FROM quote WHERE price > 0 GROUP BY m ORDER BY m"))


def latest_quotes(c):
    """Most recent quote per combo."""
    return list(c.execute(
        "SELECT * FROM quote q WHERE quoted_at = "
        "(SELECT MAX(quoted_at) FROM quote q2 WHERE q2.combo_id = q.combo_id) "
        "ORDER BY price ASC"))


# ---------- 配额 ----------

def usage_this_month(c):
    m = today()[:7]
    r = c.execute("SELECT COALESCE(SUM(n),0) AS n FROM api_usage WHERE month=?", (m,)).fetchone()
    return r["n"]


def usage_today(c):
    r = c.execute("SELECT n FROM api_usage WHERE day=?", (today(),)).fetchone()
    return r["n"] if r else 0


def bump_usage(c, k=1):
    d, m = today(), today()[:7]
    c.execute("INSERT INTO api_usage(day, month, n) VALUES (?,?,?) "
              "ON CONFLICT(day) DO UPDATE SET n = n + ?", (d, m, k, k))
    c.commit()


# ---------- 告警去重 ----------

def last_alert(c, combo_id):
    return c.execute(
        "SELECT sent_at, price FROM alert_sent WHERE combo_id=? "
        "ORDER BY sent_at DESC LIMIT 1", (combo_id,)).fetchone()


def mark_alert(c, combo_id, price):
    c.execute("INSERT OR REPLACE INTO alert_sent VALUES (?,?,?)", (combo_id, now(), price))
    c.commit()
