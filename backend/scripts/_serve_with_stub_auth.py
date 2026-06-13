"""검증 전용 부팅 스크립트 — 로컬 keypair stub JWKS로 uvicorn을 띄운다.

실제 Clerk 유효 세션 토큰은 브라우저 로그인이 필요하므로(item 11), 서명 검증 경로 자체는
test_auth.py가 확립한 로컬 RSA keypair + stub JWKS 패턴으로 결정적으로 통과시킨다.
이 스크립트는 그 패턴 그대로 get_verifier를 오버라이드한 채 라이브 Postgres에 붙어 부팅한다.

토큰은 별도 스크립트(_mint_token.py)가 동일 keypair로 발급한다 — keypair를 PEM 파일로
공유한다(프로세스 분리 때문에).
"""

from __future__ import annotations

import json
import os

import jwt
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import ClerkTokenVerifier, get_verifier
from app.main import app

ISSUER = "https://verify-local.clerk.accounts.dev"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"
KID = "verify-kid"
KEY_PATH = os.environ["VERIFY_KEY_PATH"]

# keypair를 만들고 PEM으로 저장(토큰 발급 스크립트가 같은 키로 서명하도록).
_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
with open(KEY_PATH, "wb") as f:
    f.write(
        _priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def _fake_fetch_data(self):
    pub_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(_priv.public_key(), as_dict=True)
    pub_jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return {"keys": [pub_jwk]}


# PyJWKClient의 네트워크 fetch를 로컬 공개키로 대체.
jwt.PyJWKClient.fetch_data = _fake_fetch_data


def _verifier() -> ClerkTokenVerifier:
    return ClerkTokenVerifier(issuer=ISSUER, jwks_url=JWKS_URL)


app.dependency_overrides[get_verifier] = _verifier

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8099, log_level="warning")
