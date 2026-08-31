#!/usr/bin/env python3
"""用合成数据把整条链路跑一遍：广度排序 → 配额分配 → 判据 → 看板 → 邮件正文。
不联网、不发信。跑完把临时库删掉。"""
import datetime, math, os, random, sys, tempfile

import store

TMP = os.path.join(tempfile.gettempdir(), "flightwatch_selftest.db")
if os.path.exists(TMP):
    os.remove(TMP)
store.DB = TMP

import watch, report, notify   # noqa: E402  (必须在改 store.DB 之后导入)

random.seed(7)
FAIL = []
NCHECK = [0]


def check(name, cond, detail=""):
    NCHECK[0] += 1
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  — " + detail) if detail else ""))
    if not cond:
        FAIL.append(name)


def seasonal(day_offset):
    """造一个有季节性的价格曲面：春节和圣诞贵，3-5 月便宜。"""
    d = datetime.date.today() + datetime.timedelta(days=day_offset)
    doy = d.timetuple().tm_yday
    base = 1.0 + 0.28 * math.cos((doy - 20) / 365.0 * 2 * math.pi)     # 1月峰值
    if 340 <= doy or doy <= 45:
        base += 0.22
    if 60 <= doy <= 150:
        base -= 0.12
    return base


def main():
    c = store.conn()
    t = watch.CFG["trip"]
    today = datetime.date.today()

    print("[1] 灌入合成的广度层数据")
    legs = [(t["origin"], t["stop1"], 620.0)]
    for s2 in t["stop2"]:
        legs.append((t["stop1"], s2, 180.0))
        legs.append((s2, t["origin"], 700.0))
    for o, dst, anchor in legs:
        rows = []
        for off in range(0, 400):
            if random.random() < 0.12:            # 模拟缓存缺口
                continue
            dd = today + datetime.timedelta(days=off)
            px = anchor * seasonal(off) * random.uniform(0.9, 1.12)
            rows.append({"depart_date": dd.isoformat(), "price": round(px, 2),
                         "changes": random.choice([0, 1, 1, 2]), "found_at": None})
        store.save_leg_prices(c, o, dst, rows)
    n_leg = c.execute("SELECT COUNT(*) n FROM leg_price").fetchone()["n"]
    check("广度层入库", n_leg > 1500, "%d 行" % n_leg)

    print("[2] 候选排序")
    cands = watch.build_candidates(c)
    check("生成候选组合", len(cands) > 500, "%d 个" % len(cands))
    check("按估算总价升序", all(cands[i]["est"] <= cands[i + 1]["est"] for i in range(len(cands) - 1)))
    in_win = all(watch.CFG["window"]["days_from_now_min"]
                 <= (watch.d(x["dep1"]) - today).days
                 <= watch.CFG["window"]["days_from_now_max"] for x in cands)
    check("全部落在时间窗口内", in_win)
    legs_ok = all(watch.d(x["dep2"]) == watch.d(x["dep1"]) + datetime.timedelta(days=x["stop1_nights"])
                  and watch.d(x["dep3"]) == watch.d(x["dep2"]) + datetime.timedelta(days=x["stop2_nights"])
                  for x in cands)
    check("三段日期链自洽", legs_ok)
    cheap_month = cands[0]["dep1"][:7]
    print("      最便宜的候选落在 %s，估算 $%.0f" % (cheap_month, cands[0]["est"]))

    print("[3] 配额分配")
    allow, used, left, remote = watch.budget_today(c, check_remote=False)
    check("首日额度合理", 1 <= allow <= watch.CFG["budget"]["serpapi_daily"], "allow=%d" % allow)
    store.bump_usage(c, 240)
    allow2, _, left2, _ = watch.budget_today(c, check_remote=False)
    check("接近月度上限时收紧", allow2 == 0 and left2 == 10, "allow=%d left=%d" % (allow2, left2))
    store.bump_usage(c, 10)
    allow3, _, left3, _ = watch.budget_today(c, check_remote=False)
    check("用满 250 后彻底停发", allow3 == 0 and left3 == 0, "allow=%d left=%d" % (allow3, left3))
    c.execute("DELETE FROM api_usage"); c.commit()

    print("[4] 灌入合成报价（14 天，价格逐步下探）")
    picks = watch.pick_slots(c, cands, 6)
    check("挑选槽位不重复", len({p["combo_id"] for p in picks}) == len(picks))
    for day_back in range(14, 0, -1):
        ts = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=day_back)).isoformat(timespec="seconds")
        for i, p in enumerate(picks):
            drift = 1.0 - 0.012 * (14 - day_back) if i == 0 else 1.0
            px = round(p["est"] * 0.92 * drift * random.uniform(0.985, 1.015), 2)
            c.execute("INSERT OR REPLACE INTO quote VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (p["combo_id"], ts, p["dep1"], p["dep2"], p["dep3"], p["stop2"],
                       p["stop1_nights"], p["stop2_nights"], p["total_nights"], px,
                       "China Airlines", 1580, "TPE",
                       "low" if (i == 0 and day_back == 1) else "typical",
                       px * 0.95, px * 1.35, "https://www.google.com/travel/flights", "{}"))
    c.commit()
    hist = store.all_prices(c)
    check("报价历史入库", len(hist) >= 80, "%d 条观测" % len(hist))
    latest = store.latest_quotes(c)
    check("每个组合只取最新一条", len(latest) == len(picks), "%d 个组合" % len(latest))
    check("最新报价按价格升序", all(latest[i]["price"] <= latest[i + 1]["price"]
                                    for i in range(len(latest) - 1)))

    print("[5] 判据")
    hits, rows, hist = watch.evaluate(c)
    check("触发了告警", len(hits) >= 1, "%d 个" % len(hits))
    if hits:
        why = hits[0]["reasons"]
        check("给出了触发理由", len(why) >= 1, "；".join(why))
        check("最低价组合在其中",
              min(h["row"]["price"] for h in hits) == min(r["price"] for r in rows))

    print("[6] 冷却期去重")
    for h in hits:
        store.mark_alert(c, h["row"]["combo_id"], h["row"]["price"])
    hits2, _, _ = watch.evaluate(c)
    check("同价重复不再告警", len(hits2) == 0, "第二轮 %d 个" % len(hits2))

    print("[7] 渲染")
    html = report.build(rows, hist, cands, watch.CFG, c)
    check("看板含热力图", "哪个月走便宜" in html and "grid" in html)
    check("看板含报价表", "已拿到准确报价的组合" in html)
    check("看板含价格历史 svg", "<svg" in html and "polyline" in html)
    check("看板体积合理", 20000 < len(html) < 900000, "%.0f KB" % (len(html) / 1024))
    open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_demo.html"),
         "w", encoding="utf-8").write(html)

    mail = notify.build_html(watch.CFG, hits, rows, hist)
    check("邮件正文含价格", "$" in mail and "买入条件" in mail)
    check("邮件正文含行程", "SFO → 台北" in mail and "台北停留" in mail)
    open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "email_demo.html"),
         "w", encoding="utf-8").write(mail)

    c.close()
    os.remove(TMP)
    print("\n%s  —  %d/%d 项通过"
          % ("全部通过" if not FAIL else "失败: " + ", ".join(FAIL),
             NCHECK[0] - len(FAIL), NCHECK[0]))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
