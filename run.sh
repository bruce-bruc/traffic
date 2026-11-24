#!/usr/bin/env bash
# 한 번 수집 → 화면 생성 → gh-pages 로 배포 → data/traffic.db 를 main 에 저장
set -e
export TZ=Asia/Seoul

# ── git 준비 (11-24) ──
# 이 PC 가 5분마다 data/its_live.json 을 main 에 올리므로, 수집 전에 최신 것을 받아온다.
# 예전엔 커미터 이름/메일이 없어 `pull --rebase` 가 "Committer identity unknown" 으로 멈추고
# 그 뒤로 rebase 상태에 갇혀 2회차부터 피드가 안 갱신돼 ITS 구간이 전부 '추정'으로 나왔다.
git config user.name traffic-bot
git config user.email bot@users.noreply.github.com
sync_main() {
  git rebase --abort 2>/dev/null || true          # 이전에 갇힌 rebase 가 있으면 풀기
  if ! git pull -q --rebase origin main; then
    echo "pull failed — rebase abort"; git rebase --abort 2>/dev/null || true
  fi
}
sync_main

python main.py now | head -3

# ── 페이지 배포 (gh-pages 브랜치) ──
mkdir -p site
cp data/dashboard.html site/index.html
{
  echo "== $(date) =="
  curl -s -m 20 -o /tmp/topis.xml -w "topis http=%{http_code} time=%{time_total}s\n" \
    "http://openapi.seoul.go.kr:8088/$TOPIS_KEY/xml/TrafficInfo/1/5/1220003800" || echo "curl failed: $?"
  head -c 300 /tmp/topis.xml; echo
  if [ -n "$ITS_RELAY" ]; then
    curl -s -m 40 -o /tmp/relay.json -w "relay http=%{http_code} time=%{time_total}s\n" \
      "$ITS_RELAY?token=$ITS_RELAY_TOKEN&ep=trafficInfo&type=all&getType=json&minX=126.70&maxX=126.76&minY=37.38&maxY=37.43" || echo "relay curl failed: $?"
    head -c 300 /tmp/relay.json; echo
  else
    echo "relay: not set"
  fi
} > site/debug.txt 2>&1 || true
sed -i "s/$TOPIS_KEY/TOPIS_KEY/g; s#${ITS_RELAY_TOKEN:-__none__}#TOKEN#g" site/debug.txt

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
git commit -qm "data $(date '+%m-%d %H:%M')" 2>/dev/null || true
sync_main
git push -q origin HEAD:main || echo "push failed"
