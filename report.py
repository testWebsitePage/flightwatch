"""生成自包含的看板 HTML：全年价格热力图 + 已报价组合的价格历史。"""
import datetime, html, json

import store

PAGE = """<title>Flight Watch</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans+Condensed:wght@600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
:root{--bg:#F1F2F0;--surface:#FCFCFB;--sunken:#F6F6F4;--ink:#0B0B0B;--ink2:#52514E;
      --muted:#898781;--line:#DEDDD6;--accent:#35505C;--good:#0ca30c;--crit:#d03b3b;
      --c0:#E7EDE9;--c1:#BFDCCB;--c2:#8CC7A8;--c3:#F0C98A;--c4:#E39A72;--c5:#D0705C;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
      --bg:#0D0D0D;--surface:#1A1A19;--sunken:#141413;--ink:#FFF;--ink2:#C3C2B7;
      --muted:#898781;--line:#2A2A28;--accent:#9FB6C0;
      --c0:#20302A;--c1:#2C5040;--c2:#3B7A57;--c3:#7A5C2E;--c4:#9A5A38;--c5:#B4483C;}}
:root[data-theme="dark"]{--bg:#0D0D0D;--surface:#1A1A19;--sunken:#141413;--ink:#FFF;
      --ink2:#C3C2B7;--muted:#898781;--line:#2A2A28;--accent:#9FB6C0;
      --c0:#20302A;--c1:#2C5040;--c2:#3B7A57;--c3:#7A5C2E;--c4:#9A5A38;--c5:#B4483C;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-size:15px;line-height:1.65;
     font-family:"IBM Plex Sans","PingFang SC","Hiragino Sans GB",system-ui,sans-serif}
h1,h2{font-family:"IBM Plex Sans Condensed","PingFang SC",system-ui,sans-serif;margin:0}
.wrap{max-width:1120px;margin:0 auto;padding:0 22px}
header{padding:42px 0 22px}
.eyebrow{font-family:"IBM Plex Mono",monospace;font-size:11.5px;letter-spacing:.14em;
     text-transform:uppercase;color:var(--accent);margin-bottom:11px}
h1{font-size:clamp(28px,4vw,40px);letter-spacing:-.015em;line-height:1.07}
.sub{margin-top:11px;color:var(--ink2);max-width:70ch}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;
     background:var(--line);border:1px solid var(--line);margin-top:24px}
.tile{background:var(--surface);padding:14px 16px}
.tile .k{font-family:"IBM Plex Mono",monospace;font-size:10.5px;letter-spacing:.09em;
     text-transform:uppercase;color:var(--muted);margin-bottom:5px}
.tile .v{font-family:"IBM Plex Mono",monospace;font-size:23px;font-weight:600;
     font-variant-numeric:tabular-nums;line-height:1.15}
.tile .n{font-size:11.5px;color:var(--muted);font-family:"IBM Plex Mono",monospace;margin-top:2px}
section{padding:34px 0 0}
.sec-head{display:flex;align-items:baseline;gap:12px;margin-bottom:14px;flex-wrap:wrap}
h2{font-size:20px;font-weight:700}
.note{font-family:"IBM Plex Mono",monospace;font-size:11.5px;color:var(--muted)}
.body{color:var(--ink2);max-width:72ch}
.card{background:var(--surface);border:1px solid var(--line);padding:18px;overflow-x:auto}
table{border-collapse:collapse;width:100%;min-width:640px}
th,td{padding:10px 13px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{font-family:"IBM Plex Mono",monospace;font-size:10.5px;letter-spacing:.08em;
   text-transform:uppercase;color:var(--muted);font-weight:500;background:var(--sunken)}
td{font-family:"IBM Plex Mono",monospace;font-size:12.5px;font-variant-numeric:tabular-nums;color:var(--ink2)}
tbody tr:last-child td{border-bottom:none}
td.hi{color:var(--ink);font-weight:600}
.dim{color:var(--muted);font-weight:400;font-size:11px;margin-left:4px}
.mrows{display:flex;flex-direction:column;gap:7px}
.mrow{display:grid;grid-template-columns:74px 1fr 76px;gap:14px;align-items:center}
.ml{font-family:"IBM Plex Mono",monospace;font-size:12.5px;color:var(--ink2);white-space:nowrap}
.ml.hi{color:var(--ink);font-weight:600}
.mbarwrap{display:block;background:var(--sunken);height:22px;border-radius:2px;overflow:hidden}
.mbar{display:block;height:100%;border-radius:2px}
.mbar.none{width:100%;background:repeating-linear-gradient(45deg,var(--sunken),var(--sunken) 5px,var(--line) 5px,var(--line) 10px)}
.mv{font-family:"IBM Plex Mono",monospace;font-size:13px;text-align:right;
    font-variant-numeric:tabular-nums;font-weight:600;color:var(--ink)}
.mv.none{color:var(--muted);font-weight:400;font-size:11.5px}
.mons{display:grid;grid-template-columns:repeat(auto-fit,minmax(212px,1fr));gap:14px}
.mon{background:var(--surface);border:1px solid var(--line);padding:12px}
.mon h3{margin:0 0 8px;font-size:12.5px;font-family:"IBM Plex Mono",monospace;
        color:var(--ink2);letter-spacing:.03em;font-weight:500}
.grid{display:grid;grid-template-columns:repeat(7,1fr);gap:2px}
.cell{aspect-ratio:1;border-radius:2px;background:var(--c0);position:relative}
.cell span{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
     font-size:9px;font-family:"IBM Plex Mono",monospace;color:var(--ink2);opacity:.75}
.legend{display:flex;gap:6px;align-items:center;margin-top:14px;
     font-family:"IBM Plex Mono",monospace;font-size:11px;color:var(--muted)}
.legend i{width:20px;height:9px;border-radius:2px;display:inline-block}
.empty{background:var(--surface);border:1px dashed var(--line);padding:26px;
       color:var(--muted);text-align:center;font-size:13.5px}
footer{margin-top:34px;padding:24px 0 50px;border-top:1px solid var(--line);
       color:var(--muted);font-size:11.5px;font-family:"IBM Plex Mono",monospace}
</style>
"""


