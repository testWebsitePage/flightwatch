#!/bin/bash
# 本地改完代码用这个推。云端每天都会提交 flights.db，
# 直接 push 必然撞车；这里统一以云端的数据库为准，只推代码改动。
set -e
cd "$(dirname "$0")"
for i in 1 2 3 4 5; do
  git fetch -q origin main
  if git rebase -q origin/main 2>/dev/null; then :; else
    if [ -f .git/REBASE_HEAD ] || [ -d .git/rebase-merge ]; then
      git checkout --ours flights.db 2>/dev/null || true
      git add flights.db 2>/dev/null || true
      GIT_EDITOR=true git rebase --continue >/dev/null 2>&1 || git rebase --skip >/dev/null 2>&1
    fi
  fi
  if git push -q origin main 2>/dev/null; then
    echo "✓ 已推送（第 $i 次尝试）"; exit 0
  fi
  sleep 3
done
echo "✗ 推送失败，手动看一下 git status"; exit 1
