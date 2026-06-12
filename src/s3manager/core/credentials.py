"""자격증명 관리 모듈.

세 가지 자격증명 소스를 지원한다:
1. 직접 키 (accessKeyId + secretAccessKey)
2. ~/.aws/credentials 또는 ~/.aws/config 의 named profile
3. Keychain(keyring)에 앱이 저장한 커스텀 프로파일

자격증명 평문은 절대 디스크에 쓰지 않는다.
Keychain 저장은 keyring 라이브러리를 경유한다.
"""

from __future__ import annotations

import configparser
import json
import logging
from pathlib import Path
from typing import Any

import boto3
import keyring
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

from s3manager import settings

logger = logging.getLogger(__name__)

# Keychain 서비스명 (settings에서 가져옴)
_SERVICE = settings.KEYRING_SERVICE


# ---------------------------------------------------------------------------
# Keychain (keyring) 헬퍼
# ---------------------------------------------------------------------------

def save_keychain_profile(
    name: str,
    access_key_id: str,
    secret_access_key: str,
    region: str | None,
) -> None:
    """Keychain에 프로파일 저장.

    비밀키를 JSON으로 직렬화하여 keyring에 보관한다.
    """
    payload = json.dumps(
        {
            "accessKeyId": access_key_id,
            "secretAccessKey": secret_access_key,
            "region": region,
        }
    )
    keyring.set_password(_SERVICE, name, payload)
    logger.info("Keychain 프로파일 저장 완료: %s", name)


def delete_keychain_profile(name: str) -> None:
    """Keychain에서 프로파일 삭제."""
    try:
        keyring.delete_password(_SERVICE, name)
        logger.info("Keychain 프로파일 삭제 완료: %s", name)
    except keyring.errors.PasswordDeleteError:
        logger.warning("Keychain 프로파일을 찾을 수 없음: %s", name)


def load_keychain_profile(name: str) -> dict[str, Any] | None:
    """Keychain에서 프로파일 로드.

    Returns:
        {"accessKeyId": ..., "secretAccessKey": ..., "region": ...} 또는 None
    """
    raw = keyring.get_password(_SERVICE, name)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Keychain 프로파일 JSON 파싱 실패: %s", name)
        return None


def list_keychain_profiles() -> list[dict[str, str | None]]:
    """Keychain에 저장된 모든 프로파일 목록 반환 (비밀키 미포함).

    keyring은 특정 서비스의 모든 항목을 열거하는 표준 API가 없으므로
    크리덴셜 메타데이터 인덱스를 별도 파일에 보관하는 대신,
    macOS keyring 백엔드의 get_credential()을 이용한다.
    이름 목록은 APP_SUPPORT_DIR/keychain_profiles.json 에 저장한다.
    """
    index_path = settings.APP_SUPPORT_DIR / "keychain_profiles.json"
    if not index_path.exists():
        return []
    try:
        names: list[str] = json.loads(index_path.read_text())
    except Exception:
        return []

    result = []
    for name in names:
        data = load_keychain_profile(name)
        if data is not None:
            result.append(
                {
                    "name": name,
                    "source": "keychain",
                    "region": data.get("region"),
                }
            )
    return result


def register_keychain_profile_name(name: str) -> None:
    """프로파일 이름을 인덱스 파일에 등록한다."""
    index_path = settings.APP_SUPPORT_DIR / "keychain_profiles.json"
    settings.APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    if index_path.exists():
        try:
            names = json.loads(index_path.read_text())
        except Exception:
            names = []
    if name not in names:
        names.append(name)
        index_path.write_text(json.dumps(names))


def unregister_keychain_profile_name(name: str) -> None:
    """인덱스 파일에서 프로파일 이름을 제거한다."""
    index_path = settings.APP_SUPPORT_DIR / "keychain_profiles.json"
    if not index_path.exists():
        return
    try:
        names: list[str] = json.loads(index_path.read_text())
        names = [n for n in names if n != name]
        index_path.write_text(json.dumps(names))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# ~/.aws 프로파일 탐지
# ---------------------------------------------------------------------------

