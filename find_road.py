"""호구포로(또는 다른 도로) ITS 링크 번호 찾기 — PC 에서 단독 실행용 (11-24).
저장소 없이도 이 파일 하나만 있으면 됩니다. its_feed.py 와 같은 폴더(D:\\traffic_its)에 두고:

    python find_road.py 호구포로

ITS 인증키는 (1) 환경변수 ITS_KEY, (2) 같은 폴더의 its_feed.py 안에 적힌 키, (3) 실행 시 물어봄 — 순서로 찾습니다.
"""
import json, os, re, sys, urllib.request, urllib.parse

ROAD = sys.argv[1] if len(sys.argv) > 1 else "호구포로"
ANCHOR = "1650094600"            # 고잔IC 에서 제3경인 올라타는 첫 링크 — 이 링크로 이어지는 사슬이 '회사 → 고잔IC'
BOX = dict(minX=126.70, maxX=127.03, minY=37.35, maxY=37.475)


def get_key():
    k = os.environ.get("ITS_KEY", "").strip()
    if k:
        return k
    here = os.path.dirname(os.path.abspath(__file__))
    for fn in ("its_feed.py", "config.yaml", "key.txt"):
        p = os.path.join(here, fn)
        if os.path.exists(p):
            txt = open(p, encoding="utf-8", errors="ignore").read()
            m = re.search(r"""(?:apiKey|ITS_KEY|its_national|KEY)\s*[=:]\s*['"]([A-Za-z0-9+/=_\-]{16,})['"]""", txt)
            if m:
                print(f"(키: {fn} 에서 읽음)")
                return m.group(1)
    return input("ITS 인증키를 붙여넣고 엔터: ").strip()


def fetch(key):
    q = dict(apiKey=key, type="all", getType="json", **BOX)
    url = "https://openapi.its.go.kr:9443/trafficInfo?" + urllib.parse.urlencode(q)
    with urllib.request.urlopen(url, timeout=60) as r:
        j = json.loads(r.read().decode("utf-8"))
    body = j.get("body", j)
    items = body.get("items", body.get("item", []))
    if isinstance(items, dict):
        items = items.get("item", [items])
    return items or []


def main():
    items = fetch(get_key())
    hits = [i for i in items if ROAD in str(i.get("roadName", "") or "")]
    print(f"[ITS] '{ROAD}' 링크 {len(hits)}개 (영역 전체 {len(items)}개)")
    if not hits:
        print("  (없음 — 도로명 표기가 다를 수 있음. 비슷한 이름:)",
              sorted({str(i.get("roadName")) for i in items if ROAD[:2] in str(i.get("roadName", ""))})[:30])
        return
    by_start = {str(i.get("startNodeId")): i for i in hits}
    ends = {str(i.get("endNodeId")) for i in hits}
    anchor_start = next((str(i.get("startNodeId")) for i in items if str(i.get("linkId")) == ANCHOR), None)
    heads = [i for i in hits if str(i.get("startNodeId")) not in ends or str(i.get("startNodeId")) == anchor_start] or hits[:1]
    used, chains = set(), []
    for h in heads:
        chain, cur = [], h
        while cur and str(cur.get("linkId")) not in used:
            used.add(str(cur.get("linkId"))); chain.append(cur)
            if str(cur.get("endNodeId")) == anchor_start:
                break
            cur = by_start.get(str(cur.get("endNodeId")))
        chains.append(chain)
    rest = [i for i in hits if str(i.get("linkId")) not in used]
    if rest:
        chains.append(rest)
    for n, ch in enumerate(chains, 1):
        last_end = str(ch[-1].get("endNodeId"))
        tag = f"  ← 끝이 고잔IC 링크({ANCHOR})로 이어짐 = 회사 → 고잔IC (gojan_up)" if anchor_start and last_end == anchor_start else ""
        print(f"\n사슬 {n} ({len(ch)}개){tag}")
        for i in ch:
            print(f"   {i.get('linkId')} | {i.get('roadName')} | {i.get('speed')}km/h | {i.get('startNodeId')}→{i.get('endNodeId')}")
        print("   link_ids: [" + ", ".join(str(i.get("linkId")) for i in ch) + "]")
    print("\n→ 이 출력 전체를 복사해서 Claude 에 붙여넣어 주세요.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("오류:", type(e).__name__, e)
    input("\n(엔터를 누르면 닫힙니다)")
