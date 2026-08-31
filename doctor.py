#!/usr/bin/env python3
"""开跑前的体检。逐项确认凭据可用、航线有数据，再决定要不要往下装。

  python3 doctor.py              # 只做不花钱的检查
  python3 doctor.py --spend      # 额外真跑一次 SerpApi 搜索（消耗 1 次额度）
  python3 doctor.py --send-test  # 额外真发一封测试邮件
"""
import argparse, datetime, json, os, sys, urllib.parse, urllib.request

import envfile; envfile.load()
import sources

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))

OK, WARN, BAD = "  OK   ", "  注意 ", "  缺失 "
problems, warnings = [], []


def line(tag, msg, detail=""):
    print(tag + msg + (("  — " + detail) if detail else ""))


def next_months(k):
    cur = datetime.date.today().replace(day=1)
    out = []
    for _ in range(k):
        out.append(cur.isoformat())
        cur = (cur.replace(day=28) + datetime.timedelta(days=8)).replace(day=1)
    return out


def check_travelpayouts():
    print("\n[1] Travelpayouts —— 广度层（免费，负责给日期排序）")
    tok = os.environ.get("TP_TOKEN", "")
    if not tok:
        line(BAD, "TP_TOKEN 未设置", "export TP_TOKEN=xxxxx")
        problems.append("TP_TOKEN")
        return

    t = CFG["trip"]
    legs = [(t["origin"], t["stop1"])]
    for s2 in t["stop2"]:
        legs.append((t["stop1"], s2))
        legs.append((s2, t["origin"]))

    months = next_months(3)
    thin = []
    for o, dst in legs:
        days, cheapest = 0, None
        for m in months:
            rows = sources.tp_month_matrix(o, dst, m, currency=t["currency"].lower(), token=tok)
            days += len(rows)
            for r in rows:
                if cheapest is None or r["price"] < cheapest:
                    cheapest = r["price"]
        if days == 0:
            line(BAD, "%s → %s" % (o, dst), "3 个月内一条缓存价都没有")
            thin.append("%s-%s" % (o, dst))
        elif days < 25:
            line(WARN, "%s → %s" % (o, dst), "只有 %d 天有价（偏稀），最低 $%.0f" % (days, cheapest))
            thin.append("%s-%s" % (o, dst))
        else:
            line(OK, "%s → %s" % (o, dst), "%d 天有价，最低 $%.0f" % (days, cheapest))

    if len(thin) >= len(legs):
        problems.append("Travelpayouts 全线无数据")
        print("\n     → 全部航线都没有缓存。广度层用不了，脚本会退回固定日期网格，")
        print("       精度层照常工作，只是选日期不那么聪明。")
    elif thin:
        warnings.append("部分航线缓存稀疏: " + ", ".join(thin))