def _month_overview(c, n_months=13):
    """每月一行，用真实报价画。没采样过的月份如实标出来，不猜。"""
    best = {r["m"]: r for r in store.month_best(c)}
    today = datetime.date.today()
    months, cur = [], today.replace(day=1)
    for _ in range(n_months):
        months.append(cur.strftime("%Y-%m"))
        cur = (cur.replace(day=28) + datetime.timedelta(days=8)).replace(day=1)

    vals = [best[m]["price"] for m in months if m in best]
    if not vals:
        return ('<div class="empty">还没有任何真实报价。跑一次 '
                '<code>python3 watch.py</code> 就会开始填充。</div>')
    lo, hi = min(vals), max(vals)
    cheapest_m = min((m for m in months if m in best), key=lambda m: best[m]["price"])

    out = ['<div class="card"><div class="mrows">']
    for m in months:
        r = best.get(m)
        if not r:
            out.append('<div class="mrow"><span class="ml">%s</span>'
                       '<span class="mbarwrap"><i class="mbar none"></i></span>'
                       '<span class="mv none">未采样</span></div>' % m)
            continue
        frac = 0.12 + 0.88 * ((r["price"] - lo) / (hi - lo) if hi > lo else 0.5)
        b = _bucket(r["price"], lo, hi)
        star = ' ★' if m == cheapest_m else ''
        out.append(
            '<div class="mrow"><span class="ml%s">%s%s</span>'
            '<span class="mbarwrap"><i class="mbar" style="width:%.1f%%;background:var(--c%d)" '
            'title="%s 出发　%s"></i></span>'
            '<span class="mv">$%.0f</span></div>'
            % (" hi" if m == cheapest_m else "", m, star, frac * 100, b,
               r["dep1"], html.escape(r["airlines"] or ""), r["price"]))
    out.append("</div></div>")
    return "".join(out)


def _cn(ds):
    """2026-09-20 → 9月20日(周日)"""
    wd = "一二三四五六日"
    try:
        d0 = datetime.date.fromisoformat(ds)
    except (ValueError, TypeError):
        return ds or "—"
    return "%d月%d日<span class='dim'>周%s</span>" % (d0.month, d0.day, wd[d0.weekday()])


def _tile(k, v, n=""):
    return '<div class="tile"><div class="k">%s</div><div class="v">%s</div><div class="n">%s</div></div>' % (k, v, n)


def _bucket(v, lo, hi):
    if hi <= lo:
        return 2
    f = (v - lo) / (hi - lo)
    return min(5, max(0, int(f * 6)))


