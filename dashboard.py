"""data/traffic.db 를 읽어 폰에서 보기 좋은 단일 HTML 대시보드를 만든다.
핵심 3줄(지금 출발 시 도착 / 어느 길 / 오늘 최적 출발) 위주, 상세는 접어둠."""
import sqlite3, os, json, datetime as dt
from monitor import DB, load_config, weekday_pattern

OUT = os.path.join(os.path.dirname(DB), "dashboard.html")

# 사용자용 쉬운 이름
EASY = {
    "A": "수원광명 쪽으로 (수원광명 → 강남순환로 → 사당IC → 사당역)",
    "B": "110번 외곽순환으로 (과천 → 선암IC → 우면산터널 → 서초)",
    "C": "110번 외곽순환으로 (과천 → 남태령 → 사당역)",
}


def build_dashboard():
    from predict import plan, fmt_row
    from sources import fetch_weather, fetch_incidents
    cfg = load_config()
    now = dt.datetime.now()
    con = sqlite3.connect(DB)
    latest_ts = con.execute("SELECT MAX(ts) FROM readings").fetchone()[0]
    latest = con.execute("SELECT segment, speed, status, minutes, mode FROM readings WHERE ts=?", (latest_ts,)).fetchall() if latest_ts else []
    verdict = con.execute("SELECT best_route, note, totals FROM verdicts ORDER BY ts DESC LIMIT 1").fetchone()
    today = dt.date.today().isoformat()
    series = con.execute("""SELECT ts, segment, speed FROM readings
                            WHERE ts LIKE ? AND speed IS NOT NULL ORDER BY ts""", (today + "%",)).fetchall()
    con.close()

    # ── 예측표 (남동공단 출발 기준) ──
    weather = fetch_weather(cfg)
    incidents = fetch_incidents(cfg)
    from predict import best_windows
    rows = plan(cfg, weather=weather, incidents=incidents)
    worst, before_r, after_r = best_windows(cfg, rows)
    before = [before_r] if before_r else []
    after = [after_r] if after_r else []

    # "지금 출발" = 예측표에서 지금과 가장 가까운 줄. 최근 실측(30분 내)이 있으면 그걸 우선
    nowrow = min(rows, key=lambda r: abs((r["depart"] - now).total_seconds()))
    best_route = nowrow["best"]
    total_now = nowrow["routes"][best_route]["total"]
    src = "예측"
    if verdict and latest_ts and (now - dt.datetime.fromisoformat(latest_ts)).total_seconds() < 1800:
        live = json.loads(verdict[2])
        best_route = min(live, key=live.get)
        total_now = round(live[best_route])
        src = "실시간"
    arrive = now + dt.timedelta(minutes=total_now)
    split_at = now + dt.timedelta(minutes=round(nowrow["split_at"] and (nowrow["split_at"] - nowrow["depart"]).total_seconds() / 60 or 15))

    def fmt_opt(r):
        t = r["routes"][r["best"]]
        return f"{r['depart']:%H:%M} 출발 → {t['arrive']:%H:%M} 도착 ({t['total']:.0f}분, {cfg['routes'][r['best']]['short']})"

    # 지금 이후 출발 중 가장 빠른 / 가장 느린
    future = [r for r in rows if r["depart"] >= now - dt.timedelta(minutes=5)] or rows
    min_total = min(r["routes"][r["best"]]["total"] for r in future)
    good = [r for r in future if r["routes"][r["best"]]["total"] <= min_total * 1.08]
    fastest = good[0]                                   # 가장 이른 '좋은' 출발
    slowest = max(future, key=lambda r: r["routes"][r["best"]]["total"])
    ft, st_ = fastest["routes"][fastest["best"]], slowest["routes"][slowest["best"]]
    tips = []
    if before and before[-1]["depart"] > now:
        tips.append("🏁 막히기 전 마지노선: " + fmt_opt(before[-1]))
    if after:
        tips.append("🌙 풀린 뒤: " + fmt_opt(after[0]))
    warn = ""
    if incidents:
        SH = {"A": "수원광명", "BC": "110번", "B": "우면산", "C": "남태령", "?": "?"}
        warn = "<br>".join(f"⚠ <b>{'/'.join(SH.get(r, r) for r in i.get('routes', []))}</b> {i['text'][:40]}" for i in incidents[:3])
    if weather and (weather.get("rain_mm") or weather.get("snow")):
        warn += (" · " if warn else "") + "🌧 " + weather.get("desc", "비")

    # ── 상세 (접힘) ──
    SEG_EASY = {sg["id"]: sg["name"] for sg in cfg["segments"]}
    color = {"smooth": "#2e9e5b", "slow": "#d9a400", "jam": "#d9403e", "unknown": "#888"}
    color["fixed"] = "#bbb"
    cards = "".join(
        f'<div class="card"><div class="dot" style="background:{color[st]}"></div>'
        f'<div><div class="nm">{SEG_EASY.get(seg, seg)}</div>'
        f'<div class="v">{("추정" if mode == "fixed" else (f"{spd:.0f} km/h" if spd else "자료없음"))} · 약 {mn:.0f}분'
        f'{" <small>[데모]</small>" if mode == "demo" else ""}</div></div></div>'
        for seg, spd, st, mn, mode in latest)
    table = "".join(
        f"<tr class='{'worst' if r is worst else ''}'><td>{r['depart']:%H:%M}</td>"
        f"<td>{r['routes'][r['best']]['arrive']:%H:%M}</td><td>{r['routes'][r['best']]['total']:.0f}분</td>"
        f"<td>{cfg['routes'][r['best']]['short']}</td></tr>" for r in rows)
    by_seg = {}
    for ts, seg, spd in series:
        by_seg.setdefault(seg, []).append((ts[11:16], spd))
    SEG_EASY = {sg["id"]: sg["name"] for sg in cfg["segments"]}
    names = {k: v.split(" (")[0] for k, v in SEG_EASY.items()}

    html = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>퇴근길</title>
