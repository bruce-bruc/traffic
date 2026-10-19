"""
교통 데이터 소스 어댑터.
각 함수는 {link_id: speed_kmh} 딕셔너리를 돌려준다.
인증키가 비어 있으면 데모 데이터를 만들어 돌려준다.
"""
import math, random, datetime as dt
import requests

TIMEOUT = 10


# ── 데모 ─────────────────────────────────────────────
def _demo_speed(seg, now):
    """퇴근 피크(17:00~18:30)에 느려지는 가짜 속도."""
    h = now.hour + now.minute / 60
    peak = math.exp(-((h - 17.75) ** 2) / 0.6)         # 17:45 근처가 최악
    base = seg["free_flow_kmh"]
    if seg["route"] == "namtaeryeong":
        spd = base * (1 - 0.75 * peak) + random.uniform(-6, 6)
    else:
        spd = base * (1 - 0.35 * peak) + random.uniform(-4, 4)
    return max(5, round(spd, 1))


# ── 서울시 TOPIS ─────────────────────────────────────
def _topis_rows(key, service, path, params=""):
    """TOPIS 는 xml 만 안정적으로 응답하므로 xml 로 받아 dict 리스트로 변환."""
    import xml.etree.ElementTree as ET
    url = f"http://openapi.seoul.go.kr:8088/{key}/xml/{service}/{path}{params}"
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError:
        raise RuntimeError(f"TOPIS 응답 파싱 실패: {r.text[:200]}")
    code = root.findtext(".//RESULT/CODE", "")
    if code and code != "INFO-000":
        raise RuntimeError(f"TOPIS 오류 {code}: {root.findtext('.//RESULT/MESSAGE', '')}")
    return [{c.tag: (c.text or "").strip() for c in row} for row in root.iter("row")]


def _g(row, *names):
    """대소문자 섞인 필드명 안전 조회."""
    for n in names:
        for k in (n, n.lower(), n.upper()):
            if k in row:
                return row[k]
    return None


def seoul_topis(key, link_ids):
    """
    실시간 도로소통정보 (OA-13291) — 서비스명 TrafficInfo
    http://openapi.seoul.go.kr:8088/{KEY}/json/TrafficInfo/1/5/{LINK_ID}
    출력: LINK_ID, PRCS_SPD(km/h), PRCS_TRV_TIME(초)
    """
    out = {}
    for lid in link_ids:
        for row in _topis_rows(key, "TrafficInfo", "1/5/", str(lid)):
            spd = _g(row, "PRCS_SPD")
            if spd not in (None, ""):
                out[str(lid)] = float(spd)
    return out


def seoul_topis_find_links(road_name, xlsx_path=None):
    """
    도로별 링크정보 API(OA-13309)는 종료됨.
    대신 '서울시 교통소통 표준링크 매핑정보' 엑셀(OA-15061)을 읽어 도로명으로 검색.
    data/ 폴더에 xlsx 를 넣어두면 자동으로 찾음.
    """
    import glob, os
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError("pip3 install --break-system-packages openpyxl 가 필요합니다")
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [xlsx_path] if xlsx_path else glob.glob(os.path.join(here, "data", "*.xlsx"))
    if not cands or not cands[0]:
        raise RuntimeError("data/ 폴더에 '서울특별시 교통소통 표준링크 매핑정보_*.xlsx' 를 넣어주세요 "
                           "(data.seoul.go.kr 에서 OA-15061 검색 → 다운로드)")
    wb = openpyxl.load_workbook(cands[0], read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h) for h in rows[0]]
    out = []
    for r in rows[1:]:
        d = dict(zip(header, r))
        if any(road_name in str(v) for v in d.values()):
            out.append(d)
    return header, out


# ── ITS 국가교통정보센터 ──────────────────────────────
ITS_BASE = "https://openapi.its.go.kr:9443"   # 포트 9443 필수
# 사당역~선암IC 일대 바운딩 박스 (링크 속도 조회용 — 좁게)
ITS_BOX = dict(minX=126.96, maxX=127.04, minY=37.44, maxY=37.49)
# 돌발 조회용 — 퇴근길 전체: 남동공단(인천) → 제3경인 → 외곽순환·과천봉담 / 수원광명·강남순환 → 사당·서초
ITS_EVENT_BOX = dict(minX=126.70, maxX=127.06, minY=37.34, maxY=37.50)

_ITS_CACHE = {"t": 0, "items": []}

