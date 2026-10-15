"""
예측: 남동공단 출발 시각별 → 제3경인 끝 갈림길에서 어느 길 → 집 도착 시각.
구간별 예측속도 = 쌓인 요일×시간대 실측 평균 → 없으면 기본 프로파일. 고정 구간은 fixed_min × 피크.
"""
import datetime as dt, math
from monitor import load_config, weekday_pattern, minutes_for, peak_factor, incident_factor
from sources import fetch_incidents, fetch_weather

KOR_DAY = ["월", "화", "수", "목", "금", "토", "일"]


def weather_factor(cfg, weather):
    w = cfg["weather_factors"]
    if not weather:
        return 1.0
    if weather.get("snow"):
        return w["snow"]
    if weather.get("rain_mm", 0) >= 5:
        return w["heavy_rain"]
    if weather.get("rain_mm", 0) > 0:
        return w["rain"]
    return 1.0


def predicted_speed(seg, when, pattern, cfg):
    slot = f"{when.hour:02d}:{'00' if when.minute < 30 else '30'}"
    key = (seg["id"], when.strftime("%a"), slot)
    if key in pattern:
        return pattern[key], "data"
    pr = cfg["default_profile"].get(seg["route"], {"peak_hour": 17.75, "peak_width": 0.9, "max_drop": 0.5})
    h = when.hour + when.minute / 60
    peak = math.exp(-((h - pr["peak_hour"]) ** 2) / (2 * pr["peak_width"] ** 2))
    return seg["free_flow_kmh"] * (1 - pr["max_drop"] * peak), "default"


def seg_minutes(cfg, seg, when, pattern, weather):
    """구간 하나를 'when' 시각에 통과할 때 걸리는 분."""
    wf = weather_factor(cfg, weather)
    if not seg.get("link_ids"):
        return minutes_for(seg, None, cfg, when) * wf, False
    spd, src = predicted_speed(seg, when, pattern, cfg)
    return minutes_for(seg, spd / wf), src == "data"


def route_timeline(cfg, rid, depart, pattern, weather):
    """출발 시각부터 구간을 순서대로 지나며 누적. (각 구간은 도착 시각 기준으로 예측)"""
    inc = set(cfg["routes"][rid]["includes"])
    t = depart
    used_data = False
    split_at = None
    for seg in cfg["segments"]:
        if seg["route"] not in inc:
            continue
        m, used = seg_minutes(cfg, seg, t, pattern, weather)
        used_data |= used
        t += dt.timedelta(minutes=m)
        if seg["route"] == "all":
            split_at = t
    t += dt.timedelta(minutes=cfg["routes"][rid]["extra_min"])
    return dict(total=round((t - depart).total_seconds() / 60, 1), arrive=t, split_at=split_at, data=used_data)


def plan(cfg=None, date=None, step_min=10, weather=None, incidents=None):
    cfg = cfg or load_config()
    date = date or dt.date.today()
    pattern = weekday_pattern()
    pc = cfg["plan"]
    t = dt.datetime.combine(date, dt.time.fromisoformat(pc["earliest_depart"]))
    end = dt.datetime.combine(date, dt.time.fromisoformat(pc["latest_depart"]))
    rows = []
    while t <= end:
        res = {rid: route_timeline(cfg, rid, t, pattern, weather) for rid in cfg["routes"]}
        for rid, v in res.items():
            f = incident_factor(cfg, rid, incidents)
            if f > 1:
                v["total"] = round(v["total"] * f, 1)
                v["arrive"] = t + dt.timedelta(minutes=v["total"])
        best = min(res, key=lambda r: res[r]["total"])
        rows.append(dict(depart=t, split_at=res[best]["split_at"], routes=res, best=best))
        t += dt.timedelta(minutes=step_min)
    return rows


def eta_for(cfg, depart, weather=None):
    rows = plan(cfg, depart.date(), step_min=1, weather=weather)
    return min(rows, key=lambda r: abs((r["depart"] - depart).total_seconds()))


def leg1_minutes(cfg, depart, weather=None):
    """공통 구간(남동공단→갈림길) 소요. dashboard 에서 실시간 2구간과 합칠 때 사용."""
    total = 0
    for seg in cfg["segments"]:
        if seg["route"] == "all":
            total += seg_minutes(cfg, seg, depart, {}, weather)[0]
    return total


# ── 출력 ──────────────────────────────────────────────
def fmt_row(cfg, r):
    parts = []
    for rid, t in r["routes"].items():
        mark = "◀" if r["best"] == rid else " "
        parts.append(f"{cfg['routes'][rid]['short']} {t['arrive']:%H:%M}({t['total']:.0f}분){mark}")
    return f"{r['depart']:%H:%M} 출발 → 갈림길 {r['split_at']:%H:%M}  " + " ".join(parts)


def best_windows(cfg, rows):
    tot = [r["routes"][r["best"]]["total"] for r in rows]
    worst_i = max(range(len(tot)), key=lambda i: tot[i])
    ok = min(tot) * (1 + cfg["plan"].get("tolerance", 0.12))
    before = [r for i, r in enumerate(rows) if i < worst_i and tot[i] <= ok]
    after = [r for i, r in enumerate(rows) if i > worst_i and tot[i] <= ok]
    return rows[worst_i], (before[-1] if before else None), (after[0] if after else None)


def format_plan(cfg, rows, weather=None, incidents=None, now=None):
    now = now or dt.datetime.now()
    d = rows[0]["depart"]
    head = [f"📅 {d:%m/%d}({KOR_DAY[d.weekday()]}) 남동공단 → 방배동 예측"]
    if weather:
        head.append("🌧 " + weather.get("desc", "비 예보") if weather.get("rain_mm") or weather.get("snow") else "☀ 날씨 영향 없음")
    for i in (incidents or [])[:4]:
        head.append(f"⚠ [{','.join(i.get('routes', []))}] {i['text'][:50]}")
    data_based = any(v["data"] for r in rows for v in r["routes"].values())
    head.append("(실데이터 기반)" if data_based else "(기본 프로파일 — 데이터 쌓이면 정확해짐)")
    lines = head + [""] + [fmt_row(cfg, r) for r in rows]
    worst, before, after = best_windows(cfg, rows)
    def f(r):
        t = r["routes"][r["best"]]
        return f"{r['depart']:%H:%M} 출발 → {t['arrive']:%H:%M} 도착 ({t['total']:.0f}분, {cfg['routes'][r['best']]['short']})"
    lines += ["", f"⛔ 최악: {worst['depart']:%H:%M} 출발 ({worst['routes'][worst['best']]['total']:.0f}분)"]
    if before:
        lines.append("🏁 밀리기 전 마지노선: " + f(before))
    if after:
        lines.append("🌙 풀린 뒤 첫 시각: " + f(after))
    nowrow = min(rows, key=lambda r: abs((r["depart"] - now).total_seconds()))
    if abs((nowrow["depart"] - now).total_seconds()) < 1800:
        lines.append("🚗 지금 출발하면: " + f(nowrow))
    return "\n".join(lines)


def run_plan(cfg=None, push=False):
    from monitor import notify
    cfg = cfg or load_config()
    weather = fetch_weather(cfg)
    incidents = fetch_incidents(cfg)
    rows = plan(cfg, weather=weather, incidents=incidents)
    text = format_plan(cfg, rows, weather, incidents)
    if push:
        notify(cfg, text)
    return text, rows
