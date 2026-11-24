"""구간별 지도 선(폴리라인) 만들기 → data/geo.json  (11-25)

폰 화면의 '지도' 에 쓸 실제 도로 모양. ITS 링크엔 좌표가 없어서,
  1) 몇 개 기준점(회사·사당역·과천청사·서초·남태령·이수역·집)을 Nominatim(OSM) 으로 찾고 (실패하면 대략 좌표)
  2) OSRM 공개 서버에 기준점 사이 길을 물어 '길 안내 단계(도로명 + 모양)' 를 받은 뒤
  3) 도로명으로 잘라 config 의 구간 id 에 배분한다 (예: '제3경인고속화도로' 단계 = leg_3rd_gyeongin).
나들목 좌표를 직접 맞출 필요가 없어서 틀릴 여지가 적다. GitHub Actions 에서 돌고, 정의가 바뀌었을 때만 다시 만든다.
    python geo.py          # 필요할 때만 갱신
    python geo.py --force  # 무조건 다시
"""
import hashlib, json, os, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "geo.json")
UA = {"User-Agent": "traffic-commute-monitor/1.0 (github.com/bruce-bruc/traffic)"}

# 기준점: (검색어 후보들, 대략 좌표). 검색 결과가 대략 좌표에서 7km 넘게 벗어나면 버리고 대략 좌표를 쓴다.
P = {
    "회사":     (["호구포로44번길 남동구", "인천 남동구 고잔동 호구포로 44", "남동인더스파크"], (37.3950, 126.7000)),
    "사당역":   (["사당역 서울"], (37.4766, 126.9816)),
    "학의JC":   (["학의분기점 의왕", "학의JC", "학의 분기점"], (37.3950, 126.9950)),       # 외곽순환 → 봉담과천로 갈라지는 곳 (경유 강제용)
    "과천청사": (["정부과천청사역", "정부과천청사"], (37.4265, 126.9895)),
    "서초":     (["예술의전당 서울 서초구"], (37.4803, 127.0132)),
    "남태령":   (["남태령역 과천"], (37.4656, 126.9881)),
    "이수역":   ([], (37.4860, 126.9820)),          # 동작대로 위 (검색 결과가 옆길로 붙어서 좌표 고정)
    "방배집":   ([], (37.4805, 126.9821)),          # 동작대로 위(방배동 쪽), 사당역~이수역 사이
}

# 길 묻기: 이름 → (경유 기준점들, 꼭 지나야 하는 도로명 — 대안 경로 중 이걸 포함한 것을 고른다)
ROUTES = {
    "A": (["회사", "사당역"], ["제3경인", "강남순환로"]),          # 수원광명 → 강남순환로 → 사당IC → 사당역
    "B": (["회사", "학의JC", "서초"], ["제3경인", "우면산"]),      # 외곽순환 → 학의JC → 봉담과천로 → 과천대로 → 우면산터널
    "C": (["과천청사", "남태령", "사당역"], ["과천대로"]),         # 과천대로 → 남태령 → 사당IC → 사당역
    "M": (["방배집", "이수역", "사당역", "남태령"], ["동작대로"]), # 출근: 집 앞 북행 → 유턴 → 사당역 → 사당IC
    "R": (["서초", "학의JC", "회사"], ["제3경인"]),            # 출근 역방향: 제3경인 하행 → 고잔IC
}


def _get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            time.sleep(3 * (i + 1))
    raise last


