"""从 .env 读凭据。这个文件在 .gitignore 里，不会进仓库、不会被提交。
已存在的环境变量优先，所以 GitHub Actions 上用 secrets 覆盖即可。"""
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def load():
    if not os.path.exists(PATH):
        return
    for raw in open(PATH, encoding="utf-8"):
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if not (k and v) or v.startswith("<") or k in os.environ:
            continue
        # Google 展示应用专用密码时按 4 位分段带空格，SMTP 不接受空格
        if k in ("SMTP_PASS", "SERPAPI_KEY", "RESEND_KEY", "TP_TOKEN"):
            v = "".join(v.split())
        os.environ[k] = v