def check_serpapi(spend):
    print("\n[2] SerpApi —— 精度层（250 次/月，负责拿准确联程报价）")
    key = os.environ.get("SERPAPI_KEY", "")
    if not key:
        line(BAD, "SERPAPI_KEY 未设置", "export SERPAPI_KEY=xxxxx")
        problems.append("SERPAPI_KEY")
        return

    try:  # 查额度不消耗搜索次数
        url = "https://serpapi.com/account?" + urllib.parse.urlencode({"api_key": key})
        req = urllib.request.Request(url, headers={"User-Agent": "flightwatch/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            acct = json.load(r)
        left = acct.get("total_searches_left")
        line(OK, "凭据有效", "本月剩余 %s 次 / 套餐 %s"
             % (left, acct.get("plan_name", "?")))
        if isinstance(left, int) and left < 30:
            warnings.append("SerpApi 剩余额度不多 (%d)" % left)
    except Exception as e:
        line(BAD, "凭据校验失败", str(e)[:120])
        problems.append("SERPAPI_KEY 无效")
        return

    if not spend:
        line(WARN, "未做真实搜索", "加 --spend 会真跑一次（消耗 1 次额度）")
        return

    t = CFG["trip"]
    d1 = datetime.date.today() + datetime.timedelta(days=90)
    d2 = d1 + datetime.timedelta(days=t["stop1_nights"][-1])
    d3 = d2 + datetime.timedelta(days=t["stop2_nights"][1])
    legs = [(t["origin"], t["stop1"], d1.isoformat()),
            (t["stop1"], ",".join(t["stop2"]), d2.isoformat()),
            (",".join(t["stop2"]), t["origin"], d3.isoformat())]
    import store as _store
    _c = _store.conn(); _store.bump_usage(_c, 1); _c.close()   # 体检也算一次，计入账本
    try:
        raw = sources.serp_multicity(legs, adults=t["adults"],
                                     travel_class=t["travel_class"], currency=t["currency"])
    except Exception as e:
        line(BAD, "多程搜索失败", str(e)[:200])
        problems.append("SerpApi 多程搜索")
        return
    p = sources.parse_serp(raw)
    if not p:
        line(WARN, "搜索成功但没有航班结果", "可能是日期太远或机场组合无航线")
        warnings.append("多程搜索无结果")
        return
    line(OK, "多程搜索可用", "$%.0f  %s" % (p["price"], p["airlines"] or "?"))
    if p["price_level"]:
        line(OK, "price_insights 可用", "判定 %s，常见价区间 $%s–$%s"
             % (p["price_level"], p["typical_low"], p["typical_high"]))
    else:
        line(WARN, "多程不返回 price_insights",
             "只能靠自己攒的百分位，前两周告警会偏保守")
        warnings.append("多程无 price_insights")


def check_email(send_test):
    print("\n[3] 邮件通道")
    user = os.environ.get("SMTP_USER", "")
    pw = os.environ.get("SMTP_PASS", "")
    to = os.environ.get("ALERT_TO") or CFG["email"]["to"]
    if not (user and pw):
        if os.environ.get("RESEND_KEY"):
            line(OK, "改用 Resend 通道", "已配置 RESEND_KEY，跳过 SMTP")
            if send_test:
                import notify
                ok = notify.send(CFG, [], [], [])
                line(OK if ok else BAD, "测试邮件", "已发送" if ok else "发送失败")
            return
        line(BAD, "SMTP_USER / SMTP_PASS 未设置",
             "Gmail 需应用专用密码；或改配 RESEND_KEY 走 Resend")
        problems.append("邮件凭据")
        return
    import smtplib
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    try:
        with smtplib.SMTP_SSL(host, port, timeout=30) as s:
            s.login(user, pw)
        line(OK, "SMTP 登录成功", "%s → %s" % (user, to))
    except Exception as e:
        line(BAD, "SMTP 登录失败", str(e)[:150])
        problems.append("SMTP 登录")
        return

    if send_test:
        import notify
        sent = notify.send(CFG, [], [], [])
        line(OK if sent else BAD, "测试邮件", "已发送，去收件箱确认" if sent else "发送失败")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spend", action="store_true", help="真跑一次 SerpApi 搜索")
    ap.add_argument("--send-test", action="store_true", help="真发一封测试邮件")
    a = ap.parse_args()

    print("=== flightwatch 体检 ===")
    print("行程：%s → %s (%s 晚) → %s (%s 晚) → %s" % (
        CFG["trip"]["origin"], CFG["trip"]["stop1"], "/".join(map(str, CFG["trip"]["stop1_nights"])),
        "/".join(CFG["trip"]["stop2"]), "/".join(map(str, CFG["trip"]["stop2_nights"])),
        CFG["trip"]["origin"]))

    check_travelpayouts()
    check_serpapi(a.spend)
    check_email(a.send_test)

    print("\n" + "=" * 46)
    if problems:
        print("还缺 %d 项：%s" % (len(problems), "、".join(problems)))
    else:
        print("必需项齐了，可以跑 python3 watch.py")
    for w in warnings:
        print("  注意：" + w)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
