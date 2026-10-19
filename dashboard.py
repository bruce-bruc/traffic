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


SEG_COLOR = {"smooth": "#2e9e5b", "slow": "#d9a400", "jam": "#d9403e", "unknown": "#999", "fixed": "#b9bec6"}


def route_map_svg(status_by_seg, best):
    """고정 약도. 구간 id별 상태색으로 선을 칠하고, 추천 루트는 굵게."""
    c = lambda sid: SEG_COLOR.get(status_by_seg.get(sid, "fixed"), "#b9bec6")
    w = lambda rid: 9 if rid == best else 5
    wA, wB, wC = w("A"), w("B"), w("C")
    wBC = max(wB, wC)
    dash = lambda sid: ' stroke-dasharray="6 5"' if status_by_seg.get(sid, "fixed") == "fixed" else ""
    L = lambda sid, d, wd: f'<path d="{d}" stroke="{c(sid)}" stroke-width="{wd}" fill="none" stroke-linecap="round"{dash(sid)}/>'
    return f"""<svg viewBox="0 0 360 300" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto">
<rect width="360" height="300" fill="#f5f6f8" rx="12"/>
<!-- 공통: 남동공단 → 제3경인 끝 -->
{L("leg_3rd_gyeongin", "M30 260 L100 260", max(wA, wBC))}
<!-- A: 수원광명 → 강남순환로(관악터널) → 사당IC -->
{L("a_suwon_gwangmyeong", "M100 260 C140 262 160 170 190 130", wA)}
{L("a_before_sadang", "M190 130 L205 112", wA)}
{L("a_sadang_ramp", "M205 112 L220 100", wA)}
<!-- B/C: 110번 → 과천 → 선암IC -->
{L("bc_outer_ring", "M100 260 C160 275 230 265 270 225", wBC)}
{L("bc_gwacheon", "M270 225 L278 180", wBC)}
<!-- C: 선암IC → 남태령 → 사당IC -->
{L("c_namtaeryeong", "M278 180 C265 150 245 120 220 100", wC)}
<!-- 사당IC → 사당역 (A·C 공통) -->
{L("a_sadang_to_station", "M220 100 L245 55", max(wA, wC))}
<!-- B: 선암IC → 우면산터널 → 서초 -->
{L("b_umyeonsan", "M278 180 C305 150 315 100 300 60", wB)}
<!-- 집 -->
<path d="M245 55 L262 30" stroke="#888" stroke-width="4" fill="none" stroke-linecap="round"/>
<path d="M300 60 L270 30" stroke="#888" stroke-width="4" fill="none" stroke-linecap="round"/>
<!-- 지점 -->
<g font-family="-apple-system,Noto Sans KR,sans-serif" font-size="12" fill="#333">
<circle cx="30" cy="260" r="6" fill="#1f3a5f"/><text x="8" y="284">남동공단</text>
<circle cx="100" cy="260" r="6" fill="#1f3a5f"/><text x="82" y="246" font-weight="700">갈림길</text><text x="70" y="284" font-size="10" fill="#666">(제3경인 끝)</text>
<text x="108" y="186" fill="#555">수원광명</text><text x="108" y="200" fill="#555">강남순환로</text><text x="108" y="214" fill="#555" font-size="10">(관악터널)</text>
<text x="160" y="292" fill="#555">110번 외곽순환</text>
<circle cx="270" cy="225" r="5" fill="#1f3a5f"/><text x="282" y="229">과천</text>
<circle cx="278" cy="180" r="6" fill="#1f3a5f"/><text x="288" y="184" font-weight="700">선암IC</text>
<text x="226" y="150" fill="#333" font-weight="700">남태령</text>
<circle cx="220" cy="100" r="6" fill="#1f3a5f"/><text x="150" y="104" font-weight="700">사당IC</text>
<text x="314" y="118" fill="#555">우면산</text><text x="314" y="132" fill="#555">터널</text>
<circle cx="245" cy="55" r="6" fill="#1f3a5f"/><text x="188" y="60">사당역</text>
<circle cx="300" cy="60" r="5" fill="#1f3a5f"/><text x="310" y="64">서초</text>
<text x="252" y="22" font-size="16">🏠</text><text x="274" y="22" font-size="11" fill="#333">방배동 집</text>
</g>
<g font-family="-apple-system,Noto Sans KR,sans-serif" font-size="10" fill="#555">
<rect x="10" y="10" width="178" height="34" rx="6" fill="#fff" opacity=".9"/>
<line x1="18" y1="20" x2="34" y2="20" stroke="#2e9e5b" stroke-width="4"/><text x="38" y="24">원활</text>
<line x1="60" y1="20" x2="76" y2="20" stroke="#d9a400" stroke-width="4"/><text x="80" y="24">서행</text>
<line x1="102" y1="20" x2="118" y2="20" stroke="#d9403e" stroke-width="4"/><text x="122" y="24">정체</text>
<line x1="18" y1="36" x2="34" y2="36" stroke="#b9bec6" stroke-width="4" stroke-dasharray="4 3"/><text x="38" y="40">추정</text>
<text x="128" y="40" font-weight="700">굵은선=추천</text>
</g>
</svg>"""


