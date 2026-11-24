"""구간별 지도 선(폴리라인) 만들기 → data/geo.json  (11-25)

폰 화면의 '지도' 에 쓸 실제 도로 모양. ITS 링크엔 좌표가 없어서, 구간마다 경유지(이름 또는 위경도)를 두고
  1) 이름은 Nominatim(OSM) 으로 좌표를 찾고 (실패하면 아래 적어둔 대략 좌표)
  2) OSRM 공개 서버로 경유지 사이 도로 경로를 받아 선으로 저장한다.
GitHub Actions(해외) 에서 돌며, 경유지 정의가 바뀌었을 때만 다시 만든다 (run.sh 가 호출).
    python geo.py          # 필요할 때만 갱신
    python geo.py --force  # 무조건 다시
"""
import hashlib, json, os, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "geo.json")
UA = {"User-Agent": "traffic-commute-monitor/1.0 (github.com/bruce-bruc/traffic)"}

# 경유지: ("찾을 이름", (대략 위도, 경도)) — 이름을 못 찾으면 괄호 좌표 사용. 좌표만 줄 땐 (위도, 경도).
P = {
    "회사":      ("인천 남동구 호구포로 44번길",     (37.3950, 126.7000)),
    "고잔IC":    ("고잔IC 인천 남동구",             (37.3900, 126.6950)),
    "월곶JC":    ("월곶분기점 시흥",                 (37.3880, 126.7520)),
    "도리JC":    ("도리분기점 시흥",                 (37.4085, 126.8380)),
    "소하JC":    ("소하분기점 광명",                 (37.4480, 126.8850)),
    "금천IC":    ("금천IC 서울 금천구",              (37.4565, 126.8990)),
    "봉천터널":  ("봉천터널 서울 관악구",             (37.4745, 126.9650)),
    "사당IC":    ("사당IC 서울 동작구",              (37.4700, 126.9760)),
    "사당역":    ("사당역 서울",                     (37.4766, 126.9816)),
    "학의JC":    ("학의분기점 의왕",                 (37.3985, 126.9680)),
    "과천청사":  ("정부과천청사역",                   (37.4265, 126.9890)),
    "선암IC":    ("선암IC 과천",                     (37.4480, 126.9980)),
    "우면산터널_서초": ("우면산터널 서초 출구",        (37.4820, 127.0130)),
    "서초":      ("예술의전당 서울 서초구",            (37.4790, 127.0120)),
    "남태령":    ("남태령역 과천",                    (37.4645, 126.9868)),
    "이수역":    ("이수역 서울",                     (37.4855, 126.9820)),
    "방배집":    ("방배우성아파트 서울 서초구 방배동",  (37.4815, 126.9830)),
}

# 구간 → 경유지 순서 (주행 방향). 경로가 엉뚱한 길로 가면 중간 경유지를 더 넣는다.
SEG = {
    "gojan_up":          ["회사", "고잔IC"],
    "leg_3rd_gyeongin":  ["고잔IC", "월곶JC", "도리JC"],
    "a_suwon_gwangmyeong": ["도리JC", "소하JC", "금천IC", "봉천터널"],
    "a_before_sadang":   ["봉천터널", "사당IC"],
    "a_sadang_ramp":     ["사당IC", "사당IC"],
    "a_sadang_to_station": ["사당IC", "사당역"],
    "bc_outer_ring":     ["도리JC", "학의JC", "과천청사"],
    "bc_gwacheon":       ["과천청사", "선암IC"],
    "b_umyeonsan":       ["선암IC", "우면산터널_서초", "서초"],
    "c_namtaeryeong":    ["선암IC", "남태령", "사당IC"],
    "c_sadang_to_station": ["사당IC", "사당역"],
    "m_dongjak_north":   ["방배집", "이수역"],
    "m_dongjak_south":   ["이수역", "사당역"],
    "m_sadang_front":    ["사당역", "사당IC"],
    "m_gojan_down":      ["도리JC", "월곶JC", "고잔IC"],
}


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def geocode(name, fallback, cache):
    if name in cache:
        return cache[name]
    q = urllib.parse.urlencode(dict(q=name, format="json", limit=1, countrycodes="kr"))
    try:
        res = _get("https://nominatim.openstreetmap.org/search?" + q)
        time.sleep(1.1)                                   # Nominatim 예절: 초당 1회
        if res:
            lat, lon = float(res[0]["lat"]), float(res[0]["lon"])
            # 대략 좌표에서 8km 넘게 떨어진 결과는 엉뚱한 곳으로 보고 버림
            if abs(lat - fallback[0]) < 0.07 and abs(lon - fallback[1]) < 0.09:
                cache[name] = [lat, lon, "osm"]
                return cache[name]
    except Exception as e:
        print("  geocode 실패:", name, e)
    cache[name] = [fallback[0], fallback[1], "fallback"]
    return cache[name]


def route(pts):
    """OSRM: [(lat,lon),...] → [[lat,lon],...] 도로 모양 + 지나는 도로명."""
    if len(pts) < 2 or all(p == pts[0] for p in pts):
        return [[p[0], p[1]] for p in pts[:1]] * 2, []
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in pts)
    j = _get(f"https://router.project-osrm.org/route/v1/driving/{coords}?overview=full&geometries=geojson&steps=true")
    r = j["routes"][0]
    line = [[lat, lon] for lon, lat in r["geometry"]["coordinates"]]
    roads = []
    for leg in r["legs"]:
        for st in leg["steps"]:
            n = st.get("name") or st.get("ref") or ""
            if n and (not roads or roads[-1] != n):
                roads.append(n)
    return line, roads


def main(force=False):
    sig = hashlib.md5(json.dumps([P, SEG], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    old = {}
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            old = {}
    if not force and old.get("sig") == sig and old.get("segments"):
        print("geo.json 최신 — 건너뜀")
        return
    cache = {}
    pts = {k: geocode(n, fb, cache) for k, (n, fb) in P.items()}
    for k, v in pts.items():
        print(f"  {k}: {v[0]:.4f},{v[1]:.4f} ({v[2]})")
    segs = {}
    for sid, names in SEG.items():
        try:
            line, roads = route([(pts[n][0], pts[n][1]) for n in names])
            segs[sid] = dict(line=line, roads=roads[:12])
            print(f"  {sid}: {len(line)}점 · " + " → ".join(roads[:8]))
            time.sleep(0.5)
        except Exception as e:
            print(f"  {sid}: 경로 실패 {type(e).__name__} {e}")
            if sid in (old.get("segments") or {}):
                segs[sid] = old["segments"][sid]
    json.dump(dict(sig=sig, built=time.strftime("%Y-%m-%d %H:%M"), points={k: v[:2] for k, v in pts.items()}, segments=segs),
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print("저장:", OUT, len(segs), "구간")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
