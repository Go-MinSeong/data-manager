"""QA: /api/remote/* HTTP E2E 검증.

인메모리 SFTP 서버 + 실제 FastAPI(uvicorn) 서버를 띄우고,
connect → objects → upload → download 를 HTTP로 호출해
새 라우트·모델(camelCase)·잡 매니저 경로가 통합 동작하는지 확인한다.
"""
import json
import socket
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import paramiko
import uvicorn

from s3manager import settings
from s3manager.server import app as app_module
from s3manager.core.jobs import job_manager
# 인메모리 SFTP 서버 헬퍼 재사용
from qa_sftp_test import _Server, _make_stub  # noqa: E402

# 실제 이력 파일을 건드리지 않도록 임시 경로로 격리
job_manager._history_path = Path(tempfile.mkdtemp(prefix="qa-jobs-")) / "jobs.json"


def _serve_sftp(sock, host_key, root, stop):
    sock.settimeout(1.0)
    while not stop.is_set():
        try:
            conn, _ = sock.accept()
        except (socket.timeout, OSError):
            continue
        t = paramiko.Transport(conn)
        t.add_server_key(host_key)
        t.set_subsystem_handler("sftp", paramiko.SFTPServer, _make_stub(root))
        try:
            t.start_server(server=_Server())
        except Exception:
            continue


# 실제 앱이 settings.PORT를 점유할 수 있으므로 빈 포트를 골라 사용한다.
_ps = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
_ps.bind(("127.0.0.1", 0))
API_PORT = _ps.getsockname()[1]
_ps.close()
BASE = f"http://{settings.HOST}:{API_PORT}"
# 해당 포트의 Host 헤더를 허용 목록에 추가(미들웨어는 import 시점 값 사용)
app_module._ALLOWED_HOSTS.add(f"{settings.HOST}:{API_PORT}")


def _req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _wait_job(job_id, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = _req("GET", f"/api/jobs/{job_id}")
        if job["status"] in ("done", "error", "canceled"):
            return job
        time.sleep(0.2)
    raise TimeoutError("잡 완료 대기 시간 초과")


def main():
    # 원격 SFTP 루트 준비
    root = tempfile.mkdtemp(prefix="qa-http-root-")
    Path(root, "data").mkdir()
    Path(root, "data", "a.txt").write_bytes(b"A" * 4096)
    Path(root, "data", "sub").mkdir()
    Path(root, "data", "sub", "b.txt").write_bytes(b"B" * 2048)

    host_key = paramiko.RSAKey.generate(2048)
    ssock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ssock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ssock.bind(("127.0.0.1", 0))
    ssock.listen(5)
    sftp_port = ssock.getsockname()[1]
    stop = threading.Event()
    threading.Thread(target=_serve_sftp, args=(ssock, host_key, root, stop), daemon=True).start()

    # FastAPI 서버 (settings.PORT=8765, Host 검증 통과 위해 그대로 사용)
    config = uvicorn.Config(app_module.app, host=settings.HOST, port=API_PORT, log_level="warning")
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    try:
        # health 폴링
        for _ in range(50):
            try:
                if _req("GET", "/api/health")["ok"]:
                    break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("서버 기동 실패")

        # 1) 연결 (adhoc, password)
        res = _req("POST", "/api/remote/connect", {
            "mode": "adhoc", "host": "127.0.0.1", "port": sftp_port,
            "username": "qa", "authType": "password", "secret": "x",
        })
        print("connect:", res)
        assert res["ok"] is True, res
        assert res["homeDir"], res

        conn = _req("GET", "/api/remote/connection")
        assert conn["connected"] is True and conn["host"] == "127.0.0.1", conn

        # 2) 목록 (camelCase 확인)
        objs = _req("GET", "/api/remote/objects?path=/")
        fnames = {f["name"] for f in objs["folders"]}
        print("objects(/):", fnames, "| prefix:", objs["prefix"])
        assert "data" in fnames, objs
        assert objs["folders"][0]["isFolder"] is True and objs["folders"][0]["key"].endswith("/")

        # 3) 업로드 (로컬 → 원격)
        up_src = tempfile.mkdtemp(prefix="qa-http-up-")
        Path(up_src, "u.bin").write_bytes(b"U" * 3000)
        up = _req("POST", "/api/remote/upload", {
            "remoteDir": "/uploaded", "localPaths": [str(Path(up_src, "u.bin"))],
        })
        job = _wait_job(up["jobId"])
        print("upload job:", job["kind"], job["status"], job["completedFiles"], "files")
        assert job["status"] == "done" and job["kind"] == "remote-upload", job
        assert Path(root, "uploaded", "u.bin").read_bytes() == b"U" * 3000

        # 4) 다운로드 (원격 → 로컬, 재귀)
        dl = tempfile.mkdtemp(prefix="qa-http-dl-")
        dn = _req("POST", "/api/remote/download", {"remoteDirs": ["/data"], "localDir": dl})
        job = _wait_job(dn["jobId"])
        print("download job:", job["kind"], job["status"], job["completedFiles"], "files")
        assert job["status"] == "done" and job["kind"] == "remote-download", job
        # 폴더는 local_dir/<폴더명>/ 하위로 받는다
        assert Path(dl, "data", "a.txt").read_bytes() == b"A" * 4096
        assert Path(dl, "data", "sub", "b.txt").read_bytes() == b"B" * 2048

        # 5) 연결 해제
        assert _req("POST", "/api/remote/disconnect")["ok"] is True
        assert _req("GET", "/api/remote/connection")["connected"] is False

        print("\n✅ /api/remote/* HTTP E2E 통과")
    finally:
        stop.set()
        ssock.close()
        server.should_exit = True


if __name__ == "__main__":
    main()
