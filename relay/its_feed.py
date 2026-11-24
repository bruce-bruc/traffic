"""퇴근길 모니터 — ITS 고속도로 속도를 이 PC(국내)에서 받아 GitHub 저장소 data/its_live.json 에 올린다.

왜: ITS 는 해외 IP(GitHub Actions)를 막고, 카페24 중계도 해외 서버에는 보안 확인 페이지를 보낸다 (2026-11-23 확인).
그래서 국내에 있는 이 PC가 5분마다 ITS 를 직접 부르고, 필요한 링크 속도만 저장소에 올린다.
GitHub 쪽(sources.py)은 이 파일이 12분 안의 것이면 그 속도를 쓴다.

- 작업 스케줄러가 5분마다 pythonw 로 실행 (창 없음). 평일 05:25~07:35, 14:25~19:05 에만 일하고 나머지는 바로 끝난다.
- 링크 번호는 저장소 config.yaml 에서 읽는다 (source 가 seoul_topis 가 아닌 구간의 link_ids).
- 설정: 같은 폴더 its_key.txt (ITS 인증키), github_token.txt (대표가 만든 GitHub 토큰, Contents 쓰기 권한).
- 기록: 같은 폴더 its_feed.log (최근 500줄).
- 11-25: 조회 영역을 서쪽(126.60)으로 넓힘 — 호구포로 남쪽·아암대로 링크가 126.70 경계 밖에 있었음.
  (이 파일의 원본은 PC 의 D:\\traffic_its\\its_feed.py. 저장소의 relay/its_feed.py 는 그 사본.)
"""
import base64, datetime as dt, json, os, re, sys, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "bruce-bruc/traffic"
PATH = "data/its_live.json"
ITS_BOX = dict(minX=126.60, maxX=127.03, minY=37.33, maxY=37.475)   # sources.py 의 ITS_BOX 와 같게 (11-25 서쪽 확장)
WINDOWS = [("05:25", "07:35"), ("14:25", "19:05")]
UA = {"User-Agent": "traffic-its-feed"}


def log(msg):
    p = os.path.join(HERE, "its_feed.log")
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    try:
        old = open(p, encoding="utf-8").read().splitlines()[-499:] if os.path.exists(p) else []
        open(p, "w", encoding="utf-8").write("\n".join(old + [line]) + "\n")
    except OSError:
        pass
    print(line)


def read(name):
    p = os.path.join(HERE, name)
    return open(p, encoding="utf-8").read().strip() if os.path.exists(p) else ""


def in_window(now):
    if now.weekday() >= 5:
        return False
    hm = now.strftime("%H:%M")
    return any(a <= hm <= b for a, b in WINDOWS)


def link_ids():
    """config.yaml 에서 ITS 구간(source 없음 또는 its_national)의 link_ids 를 모은다."""
    with urllib.request.urlopen(urllib.request.Request(
            f"https://raw.githubusercontent.com/{REPO}/main/config.yaml", headers=UA), timeout=30) as r:
        cfg = r.read().decode("utf-8")
    seg_part = cfg.split("\nsegments:", 1)[-1].split("\nroutes:", 1)[0]
    ids = set()
    for block in re.split(r"\n  - id: ", seg_part)[1:]:
        src = re.search(r"\n    source:\s*(\S+)", block)
        if src and src.group(1) != "its_national":
            continue
        m = re.search(r"\n    link_ids:\s*\[([^\]]*)\]", block)
        if m:
            ids |= {x.strip() for x in m.group(1).split(",") if x.strip()}
    return ids


def its_items(key):
    q = urllib.parse.urlencode(dict(apiKey=key, type="all", getType="json", **ITS_BOX))
    with urllib.request.urlopen("https://openapi.its.go.kr:9443/trafficInfo?" + q, timeout=60) as r:
        j = json.loads(r.read().decode("utf-8"))
    body = j.get("body", j)
    items = body.get("items", body.get("item", []))
    if isinstance(items, dict):
        items = items.get("item", [items])
    return items


def gh(method, url, token, data=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(data).encode() if data else None,
                                 headers={**UA, "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def main(dry=False, force=False):
    now = dt.datetime.now()
    if not dry and not force and not in_window(now):
        return
    key, token = read("its_key.txt"), read("github_token.txt")
    if not key:
        return log("its_key.txt 가 비어 있음")
    want = link_ids()
    items = its_items(key)
    speeds, tts = {}, {}
    for i in items:
        lid = str(i.get("linkId", ""))
        if lid in want:
            try:
                speeds[lid] = float(i.get("speed", 0))
                tts[lid] = float(i.get("travelTime", 0))
            except (TypeError, ValueError):
                pass
    doc = {"ts": now.isoformat(timespec="seconds"), "source": "ITS (이 PC에서 직접)", "speeds": speeds, "travel_s": tts}
    msg = f"링크 {len(speeds)}/{len(want)}개 받음"
    missing = sorted(want - set(speeds))
    if missing:
        msg += f" (못 받은 링크: {', '.join(missing[:12])}{' …' if len(missing) > 12 else ''})"
    if dry or not token:
        return log(msg + (" (시험: 올리지 않음)" if dry else " — github_token.txt 가 비어 있어 올리지 못함"))
    api = f"https://api.github.com/repos/{REPO}/contents/{PATH}"
    sha = None
    try:
        sha = gh("GET", api + "?ref=main", token).get("sha")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    body = {"message": f"its feed {now:%m-%d %H:%M}", "branch": "main",
            "content": base64.b64encode(json.dumps(doc, ensure_ascii=False, indent=0).encode("utf-8")).decode()}
    if sha:
        body["sha"] = sha
    gh("PUT", api, token, body)
    log(msg + " → 저장소에 올림")


if __name__ == "__main__":
    try:
        main(dry="--dry" in sys.argv, force="--force" in sys.argv)  # --force: 시간대 밖에서도 한 번 올려 보기 (시험용)
    except Exception as e:
        log(f"실패: {type(e).__name__} {str(e)[:200]}")
