# data-manager — 프로젝트 가이드 (CLAUDE.md)

개인 프로젝트. macOS **메뉴바 + Dock** 데이터 전송 도구 — AWS S3 · 원격 SFTP 다운로드/업로드.
이 문서는 (1) 이 프로젝트의 유지보수 기준이자 (2) 유사한 "로컬 네이티브 + 웹UI" 앱의 개발 방향 참고용이다.

## 스택 한눈에

- **백엔드**: FastAPI(`127.0.0.1:8765` 전용) + boto3(S3) + paramiko(SFTP). 활성 세션은 메모리 보관.
- **프론트**: Vite + React + TypeScript + Tailwind v4.
- **셸**: pywebview(WKWebView) 창 + pystray/NSStatusItem 메뉴바. PyInstaller `.app` 번들.
- **단일 진실원**: `src/s3manager/settings.py` (포트·경로·APP_ID·Keychain 서비스). 값은 읽기만, 변경은 여기서.

> 내부 패키지명은 역사적 이유로 `s3manager`(repo·앱명은 `data-manager`). 공개용 식별자(번들 id·Keychain)는 중립값 `io.github.<user>.datamanager`.

## 작업·검증 워크플로 (이 방식으로 진행할 것)

- **결정은 번호 옵션 + 추천안**으로 제시해 한 줄 승인이 되게 한다. 요구가 모호하면 먼저 질문.
- **눈에 보이는 결과(UI·메뉴바·알림)는 실제로 실행·확인하기 전에 "완료"라고 하지 않는다.** UI 변경은 빌드→재설치→스크린샷으로 검증한다.
- 검증 못 한 부분(연결 필요·수동 동작 등)은 **숨기지 말고 정직하게 보고**하고 사용자 확인을 요청한다.
- **작업 단위로 커밋**하고, **푸시·병합·릴리스 여부는 먼저 보고 후 사용자가 결정**한다(특히 공개·되돌리기 어려운 단계).
- 변경 후 `qa/`의 오프라인 스모크 테스트를 돌려 회귀를 확인한다.

## 빌드·재설치·릴리스

```bash
bash packaging/build.sh          # frontend/dist → PyInstaller → dist/Data Manager.app
# 재설치(런에이전트 라벨 교체 포함)
launchctl bootout gui/$(id -u)/<LABEL>; cp -R "dist/Data Manager.app" /Applications/; launchctl bootstrap gui/$(id -u) <plist>
curl -s 127.0.0.1:8765/api/health # 버전 확인
```

- 버전은 **4곳 동시** 변경: `src/s3manager/__init__.py`, `pyproject.toml`, spec의 `CFBundleVersion`·`CFBundleShortVersionString`.
- 릴리스: 태그 `vX.Y.Z` + `gh release create`에 `Data-Manager-arm64.zip` 첨부. 기능 추가=minor, 수정/정리=patch.

## 코드 규칙

- Python은 **black**, **uv**(`.venv`). 폴더·식별자는 kebab/snake 일관.
- **Surgical changes**: 작업에 필요한 부분만. 인접 코드·포맷 임의 개선 금지, 기존 스타일을 따른다.
- **Simplicity first**: 요청된 문제만 푸는 최소 코드. 단일 사용처에 추상화 금지.
- `qa/`는 pytest가 아닌 단독 실행 스크립트(인메모리 SFTP 스텁 사용). 상호 import는 실행 시 스크립트 디렉터리가 `sys.path`에 들어가 동작.

## 보안 (설계상 보장)

- 서버는 `127.0.0.1`에만 바인딩 + **실행마다 무작위 토큰**(창 URL로만 전달) + **Host 헤더 검증**(DNS 리바인딩 차단).
- **자격증명 평문은 디스크/repo에 절대 쓰지 않는다.** 비밀은 macOS Keychain만. 메타데이터(프로파일 host/port 등)만 평문 json.
- `.env`·키 파일은 커밋 금지. 개인 절대경로(`/Users/...`) 하드코딩 금지 — 설정/환경변수로 주입.
- 차단/블로킹 I/O 라우트(boto3·paramiko·os.walk)는 **sync `def`** 로 둬 FastAPI 스레드풀로 보낸다 — `async def` 안에서 블로킹하면 이벤트 루프 전체가 멈춘다.

## 잡(전송) 엔진 주의점

