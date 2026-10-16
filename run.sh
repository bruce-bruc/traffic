#!/usr/bin/env bash
# 한 번 수집 → 화면 생성 → gh-pages 로 배포 → data/traffic.db 를 main 에 저장
set -e
export TZ=Asia/Seoul
python main.py now | head -3

# ── 페이지 배포 (gh-pages 브랜치) ──
mkdir -p site
cp data/dashboard.html site/index.html
{
  echo "== $(date) =="
  curl -s -m 20 -o /tmp/topis.xml -w "topis http=%{http_code} time=%{time_total}s\n" \
    "http://openapi.seoul.go.kr:8088/$TOPIS_KEY/xml/TrafficInfo/1/5/1220003800" || echo "curl failed: $?"
  head -c 300 /tmp/topis.xml; echo
} > site/debug.txt 2>&1 || true
sed -i "s/$TOPIS_KEY/TOPIS_KEY/g" site/debug.txt

if [ ! -d gh-pages ]; then
  git fetch -q origin gh-pages 2>/dev/null && git worktree add -q gh-pages origin/gh-pages 2>/dev/null \
    || { git worktree add -q --detach gh-pages && (cd gh-pages && git checkout -q --orphan gh-pages && git rm -rfq . 2>/dev/null || true); }
fi
cp site/* gh-pages/
touch gh-pages/.nojekyll
(cd gh-pages && git add -A && git -c user.name=traffic-bot -c user.email=bot@users.noreply.github.com \
   commit -qm "site $(date '+%m-%d %H:%M')" 2>/dev/null && git push -qf origin HEAD:gh-pages) || echo "site unchanged"

# ── 기록 저장 (main) ──
git add data/traffic.db
git -c user.name=traffic-bot -c user.email=bot@users.noreply.github.com commit -qm "data $(date '+%m-%d %H:%M')" 2>/dev/null || true
git pull -q --rebase origin main || true
git push -q origin HEAD:main || true