def _its_items(key):
    import time
    if time.time() - _ITS_CACHE["t"] < 120:          # 2분 내 재호출은 캐시 (한도 절약)
        return _ITS_CACHE["items"]
    params = dict(apiKey=key, type="all", getType="json", **ITS_BOX)
    r = requests.get(ITS_BASE + "/trafficInfo", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    j = r.json()
    body = j.get("body", j)
    items = body.get("items", body.get("item", []))
    if isinstance(items, dict):
        items = items.get("item", [items])
    _ITS_CACHE.update(t=time.time(), items=items)
    return items


def its_national(key, link_ids):
    """
    https://openapi.its.go.kr:9443/trafficInfo?apiKey=..&type=all&getType=json&minX..maxY
    응답 items[]: linkId, roadName, speed, travelTime, startNodeId, endNodeId ...
    """
    want = set(str(x) for x in link_ids)
    out = {}
    for i in _its_items(key):
        lid = str(i.get("linkId", ""))
        if lid in want:
            try:
                out[lid] = float(i.get("speed", 0))
            except (TypeError, ValueError):
                pass
    return out


def its_find_links(key):
    """바운딩 박스 안 모든 링크 — 도로명으로 골라 config 에 넣는다."""
    return _its_items(key)


def its_incidents(key):
    """돌발(사고·공사) — eventInfo. 실패하면 빈 목록."""
    try:
        params = dict(apiKey=key, type="all", eventType="all", getType="json", **ITS_EVENT_BOX)
        r = requests.get(ITS_BASE + "/eventInfo", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        j = r.json()
        body = j.get("body", j)
        items = body.get("items", body.get("item", [])) or []
        if isinstance(items, dict):
            items = items.get("item", [items])
        out = []
        for i in items:
            road = str(i.get("roadName", "") or "")
            msg = str(i.get("message", "") or "")
            if not any(k in road + " " + msg for k in INCIDENT_KEYWORDS):
                continue
            kind = str(i.get("eventType", "") or "돌발")
            detail = str(i.get("eventDetailType", "") or "")
            label = f"[{kind}{'·' + detail if detail and detail != kind else ''}]"
            text = f"{label} {road} {msg}".strip()
            start = str(i.get("startDate", "") or "")
            if len(start) >= 12 and start.isdigit():           # 202610191720 → 2026-10-19 17:20
                start = f"{start[:4]}-{start[4:6]}-{start[6:8]} {start[8:10]}:{start[10:12]}"
            out.append(dict(text=text, start=start, type=kind))
        return out
    except Exception:
        return []


# ── 경기도 GITS ──────────────────────────────────────
def gyeonggi_gits(key, link_ids):
    """
    경기도 구간소통정보 API — 발급 후 문서의 엔드포인트/필드명에 맞춰 수정.
    """
    url = "https://openapi.gg.go.kr/TrafficSectionInfo"
    params = dict(KEY=key, Type="json", pIndex=1, pSize=1000)
    r = requests.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    rows = data.get("TrafficSectionInfo", [{}, {}])[1].get("row", [])
    want = set(str(x) for x in link_ids)
    return {str(x.get("LINK_ID")): float(x.get("SPEED", 0)) for x in rows if str(x.get("LINK_ID")) in want}


SOURCES = {
    "seoul_topis": seoul_topis,
    "its_national": its_national,
    "gyeonggi_gits": gyeonggi_gits,
}


def fetch_segment(seg, keys, now=None):
    """구간 하나의 평균 속도(km/h)를 돌려준다. 실패/데모면 (speed, mode)."""
    now = now or dt.datetime.now()
    key = keys.get(seg.get("source", "its_national"), "")
    if not key or not seg.get("link_ids"):
        return _demo_speed(seg, now), "demo"
    try:
        speeds = SOURCES[seg.get("source", "its_national")](key, seg["link_ids"])
        vals = [v for v in speeds.values() if v > 0]
        if not vals:
            return None, "nodata"
        return round(sum(vals) / len(vals), 1), "live"
    except Exception as e:                      # 네트워크/파싱 오류는 기록만
        return None, f"error:{type(e).__name__}"


# ── 돌발정보 (서울시 TOPIS 실시간 돌발) ───────────────────
INCIDENT_KEYWORDS = ("제3경인", "남동", "시흥", "물왕", "남태령", "사당", "과천대로", "과천봉담", "동작대로", "우면산", "강남순환", "선암", "봉천터널", "금천터널",
                     "서초터널", "수원광명", "소하", "외곽순환", "제1순환", "학의")

# 이슈 → 영향받는 루트 (A: 수원광명·강남순환, BC: 110번·과천, B: 우면산, C: 남태령)
ROUTE_KEYWORDS = {
    "all": ("제3경인", "남동", "시흥", "물왕"),
    "A":  ("강남순환", "봉천터널", "금천터널", "서초터널", "수원광명", "소하", "사당IC", "사당 IC", "사당역", "동작대로"),
    "BC": ("외곽순환", "제1순환", "학의", "과천봉담", "과천대로"),
    "B":  ("우면산", "선암"),
    "C":  ("남태령", "사당역", "동작대로"),
}


def routes_affected(text):
    hit = [r for r, kws in ROUTE_KEYWORDS.items() if any(k in text for k in kws)]
    return hit or ["?"]


def fetch_notices(cfg):
    """서울시 TOPIS 공지(통제안내: 집회·행사·마라톤 등). 관심 키워드만."""
    key = cfg["api_keys"].get("seoul_topis")
    if not key:
        return []
    try:
        rows = _topis_rows(key, "TopisNotice", "1/100/")
    except Exception:
        return []
    out = []
    for r in rows:
        title = str(_g(r, "TITLE", "SUBJECT", "NOTICE_TITLE") or "")
        kind = str(_g(r, "GUBUN", "CATEGORY", "NOTICE_GUBUN") or "")
        if any(k in title for k in INCIDENT_KEYWORDS):
            out.append(dict(text=f"[{kind or '공지'}] {title}", start=_g(r, "REG_DATE", "REGDATE") or "",
                            type="notice", routes=routes_affected(title)))
    return out


def fetch_incidents(cfg):
    """사당·과천 일대 돌발(사고·공사·통제) + 통제 공지. 각 항목에 영향 루트 태깅."""
    out = []
    if cfg["api_keys"].get("its_national"):
        out += its_incidents(cfg["api_keys"]["its_national"])
    key = cfg["api_keys"].get("seoul_topis")
    if key:
        try:
            rows = _topis_rows(key, "AccInfo", "1/500/")
            for r in rows:
                txt = " ".join(str(_g(r, n) or "") for n in ("ACC_ROAD_CODE", "ACC_INFO", "ACC_TYPE", "ACC_DTYPE"))
                if any(k in txt for k in INCIDENT_KEYWORDS):
                    out.append(dict(text=txt.strip(), start=_g(r, "OCCR_DATE") or "", type=_g(r, "ACC_TYPE") or "돌발"))
        except Exception:
            pass
    out += fetch_notices(cfg)
    for i in out:
        i.setdefault("routes", routes_affected(i["text"]))
    return out


# ── 날씨 (기상청 단기예보, 과천/사당 격자) ────────────────
def fetch_weather(cfg):
    """
    기상청 단기예보 (data.go.kr '기상청_단기예보 조회서비스') — 키 비면 None.
    돌려주는 값: {rain_mm, snow, desc}  (퇴근 시간대 17~19시 기준)
    """
    key = cfg["api_keys"].get("kma_weather")
    if not key:
        return None
    try:
        now = dt.datetime.now()
        base = now.replace(hour=5, minute=0)             # 05시 발표본
        params = dict(serviceKey=key, dataType="JSON", numOfRows=500, pageNo=1,
                      base_date=base.strftime("%Y%m%d"), base_time="0500",
                      nx=cfg["weather_grid"]["nx"], ny=cfg["weather_grid"]["ny"])
        r = requests.get("https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst",
                         params=params, timeout=TIMEOUT)
        items = r.json()["response"]["body"]["items"]["item"]
        today = now.strftime("%Y%m%d")
        rain, snow, pty = 0.0, False, 0
        for it in items:
            if it["fcstDate"] != today or it["fcstTime"] not in ("1700", "1800", "1900"):
                continue
            if it["category"] == "PCP":
                v = it["fcstValue"]
                if v not in ("강수없음", "0"):
                    rain = max(rain, float(str(v).replace("mm", "").replace("미만", "").replace("1.0", "1") or 0))
            if it["category"] == "PTY" and it["fcstValue"] in ("2", "3"):
                snow = True
            if it["category"] == "PTY" and it["fcstValue"] != "0":
                pty = 1
        desc = "눈" if snow else (f"비 {rain:.0f}mm" if rain or pty else "맑음")
        return dict(rain_mm=rain if rain else (1.0 if pty else 0), snow=snow, desc=desc)
    except Exception:
        return None
