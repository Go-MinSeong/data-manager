"""QA: sftp_engine 실제 동작 E2E 검증.

메모리 내(loopback) paramiko SFTP 서버를 임시 디렉터리에 띄우고,
sftp_engine.connect / list_one_level / list_all_files / download_files /
upload_files 가 실제 paramiko 경로를 통해 올바르게 동작하는지 확인한다.
진행률(on_bytes) 누적이 파일 크기와 일치하는지도 검증한다.
"""
import os
import socket
import tempfile
import threading
from pathlib import Path

import paramiko

from s3manager.core import sftp_engine


# ---------------------------------------------------------------------------
# 임시 디렉터리에 루팅된 최소 SFTP 서버 (paramiko 데모 StubSFTPServer 간소화)
# ---------------------------------------------------------------------------

class _Server(paramiko.ServerInterface):
    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED

    def get_allowed_auths(self, username):
        return "password"


def _make_stub(root: str):
    class StubSFTPHandle(paramiko.SFTPHandle):
        def stat(self):
            try:
                return paramiko.SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))
            except OSError as e:
                return paramiko.SFTPServer.convert_errno(e.errno)

    class StubSFTPServer(paramiko.SFTPServerInterface):
        ROOT = root

        def _realpath(self, path):
            return self.ROOT + self.canonicalize(path)

        def list_folder(self, path):
            p = self._realpath(path)
            out = []
            for fname in os.listdir(p):
                attr = paramiko.SFTPAttributes.from_stat(os.stat(os.path.join(p, fname)))
                attr.filename = fname
                out.append(attr)
            return out

        def stat(self, path):
            try:
                return paramiko.SFTPAttributes.from_stat(os.stat(self._realpath(path)))
            except OSError as e:
                return paramiko.SFTPServer.convert_errno(e.errno)

        def lstat(self, path):
            try:
                return paramiko.SFTPAttributes.from_stat(os.lstat(self._realpath(path)))
            except OSError as e:
                return paramiko.SFTPServer.convert_errno(e.errno)

        def open(self, path, flags, attr):
            p = self._realpath(path)
            try:
                binary_flag = getattr(os, "O_BINARY", 0)
                flags |= binary_flag
                mode = getattr(attr, "st_mode", None) or 0o666
                fd = os.open(p, flags, mode)
            except OSError as e:
                return paramiko.SFTPServer.convert_errno(e.errno)
            if flags & os.O_CREAT and attr is not None:
                attr._flags &= ~attr.FLAG_PERMISSIONS
                paramiko.SFTPServer.set_file_attr(p, attr)
            if flags & os.O_WRONLY:
                fstr = "ab" if (flags & os.O_APPEND) else "wb"
            elif flags & os.O_RDWR:
                fstr = "a+b" if (flags & os.O_APPEND) else "r+b"
            else:
                fstr = "rb"
            try:
                f = os.fdopen(fd, fstr)
            except OSError as e:
                return paramiko.SFTPServer.convert_errno(e.errno)
            fobj = StubSFTPHandle(flags)
            fobj.filename = p
            fobj.readfile = f
            fobj.writefile = f
            return fobj

        def remove(self, path):
            try:
                os.remove(self._realpath(path))
            except OSError as e:
                return paramiko.SFTPServer.convert_errno(e.errno)
            return paramiko.SFTP_OK

        def mkdir(self, path, attr):
            try:
                os.mkdir(self._realpath(path))
            except OSError as e:
                return paramiko.SFTPServer.convert_errno(e.errno)
            return paramiko.SFTP_OK

        def canonicalize(self, path):
            # 루트 기준 정규화: 항상 '/'로 시작하는 경로 반환
            if not path or path == ".":
                return "/"
            return os.path.normpath("/" + path.lstrip("/"))

    return StubSFTPServer


def _serve_once(sock, host_key, root, stop):
    sock.settimeout(1.0)
    while not stop.is_set():
        try:
            conn, _ = sock.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        t = paramiko.Transport(conn)
        t.add_server_key(host_key)
        t.set_subsystem_handler("sftp", paramiko.SFTPServer, _make_stub(root))
        try:
            t.start_server(server=_Server())
        except Exception:
            continue