def geocode(name):
    qs, fb = P[name]
    for q in qs:
        try:
            res = _get("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(dict(q=q, format="json", limit=3, countrycodes="kr")))
            time.sleep(1.1)                                   # Nominatim 예절: 초당 1회
            for r in res:
                lat, lon = float(r["lat"]), float(r["lon"])
                if abs(lat - fb[0]) < 0.065 and abs(lon - fb[1]) < 0.08:
                    return [lat, lon, "osm:" + q]
        except Exception as e:
            print("  찾기 실패:", q, type(e).__name__, e)
    return [fb[0], fb[1], "fallback"]


def osrm(pts):
    """기준점들 사이 길. 돌려주는 값: 대안 경로 목록, 각 경로는 leg 별 steps [{name, dist, line}]"""
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in pts)
    j = _get(f"https://router.project-osrm.org/route/v1/driving/{coords}?overview=false&geometries=geojson&steps=true&alternatives=true")
    out = []
    for r in j.get("routes", []):
        legs = []
        for leg in r["legs"]:
            steps = []
            for st in leg["steps"]:
                line = [[lat, lon] for lon, lat in st["geometry"]["coordinates"]]
                steps.append(dict(name=st.get("name") or "", dist=float(st.get("distance") or 0), line=line))
            legs.append(steps)
        out.append(legs)
    return out


def pick(routes, must):
    """꼭 지나야 하는 도로명을 모두 포함한 대안 경로. 없으면 첫 번째."""
    for k, legs in enumerate(routes):
        big = [s["name"] for leg in legs for s in leg if s["dist"] > 1500 and s["name"]]
        print(f"   대안 {k + 1}: " + " → ".join(dict.fromkeys(big)))
    for legs in routes:
        names = " ".join(s["name"] for leg in legs for s in leg)
        if all(m in names for m in must):
            return legs
    print("   (원하는 도로를 지나는 경로를 못 찾아 첫 번째 경로 사용)")
    return routes[0] if routes else None


def tail_m(steps, meters):
    """단계 목록의 뒤에서 meters 만큼만 남김 (단계 단위로 자르고, 걸치는 단계는 점 비율로)."""
    acc, keep = 0.0, []
    for s in reversed(steps):
        if acc >= meters:
            break
        if acc + s["dist"] <= meters:
            keep.insert(0, s); acc += s["dist"]
        else:
            frac = (meters - acc) / max(s["dist"], 1)
            n = max(2, int(len(s["line"]) * frac) + 1)
            keep.insert(0, dict(name=s["name"], dist=meters - acc, line=s["line"][-n:]))
            break
    return keep


def head_m(steps, meters):
    """앞에서 meters 만큼만 남김."""
    acc, keep = 0.0, []
    for s in steps:
        if acc >= meters:
            break
        if acc + s["dist"] <= meters:
            keep.append(s); acc += s["dist"]
        else:
            frac = (meters - acc) / max(s["dist"], 1)
            n = max(2, int(len(s["line"]) * frac) + 1)
            keep.append(dict(name=s["name"], dist=meters - acc, line=s["line"][:n]))
            break
    return keep


def total_m(steps):
    return sum(s["dist"] for s in steps)


def line_of(steps):
    out = []
    for s in steps:
        for p in s["line"]:
            if not out or out[-1] != p:
                out.append(p)
    return out


def split_by(steps, key):
    """key(name) 가 True 인 첫 단계부터 끝까지 / 그 앞."""
    for i, s in enumerate(steps):
        if key(s["name"]):
            return steps[:i], steps[i:]
    return steps, []