def build(rows, hist, cands, cfg, c):
    today = datetime.date.today()
    lo_all = min(hist) if hist else None
    best = rows[0] if rows else None
    used = store.usage_this_month(c)

    out = [PAGE, '<div class="wrap"><header>',
           '<div class="eyebrow">SFO → 台北 → 华中 → SFO · 未来 12 个月</div>',
           "<h1>Flight Watch</h1>",
           '<p class="sub">广度层每天用 Travelpayouts 免费缓存刷出全年每日单程价，'
           '排出候选；精度层再用有限的 SerpApi 额度去拿准确的联程报价。</p>',
           '<div class="tiles">']

    out.append(_tile("当前最优", ("$%.0f" % best["price"]) if best else "—",
                     (best["dep1"] + " 出发") if best else "尚无报价"))
    out.append(_tile("历史最低", ("$%.0f" % lo_all) if lo_all else "—",
                     "%d 次观测" % len(hist)))
    out.append(_tile("候选组合", "%d" % len(cands), "来自广度层排序"))
    out.append(_tile("本月额度", "%d / %d" % (used, cfg["budget"]["serpapi_monthly"]), "SerpApi 搜索"))
    out.append("</div></header>")

    # ---------- 月度概览（真实报价） ----------
    out.append('<section><div class="sec-head"><h2>哪个月走便宜</h2>'
               '<span class="note">每月最便宜的一条真实报价　★＝全年最低</span></div>')
    out.append(_month_overview(c))
    out.append('<p class="body" style="margin-top:12px;font-size:13px">'
               '每天自动补一个还没采样过的月份，日历会逐渐填满。'
               '航司通常只提前约 11 个月放票，所以最远那一两个月可能长期是「未采样」。</p>')
    out.append("</section>")

    # ---------- 全年日历热力图（需要广度层） ----------
    out.append('<section><div class="sec-head"><h2>逐日热力图</h2>'
               '<span class="note">需要 Travelpayouts 广度层，按出发日估算总价</span></div>')
    best_by_date = {}
    for x in cands:
        if x.get("est") is None:
            continue
        d0 = x["dep1"]
        if d0 not in best_by_date or x["est"] < best_by_date[d0]:
            best_by_date[d0] = x["est"]

    if best_by_date:
        vals = sorted(best_by_date.values())
        lo = vals[max(0, int(len(vals) * 0.05))]
        hi = vals[min(len(vals) - 1, int(len(vals) * 0.95))]
        months = {}
        for ds, v in best_by_date.items():
            months.setdefault(ds[:7], {})[int(ds[8:10])] = v
        out.append('<div class="mons">')
        for m in sorted(months):
            y, mo = int(m[:4]), int(m[5:7])
            first = datetime.date(y, mo, 1)
            ndays = ((first.replace(day=28) + datetime.timedelta(days=8)).replace(day=1)
                     - first).days
            pad = (first.weekday() + 1) % 7           # 周日起
            cheapest = min(months[m].values())
            out.append('<div class="mon"><h3>%s　最低 $%.0f</h3><div class="grid">' % (m, cheapest))
            out.append('<div style="grid-column:span %d"></div>' % pad if pad else "")
            for day in range(1, ndays + 1):
                v = months[m].get(day)
                if v is None:
                    out.append('<div class="cell"><span>%d</span></div>' % day)
                else:
                    out.append('<div class="cell" style="background:var(--c%d)" title="%s-%02d  估算 $%.0f">'
                               '<span>%d</span></div>' % (_bucket(v, lo, hi), m, day, v, day))
            out.append("</div></div>")
        out.append("</div>")
        out.append('<div class="legend"><span>便宜</span>'
                   + "".join('<i style="background:var(--c%d)"></i>' % i for i in range(6))
                   + "<span>贵</span><span style='margin-left:12px'>灰格＝该日期缓存里没有价格</span></div>")
    else:
        out.append('<div class="empty">广度层还没有数据。设置 <code>TP_TOKEN</code> 后跑一次 '
                   '<code>python3 watch.py --no-quote</code> 即可填充。</div>')
    out.append("</section>")

    # ---------- 已报价组合 ----------
    out.append('<section><div class="sec-head"><h2>已拿到准确报价的组合</h2>'
               '<span class="note">SerpApi 多程搜索结果</span></div>')
    if rows:
        out.append('<div class="card"><table><tr>'
                   '<th>① SFO → 台北</th><th>台北停留</th>'
                   '<th>② 台北 → 华中</th><th>华中停留</th>'
                   '<th>③ 华中 → SFO</th><th>全程</th>'
                   '<th>航司</th><th>价格</th></tr>')
        for r in rows[:20]:
            out.append(
                "<tr><td class='hi'>%s</td><td>%d 晚</td>"
                "<td class='hi'>%s <span class='dim'>→%s</span></td><td>%d 晚</td>"
                "<td class='hi'>%s</td><td>%d 天</td>"
                "<td>%s</td><td class='hi'>$%.0f</td></tr>" % (
                    _cn(r["dep1"]), r["stop1_nights"],
                    _cn(r["dep2"]), r["stop2"], r["stop2_nights"],
                    _cn(r["dep3"]), r["total_nights"] + 1,
                    html.escape((r["airlines"] or "—")[:24]), r["price"]))
        out.append("</table></div>")
        out.append('<p class="body" style="margin-top:11px;font-size:13px">'
                   '「全程」含出发当天。价格是三段联程一张票的总价，'
                   'Google Flights 对多程行程不返回常见价区间，所以贵贱只能靠自己攒的历史来判断。</p>')
    else:
        out.append('<div class="empty">还没有精度层报价。设置 <code>SERPAPI_KEY</code> 后跑 '
                   '<code>python3 watch.py</code>。</div>')
    out.append("</section>")

    # ---------- 价格历史 ----------
    series = []
    for r in rows[:5]:
        h = store.combo_history(c, r["combo_id"])
        if len(h) >= 2:
            series.append((r["combo_id"], h))
    out.append('<section><div class="sec-head"><h2>价格历史</h2>'
               '<span class="note">跟踪中的组合</span></div>')
    if series:
        out.append('<div class="card">%s</div>' % _spark(series))
    else:
        out.append('<div class="empty">至少要有两天的观测才画得出走势。</div>')
    out.append("</section>")

    out.append('<footer>生成于 %s · 数据 Travelpayouts (缓存) + SerpApi Google Flights · '
               '价格以航司页面为准</footer></div>' % today.isoformat())
    return "".join(out)


