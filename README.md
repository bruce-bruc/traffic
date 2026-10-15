# 퇴근길 모니터 (남동공단 → 방배동)

GitHub Actions 가 5분마다 교통 데이터를 수집해 `index.html` 을 만들고 GitHub Pages 로 올립니다.
컴퓨터를 켜둘 필요가 없습니다.

## 설정 (한 번만)
1. Settings → Secrets and variables → Actions → New repository secret
   - `ITS_KEY` : ITS 국가교통정보센터 인증키
   - `TOPIS_KEY` : 서울 열린데이터광장 인증키
2. Settings → Pages → Source: **GitHub Actions**
3. Actions 탭 → "퇴근길 모니터" → Run workflow (첫 실행)

페이지 주소: `https://<아이디>.github.io/traffic/`
