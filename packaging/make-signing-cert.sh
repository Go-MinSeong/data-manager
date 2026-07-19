#!/usr/bin/env bash
# Data Manager — 안정적 코드서명 인증서 생성(1회)
#
# 왜: ad-hoc 서명(`codesign -s -`)은 빌드마다 코드 해시가 달라져, macOS Keychain이
#     "이전 빌드가 저장한 비밀번호"를 새 빌드에 대해 접근 거부한다(원격 비밀번호 인증 깨짐).
#     같은 자체 서명 인증서로 매 빌드를 서명하면 코드 아이덴티티가 고정돼 Keychain 접근이 유지된다.
#
# 사용: bash packaging/make-signing-cert.sh   (이미 있으면 아무것도 안 함)
# 결과: 로그인 키체인에 "Data Manager Dev" 코드서명 아이덴티티 등록.
#       이후 build.sh 가 이 아이덴티티로 서명한다.

set -euo pipefail

CN="Data Manager Dev"
KEYCHAIN="${HOME}/Library/Keychains/login.keychain-db"

# -v(유효/신뢰됨) 없이 조회 — 자체 서명은 미신뢰라 -v 목록엔 안 뜨지만 서명엔 문제없다.
if security find-identity -p codesigning 2>/dev/null | grep -q "$CN"; then
    echo "이미 존재: '$CN' 코드서명 아이덴티티 — 생성 건너뜀."
    exit 0
fi

echo "자체 서명 코드서명 인증서 '$CN' 생성 중..."
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cat > "$TMP/openssl.cnf" <<EOF
[req]
distinguished_name = dn
x509_extensions = v3
prompt = no
[dn]
CN = $CN
[v3]
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
EOF

openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
    -keyout "$TMP/key.pem" -out "$TMP/cert.pem" \
    -config "$TMP/openssl.cnf" -extensions v3 >/dev/null 2>&1

# macOS `security import` 는 구형 PKCS12 MAC(SHA1)+PBE만 검증한다. OpenSSL 3 기본값
# (SHA-256 MAC)은 "MAC verification failed"로 거부되므로 레거시 알고리즘을 강제한다.
# 또한 빈 비밀번호 p12도 MAC 검증에 실패하므로 임시 비밀번호를 쓴다.
P12PW="dm-cert-import"
P12_ARGS=(-macalg sha1 -certpbe PBE-SHA1-3DES -keypbe PBE-SHA1-3DES)
if openssl version | grep -q "OpenSSL 3"; then
    P12_ARGS+=(-legacy)  # OpenSSL 3 에서 3DES/RC2(레거시 provider) 사용
fi
openssl pkcs12 -export -inkey "$TMP/key.pem" -in "$TMP/cert.pem" \
    -out "$TMP/cert.p12" -passout "pass:$P12PW" -name "$CN" "${P12_ARGS[@]}" >/dev/null 2>&1

# 로그인 키체인에 개인키+인증서 임포트. -T /usr/bin/codesign: codesign 이 이 키로
# 서명할 수 있도록 ACL에 추가(첫 빌드 시 "항상 허용" 한 번이면 이후 무프롬프트).
security import "$TMP/cert.p12" -k "$KEYCHAIN" -P "$P12PW" -T /usr/bin/codesign >/dev/null

echo "완료. 등록된 코드서명 아이덴티티:"
security find-identity -v -p codesigning | grep "$CN" || true
echo ""
echo "다음: bash packaging/build.sh 로 빌드하면 이 아이덴티티로 서명됩니다."
echo "(첫 빌드 때 키체인 접근 창이 뜨면 '항상 허용'을 누르세요.)"
