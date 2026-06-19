# data-manager

개인 프로젝트. macOS 메뉴바 + Dock 데이터 전송 도구(S3 · 원격 SFTP).

- Python은 black 포맷, uv로 의존성 관리(`.venv`).
- 자격증명·`.env`는 절대 커밋하지 않는다. 비밀은 macOS Keychain에만 저장.
- 개인 절대경로(`/Users/...`) 하드코딩 금지 — 설정·환경변수로 주입.
