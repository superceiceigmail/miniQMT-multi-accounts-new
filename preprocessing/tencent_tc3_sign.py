#!/usr/bin/env python3
# preprocessing/tencent_tc3_sign.py
# TC3-HMAC-SHA256 signing helper for Tencent Cloud APIs
#
# Security:
# - Do NOT hardcode SecretId/SecretKey in this file.
# - Provide credentials through environment variables, a secrets manager,
#   or other secure store.
# - This file avoids printing secrets and attempts to minimize accidental leaks.
#
# Improvements over naive versions:
# - Deterministic JSON serialization (sort_keys=True)
# - Normalization of header values used for canonicalization
# - Input validation and clear error messages
# - Best-effort clearing of secret references after use
# - Example usage avoids embedding secrets in source and prints masked output

from __future__ import annotations
import os
import time
import json
import hashlib
import hmac
import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_CONTENT_TYPE = "application/json; charset=utf-8"


def _sha256_hex(msg: bytes) -> str:
    return hashlib.sha256(msg).hexdigest()


def _hmac_sha256(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def _mask_secret(value: Optional[str], keep: int = 4) -> str:
    """Return a masked form of a secret for safe logging/display."""
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "..."


def tc3_sign(
    secret_id: str,
    secret_key: str,
    service: str,
    host: str,
    region: str,
    action: str,
    version: str,
    payload: Dict,
    timestamp: Optional[int] = None,
    content_type: str = DEFAULT_CONTENT_TYPE,
) -> Tuple[Dict[str, str], str]:
    """
    Construct TC3-HMAC-SHA256 Authorization headers and return (headers_dict, request_body_str).

    This implementation:
    - Serializes payload deterministically (sort_keys=True).
    - Normalizes header values used for canonical request.
    - Performs input validation and avoids printing secrets.
    - Best-effort clears sensitive variables before returning.

    Note: Clearing Python string variables does NOT guarantee zeroing memory.
    For highly sensitive workflows use a dedicated secrets manager and memory-safe libraries.
    """

    # --- Input validation ---
    if not isinstance(secret_id, str) or not secret_id:
        raise ValueError("secret_id must be a non-empty string")
    if not isinstance(secret_key, str) or not secret_key:
        raise ValueError("secret_key must be a non-empty string")
    if not isinstance(service, str) or not service:
        raise ValueError("service must be a non-empty string")
    if not isinstance(host, str) or not host:
        raise ValueError("host must be a non-empty string")
    if not isinstance(region, str) or not region:
        raise ValueError("region must be a non-empty string")
    if not isinstance(action, str) or not action:
        raise ValueError("action must be a non-empty string")
    if not isinstance(version, str) or not version:
        raise ValueError("version must be a non-empty string")
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")

    # --- Timestamp and date ---
    if timestamp is None:
        timestamp = int(time.time())
    t = int(timestamp)
    date = time.strftime("%Y-%m-%d", time.gmtime(t))  # UTC date

    # --- HTTP request components ---
    http_request_method = "POST"
    canonical_uri = "/"
    canonical_querystring = ""

    # Deterministic JSON: sort keys, no extra whitespace
    body_str = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    body_bytes = body_str.encode("utf-8")

    # step 1: hashed request payload
    hashed_request_payload = _sha256_hex(body_bytes)

    # step 2: canonical headers and signed headers
    # Normalize header values: lower-case header names and trimmed lower-case values for canonicalization
    content_type_norm = content_type.strip().lower()
    host_norm = host.strip().lower()

    canonical_headers = f"content-type:{content_type_norm}\nhost:{host_norm}\n"
    signed_headers = "content-type;host"

    # canonical request
    canonical_request = (
        f"{http_request_method}\n"
        f"{canonical_uri}\n"
        f"{canonical_querystring}\n"
        f"{canonical_headers}\n"
        f"{signed_headers}\n"
        f"{hashed_request_payload}"
    )

    # step 3: string to sign
    algorithm = "TC3-HMAC-SHA256"
    credential_scope = f"{date}/{service}/tc3_request"
    hashed_canonical_request = _sha256_hex(canonical_request.encode("utf-8"))
    string_to_sign = f"{algorithm}\n{t}\n{credential_scope}\n{hashed_canonical_request}"

    # step 4: calculate signature
    secret_date = _hmac_sha256(("TC3" + secret_key).encode("utf-8"), date.encode("utf-8"))
    secret_service = _hmac_sha256(secret_date, service.encode("utf-8"))
    secret_signing = _hmac_sha256(secret_service, b"tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    # step 5: authorization
    authorization = (
        f"{algorithm} "
        f"Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )

    # headers to send
    headers = {
        "Authorization": authorization,
        "Content-Type": content_type,
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Version": version,
        "X-TC-Region": region,
        "X-TC-Timestamp": str(t),
    }

    # Best-effort: remove references to secrets in local scope
    # (Note: this does not zero memory; it reduces accidental reuse in subsequent code)
    secret_key = None
    secret_date = None
    secret_service = None
    secret_signing = None
    signature_local = None  # not the same as signature in headers, but tidy local names

    return headers, body_str


def make_tc3_headers_from_env(
    service: str,
    host: str,
    region: str,
    action: str,
    version: str,
    payload: Dict,
    timestamp: Optional[int] = None,
) -> Tuple[Dict[str, str], str]:
    """
    Read credentials from environment variables and call tc3_sign.

    Environment variables:
      - TENCENT_SECRET_ID
      - TENCENT_SECRET_KEY

    Raises RuntimeError if environment variables are missing.
    """
    secret_id = os.environ.get("TENCENT_SECRET_ID")
    secret_key = os.environ.get("TENCENT_SECRET_KEY")
    if not secret_id or not secret_key:
        raise RuntimeError(
            "TENCENT_SECRET_ID and TENCENT_SECRET_KEY must be set in environment. "
            "Do NOT hardcode credentials in source code."
        )
    return tc3_sign(secret_id, secret_key, service, host, region, action, version, payload, timestamp)


# -------------------------
# Example usage (safe)
# -------------------------
if __name__ == "__main__":
    # Very small example. DO NOT hardcode secrets here.
    # Ensure environment variables TENCENT_SECRET_ID and TENCENT_SECRET_KEY are set before running.
    import sys

    logging.basicConfig(level=logging.INFO)

    example_service = "cvm"
    example_host = "cvm.tencentcloudapi.com"
    example_region = "ap-shanghai"
    example_action = "DescribeInstances"
    example_version = "2017-03-12"
    example_payload = {"Limit": 1, "Offset": 0}

    if not os.environ.get("TENCENT_SECRET_ID") or not os.environ.get("TENCENT_SECRET_KEY"):
        logger.error(
            "Environment variables TENCENT_SECRET_ID and TENCENT_SECRET_KEY are not set.\n"
            "Set them in your environment or use a secrets manager. Example (Linux/macOS):\n"
            "  export TENCENT_SECRET_ID=your_secret_id\n"
            "  export TENCENT_SECRET_KEY=your_secret_key\n"
        )
        sys.exit(1)

    headers, body = make_tc3_headers_from_env(
        example_service, example_host, example_region, example_action, example_version, example_payload
    )

    # Safe display: do NOT print full Authorization or secrets. Mask sensitive parts.
    credential_part = ""
    try:
        # Authorization has form 'TC3-HMAC-SHA256 Credential=SECRETID/...., SignedHeaders=..., Signature=...'
        # We'll mask the SECRETID for display.
        auth = headers.get("Authorization", "")
        if "Credential=" in auth:
            # naive extraction just for safe display
            cred_section = auth.split("Credential=", 1)[1].split(",", 1)[0]
            secret_id_raw = cred_section.split("/", 1)[0]
            credential_part = cred_section.replace(secret_id_raw, _mask_secret(secret_id_raw))
    except Exception:
        credential_part = "[masked]"

    logger.info("Prepared headers (keys only): %s", list(headers.keys()))
    logger.info("Authorization (masked credential): %s", credential_part)
    logger.info("Request body length (bytes): %d", len(body.encode("utf-8")))
    logger.info("If you want to actually send the request, use a secure HTTP client and do NOT log secrets.")