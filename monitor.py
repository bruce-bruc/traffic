"""
핵심 로직: 수집 → 점수화 → 루트 비교 → 기록 → 알림.
"""
import sqlite3, datetime as dt, json, os, math
import requests, yaml
from sources import fetch_segment, fetch_incidents

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "data", "traffic.db")


def load_config():
    with open(os.path.join(HERE, "config.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # GitHub Actions 등에서는 환경변수로 키 주입 (공개 저장소에 키를 두지 않기 위해)
    for env, key in (("ITS_KEY", "its_national"), ("TOPIS_KEY", "seoul_topis"), ("KMA_KEY", "kma_weather")):
        if os.environ.get(env):
            cfg["api_keys"][key] = os.environ[env]
    return cfg


def db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS readings(
        ts TEXT, segment TEXT, speed REAL, mode TEXT, status TEXT, minutes REAL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS verdicts(
        ts TEXT, best_route TEXT, totals TEXT, note TEXT)""")
    # 이슈(돌발·공사·통제·공지) 기록: 같은 이슈는 첫 발견(first_seen)~마지막 발견(last_seen) 으로 한 줄
    con.execute("""CREATE TABLE IF NOT EXISTS incidents(
        key TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT,
        type TEXT, routes TEXT, start TEXT, text TEXT)""")
    return con


def peak_factor(cfg, when):
    """0~1: 퇴근 피크 중심에서 1."""
    p = cfg.get("peak", {"hour": 17.75, "width": 0.9})
    h = when.hour + when.minute / 60
    return math.exp(-((h - p["hour"]) ** 2) / (2 * p["width"] ** 2))


def status_of(speed, th):
    if speed is None:
        return "unknown"
    if speed >= th["smooth"]:
        return "smooth"
    if speed >= th["slow"]:
        return "slow"
    return "jam"


def minutes_for(seg, speed, cfg=None, when=None):
    """링크 구간: 길이/속도. 고정 구간: fixed_min × (1 + ratio × peak)."""
    if not seg.get("link_ids"):
        when = when or dt.datetime.now()
        pf = peak_factor(cfg, when) if cfg else 0
        m = seg["fixed_min"] * (1 + seg.get("peak_extra_ratio", 0) * pf)
        if cfg and when.weekday() == 4:
            m *= cfg.get("friday_factor", 1.0)
        return round(m, 1)
    v = speed if speed else seg["free_flow_kmh"] / 2.5
    return round(seg["length_km"] / max(v, 3) * 60, 1)


def collect_once(cfg, now=None):
    now = now or dt.datetime.now()
    th = cfg["thresholds"]
    rows = []
    for seg in cfg["segments"]:
        if seg.get("link_ids"):
            spd, mode = fetch_segment(seg, cfg["api_keys"], now)
            st = status_of(spd, th)
        else:
            spd, mode, st = None, "fixed", "fixed"
        rows.append(dict(ts=now.isoformat(timespec="minutes"), segment=seg["id"],
                         name=seg["name"], route=seg["route"],
                         speed=spd, mode=mode, status=st, minutes=minutes_for(seg, spd, cfg, now)))
    return rows


def route_total(cfg, rid, rows):
    r = cfg["routes"][rid]
    inc = set(r["includes"])
    return round(sum(x["minutes"] for x in rows if x["route"] in inc) + r["extra_min"], 1)


def incident_factor(cfg, rid, incidents):
    """해당 루트에 걸린 이슈 중 가장 큰 계수."""
    f = 1.0
    inc_r = set(cfg["routes"][rid]["includes"])
    for i in incidents or []:
        if not (set(i.get("routes", [])) & inc_r):
            continue
        t = str(i.get("type", "")) + i.get("text", "")
        k = ("accident" if any(x in t for x in ("사고", "고장", "accident")) else
             "construction" if any(x in t for x in ("공사", "작업")) else
             "control" if any(x in t for x in ("통제", "집회", "행사", "마라톤", "퍼레이드")) else "other")
        f = max(f, cfg.get("incident_factors", {}).get(k, 1.15))
    return f


def compare_routes(cfg, rows, incidents=None):
    totals = {rid: round(route_total(cfg, rid, rows) * incident_factor(cfg, rid, incidents), 1)
              for rid in cfg["routes"]}
    best = min(totals, key=totals.get)
    vals = sorted(totals.values())
    diff = vals[1] - vals[0] if len(vals) > 1 else 0
    note = "비슷함 — 아무 쪽이나" if diff < 4 else f"{cfg['routes'][best]['short']}이 다음 길보다 약 {diff:.0f}분 빠름"
    return best, totals, note


def save(con, rows, best, totals, note):
    con.executemany("INSERT INTO readings VALUES (?,?,?,?,?,?)",
                    [(r["ts"], r["segment"], r["speed"], r["mode"], r["status"], r["minutes"]) for r in rows])
    con.execute("INSERT INTO verdicts VALUES (?,?,?,?)",
                (rows[0]["ts"], best, json.dumps(totals), note))
    con.commit()


def incident_key(i):
    return f"{i.get('start','')}|{i.get('text','')[:120]}"


def save_incidents(con, ts, incidents):
    """현재 보이는 이슈를 기록 (처음 본 건 추가, 이미 있으면 last_seen 갱신)."""
    for i in incidents or []:
        con.execute("""INSERT INTO incidents(key, first_seen, last_seen, type, routes, start, text)
                       VALUES (?,?,?,?,?,?,?)
                       ON CONFLICT(key) DO UPDATE SET last_seen=excluded.last_seen""",
                    (incident_key(i), ts, ts, str(i.get("type", "")), ",".join(i.get("routes", [])),
                     str(i.get("start", "")), i.get("text", "")))
    con.commit()


def incident_history(days=1):
    """최근 days 일 동안 기록된 이슈 (최근 발견 순)."""
    con = db()
    since = (dt.datetime.now() - dt.timedelta(days=days)).isoformat(timespec="minutes")
    rows = con.execute("""SELECT first_seen, last_seen, type, routes, start, text FROM incidents
                          WHERE last_seen >= ? ORDER BY last_seen DESC, first_seen DESC""", (since,)).fetchall()
    con.close()
    return [dict(first_seen=a, last_seen=b, type=c, routes=d.split(",") if d else [], start=e, text=f)
            for a, b, c, d, e, f in rows]


ICON ={"smooth": "🟢", "slow": "🟡", "jam": "🔴", "unknown": "⚪", "fixed": "▫️"}


def format_summary(cfg, rows, best, totals, note, incidents=None):
    ts = rows[0]["ts"].replace("T", " ")
    demo = any(r["mode"] == "demo" for r in rows)
    lines = [f"🚗 퇴근길 {ts}" + ("  [데모]" if demo else "")]
    for i in (incidents or [])[:4]:
        rt = ",".join(i.get("routes", []))
        lines.append(f"⚠ [{rt}] {i['text'][:60]}")
    for r in rows:
        if r["mode"] == "fixed":
            lines.append(f"▫️ {r['name']}: 약 {r['minutes']:.0f}분 (추정)")
        else:
            spd = f"{r['speed']:.0f}km/h" if r["speed"] else "자료없음"
            lines.append(f"{ICON[r['status']]} {r['name']}: {spd} ({r['minutes']:.0f}분)")
    lines.append("")
    for rid, t in totals.items():
        lines.append(f"{'👉' if rid == best else '  '} {cfg['routes'][rid]['name']} ≈ {t:.0f}분")
    lines.append(note)
    return "\n".join(lines)


def notify(cfg, text):
    n = cfg["notify"]
    if n.get("telegram_bot_token") and n.get("telegram_chat_id"):
        try:
            requests.post(f"https://api.telegram.org/bot{n['telegram_bot_token']}/sendMessage",
                          json={"chat_id": n["telegram_chat_id"], "text": text}, timeout=10)
            return "telegram"
        except Exception as e:
            print("텔레그램 전송 실패:", e)
    print(text)
    return "console"


def run_once(cfg=None, push=False, now=None):
    cfg = cfg or load_config()
    rows = collect_once(cfg, now)
    incidents = fetch_incidents(cfg)
    best, totals, note = compare_routes(cfg, rows, incidents)
    con = db()
    save(con, rows, best, totals, note)
    save_incidents(con, rows[0]["ts"], incidents)
    con.close()
    text = format_summary(cfg, rows, best, totals, note, incidents)
    if push:
        notify(cfg, text)
    return text, rows, totals


# ── 통계 ──────────────────────────────────────────────
def weekday_pattern(segment_id=None):
    """요일×30분대별 평균 속도."""
    con = db()
    rows = con.execute("SELECT ts, segment, speed FROM readings WHERE speed IS NOT NULL").fetchall()
    con.close()
    agg = {}
    for ts, seg, spd in rows:
        if segment_id and seg != segment_id:
            continue
        t = dt.datetime.fromisoformat(ts)
        slot = f"{t.hour:02d}:{'00' if t.minute < 30 else '30'}"
        agg.setdefault((seg, t.strftime("%a"), slot), []).append(spd)
    return {k: round(sum(v) / len(v), 1) for k, v in sorted(agg.items())}
