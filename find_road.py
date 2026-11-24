"""호구포로(또는 다른 도로) ITS 링크 번호 찾기 — PC 에서 단독 실행용 (11-24).
저장소 없이도 이 파일 하나만 있으면 됩니다. its_feed.py 와 같은 폴더(D:\\traffic_its)에 두고:

    python find_road.py 호구포로

ITS 인증키는 (1) 명령줄 두 번째 인자, (2) 환경변수 ITS_KEY, (3) 같은 폴더 파일들 안의 키 후보를 차례로 시도, (4) 실행 시 물어봄.\n    python find_road.py 호구포로 여기에키   ← 키를 직접 줄 때
"""
import json, os, re, sys, urllib.request, urllib.parse

ROAD = sys.argv[1] if len(sys.argv) > 1 else "호구포로"
ANCHOR = "1650094600"            # 고잔IC 에서 제3경인 올라타는 첫 링크 — 이 링크로 이어지는 사슬이 '회사 → 고잔IC'
BOX = dict(minX=126.70, maxX=127.03, minY=37.35, maxY=37.475)


def key_candidates():
    """환경변수 → 같은 폴더의 모든 설정/스크립트 파일에서 'key' 근처의 긴 영숫자 토큰을 모두 모은다."""
    out = []
    k = os.environ.get("ITS_KEY", "").strip()
    if k:
        out.append(("환경변수 ITS_KEY", k))
    here = os.path.dirname(os.path.abspath(__file__))
    for fn in sorted(os.listdir(here)):
        if fn == os.path.basename(__file__) or not fn.lower().endswith((".py", ".txt", ".yaml", ".yml", ".json", ".ini", ".env", ".cfg", ".bat", ".cmd", ".ps1")):
            continue
        try:
            txt = open(os.path.join(here, fn), encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for m in re.finditer(r"[Kk][Ee][Yy][^\n]{0,80}?([A-Za-z0-9+/_\-][A-Za-z0-9+/=_\-]{23,79})", txt):
            tok = m.group(1)
            if tok not in (c[1] for c in out):
                out.append((fn, tok))
    return out


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
    items = None
    cands = key_candidates()
    if len(sys.argv) > 2:
        cands.insert(0, ("명령줄", sys.argv[2]))
    for src, k in cands:
        try:
            items = fetch(k)
            print(f"(키: {src} 의 것으로 연결됨)")
            break
        except Exception as e:
            print(f"  {src} 의 키 실패: {type(e).__name__} {e}")
    if items is None:
        k = input("키를 못 찾았습니다. ITS 인증키를 붙여넣고 엔터: ").strip()
        items = fetch(k)
    def rn(i): return str(i.get("roadName", "") or "")
    def lid(i): return str(i.get("linkId"))
    def km(i):
        try: return float(i.get("speed") or 0) * float(i.get("travelTime") or 0) / 3600
        except (TypeError, ValueError): return 0.0
    hits = [i for i in items if ROAD in rn(i)]
    print(f"[ITS] '{ROAD}' 링크 {len(hits)}개 (영역 전체 {len(items)}개)")
    if not hits:
        print("  (없음 — 도로명 표기가 다를 수 있음. 비슷한 이름:)",
              sorted({rn(i) for i in items if ROAD[:2] in rn(i)})[:30])
        return
    by_end, by_start = {}, {}
    for i in items:
        by_end.setdefault(str(i.get("endNodeId")), []).append(i)
        by_start.setdefault(str(i.get("startNodeId")), []).append(i)
    anchor = next((i for i in items if lid(i) == ANCHOR), None)
    if not anchor:
        print(f"고잔IC 기준 링크 {ANCHOR} 가 응답에 없습니다 — 영역을 확인하세요."); return
    print(f"기준 링크 {ANCHOR} ({rn(anchor)}) 시작노드 {anchor.get('startNodeId')} 에서 거꾸로 따라갑니다.\n")

    # ① 고잔IC 진입 링크의 시작 노드에서 거꾸로(상류로) 따라가며 호구포로 본선(번길 제외)을 모은다 = 회사 → 고잔IC 방향
    chain, seen, node, hops_off = [], set(), str(anchor.get("startNodeId")), 0
    visited_nodes, prev_end = {node}, str(anchor.get("endNodeId"))
    while len(chain) < 60:
        preds = [i for i in by_end.get(node, []) if lid(i) not in seen and lid(i) != ANCHOR
                 and str(i.get("startNodeId")) != prev_end                 # 방금 온 링크의 반대편(유턴) 제외
                 and str(i.get("startNodeId")) not in visited_nodes]       # 고리 방지
        main = [i for i in preds if rn(i) == ROAD]
        if main:
            cur, hops_off = main[0], 0
        elif preds and hops_off < 3 and not chain:        # IC 램프 등 호구포로 아닌 링크 몇 개는 건너뛴다
            cur, hops_off = preds[0], hops_off + 1
        else:
            break
        seen.add(lid(cur)); chain.insert(0, cur)
        prev_end, node = str(cur.get("endNodeId")), str(cur.get("startNodeId")); visited_nodes.add(node)
    print("■ 회사 → 고잔IC 방향 (주행 순서, 누적 km 는 ITS 속도×시간으로 추정)")
    acc = 0.0
    for n, i in enumerate(chain, 1):
        acc += km(i)
        print(f"  {n:2d}. {lid(i)} | {rn(i)} | {i.get('speed')}km/h | {i.get('startNodeId')}→{i.get('endNodeId')} | 누적 {acc:.1f}km")
    print("  gojan_up link_ids: [" + ", ".join(lid(i) for i in chain) + "]")

    # ② 반대 방향 = 같은 노드쌍을 거꾸로 잇는 링크 (출근: 고잔IC → 회사)
    rev = []
    for i in reversed(chain):
        s_, e_ = str(i.get("startNodeId")), str(i.get("endNodeId"))
        pair = [j for j in by_start.get(e_, []) if str(j.get("endNodeId")) == s_]
        rev.append(pair[0] if pair else None)
    print("\n■ 고잔IC → 회사 방향 (출근)")
    for n, j in enumerate(rev, 1):
        print(f"  {n:2d}. " + (f"{lid(j)} | {rn(j)} | {j.get('speed')}km/h | {j.get('startNodeId')}→{j.get('endNodeId')}" if j else "(반대 링크 없음 — 일방통행?)"))
    print("  m_gojan_down link_ids: [" + ", ".join(lid(j) for j in rev if j) + "]")
    print("\n→ 이 출력 전체를 복사해서 Claude 에 붙여넣어 주세요. (같은 폴더의 result.txt 에도 저장됨)")


class Tee:
    def __init__(self, *fs): self.fs = fs
    def write(self, s):
        for f in self.fs: f.write(s)
    def flush(self):
        for f in self.fs: f.flush()


if __name__ == "__main__":
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "result.txt")
    try:
        with open(out_path, "w", encoding="utf-8") as fo:
            sys.stdout = Tee(sys.__stdout__, fo)
            main()
            sys.stdout = sys.__stdout__
    except Exception as e:
        sys.stdout = sys.__stdout__
        print("오류:", type(e).__name__, e)
    input("\n(엔터를 누르면 닫힙니다)")