ROUTE_SHORT = {"A": "수원광명", "BC": "110번·과천", "B": "우면산터널", "C": "남태령", "?": "구간 미상"}


def _issue_icon(i):
    t = str(i.get("type", "")) + i.get("text", "")
    if any(x in t for x in ("사고", "고장")):
        return "🚨"
    if any(x in t for x in ("공사", "작업")):
        return "🚧"
    if any(x in t for x in ("통제", "집회", "행사", "마라톤", "퍼레이드")):
        return "🚫"
    if i.get("type") == "notice":
        return "📢"
    return "⚠"


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def issues_html(incidents, history):
    """내 길 이슈 목록: 지금 걸린 이슈 전체 + 오늘 지나간 이슈."""
    def line(i, extra=""):
        rt = "/".join(ROUTE_SHORT.get(r, r) for r in i.get("routes", []) or ["?"])
        meta = " · ".join(x for x in (str(i.get("start", ""))[:16], extra) if x)
        return (f'<div class="iss">{_issue_icon(i)} <b>[{_esc(rt)}]</b> {_esc(i.get("text", ""))}'
                f'{f"<small>{_esc(meta)}</small>" if meta else ""}</div>')
    cur_keys = {f"{i.get('start','')}|{i.get('text','')[:120]}" for i in incidents}
    today = dt.date.today().isoformat()
    gone = [h for h in history if f"{h['start']}|{h['text'][:120]}" not in cur_keys and h["first_seen"][:10] == today]
    body = "".join(line(i) for i in incidents) or '<div class="iss ok">✅ 지금 내 길에 걸린 이슈 없음</div>'
    if gone:
        body += '<div class="sub">오늘 지나간 이슈</div>' + "".join(
            line(h, f"{h['first_seen'][11:16]}~{h['last_seen'][11:16]} 확인됨") for h in gone)
    body += '<div class="src">출처: 서울시 TOPIS 돌발·통제공지 (사당·남태령·과천·우면산·강남순환 키워드)</div>'
    return (f'<details{" open" if incidents else ""}><summary>⚠ 내 길 이슈 {len(incidents)}건'
            f'{f" · 지나간 {len(gone)}건" if gone else ""}</summary>{body}</details>')


