#!/usr/bin/env python3
"""
每天跑一次。

  广度层  Travelpayouts 月度矩阵 —— 免费，刷出全年每天的单程腿价格
  排序    三段相加得到「估算总价」，只用来给候选行程排队
  精度层  SerpApi 多程搜索 —— 250 次/月，只花在队首的几个候选上
  判据    Google 的 price_level  +  我们自己观测历史的百分位
"""
import argparse, datetime, itertools, json, os, sys

import envfile; envfile.load()
import store, sources, report, notify

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))


def d(s):
    return datetime.date.fromisoformat(s)


def iso(x):
    return x.isoformat()


# ---------------------------------------------------------------- 广度层
def broad_scan(c, verbose=True):
    t = CFG["trip"]
    legs = [(t["origin"], t["stop1"])]
    for s2 in t["stop2"]:
        legs.append((t["stop1"], s2))
        legs.append((s2, t["origin"]))

    today = datetime.date.today()
    months, cur = [], today.replace(day=1)
    for _ in range(14):
        months.append(iso(cur))
        cur = (cur.replace(day=28) + datetime.timedelta(days=8)).replace(day=1)

    total = 0
    for o, dst in legs:
        got = 0
        for m in months:
            rows = sources.tp_month_matrix(o, dst, m, currency=t["currency"].lower())
            if rows:
                store.save_leg_prices(c, o, dst, rows)
                got += len(rows)
        total += got
        if verbose:
            print("  %s->%s  %4d 个日期报价" % (o, dst, got))
    return total


# ---------------------------------------------------------------- 候选排序
def build_candidates(c):
    t = CFG["trip"]
    today = datetime.date.today()
    lo = today + datetime.timedelta(days=CFG["window"]["days_from_now_min"])
    hi = today + datetime.timedelta(days=CFG["window"]["days_from_now_max"])

    leg1 = store.latest_leg_map(c, t["origin"], t["stop1"])
    out = []
    for s2 in t["stop2"]:
        leg2 = store.latest_leg_map(c, t["stop1"], s2)
        leg3 = store.latest_leg_map(c, s2, t["origin"])
        for dep1s, p1 in leg1.items():
            try:
                dep1 = d(dep1s)
            except ValueError:
                continue
            if not (lo <= dep1 <= hi):
                continue
            for n1, n2 in itertools.product(t["stop1_nights"], t["stop2_nights"]):
                dep2 = dep1 + datetime.timedelta(days=n1)
                dep3 = dep2 + datetime.timedelta(days=n2)
                p2, p3 = leg2.get(iso(dep2)), leg3.get(iso(dep3))
                if p2 is None or p3 is None:
                    continue
                out.append({
                    "combo_id": "%s|%s|%d|%d" % (iso(dep1), s2, n1, n2),
                    "dep1": iso(dep1), "dep2": iso(dep2), "dep3": iso(dep3),
                    "stop2": s2, "stop1_nights": n1, "stop2_nights": n2,
                    "total_nights": n1 + n2,
                    "est": p1 + p2 + p3,
                })
    out.sort(key=lambda x: x["est"])
    return out


def _spread(items):
    """把序列重排成「任取前 N 个都均匀散布在全区间」的顺序（二分中点法）。
    这样即使一天只跑得起 8 次搜索，也能覆盖整个 12 个月，而不是全挤在最近几个月。"""
    order, todo = [], [(0, len(items) - 1)]
    if not items:
        return []
    order.append(0)
    if len(items) > 1:
        order.append(len(items) - 1)
    while todo:
        a, b = todo.pop(0)
        m = (a + b) // 2
        if m != a and m != b:
            order.append(m)
            todo.append((a, m))
            todo.append((m, b))
    seen, out = set(), []
    for i in order:
        if i not in seen:
            seen.add(i); out.append(items[i])
    return out


def fallback_candidates():
    """Travelpayouts 没数据时的兜底：在窗口里铺一层日期网格，按散布顺序排列。"""
    t = CFG["trip"]
    today = datetime.date.today()
    lo = CFG["window"]["days_from_now_min"]
    hi = CFG["window"]["days_from_now_max"]
    out, step = [], 11
    for off in range(lo, hi, step):
        dep1 = today + datetime.timedelta(days=off)
        n1, n2, s2 = t["stop1_nights"][-1], t["stop2_nights"][1], t["stop2"][0]
        dep2 = dep1 + datetime.timedelta(days=n1)
        dep3 = dep2 + datetime.timedelta(days=n2)
        out.append({"combo_id": "%s|%s|%d|%d" % (iso(dep1), s2, n1, n2),
                    "dep1": iso(dep1), "dep2": iso(dep2), "dep3": iso(dep3),
                    "stop2": s2, "stop1_nights": n1, "stop2_nights": n2,
                    "total_nights": n1 + n2, "est": None})
    return _spread(out)


