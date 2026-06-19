# qa — 스모크 / E2E 스크립트

pytest가 아니라 단독 실행 스크립트다. 각 파일은 `if __name__` 진입점을 가지며,
성공 시 `✅`를 출력한다. 프로젝트 루트에서 venv를 활성화하고 실행한다:

```bash
python qa/qa_pipeline_test.py
```

네트워크·AWS 자격증명 없이 도는 것들(인메모리 SFTP 서버 + 시뮬레이션 사용):

| 파일 | 검증 |
|---|---|
| `qa_pipeline_test.py` | 잡 매니저 ↔ WebSocket 이벤트 파이프라인 |
| `qa_cancel_test.py` | 전송 중 취소(중간 중단) |
| `qa_jobs_persist_test.py` | 작업 이력 영속화 |
| `qa_sftp_channel_test.py` | SFTP 채널 재사용(MaxSessions 회피) |
| `qa_transfer_test.py` | S3↔원격 전송(릴레이 + 직통 커맨드 구성) |
| `qa_diskspeed_test.py` | 여유 공간·속도 측정 |
| `qa_r2r_test.py` | 원격→원격 릴레이 |
| `qa_direct_cancel_test.py` | 직통(curl) 모드 취소 |
| `qa_sftp_test.py` | SFTP 엔진 E2E(다른 테스트가 헬퍼로 재사용) |
| `qa_remote_http_test.py` | `/api/remote/*` HTTP E2E (실 uvicorn 기동) |
