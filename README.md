# flightwatch

监控 **SFO → 台北（停 3-4 晚）→ 武汉/长沙（停 9-11 晚）→ SFO** 这条行程，
在未来 12 个月里找便宜的日期组合，价格到位时发邮件。

纯 Python 标准库，无第三方依赖。

---

## 它为什么这么设计

一次搜索只能查一个日期组合，而 SerpApi 免费档只有 **250 次/月**（约每天 8 次）。
12 个月的日期组合有几千种，硬扫扫不动。所以拆成两层：

| 层 | 数据源 | 成本 | 职责 |
|---|---|---|---|
| **广度层** | Travelpayouts 月度矩阵 | 免费、不限量 | 一次调用拿整月每日最低价。5 条航线 × 14 个月 = 每天 70 次调用，刷出全年热力图 |
| **精度层** | SerpApi Google Flights | 250 次/月 | 只对广度层排在最前面的候选做真正的多程搜索 |

广度层用的是 Aviasales 缓存价，**不准**——但它不需要准，它只负责**排序**，
决定那 8 次宝贵的精确搜索该花在哪几天。

告警用相对判据而不是拍脑袋的绝对价格：绝对阈值猜高了永远不响，猜低了天天响。

- Google 自己的 `price_level == "low"`，或
- 价格落在我们自己观测历史的第 15 百分位以下，或
- 刷新观测到的最低价

外加 5 天冷却期（除非再跌 4% 以上），避免同一个行程反复轰炸。

---

## 装上要做的三件事

### 1. 拿两个 key（都免费）

**Travelpayouts**（广度层）— <https://www.travelpayouts.com/>
注册联盟账号 → Tools → API → 复制 token。免费，无需信用卡。

**SerpApi**（精度层）— <https://serpapi.com/>
注册 → Dashboard → Your Private API Key。免费档 250 次搜索/月。

### 2. Gmail 应用专用密码（发邮件用）

普通 Gmail 密码不能用于 SMTP。去 <https://myaccount.google.com/apppasswords>
生成一个 16 位的应用专用密码（需要先开两步验证）。

### 3. 跑起来

**先体检**——一条命令告诉你缺什么、哪条航线没数据，不消耗任何额度：

```bash
cd ~/flightwatch
export TP_TOKEN=xxxxx
export SERPAPI_KEY=xxxxx
python3 doctor.py                 # 只查凭据和航线覆盖，不花钱
python3 doctor.py --spend         # 额外真跑一次多程搜索（消耗 1 次额度）
python3 doctor.py --send-test     # 额外真发一封测试邮件
```

体检说「必需项齐了」再往下走。

**本地试跑**（先只跑免费的广度层，确认 Travelpayouts 有数据）：

```bash
cd ~/flightwatch
export TP_TOKEN=xxxxx
python3 watch.py --no-quote
open dashboard.html
```

看板上「哪个月走便宜」的热力图有颜色，就说明广度层通了。

**加上精度层**：

```bash
export SERPAPI_KEY=xxxxx
python3 watch.py
```

**接上邮件**：

```bash
# 凭据写在 .env 里（已 gitignore），不要写进任何会提交的文件
#   SMTP_USER=你的Gmail地址
#   SMTP_PASS=16位应用专用密码（粘贴时带的空格会自动剥离）
#   ALERT_TO=收件地址
python3 watch.py --force-email        # 强制发一封，验证通道
```

### 4. 挂成每天自动跑（GitHub Actions，免费且不依赖你电脑开机）

```bash
cd ~/flightwatch
git init && git add -A && git commit -m "init"
gh repo create flightwatch --private --source=. --push
```

然后在仓库 Settings → Secrets and variables → Actions 里加五个 secret：

| Secret | 值 |
|---|---|
| `TP_TOKEN` | Travelpayouts token |
| `SERPAPI_KEY` | SerpApi key |
| `SMTP_USER` | 你的 Gmail 地址 |
| `SMTP_PASS` | 应用专用密码 |
| `ALERT_TO` | 收件地址（代码里不再硬编码） |

### 5. 要一个固定网址（可选）

workflow 每次跑完都会把 `dashboard.html` 传成 Actions artifact，随时能下载。
想要一个「打开就能看、每天自动更新」的网址：

1. 仓库 Settings → Pages → Source 选 **GitHub Actions**
2. 仓库 Settings → Secrets and variables → Actions → **Variables** 页签 → 新建 `ENABLE_PAGES` = `true`

网址是 `https://<你的用户名>.github.io/flightwatch/`。

注意：**私有仓库开 Pages 需要 GitHub Pro**。免费账号的话把仓库设成公开即可——
里面只有机票价格，密钥都存在 Actions secrets 里，不会进仓库。

---

`.github/workflows/flightwatch.yml` 每天 08:00（太平洋时间）跑一次，
把 `flights.db` 和 `dashboard.html` 提交回仓库——**价格历史就是这个工具的核心资产**，
攒得越久，百分位判据越可靠。

---

## 命令

```bash
python3 watch.py                # 完整跑一轮
python3 watch.py --no-quote     # 只跑广度层，不消耗 SerpApi 额度
python3 watch.py --no-broad     # 跳过广度扫描，用库里已有的数据
python3 watch.py --slots 3      # 手动限定今天用几次精确搜索
python3 watch.py --force-email  # 无论有没有触发都发一封摘要
python3 doctor.py               # 体检：凭据 + 航线覆盖 + 邮件通道
python3 selftest.py             # 合成数据自检，21 项，不联网不发信
```

## 调参

改 `config.json`：

- `trip.stop2` — 目的地备选，现在是 `["WUH","CSX"]`，可以加 `"CAN"`、`"NKG"` 等
- `trip.stop1_nights` / `stop2_nights` — 停留天数的候选，组合数会相乘，别开太多
- `window.days_from_now_min/max` — 监控的时间窗口，默认 21–365 天
- `budget.serpapi_daily` — 每天最多几次精确搜索。升级到 $25 档后可以改成 30
- `alerts.own_history_percentile` — 越小越挑剔，默认 15
- `alerts.absolute_ceiling_usd` — 设个数字就是硬上限，超过不报；`null` 表示不设

## 数据库

`flights.db` 四张表：`leg_price`（广度层每日报价）、`quote`（精度层报价，
含 Google 的 `price_level` 和常见价区间）、`api_usage`（配额账本）、
`alert_sent`（告警去重）。历史只增不删。

## 已知限制

- **广度层的价格是缓存的**，最长 7 天前的搜索结果，且 Aviasales 对美国出发的航线
  覆盖偏弱。如果热力图大面积空白，说明这条航线缓存太少 —— 代码会自动退回到
  固定日期网格（`fallback_candidates`），精度层照常工作，只是选日期不那么聪明。
- **多程搜索不一定返回 `price_insights`**。Google 主要对往返/单程给这个字段。
  拿不到时就只靠我们自己的观测百分位，所以前两周告警会偏保守
  （`min_observations_before_percentile` 默认 12）。
- 只监控**联程一张票**的结构。分开买三段有时更便宜，但组合爆炸，
  以现在的免费额度盯不过来。升级到付费档后可以加。
- 价格是搜索时点的结果，**下单前务必到航司页面复核**。