# ---------------------------------------------------------------- 配额
def budget_today(c, check_remote=True):
    """三道闸门，任意一道为 0 就不再发搜索请求：
      1. SerpApi 官方剩余额度（权威；免费档按注册日循环，不是自然月）
      2. 本地账本的月度上限
      3. 每日上限 + 均匀配速
    另外始终留 safety_margin 次不用，避免刚好踩到 0。"""
    b = CFG["budget"]
    margin = b.get("safety_margin", 5)
    used_m = store.usage_this_month(c)
    used_d = store.usage_today(c)
    left_local = max(0, b["serpapi_monthly"] - used_m)

    left_remote = None
    if check_remote:
        acct = sources.serp_account()
        if acct and isinstance(acct.get("total_searches_left"), int):
            left_remote = max(0, acct["total_searches_left"] - margin)

    left = left_local if left_remote is None else min(left_local, left_remote)

    today = datetime.date.today()
    nxt = (today.replace(year=today.year + 1, month=1, day=1) if today.month == 12
           else today.replace(month=today.month + 1, day=1))
    days_left = max(1, (nxt - today).days)

    pace = left / days_left                          # 均匀配速，避免月初烧光
    allow = int(min(b["serpapi_daily"], max(1, round(pace)), left))
    return max(0, allow - used_d), used_m, left, left_remote


# ---------------------------------------------------------------- 精度层
def quote_combos(c, combos, n_slots, verbose=True):
    t = CFG["trip"]
    done = []
    for cand in combos[:n_slots]:
        legs = [(t["origin"], t["stop1"], cand["dep1"]),
                (t["stop1"], cand["stop2"], cand["dep2"]),
                (cand["stop2"], t["origin"], cand["dep3"])]
        store.bump_usage(c, 1)                     # 先记账再发请求，宁可多算不可少算
        try:
            raw = sources.serp_multicity(
                legs, adults=t["adults"], travel_class=t["travel_class"],
                currency=t["currency"])
        except Exception as e:
            print("  ! %s 查询失败: %s" % (cand["combo_id"], e))
            continue
        p = sources.parse_serp(raw)
        if not p:
            if verbose:
                print("  - %s 无结果" % cand["combo_id"])
            continue
        row = dict(cand); row.update(p); row.pop("est", None)
        store.save_quote(c, row)
        done.append(row)
        if verbose:
            print("  $%-7.0f %s  %s→%s  %s" % (
                p["price"], cand["dep1"], t["stop1"], cand["stop2"],
                p.get("price_level") or "-"))
    return done


def pick_slots(c, candidates, allow):
    """额度分三档花：
      1. 追踪已知最优行程，攒它的价格历史（判断贵贱要靠这个）
      2. 补还没有任何报价的月份，把全年日历填满
      3. 剩下的给广度层排序最靠前的便宜候选
    """
    reserve = min(CFG["budget"]["reserve_for_incumbent"], max(0, allow - 1))
    incumbents = [r["combo_id"] for r in store.latest_quotes(c)[:reserve]]
    by_id = {x["combo_id"]: x for x in candidates}
    covered = store.quoted_months(c)

    picked, seen = [], set()

    def take(x):
        if x and x["combo_id"] not in seen and len(picked) < allow:
            picked.append(x); seen.add(x["combo_id"]); return True
        return False

    for cid in incumbents:                      # 1. 在手的最优
        take(by_id.get(cid))

    for x in candidates:                        # 2. 未覆盖的月份优先
        if len(picked) >= allow:
            break
        if x["dep1"][:7] not in covered:
            if take(x):
                covered.add(x["dep1"][:7])

    for x in candidates:                        # 3. 其余按便宜程度
        if len(picked) >= allow:
            break
        take(x)
    return picked[:allow]


# ---------------------------------------------------------------- 判据
def percentile_of(price, history):
    if not history:
        return None
    return 100.0 * sum(1 for v in history if v < price) / len(history)


