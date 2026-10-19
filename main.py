"""
사용법
  python main.py now            지금 한 번 수집해서 요약 출력
  python main.py push           지금 수집하고 텔레그램 푸시
  python main.py loop           설정된 시간대에 interval 마다 수집, push_time 에 푸시 (계속 실행)
  python main.py stats          쌓인 데이터로 요일·시간대별 평균 속도 표
  python main.py dashboard      data/dashboard.html 생성
  python main.py find-links     인증키로 링크 ID 후보 찾기 (config 에 채워넣기용)
  python main.py plan           오늘 출발 시각별 예상 도착 + 가장 덜 밀리는 출발 시각
  python main.py eta 17:10      17:10 에 남동공단 출발하면 몇 시 도착?
  python main.py plan push      예측표를 텔레그램으로
  python main.py issues         내 길에 걸린 이슈(사고·공사·통제·공지) 목록 + 오늘 기록
"""
import sys, time, datetime as dt
from monitor import load_config, run_once, weekday_pattern
from dashboard import build_dashboard
from sources import seoul_topis_find_links, its_find_links
from predict import run_plan, eta_for, fmt_row


def in_window(cfg, now):
    c = cfg["collect"]
    if c.get("weekdays_only") and now.weekday() >= 5:
        return False
    hm = now.strftime("%H:%M")
    return c["start"] <= hm <= c["end"]


def open_dashboard():
    import subprocess, platform, os
    path = os.path.abspath(os.path.join("data", "dashboard.html"))
    try:
        if platform.system() == "Darwin":
            subprocess.Popen(["open", path])
        elif platform.system() == "Windows":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        print("브라우저 열기 실패:", e)


def loop(cfg):
    pushed_date = None
    planned_date = None
    print("모니터 시작. Ctrl+C 로 종료.")
    run_once(cfg)                      # 시작하자마자 한 번 수집
    build_dashboard()
    open_dashboard()                   # 브라우저 창 자동 열기 (이후 5분마다 자동 새로고침)
    while True:
        now = dt.datetime.now()
        if now.weekday() < 5 and now.strftime("%H:%M") >= cfg["plan"]["push_time"] and planned_date != now.date():
            run_plan(cfg, push=True)          # 오후 예측표 1회 푸시
            planned_date = now.date()
        if in_window(cfg, now):
            push = (now.strftime("%H:%M") >= cfg["notify"]["push_time"] and pushed_date != now.date())
            text, *_ = run_once(cfg, push=push, now=now)
            if push:
                pushed_date = now.date()
            else:
                print(text.splitlines()[0], "| 저장됨")
            try:
                build_dashboard()
            except Exception as e:
                print("대시보드 갱신 실패:", e)
        else:
            try:
                run_once(cfg); build_dashboard()
            except Exception as e:
                print("갱신 실패:", e)
            time.sleep(25 * 60)
            continue
        time.sleep(cfg["collect"]["interval_min"] * 60)


def stats():
    pat = weekday_pattern()
    if not pat:
        print("아직 쌓인 데이터가 없습니다.")
        return
    cur = None
    for (seg, day, slot), spd in pat.items():
        if seg != cur:
            print(f"\n■ {seg}")
            cur = seg
        print(f"  {day} {slot}  {spd:5.1f} km/h")


def find_links(cfg):
    keys = cfg["api_keys"]
    seen = set()
    for seg in cfg["segments"]:
        if seg["source"] == "seoul_topis" and seg["road_axis"] not in seen:
            seen.add(seg["road_axis"])
            print(f"\n[TOPIS 매핑표] {seg['road_axis']} 후보:")
            try:
                header, rows = seoul_topis_find_links(seg["road_axis"])
                print("   컬럼:", " | ".join(header))
                for d in rows[:60]:
                    print("  ", " | ".join(str(v) for v in d.values()))
                if not rows:
                    print("   (없음 — 도로명 표기가 다를 수 있음. 엑셀을 직접 열어 확인)")
            except Exception as e:
                print("  ", e)
    if keys.get("its_national"):
        print("\n[ITS] 사당~선암 영역 링크 (도로명으로 골라 쓰세요):")
        try:
            items = its_find_links(keys["its_national"])
            print(f"   총 {len(items)}개. 첫 항목 필드:", list(items[0].keys()) if items else "-")
            KEY_ROADS = ("과천대로", "동작대로", "남부순환", "우면산", "강남순환", "사당로", "방배로", "남태령", "효령로")
            hits = [i for i in items if any(k in str(i.get("roadName", "")) for k in KEY_ROADS)]
            for i in sorted(hits, key=lambda x: str(x.get("roadName"))):
                print(f"   {i.get('linkId')} | {i.get('roadName')} | {i.get('speed')}km/h | {i.get('startNodeId','')}→{i.get('endNodeId','')}")
            if not hits:
                print("   (관심 도로명 매칭 없음 — 전체 도로명 목록:)", sorted({str(i.get("roadName")) for i in items})[:60])
        except Exception as e:
            print("  ", e)
    if keys.get("seoul_topis"):
        print("\n[TOPIS 연결 테스트] 샘플 링크 1220003800:")
        try:
            from sources import seoul_topis
            print("  ", seoul_topis(keys["seoul_topis"], ["1220003800"]) or "응답은 왔지만 속도값 없음")
        except Exception as e:
            print("  ", e)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "now"
    cfg = load_config()
    if cmd == "now":
        text, rows, totals = run_once(cfg)
        now = dt.datetime.now()
        best = min(totals, key=totals.get)
        total = round(totals[best])
        arrive = now + dt.timedelta(minutes=total)
        r = cfg["routes"][best]
        print(f"\n🚗 지금 남동공단 출발 → 집 도착 {arrive:%H:%M} (약 {total}분)")
        print(f"👉 제3경인 끝 갈림길에서 {r['short']}: {r['name']}\n")
        print(text)
        build_dashboard()
    elif cmd == "push":
        run_once(cfg, push=True)
    elif cmd == "loop":
        loop(cfg)
    elif cmd == "stats":
        stats()
    elif cmd == "dashboard":
        print("생성:", build_dashboard())
    elif cmd == "find-links":
        find_links(cfg)
    elif cmd == "plan":
        text, _ = run_plan(cfg, push=(len(sys.argv) > 2 and sys.argv[2] == "push"))
        print(text)
    elif cmd == "issues":
        from sources import fetch_incidents
        from monitor import incident_history
        from dashboard import ROUTE_SHORT
        cur = fetch_incidents(cfg)
        print(f"⚠ 지금 내 길 이슈 {len(cur)}건")
        for i in cur:
            print(f"  [{'/'.join(ROUTE_SHORT.get(r, r) for r in i['routes'])}] {i['text']}  ({i.get('start','')[:16]})")
        hist = incident_history(days=1)
        if hist:
            print(f"\n최근 24시간 기록 {len(hist)}건")
            for h in hist:
                print(f"  {h['first_seen'][5:16]}~{h['last_seen'][11:16]} [{'/'.join(ROUTE_SHORT.get(r, r) for r in h['routes'])}] {h['text']}")
    elif cmd == "eta":
        hm = sys.argv[2] if len(sys.argv) > 2 else dt.datetime.now().strftime("%H:%M")
        depart = dt.datetime.combine(dt.date.today(), dt.time.fromisoformat(hm))
        print(fmt_row(cfg, eta_for(cfg, depart)))
    else:
        print(__doc__)