def _spark(series):
    W, H, P = 900, 268, 34
    LEG, R = 26, 62                      # 图例带高度；右侧留给价格刻度
    top, bot = P + LEG, H - P
    allv = [p for _, h in series for _, p in h]
    lo, hi = min(allv), max(allv)
    if hi == lo:
        hi = lo + 1
    alld = sorted({t[:10] for _, h in series for t, _ in h})
    xi = {d: i for i, d in enumerate(alld)}
    n = max(1, len(alld) - 1)
    colors = ["#2a78d6", "#eb6834", "#1baf7a", "#8a5cd6", "#c9a227"]

    s = ['<svg viewBox="0 0 %d %d" style="width:100%%;height:auto;overflow:visible" '
         'font-family="IBM Plex Mono, monospace" font-size="10">' % (W, H)]

    # 图例：单行横排，放在绘图区之上，不与折线重叠
    x = P
    for i, (cid, _) in enumerate(series):
        col = colors[i % len(colors)]
        s.append('<rect x="%.0f" y="%d" width="14" height="3" rx="1.5" fill="%s"/>' % (x, 12, col))
        s.append('<text x="%.0f" y="%d" fill="var(--ink2)" font-size="9.5" '
                 'dominant-baseline="middle">%s</text>' % (x + 19, 14, html.escape(cid)))
        x += 24 + 7.0 * len(cid)

    for k in range(5):
        v = hi - (hi - lo) * k / 4.0
        y = top + (bot - top) * k / 4.0
        s.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="var(--line)"/>' % (P, y, W - R, y))
        s.append('<text x="%d" y="%.1f" fill="var(--muted)" dominant-baseline="middle">$%.0f</text>'
                 % (W - R + 6, y, v))

    for i, (cid, h) in enumerate(series):
        col = colors[i % len(colors)]
        pts = []
        for t, p in h:
            px = P + (W - R - P) * (xi.get(t[:10], 0) / n)
            py = top + (bot - top) * (1 - (p - lo) / (hi - lo))
            pts.append("%.1f,%.1f" % (px, py))
        s.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2" '
                 'stroke-linejoin="round" stroke-linecap="round"/>' % (" ".join(pts), col))

    s.append('<text x="%d" y="%d" fill="var(--muted)">%s</text>' % (P, H - 8, alld[0]))
    s.append('<text x="%d" y="%d" fill="var(--muted)" text-anchor="end">%s</text>'
             % (W - R, H - 8, alld[-1]))
    s.append("</svg>")
    return "".join(s)