<style>
body{{font-family:-apple-system,"Noto Sans KR",sans-serif;margin:0;padding:16px;background:#f5f6f8;color:#222}}
.big{{background:#1f3a5f;color:#fff;border-radius:16px;padding:22px 20px;margin-bottom:12px}}
.big .l{{font-size:14px;opacity:.85}} .big .n{{font-size:44px;font-weight:700;line-height:1.1;margin:6px 0}}
.big .a{{font-size:18px}} .big .s{{font-size:12px;opacity:.7;margin-top:8px}}
.route{{background:#fff;border-radius:14px;padding:16px;margin-bottom:12px;font-size:17px;box-shadow:0 1px 2px rgba(0,0,0,.06)}}
.route b{{display:block;font-size:20px;margin-bottom:4px}} .route .l{{font-size:13px;color:#666;margin-bottom:4px}}
.two{{display:flex;gap:10px;margin-bottom:12px}}
.box{{flex:1;border-radius:14px;padding:14px 12px;color:#fff}} .box.good{{background:#2e9e5b}} .box.bad{{background:#d9403e}}
.box .t{{font-size:13px;opacity:.9}} .box .h{{font-size:24px;font-weight:700;margin:4px 0}} .box .d{{font-size:13px;opacity:.95;line-height:1.4}}
.tips{{background:#fff;border-radius:14px;padding:14px 16px;margin-bottom:12px;box-shadow:0 1px 2px rgba(0,0,0,.06)}}
.tips div{{padding:6px 0;font-size:15px;border-bottom:1px solid #eee}} .tips div:last-child{{border:0}}
.warn{{background:#fff3cd;border-radius:12px;padding:12px 14px;margin-bottom:12px;font-size:14px}}
details{{background:#fff;border-radius:14px;padding:12px 16px;margin-bottom:10px;box-shadow:0 1px 2px rgba(0,0,0,.06)}}
summary{{font-size:15px;font-weight:600;cursor:pointer;padding:4px 0}}
.card{{display:flex;gap:12px;align-items:center;padding:10px 0;border-bottom:1px solid #eee}} .card:last-child{{border:0}}
.dot{{width:14px;height:14px;border-radius:50%;flex:none}} .nm{{font-size:14px}} .v{{font-size:13px;color:#555}}
table{{width:100%;border-collapse:collapse;font-size:13px}} td,th{{padding:6px 4px;border-bottom:1px solid #eee;text-align:left}}
tr.worst td{{color:#d9403e;font-weight:600}}
canvas{{width:100%;margin-top:8px}}
.foot{{font-size:11px;color:#888;text-align:center;margin-top:10px}}
</style></head><body>

<div class="big">
  <div class="l">지금 남동공단에서 출발하면</div>
  <div class="n">{total_now:.0f}분</div>
  <div class="a">집 도착 {arrive:%H:%M}</div>
  <div class="s">{now:%H:%M} 기준 · {src}</div>
</div>

<div class="route"><div class="l">제3경인 끝 갈림길({split_at:%H:%M}쯤)에서</div><b>👉 {EASY[best_route].split(' (')[0]}</b>
  {EASY[best_route].split(' (')[1].rstrip(')')}</div>

{f'<div class="warn">{warn}</div>' if warn else ''}

<div class="two">
  <div class="box good"><div class="t">🟢 가장 빨리 (이르게)</div><div class="h">{fastest['depart']:%H:%M} 출발</div>
    <div class="d">{ft['arrive']:%H:%M} 도착 · {ft['total']:.0f}분<br>{cfg['routes'][fastest['best']]['short']}</div></div>
  <div class="box bad"><div class="t">🔴 가장 위험</div><div class="h">{slowest['depart']:%H:%M} 출발</div>
    <div class="d">{st_['arrive']:%H:%M} 도착 · {st_['total']:.0f}분<br>{cfg['routes'][slowest['best']]['short']}</div></div>
</div>
{f'<div class="tips">{"".join(f"<div>{t}</div>" for t in tips)}</div>' if tips else ''}

<details><summary>출발 시각별 예상</summary>
  <table><tr><th>출발</th><th>도착</th><th>소요</th><th>길</th></tr>{table}</table></details>

<details><summary>구간별 지금 상태</summary>{cards or '<div class="v">아직 수집 전</div>'}</details>

<details><summary>오늘 속도 그래프</summary><canvas id="c" height="200"></canvas></details>

<div class="foot">마지막 수집 {latest_ts.replace('T',' ') if latest_ts else '-'} · 5분마다 자동 새로고침</div>

<script>
const data={json.dumps(by_seg, ensure_ascii=False)}, names={json.dumps(names, ensure_ascii=False)};
const cv=document.getElementById('c');
function draw(){{const ctx=cv.getContext('2d');cv.width=cv.clientWidth*2;cv.height=400;ctx.scale(2,2);
const W=cv.clientWidth,H=200,P=28,cols=['#d9403e','#e8923a','#6b8fc2','#2e9e5b'];
const all=Object.values(data).flat();if(!all.length)return;
const xs=[...new Set(all.map(p=>p[0]))].sort(),vmax=90;
ctx.strokeStyle='#ddd';for(let v=0;v<=vmax;v+=30){{const y=H-P-(v/vmax)*(H-2*P);ctx.beginPath();ctx.moveTo(P,y);ctx.lineTo(W-6,y);ctx.stroke();ctx.fillStyle='#888';ctx.font='10px sans-serif';ctx.fillText(v,4,y+3);}}
Object.entries(data).forEach(([seg,pts],i)=>{{ctx.strokeStyle=cols[i%4];ctx.lineWidth=2;ctx.beginPath();
pts.forEach(([t,v],j)=>{{const x=P+(xs.indexOf(t)/(Math.max(xs.length-1,1)))*(W-P-10),y=H-P-(Math.min(v,vmax)/vmax)*(H-2*P);j?ctx.lineTo(x,y):ctx.moveTo(x,y);}});ctx.stroke();
ctx.fillStyle=cols[i%4];ctx.fillRect(P+i*85,H-12,10,10);ctx.fillStyle='#444';ctx.fillText((names[seg]||seg).slice(0,7),P+i*85+13,H-3);}});
xs.filter((_,i)=>i%Math.ceil(xs.length/6)===0).forEach(t=>{{const x=P+(xs.indexOf(t)/(Math.max(xs.length-1,1)))*(W-P-10);ctx.fillStyle='#888';ctx.fillText(t,x-12,H-P+12);}});}}
document.querySelectorAll('details')[2].addEventListener('toggle',e=>{{if(e.target.open)setTimeout(draw,50);}});
</script></body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    upload(cfg, OUT)
    return OUT


def upload(cfg, path):
    """config.upload 가 채워져 있으면 FTP 로 올린다. 실패해도 프로그램은 계속."""
    u = cfg.get("upload") or {}
    if not (u.get("ftp_host") and u.get("ftp_user")):
        return
    import ftplib
    try:
        ftp = ftplib.FTP(u["ftp_host"], timeout=15)
        ftp.login(u["ftp_user"], u.get("ftp_pass", ""))
        for part in [p for p in u.get("remote_dir", "/").split("/") if p]:
            try:
                ftp.cwd(part)
            except ftplib.error_perm:
                ftp.mkd(part); ftp.cwd(part)
        with open(path, "rb") as f:
            ftp.storbinary(f"STOR {u.get('remote_name', 'index.html')}", f)
        ftp.quit()
        print("업로드 완료 →", u.get("public_url", ""))
    except Exception as e:
        print("업로드 실패:", e)