def list_aws_profiles() -> list[dict[str, str | None]]:
    """~/.aws/credentials 와 ~/.aws/config 에서 프로파일 목록을 반환한다.

    빈 ~/.aws 디렉터리 또는 파일 없음에서도 크래시 없이 빈 리스트를 반환한다.
    """
    profiles: dict[str, dict[str, str | None]] = {}

    credentials_path = Path.home() / ".aws" / "credentials"
    config_path = Path.home() / ".aws" / "config"

    def _parse_credentials(path: Path) -> None:
        if not path.exists():
            return
        parser = configparser.RawConfigParser()
        try:
            parser.read(str(path))
        except Exception as exc:
            logger.warning("~/.aws/credentials 파싱 실패: %s", exc)
            return
        for section in parser.sections():
            name = section  # credentials 파일은 그대로 프로파일명
            if name not in profiles:
                profiles[name] = {"name": name, "source": "aws", "region": None}

    def _parse_config(path: Path) -> None:
        if not path.exists():
            return
        parser = configparser.RawConfigParser()
        try:
            parser.read(str(path))
        except Exception as exc:
            logger.warning("~/.aws/config 파싱 실패: %s", exc)
            return
        for section in parser.sections():
            # config 파일의 섹션명: "profile <name>" 또는 "[default]"
            if section == "default":
                name = "default"
            elif section.startswith("profile "):
                name = section[len("profile "):]
            else:
                name = section

            region = None
            try:
                region = parser.get(section, "region")
            except configparser.NoOptionError:
                pass

            if name not in profiles:
                profiles[name] = {"name": name, "source": "aws", "region": region}
            else:
                if profiles[name]["region"] is None:
                    profiles[name]["region"] = region

    _parse_credentials(credentials_path)
    _parse_config(config_path)

    return list(profiles.values())


def list_all_profiles() -> list[dict[str, str | None]]:
    """~/.aws 프로파일과 Keychain 프로파일을 합쳐 반환한다."""
    aws = list_aws_profiles()
    kc = list_keychain_profiles()
    # 이름 충돌 시 keychain 우선 (앱이 저장한 것)
    merged: dict[str, dict[str, str | None]] = {p["name"]: p for p in aws}
    for p in kc:
        merged[p["name"]] = p
    return list(merged.values())


# ---------------------------------------------------------------------------
# boto3 세션/클라이언트 생성 및 검증
# ---------------------------------------------------------------------------

def make_boto3_session(
    *,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    region: str | None = None,
    profile_name: str | None = None,
) -> boto3.Session:
    """boto3 세션을 생성한다.

    직접 키 또는 프로파일명 중 하나를 지정해야 한다.
    """
    if access_key_id and secret_access_key:
        return boto3.Session(
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region or settings.DEFAULT_REGION,
        )
    if profile_name:
        return boto3.Session(
            profile_name=profile_name,
            region_name=region,
        )
    raise ValueError("access_key_id+secret_access_key 또는 profile_name 중 하나가 필요합니다.")


def validate_session(session: boto3.Session) -> dict[str, str]:
    """STS get_caller_identity로 세션을 검증한다.

    Returns:
        {"account": "...", "arn": "...", "userId": "..."}

    Raises:
        ClientError, NoCredentialsError 등 boto3 예외
    """
    sts = session.client("sts")
    resp = sts.get_caller_identity()
    return {
        "account": resp["Account"],
        "arn": resp["Arn"],
        "userId": resp["UserId"],
    }


def build_session_for_connect(
    mode: str,
    *,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    region: str | None = None,
    profile_name: str | None = None,
) -> tuple[boto3.Session, dict[str, str]]:
    """connect 요청에 따라 세션을 빌드하고 검증한다.

    mode="keys": 직접 키 사용
    mode="profile": ~/.aws 또는 Keychain 프로파일 사용

    Returns:
        (boto3.Session, identity_dict)
    """
    if mode == "keys":
        if not access_key_id or not secret_access_key:
            raise ValueError("keys 모드에는 accessKeyId와 secretAccessKey가 필요합니다.")
        session = make_boto3_session(
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            region=region,
        )
    elif mode == "profile":
        if not profile_name:
            raise ValueError("profile 모드에는 profileName이 필요합니다.")
        # Keychain에 있으면 키를 꺼내서 직접 세션 생성
        kc_data = load_keychain_profile(profile_name)
        if kc_data:
            session = make_boto3_session(
                access_key_id=kc_data["accessKeyId"],
                secret_access_key=kc_data["secretAccessKey"],
                region=region or kc_data.get("region"),
            )
        else:
            # ~/.aws 프로파일
            session = make_boto3_session(profile_name=profile_name, region=region)
    else:
        raise ValueError(f"알 수 없는 mode: {mode}")

    identity = validate_session(session)
    return session, identity
