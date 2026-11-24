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

# 경유지. 종류:
#   ("jct", "이름 정규식", (위도, 경도))  → OSM 고속도로 나들목/분기점 노드(highway=motorway_junction)에서 찾음 (가장 정확)
#   ("way", "도로명", (위도, 경도))       → OSM 에서 그 이름의 길을 찾아 가운데 좌표
#   ("name", "검색어", (위도, 경도))      → Nominatim 주소 검색
#   ("fixed", 위도, 경도)                → 좌표 그대로
# 괄호 좌표는 못 찾았을 때 쓰는 대략값이자, 검색 범위(±5km)의 중심.
P = {
    "회사":      ("way",  "호구포로44번길",        (37.3950, 126.7000)),
    "고잔IC":    ("jct",  "고잔",                 (37.3900, 126.6950)),
    "월곶JC":    ("jct",  "월곶",                 (37.3840, 126.7600)),
    "도리JC":    ("jct",  "도리",                 (37.3944, 126.8503)),
    "소하JC":    ("jct",  "소하",                 (37.4338, 126.8983)),
    "금천IC":    ("jct",  "금천",                 (37.4500, 126.9000)),
    "봉천터널":  ("name", "봉천터널 서울 관악구",   (37.4672, 126.9704)),
    "사당IC":    ("jct",  "사당",                 (37.4710, 126.9770)),
    "사당역":    ("name", "사당역 서울",           (37.4744, 126.9820)),
    "학의JC":    ("jct",  "학의",                 (37.3950, 126.9800)),
    "과천청사":  ("name", "정부과천청사역",         (37.4265, 126.9890)),
    "선암IC":    ("jct",  "선암",                 (37.4480, 126.9980)),
    "우면산터널_서초": ("name", "우면산터널 서초",  (37.4820, 127.0130)),
    "서초":      ("name", "예술의전당 서울 서초구",  (37.4803, 127.0132)),
    "남태령":    ("name", "남태령역 과천",          (37.4656, 126.9881)),
    "이수역":    ("name", "이수역 서울",           (37.4866, 126.9820)),
    "방배집":    ("fixed", 37.4810, 126.9822),     # 동작대로 위(방배동 쪽), 사당역~이수역 사이
}

# 구간 → 경유지 순서 (주행 방향). 경로가 엉뚱한 길로 가면 중간 경유지를 더 넣는다.
SEG = {
    "gojan_up":          ["회사", "고잔IC"],
    "leg_3rd_gyeongin":  ["고잔IC", "월곶JC", "도리JC"],
    "a_suwon_gwangmyeong": ["도리JC", "소하JC", "금천IC", "봉천터널"],   # 외곽순환 → 소하JC → 수원광명 끝 → 강남순환로
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


OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
            "https://lz4.overpass-api.de/api/interpreter", "https://z.overpass-api.de/api/interpreter"]


def _overpass(q):
    """서버가 바쁘면(502/429/504) 다른 미러로, 그래도 안 되면 잠시 쉬고 다시."""
    data = urllib.parse.urlencode({"data": q}).encode()
    last = None
    for attempt in range(3):
        for url in OVERPASS:
            try:
                req = urllib.request.Request(url, data=data, headers=UA)
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.loads(r.read().decode("utf-8")).get("elements", [])
            except Exception as e:
                last = e
                time.sleep(1)
        time.sleep(8 * (attempt + 1))
    raise last


def _bbox(c, d=0.045):
    return f"{c[0]-d},{c[1]-d},{c[0]+d},{c[1]+d}"


def _near(c, lat, lon, d=0.07):
    return abs(lat - c[0]) < d and abs(lon - c[1]) < d


def geocode(spec, cache):
    kind = spec[0]
    key = json.dumps(spec, ensure_ascii=False)
    if key in cache:
        return cache[key]
    if kind == "fixed":
        cache[key] = [spec[1], spec[2], "fixed"]
        return cache[key]
    q, fb = spec[1], spec[2]
    try:
        if kind == "jct":
            els = _overpass(f'[out:json][timeout:25];node["highway"="motorway_junction"]["name"~"{q}"]({_bbox(fb)});out;')
            if els:          # 여러 개(상·하행)면 대략값에 가장 가까운 것
                e = min(els, key=lambda e: (e["lat"] - fb[0]) ** 2 + (e["lon"] - fb[1]) ** 2)
                cache[key] = [e["lat"], e["lon"], "osm-jct:" + str(e.get("tags", {}).get("name"))]
                return cache[key]
        elif kind == "way":
            els = _overpass(f'[out:json][timeout:25];way["name"="{q}"]({_bbox(fb)});out center;')
            if els and "center" in els[0]:
                cache[key] = [els[0]["center"]["lat"], els[0]["center"]["lon"], "osm-way"]
                return cache[key]
        elif kind == "name":
            res = _get("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(dict(q=q, format="json", limit=3, countrycodes="kr")))
            time.sleep(1.1)                           # Nominatim 예절: 초당 1회
            for r in res:
                lat, lon = float(r["lat"]), float(r["lon"])
                if _near(fb, lat, lon):
                    cache[key] = [lat, lon, "osm"]
                    return cache[key]
    except Exception as e:
        print("  찾기 실패:", spec, type(e).__name__, e)
    cache[key] = [fb[0], fb[1], "fallback"]
    return cache[key]


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
    pts = {k: geocode(spec, cache) for k, spec in P.items()}
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