def main():
    root = tempfile.mkdtemp(prefix="qa-sftp-root-")
    dl_dir = tempfile.mkdtemp(prefix="qa-sftp-dl-")
    up_src = tempfile.mkdtemp(prefix="qa-sftp-up-")

    # 서버 측 원격 파일 준비
    Path(root, "data").mkdir()
    Path(root, "data", "a.txt").write_bytes(b"A" * 4096)
    Path(root, "data", "sub").mkdir()
    Path(root, "data", "sub", "b.txt").write_bytes(b"B" * 2048)
    Path(root, "top.txt").write_bytes(b"T" * 100)

    host_key = paramiko.RSAKey.generate(2048)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(5)
    port = sock.getsockname()[1]

    stop = threading.Event()
    server_thread = threading.Thread(
        target=_serve_once, args=(sock, host_key, root, stop), daemon=True
    )
    server_thread.start()

    try:
        ssh = sftp_engine.connect(
            host="127.0.0.1", port=port, username="qa", password="x", timeout=10
        )
        print("연결 성공, home:", sftp_engine.home_dir(ssh))

        # 1) list_one_level (루트)
        top = sftp_engine.list_one_level(ssh, "/")
        fnames = {f["name"] for f in top["folders"]}
        onames = {os.path.basename(o["key"]) for o in top["objects"]}
        print("루트 folders:", fnames, "objects:", onames)
        assert "data" in fnames, fnames
        assert "top.txt" in onames, onames
        assert top["folders"][0]["key"].endswith("/"), "폴더 key 트레일링 슬래시 누락"

        # 2) list_all_files + flat_summary (재귀)
        summary = sftp_engine.flat_summary(ssh, "/data")
        print("flat_summary(/data):", summary)
        assert summary["totalFiles"] == 2, summary
        assert summary["totalBytes"] == 4096 + 2048, summary

        # 3) download_files — 폴더 모드(폴더명 하위 보존) + on_bytes 누적 검증
        recv = {"bytes": 0}
        s, f = sftp_engine.download_files(
            ssh, dl_dir, remote_dirs=["/data"],
            on_bytes=lambda n: recv.__setitem__("bytes", recv["bytes"] + n),
        )
        print("다운로드(dir) 성공/실패:", s, f, "| on_bytes 합:", recv["bytes"])
        assert (s, f) == (2, 0), (s, f)
        # 폴더는 local_dir/<폴더명>/ 하위로 받는다
        assert Path(dl_dir, "data", "a.txt").read_bytes() == b"A" * 4096
        assert Path(dl_dir, "data", "sub", "b.txt").read_bytes() == b"B" * 2048
        assert recv["bytes"] == 4096 + 2048, "on_bytes 누적이 총 크기와 불일치"

        # 4) download_files — keys 모드(평면)
        dl2 = tempfile.mkdtemp(prefix="qa-sftp-dl2-")
        s2, f2 = sftp_engine.download_files(ssh, dl2, keys=["/data/sub/b.txt"])
        assert (s2, f2) == (1, 0), (s2, f2)
        assert Path(dl2, "b.txt").read_bytes() == b"B" * 2048

        # 4b) download_files — 여러 폴더 + 파일 동시(다중 선택)
        Path(root, "data2").mkdir()
        Path(root, "data2", "c.txt").write_bytes(b"C" * 512)
        dl3 = tempfile.mkdtemp(prefix="qa-sftp-dl3-")
        s3_, f3 = sftp_engine.download_files(
            ssh, dl3, remote_dirs=["/data", "/data2"], keys=["/top.txt"]
        )
        print("다운로드(다중) 성공/실패:", s3_, f3)
        assert (s3_, f3) == (4, 0), (s3_, f3)  # data(2) + data2(1) + top.txt(1)
        assert Path(dl3, "data", "a.txt").exists()
        assert Path(dl3, "data2", "c.txt").read_bytes() == b"C" * 512
        assert Path(dl3, "top.txt").read_bytes() == b"T" * 100

        # 5) upload_files — 폴더 업로드(원격 디렉터리 자동 생성)
        Path(up_src, "local").mkdir()
        Path(up_src, "local", "x.bin").write_bytes(b"X" * 8192)
        Path(up_src, "local", "deep").mkdir()
        Path(up_src, "local", "deep", "y.bin").write_bytes(b"Y" * 512)
        up_recv = {"bytes": 0}
        su, fu = sftp_engine.upload_files(
            ssh, "/uploaded", [str(Path(up_src, "local"))],
            on_bytes=lambda n: up_recv.__setitem__("bytes", up_recv["bytes"] + n),
        )
        print("업로드 성공/실패:", su, fu, "| on_bytes 합:", up_recv["bytes"])
        assert (su, fu) == (2, 0), (su, fu)
        assert Path(root, "uploaded", "local", "x.bin").read_bytes() == b"X" * 8192
        assert Path(root, "uploaded", "local", "deep", "y.bin").read_bytes() == b"Y" * 512
        assert up_recv["bytes"] == 8192 + 512, "업로드 on_bytes 누적 불일치"

        ssh.close()
        print("\n✅ sftp_engine E2E 통과")
    finally:
        stop.set()
        sock.close()


if __name__ == "__main__":
    main()