- ThreadPoolExecutor + asyncio 큐 + WebSocket 진행률. **워커 스레드가 건드리는 카운터(bytes/completed/failed)는 락으로 보호**(원자적 `+=` 아님).
- 이력(`jobs.json`)은 **임시파일 + `os.replace`로 원자적 저장**(동시 종료 시 손상 방지).
- 전 파일 실패는 `done`이 아니라 `error`로. 진행률 총량은 **다운로드 열거를 재사용**해 별도 LIST를 추가로 호출하지 않는다.
- 취소는 콜백에서 예외를 던져 **파일 전송 중간에도** 멈춘다. 직통(curl) 모드는 채널 close로 원격 프로세스를 중단.

## S3 비용 의식

- 트리는 **lazy + 캐시**(폴더 펼칠 때 1회 `list_one_level`, 재펼침 무과금). 재귀 전체 목록(`flat_summary`)은 **미리보기·추천 버튼 등 사용자 동작에서만**, 자동 호출 금지.
- 같은 prefix를 두 번 LIST하지 않도록 주의(진행률 총량 ↔ 실제 전송 열거 공유).

## pywebview / macOS 함정 (하드원)

- `window.native`(NSWindow)는 **start 콜백 시점엔 `None`**. 네이티브 창 조작은 `window.events.shown`에서.
- **타이틀바 통합**(앱 헤더와 하나로): `shown`에서 `setTitlebarAppearsTransparent_(True)` + `setTitleVisibility_(1)` + styleMask에 FullSizeContentView(`1<<15`) + pywebview가 칠한 타이틀바 배경을 `contentView().superview().subviews().lastObject().setBackgroundColor_(clearColor)`로 제거. 신호등 버튼은 유지.
- **창 드래그**: 헤더에 `.pywebview-drag-region` + `webview.settings['DRAG_REGION_DIRECT_TARGET_ONLY']=True` → 빈 영역만 드래그, 버튼 클릭은 드래그로 안 샌다.
- **파일 드래그-드롭**: WKWebView JS는 드롭 파일의 절대경로를 안 준다. pywebview **Python DOM 드롭 핸들러**(`window.dom.document.events.drop`, `DOMEventHandler(prevent_default=True)`)에서 `pywebviewFullPath`를 받아 `evaluate_js`로 프론트에 전달.
- **Dock/메뉴바**: 메뉴바 NSStatusItem은 노치/혼잡 시 macOS가 화면 밖으로 숨길 수 있다(코드 정상이어도). Dock 아이콘(Regular 활성화 + `LSUIElement=false`)과 `applicationShouldHandleReopen_`(pywebview AppDelegate 상속)으로 **확실한 진입점**을 둔다.
- **번들 id·Keychain 서비스를 바꾸면 기존 Keychain 비밀이 끊긴다**(재입력 필요). 변경은 신중히.

## 테마 (Tailwind v4)

- Tailwind v4는 `bg-zinc-950` 등을 `var(--color-zinc-950)`로 컴파일. `[data-theme]`에서 변수만 오버라이드하면 컴포넌트 수정 없이 테마가 바뀐다.
- **테마에 안 따라오는 색 주의**: 매핑 안 한 토큰(`yellow-400` 등)·고정색 이미지·이모지는 라이트 테마에서 튄다. 필요한 토큰은 테마별로 `--color-*`를 추가하고, 로고 등은 `currentColor` 인라인 SVG로.

## 공개 레포 / 스크린샷

- 공개 전 **working tree + git 히스토리 전체**를 시크릿·내부 IP·회사 이메일·개인 경로·작성자 메일까지 감사한다.
- 스크린샷은 **민감 필드 블러**(경로의 사용자명, 프로파일명 등). 기능 화면은 **인메모리 SFTP 스텁**에 연결해 더미 데이터로 캡처(`dev/preview_shot.py`, `dev/`는 gitignore).
- 개발 중간 산출물(프리뷰 스크립트·메모)은 `dev/`에 두고 git에서 제외.

## 다음 유사 프로젝트를 위한 교훈

1. 처음부터 **중립 식별자**(`io.github.<user>.<app>`)와 비밀=Keychain 원칙으로 시작 — 나중에 공개할 때 리네임·마이그레이션 비용이 없다.
2. 로컬 웹서버형 네이티브 앱은 **토큰 + Host 검증 + 127.0.0.1 바인딩**을 기본 보안 3종으로.
3. pywebview의 네이티브 연동(타이틀바·드롭·델리게이트)은 **이벤트 타이밍**(`shown`/`loaded`)이 핵심 — start 콜백을 믿지 말 것.
4. 비용 있는 외부 API(S3 LIST 등)는 **lazy·캐시·온디맨드**를 처음부터 설계에 넣는다.
5. 결정-옵션 제시 → 작업 → 빌드·검증 → 커밋 → 보고 의 리듬을 유지한다.