def build_dashboard():
    from predict import plan, fmt_row
    from sources import fetch_weather, fetch_incidents
    from monitor import incident_history
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
    try:
        issues_box = issues_html(incidents, incident_history(days=1))
    except Exception as e:
        issues_box = f'<details><summary>⚠ 내 길 이슈</summary><div class="iss">목록 생성 실패: {_esc(e)}</div></details>'
    from predict import best_windows
    rows = plan(cfg, step_min=5, weather=weather, incidents=incidents)
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

    status_by_seg = {seg: st for seg, spd, st, mn, mode in latest}
    map_svg = route_map_svg(status_by_seg, best_route)

    # ── 출발 시각 선택용 데이터 ──
    SHORT = {rid: r["short"] for rid, r in cfg["routes"].items()}
    picker = [dict(d=r["depart"].strftime("%H:%M"), b=r["best"],
                   t=round(r["routes"][r["best"]]["total"]),
                   a=r["routes"][r["best"]]["arrive"].strftime("%H:%M"),
                   all={rid: round(v["total"]) for rid, v in r["routes"].items()}) for r in rows]
    # 기본 선택: 지금 이후 첫 슬롯
    default_i = next((i for i, r in enumerate(rows) if r["depart"] >= now), 0)

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
.mapbox{{background:#fff;border-radius:14px;padding:8px;margin-bottom:12px;box-shadow:0 1px 2px rgba(0,0,0,.06)}}
.pick{{background:#fff;border-radius:14px;padding:14px 16px;margin-bottom:12px;box-shadow:0 1px 2px rgba(0,0,0,.06)}}
.pick .pl{{font-size:13px;color:#666;margin-bottom:8px}} .pick .row{{display:flex;gap:8px;align-items:center}}
.pick select{{flex:1;font-size:22px;font-weight:700;padding:8px;border:1px solid #ddd;border-radius:10px;background:#fff;color:#222}}
.pb{{width:44px;height:44px;font-size:24px;border:0;border-radius:10px;background:#eef1f5;color:#222}}
.prs{{margin-top:10px;font-size:15px;line-height:1.6}} .prs b{{font-size:20px}} .prs .alt{{font-size:13px;color:#666}}
.two{{display:flex;gap:10px;margin-bottom:12px}}
.box{{flex:1;border-radius:14px;padding:14px 12px;color:#fff}} .box.good{{background:#2e9e5b}} .box.bad{{background:#d9403e}}
.box .t{{font-size:13px;opacity:.9}} .box .h{{font-size:24px;font-weight:700;margin:4px 0}} .box .d{{font-size:13px;opacity:.95;line-height:1.4}}
.tips{{background:#fff;border-radius:14px;padding:14px 16px;margin-bottom:12px;box-shadow:0 1px 2px rgba(0,0,0,.06)}}
.tips div{{padding:6px 0;font-size:15px;border-bottom:1px solid #eee}} .tips div:last-child{{border:0}}
.warn{{background:#fff3cd;border-radius:12px;padding:12px 14px;margin-bottom:12px;font-size:14px}}
.iss{{padding:8px 0;border-bottom:1px solid #eee;font-size:14px;line-height:1.45}} .iss:last-of-type{{border:0}}
.iss small{{display:block;color:#888;font-size:12px}} .iss.ok{{color:#2e9e5b;font-weight:600}}
.sub{{font-size:12px;color:#888;margin-top:10px;padding-top:6px;border-top:1px dashed #ddd}}
.src{{font-size:11px;color:#aaa;margin-top:8px}}
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

{issues_box}

<div class="mapbox">{map_svg}</div>

<div class="pick">
  <div class="pl">출발 예정 시각 고르기</div>
  <div class="row"><button id="pm" class="pb">−</button><select id="ps"></select><button id="pp" class="pb">+</button></div>
  <div id="pr" class="prs"></div>
  <div class="pl" style="margin-top:14px">몇 시까지 도착해야 하나요?</div>
  <div class="row"><button id="am" class="pb">−</button><select id="as"></select><button id="ap" class="pb">+</button></div>
  <div id="ar" class="prs"></div>
</div>

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

<details id="gd"><summary>오늘 속도 그래프</summary><canvas id="c" height="200"></canvas></details>

<div class="foot">마지막 수집 {latest_ts.replace('T',' ') if latest_ts else '-'} · 5분마다 자동 새로고침</div>

<script>
const P={json.dumps(picker, ensure_ascii=False)}, SHORT={json.dumps(SHORT, ensure_ascii=False)};
const ps=document.getElementById('ps'),pr=document.getElementById('pr');
P.forEach((r,i)=>{{const o=document.createElement('option');o.value=i;o.textContent=r.d+' 출발';ps.appendChild(o);}});
let saved=null;try{{saved=localStorage.getItem('depart');}}catch(e){{}}
ps.value=(saved!==null&&P.some((r,i)=>r.d===saved&&(ps.value=i,true)))?ps.value:{default_i};
function show(){{const r=P[ps.value];if(!r)return;try{{localStorage.setItem('depart',r.d);}}catch(e){{}}
  const alts=Object.entries(r.all).filter(([k])=>k!==r.b).map(([k,v])=>SHORT[k]+' '+v+'분').join(' · ');
  pr.innerHTML='<b>'+r.a+' 도착</b> · '+r.t+'분<br>👉 '+SHORT[r.b]+'<div class="alt">다른 길: '+alts+'</div>';}}
ps.onchange=show;document.getElementById('pm').onclick=()=>{{if(ps.value>0){{ps.value--;show();}}}};
document.getElementById('pp').onclick=()=>{{if(ps.value<P.length-1){{ps.value++;show();}}}};show();
// 도착 희망 시각 → 늦어도 언제 출발
const as_=document.getElementById('as'),ar=document.getElementById('ar');
const toM=t=>{{const [h,m]=t.split(':').map(Number);return h*60+m;}};
const arrs=[];for(let m=toM(P[0].d)+30;m<=toM(P[P.length-1].d)+90;m+=10)arrs.push(String(Math.floor(m/60)).padStart(2,'0')+':'+String(m%60).padStart(2,'0'));
arrs.forEach((t,i)=>{{const o=document.createElement('option');o.value=i;o.textContent=t+' 까지';as_.appendChild(o);}});
let sv=null;try{{sv=localStorage.getItem('arrive');}}catch(e){{}}
as_.value=Math.max(0,sv!==null&&arrs.indexOf(sv)>=0?arrs.indexOf(sv):arrs.indexOf('19:00'));
function showA(){{const t=arrs[as_.value];if(!t)return;try{{localStorage.setItem('arrive',t);}}catch(e){{}}
  const ok=P.filter(r=>toM(r.a)<=toM(t));
  if(!ok.length){{ar.innerHTML='<b>그 시각엔 못 가요</b><div class="alt">가장 이른 도착이 '+P[0].a+' 입니다</div>';return;}}
  const last=ok[ok.length-1];
  ar.innerHTML='<b>늦어도 '+last.d+' 출발</b> · '+last.t+'분 → '+last.a+' 도착<br>👉 '+SHORT[last.b]+
    '<div class="alt">여유 있게는 '+(ok.length>2?ok[ok.length-3].d:ok[0].d)+' 출발</div>';}}
as_.onchange=showA;document.getElementById('am').onclick=()=>{{if(as_.value>0){{as_.value--;showA();}}}};
document.getElementById('ap').onclick=()=>{{if(as_.value<arrs.length-1){{as_.value++;showA();}}}};showA();
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
document.getElementById('gd').addEventListener('toggle',e=>{{if(e.target.open)setTimeout(draw,50);}});
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