def evaluate(c):
    a = CFG["alerts"]
    hist = store.all_prices(c)
    rows = store.latest_quotes(c)
    hits = []
    for r in rows:
        price, cid = r["price"], r["combo_id"]
        pct = percentile_of(price, hist) if len(hist) >= a["min_observations_before_percentile"] else None

        reasons = []
        if r["price_level"] == "low":
            reasons.append("Google 判定 low")
        if pct is not None and pct <= a["own_history_percentile"]:
            reasons.append("处在我方观测历史第 %.0f 百分位" % pct)
        if hist and price <= min(hist):
            reasons.append("刷新观测到的最低价")
        if a["absolute_ceiling_usd"] and price > a["absolute_ceiling_usd"]:
            reasons = []                        # 超过硬上限就不报
        if not reasons:
            continue

        prev = store.last_alert(c, cid)
        if prev:
            gap = (datetime.datetime.now(datetime.timezone.utc)
                   - datetime.datetime.fromisoformat(prev["sent_at"])).days
            if gap < a["cooldown_days"] and price > prev["price"] * (1 - a["redrop_pct"] / 100.0):
                continue

        hits.append({"row": dict(r), "pct": pct, "reasons": reasons})
    return hits, rows, hist


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-broad", action="store_true", help="跳过 Travelpayouts 广度扫描")
    ap.add_argument("--no-quote", action="store_true", help="跳过 SerpApi，只跑广度层")
    ap.add_argument("--force-email", action="store_true", help="无论有没有告警都发一封")
    ap.add_argument("--digest-days", type=int, default=0,
                    help="距上次发信超过 N 天就发一封摘要（证明任务还活着）")
    ap.add_argument("--slots", type=int, default=None, help="覆盖今日搜索次数")
    args = ap.parse_args()

    c = store.conn()
    print("=== flightwatch %s ===" % store.today())

    if not args.no_broad:
        print("[1] 广度扫描 (Travelpayouts, 免费)")
        n = broad_scan(c)
        print("    共 %d 条日期报价入库" % n)

    cands = build_candidates(c)
    if cands:
        print("[2] 候选组合 %d 个，估算最低 $%.0f (%s → %s)"
              % (len(cands), cands[0]["est"], cands[0]["dep1"], cands[0]["stop2"]))
    else:
        print("[2] 广度层无可用数据，改用固定日期网格兜底")
        cands = fallback_candidates()

    quoted = []
    if not args.no_quote:
        allow, used_m, left, left_remote = budget_today(c)
        if args.slots is not None:
            allow = min(args.slots, left)          # --slots 也不能突破闸门
        print("[3] 精度层 (SerpApi)：本地账本已用 %d/%d%s，今日额度 %d 次"
              % (used_m, CFG["budget"]["serpapi_monthly"],
                 ("，官方剩余 %d 次" % (left_remote + CFG["budget"].get("safety_margin", 5)))
                 if left_remote is not None else "（官方额度查询失败，按本地账本执行）",
                 allow))
        if allow > 0:
            quoted = quote_combos(c, pick_slots(c, cands, allow), allow)
        else:
            print("    今日额度已用尽，跳过")

    print("[4] 判据")
    hits, rows, hist = evaluate(c)
    for h in hits:
        print("    ★ $%.0f  %s  %s" % (h["row"]["price"], h["row"]["combo_id"],
                                       "；".join(h["reasons"])))
    if not hits:
        print("    无触发")

    html = report.build(rows, hist, cands, CFG, c)
    out = os.path.join(HERE, "dashboard.html")
    open(out, "w", encoding="utf-8").write(html)
    print("[5] 看板已写入 %s" % out)

    quiet = store.days_since_email(c)
    digest = args.digest_days and quiet >= args.digest_days
    if hits or args.force_email or digest:
        why = "告警触发" if hits else ("手动强制" if args.force_email
                                       else "距上次发信 %d 个日历天，发摘要报平安" % quiet)
        ok = notify.send(CFG, hits, rows, hist)
        if ok:
            store.set_meta(c, "last_email", store.now())
            for h in hits:                      # 记账，冷却期才会真正生效
                store.mark_alert(c, h["row"]["combo_id"], h["row"]["price"])
        print("[6] 邮件：%s（%s）" % ("已发送" if ok else "未发送（缺少凭据）", why))
    else:
        print("[6] 邮件：无触发，今天已发过（距上次 %d 个日历天），不重复发" % quiet)


if __name__ == "__main__":
    sys.exit(main())
