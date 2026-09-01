"""邮件通知。SMTP 走环境变量，仓库里不留任何密码。"""
import os, smtplib, datetime
from email.message import EmailMessage

CSS = """
body{font-family:-apple-system,'Helvetica Neue',Arial,'PingFang SC',sans-serif;
     color:#15191a;background:#f2f3f1;margin:0;padding:22px}
.card{background:#fff;border:1px solid #d8dcda;max-width:660px;margin:0 auto;padding:22px}
h1{font-size:19px;margin:0 0 4px}
.sub{color:#5b6566;font-size:13px;margin:0 0 18px}
.hit{border:1px solid #d8dcda;border-left:3px solid #1a7f4b;padding:13px 15px;margin-bottom:12px}
.price{font-size:26px;font-weight:700;letter-spacing:-.01em}
.route{font-family:ui-monospace,Menlo,monospace;font-size:13px;color:#3d4647;margin:5px 0}
.why{font-size:13px;color:#1a7f4b;margin-top:6px}
.meta{font-size:12px;color:#6f7a7a;margin-top:6px}
a.btn{display:inline-block;margin-top:10px;background:#15191a;color:#fff;
      text-decoration:none;padding:8px 14px;font-size:13px}
table{border-collapse:collapse;width:100%;margin-top:8px;font-size:12.5px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid #e6e9e7}
th{color:#6f7a7a;font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.06em}
td.n{text-align:right;font-family:ui-monospace,Menlo,monospace}
.foot{color:#8b9494;font-size:11.5px;margin-top:18px;border-top:1px solid #e6e9e7;padding-top:12px}
"""


CITY = {"WUH": "武汉", "CSX": "长沙", "CAN": "广州", "NKG": "南京", "PVG": "上海"}


def _cn(ds):
    wd = "一二三四五六日"
    d0 = datetime.date.fromisoformat(ds)
    return "%d月%d日(周%s)" % (d0.month, d0.day, wd[d0.weekday()])


def _fmt_combo(r):
    city = CITY.get(r["stop2"], r["stop2"])
    return "全程 %d 天　SFO → 台北 → %s → SFO" % (r["total_nights"] + 1, city)


def _fmt_legs(r):
    city = CITY.get(r["stop2"], r["stop2"])
    return ("① %s　SFO → 台北<br>"
            "　　台北停留 %d 晚<br>"
            "② %s　台北 → %s<br>"
            "　　%s停留 %d 晚<br>"
            "③ %s　%s → SFO") % (
        _cn(r["dep1"]), r["stop1_nights"],
        _cn(r["dep2"]), city, city, r["stop2_nights"],
        _cn(r["dep3"]), city)


def build_html(cfg, hits, rows, hist):
    lo = min(hist) if hist else None
    parts = ['<html><head><meta charset="utf-8"><style>%s</style></head><body><div class="card">' % CSS]

    if hits:
        parts.append('<h1>%d 个行程达到买入条件</h1>' % len(hits))
    else:
        parts.append("<h1>每日机票摘要</h1>")
    parts.append('<p class="sub">%s · 共 %d 次报价观测%s</p>' % (
        datetime.date.today().isoformat(), len(hist),
        ("，历史最低 $%.0f" % lo) if lo else ""))

    for h in hits:
        r = h["row"]
        parts.append('<div class="hit">')
        parts.append('<div class="price">$%.0f</div>' % r["price"])
        parts.append('<div class="route">%s</div>' % _fmt_combo(r))
        parts.append('<div class="route">%s</div>' % _fmt_legs(r))
        parts.append('<div class="why">%s</div>' % "；".join(h["reasons"]))
        meta = []
        if r["airlines"]:
            meta.append(r["airlines"])
        if r["duration_min"]:
            meta.append("总时长 %d 小时 %d 分" % (r["duration_min"] // 60, r["duration_min"] % 60))
        if r["typical_low"]:
            meta.append("Google 常见价区间 $%.0f–$%.0f" % (r["typical_low"], r["typical_high"]))
        if meta:
            parts.append('<div class="meta">%s</div>' % "　·　".join(meta))
        if r["booking_url"]:
            parts.append('<a class="btn" href="%s">在 Google Flights 打开</a>' % r["booking_url"])
        parts.append("</div>")

    if rows:
        parts.append("<h1 style='font-size:15px;margin-top:22px'>当前最优的几个组合</h1>")
        parts.append("<table><tr><th>①SFO→台北</th><th>②台北→华中</th><th>③华中→SFO</th>"
                     "<th>航司</th><th style='text-align:right'>价格</th></tr>")
        for r in rows[:8]:
            parts.append("<tr><td>%s</td><td>%s→%s</td><td>%s</td><td>%s</td>"
                         "<td class='n'>$%.0f</td></tr>" % (
                             _cn(r["dep1"]), _cn(r["dep2"]),
                             CITY.get(r["stop2"], r["stop2"]), _cn(r["dep3"]),
                             (r["airlines"] or "—")[:24], r["price"]))
        parts.append("</table>")

    parts.append('<div class="foot">价格为搜索时点的缓存结果，实际以航司页面为准。'
                 '判据：Google price_level 为 low，或价格落在我方观测历史的低位。</div>')
    parts.append("</div></body></html>")
    return "".join(parts)


def _send_resend(cfg, subject, html_body, to):
    """备选通道：Resend。只要一个 API key，不用碰 Google 两步验证。
    免费档 3000 封/月；未验证域名时只能发给注册邮箱本人 —— 正好是我们的用法。"""
    import json as _json, urllib.request
    key = os.environ.get("RESEND_KEY", "")
    if not key:
        return False
    payload = _json.dumps({
        "from": os.environ.get("RESEND_FROM", "onboarding@resend.dev"),
        "to": [to], "subject": subject, "html": html_body}).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=payload,
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return 200 <= r.status < 300


def send(cfg, hits, rows, hist):
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ.get("SMTP_USER", "")
    pw = os.environ.get("SMTP_PASS", "")
    to = os.environ.get("ALERT_TO") or cfg["email"].get("to") or ""
    if not to:
        print("  未设置 ALERT_TO，不知道该发给谁")
        return False
    if not (user and pw) and not os.environ.get("RESEND_KEY"):
        return False

    if hits:
        best = min(h["row"]["price"] for h in hits)
        subj = "%s $%.0f 起 · %d 个行程达到买入条件" % (cfg["email"]["subject_prefix"], best, len(hits))
    elif rows:
        b = rows[0]
        subj = "%s 每日摘要 · 当前最低 $%.0f（%s 出发）" % (
            cfg["email"]["subject_prefix"], b["price"], _cn(b["dep1"]))
    else:
        subj = "%s 每日摘要" % cfg["email"]["subject_prefix"]

    body = build_html(cfg, hits, rows, hist)

    if user and pw:                                   # 首选：SMTP
        try:
            m = EmailMessage()
            m["Subject"] = subj
            m["From"] = user
            m["To"] = to
            m.set_content("需要支持 HTML 的邮件客户端查看。")
            m.add_alternative(body, subtype="html")
            with smtplib.SMTP_SSL(host, port, timeout=40) as s:
                s.login(user, pw)
                s.send_message(m)
            return True
        except Exception as e:
            if not os.environ.get("RESEND_KEY"):
                raise
            print("  SMTP 失败(%s)，改用 Resend" % str(e)[:80])

    return _send_resend(cfg, subj, body, to)          # 备选：Resend HTTP API