def main(force=False):
    sig = hashlib.md5(json.dumps([P, ROUTES, 7], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    old = {}
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            old = {}
    if not force and old.get("sig") == sig and old.get("segments"):
        print("geo.json 최신 — 건너뜀")
        return
    pts = {k: geocode(k) for k in P}
    for k, v in pts.items():
        print(f"  {k}: {v[0]:.4f},{v[1]:.4f} ({v[2]})")
    segs = {}

    def put(sid, steps):
        ln = line_of(steps)
        if len(ln) >= 2:
            segs[sid] = dict(line=ln, roads=[s["name"] for s in steps if s["name"]][:10])
            print(f"  {sid}: {len(ln)}점 {total_m(steps)/1000:.1f}km · " + " → ".join(dict.fromkeys(s["name"] for s in steps if s["name"])))
        else:
            print(f"  {sid}: 선 없음")

    def get(rid):
        names, must = ROUTES[rid]
        legs = pick(osrm([(pts[n][0], pts[n][1]) for n in names]), must)
        time.sleep(1)
        return legs

    # A: 회사 → [호구포로·아암대로] → 제3경인 → 외곽순환·수원광명·강남순환로 → (마지막 1km) → 램프 → 사당역
    try:
        a = get("A")[0]
        pre, rest = split_by(a, lambda n: "제3경인" in n)
        put("gojan_up", pre)
        leg3 = [s for s in rest if "제3경인" in s["name"]]
        put("leg_3rd_gyeongin", leg3)
        after = rest[len(leg3):]
        last_g = max((i for i, s in enumerate(after) if "강남순환로" in s["name"]), default=len(after) - 1)
        hwy, city = after[:last_g + 1], after[last_g + 1:]
        put("a_suwon_gwangmyeong", head_m(hwy, total_m(hwy) - 1000))
        put("a_before_sadang", tail_m(hwy, 1000))
        put("a_sadang_ramp", city[:1])
        put("a_sadang_to_station", city[1:] if len(city) > 1 else city)
    except Exception as e:
        print("  A 실패:", type(e).__name__, e)

    # B: 회사 → 제3경인 → 외곽순환 → 봉담과천로 → [과천대로 시내] → 우면산터널 → 서초
    try:
        b = [st for leg in get("B") for st in leg]
        _, rest = split_by(b, lambda n: "제3경인" in n)
        rest = rest[len([s for s in rest if "제3경인" in s["name"]]):]
        ring, gc = split_by(rest, lambda n: "과천대로" in n)
        put("bc_outer_ring", ring)
        gc, um = split_by(gc, lambda n: "우면산" in n)
        put("bc_gwacheon", gc)
        put("b_umyeonsan", um)
    except Exception as e:
        print("  B 실패:", type(e).__name__, e)

    # C: 과천청사 → 남태령 → 사당IC → 사당역  (마지막 1km = 사당IC → 사당역)
    try:
        c = get("C")
        allc = c[0] + c[1]
        _, allc = split_by(allc, lambda n: "과천대로" in n)        # 과천 시내 골목은 빼고 과천대로부터
        put("c_namtaeryeong", head_m(allc, total_m(allc) - 1000))
        put("c_sadang_to_station", tail_m(allc, 1000))
    except Exception as e:
        print("  C 실패:", type(e).__name__, e)

    # M: 집 → 이수역(북행) → 사당역(남행) → 사당IC 방향 (남태령 쪽으로 가는 길의 앞 1.2km)
    try:
        m = get("M")
        put("m_dongjak_north", m[0])
        put("m_dongjak_south", m[1])
        put("m_sadang_front", head_m(m[2], 1200))
    except Exception as e:
        print("  M 실패:", type(e).__name__, e)

    # R: 서초 → 과천 → 외곽순환 → 제3경인 하행 → 고잔IC : 제3경인 단계의 뒤쪽 9km (영동JC 전 ~ 고잔IC) + 출구 한 단계
    try:
        r = get("R")
        allr = [s for leg in r for s in leg]
        idx = [i for i, s in enumerate(allr) if "제3경인" in s["name"]]
        leg3 = [allr[i] for i in idx]
        exit_ = allr[idx[-1] + 1: idx[-1] + 2] if idx else []
        put("m_gojan_down", tail_m(leg3, 9000) + exit_)
    except Exception as e:
        print("  R 실패:", type(e).__name__, e)

    if not segs:
        print("아무 구간도 못 만듦 — 이전 geo.json 유지")
        return
    for sid, v in (old.get("segments") or {}).items():
        segs.setdefault(sid, v)
    json.dump(dict(sig=sig, built=time.strftime("%Y-%m-%d %H:%M"), points={k: v[:2] for k, v in pts.items()}, segments=segs),
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print("저장:", OUT, len(segs), "구간")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
