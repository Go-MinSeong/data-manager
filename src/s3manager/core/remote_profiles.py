"""원격(SFTP) 서버 프로파일 관리.

비밀이 아닌 메타데이터(host/port/username/keyPath/authType)는
APP_SUPPORT_DIR/remote_profiles.json 에 평문으로 저장하고,
비밀(키 passphrase 또는 password)만 Keychain(keyring)에 보관한다.

자격증명 평문은 절대 디스크에 쓰지 않는다(S3 정책과 동일).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import keyring

from s3manager import settings

logger = logging.getLogger(__name__)

# Keychain 서비스명: S3 프로파일과 충돌하지 않도록 별도 네임스페이스
_SERVICE = settings.KEYRING_SERVICE + ".remote"

_PROFILES_PATH = settings.APP_SUPPORT_DIR / "remote_profiles.json"


# ---------------------------------------------------------------------------
# 메타데이터 (json) 저장/조회
# ---------------------------------------------------------------------------

def _load_all() -> dict[str, dict[str, Any]]:
    if not _PROFILES_PATH.exists():
        return {}
    try:
        data = json.loads(_PROFILES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("원격 프로파일 로드 실패(빈 목록 사용): %s", exc)
        return {}


def _save_all(profiles: dict[str, dict[str, Any]]) -> None:
    _PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PROFILES_PATH.write_text(
        json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def list_remote_profiles() -> list[dict[str, Any]]:
    """저장된 원격 프로파일 목록을 반환한다(비밀 미포함)."""
    profiles = _load_all()
    result = []
    for name, p in profiles.items():
        result.append(
            {
                "name": name,
                "host": p.get("host", ""),
                "port": p.get("port", 22),
                "username": p.get("username", ""),
                "authType": p.get("authType", "key"),
                "keyPath": p.get("keyPath"),
                "defaultPath": p.get("defaultPath"),
            }
        )
    return sorted(result, key=lambda p: p["name"].lower())


def save_remote_profile(
    name: str,
    host: str,
    port: int,
    username: str,
    auth_type: str,
    *,
    key_path: str | None = None,
    secret: str | None = None,
) -> None:
    """원격 프로파일을 저장한다.

    메타데이터는 json에, secret(passphrase/password)은 Keychain에 보관한다.
    secret이 None이면 기존 Keychain 항목을 변경하지 않는다(메타만 갱신).
    """
    profiles = _load_all()
    existing = profiles.get(name, {})
    profiles[name] = {
        "host": host,
        "port": port,
        "username": username,
        "authType": auth_type,
        "keyPath": key_path,
        # 기존 기본 폴더는 보존(메타 갱신 시 지워지지 않게)
        "defaultPath": existing.get("defaultPath"),
    }
    _save_all(profiles)
    if secret:
        keyring.set_password(_SERVICE, name, secret)
    logger.info("원격 프로파일 저장 완료: %s", name)


def set_default_path(name: str, path: str | None) -> bool:
    """프로파일의 기본 탐색 폴더를 저장한다. 프로파일이 없으면 False."""
    profiles = _load_all()
    if name not in profiles:
        return False
    profiles[name]["defaultPath"] = path or None
    _save_all(profiles)
    logger.info("원격 프로파일 기본 폴더 저장: %s → %s", name, path)
    return True


def delete_remote_profile(name: str) -> None:
    """원격 프로파일과 Keychain의 비밀을 삭제한다."""
    profiles = _load_all()
    if name in profiles:
        del profiles[name]
        _save_all(profiles)
    try:
        keyring.delete_password(_SERVICE, name)
    except keyring.errors.PasswordDeleteError:
        pass
    logger.info("원격 프로파일 삭제 완료: %s", name)


def load_remote_profile(name: str) -> dict[str, Any] | None:
    """연결용 전체 프로파일(secret 포함)을 반환한다. 없으면 None."""
    profiles = _load_all()
    p = profiles.get(name)
    if p is None:
        return None
    secret = keyring.get_password(_SERVICE, name)
    return {
        "name": name,
        "host": p.get("host", ""),
        "port": p.get("port", 22),
        "username": p.get("username", ""),
        "authType": p.get("authType", "key"),
        "keyPath": p.get("keyPath"),
        "defaultPath": p.get("defaultPath"),
        "secret": secret,
    }
