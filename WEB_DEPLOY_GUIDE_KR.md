# 동그라미 Editor — 카카오톡 공유용 웹 배포

이 폴더는 Render Web Service 배포용입니다.

## 가장 간단한 방법
1. 이 폴더 전체를 GitHub 저장소에 업로드합니다.
2. Render에서 `New > Web Service`를 선택합니다.
3. GitHub 저장소를 연결합니다.
4. `render.yaml`을 사용하거나 아래 값으로 설정합니다.
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn --workers 1 --threads 4 --timeout 180 --bind 0.0.0.0:$PORT app:app`
5. 배포가 완료되면 `https://...onrender.com` 주소가 발급됩니다.
6. 그 주소를 카카오톡으로 보내면 상대방은 설치 없이 모바일 브라우저에서 테스트할 수 있습니다.

## 테스트
- 첫 화면 열림
- 상품 > 아크릴 > 키링/스탠드 표시
- PNG 업로드
- 키링 칼선/타공
- 스탠드 탭/슬롯
- 모바일 하단 메뉴
- 인쇄파일 생성

## 주의
무료 인스턴스는 장시간 미사용 후 첫 접속이 느릴 수 있습니다.
실서비스 전에는 인증, 파일 보관 정책, 동시 사용자, HTTPS 도메인, 서버 저장소를 별도로 점검하세요.
