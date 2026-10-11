"""Read-only Cloudflare R2 client used by recorded-data backtests."""

from __future__ import annotations

import hashlib
import hmac
import os
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class R2Client:
    """Minimal AWS Signature V4 client for the R2 S3-compatible API."""

    def __init__(
        self,
        endpoint_url: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        timeout_seconds: float = 30.0,
    ):
        settings = {
            "R2_ENDPOINT_URL": endpoint_url,
            "R2_BUCKET": bucket,
            "R2_ACCESS_KEY_ID": access_key_id,
            "R2_SECRET_ACCESS_KEY": secret_access_key,
        }
        missing = [name for name, value in settings.items() if not value]
        if missing:
            raise ValueError("Missing R2 environment variables: " + ", ".join(missing))

        endpoint = urllib.parse.urlsplit(endpoint_url.rstrip("/"))
        if endpoint.scheme != "https" or not endpoint.netloc:
            raise ValueError("R2_ENDPOINT_URL must be an https URL")
        if not bucket or "/" in bucket:
            raise ValueError("R2_BUCKET is invalid")

        self.endpoint = endpoint
        self.bucket = bucket
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_environment(cls) -> R2Client:
        return cls(
            os.getenv("R2_ENDPOINT_URL", "").strip(),
            os.getenv("R2_BUCKET", "").strip(),
            os.getenv("R2_ACCESS_KEY_ID", "").strip(),
            os.getenv("R2_SECRET_ACCESS_KEY", "").strip(),
        )

    def _signing_key(self, day: str) -> bytes:
        def sign(key: bytes, value: str) -> bytes:
            return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()

        key = sign(("AWS4" + self.secret_access_key).encode("utf-8"), day)
        key = sign(key, "auto")
        key = sign(key, "s3")
        return sign(key, "aws4_request")

    def _request(
        self,
        method: str,
        key: str = "",
        *,
        query: dict[str, str] | None = None,
    ) -> tuple[bytes, Any]:
        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        day = now.strftime("%Y%m%d")
        base_path = self.endpoint.path.rstrip("/")
        bucket = urllib.parse.quote(self.bucket, safe="-_.~")
        canonical_uri = f"{base_path}/{bucket}"
        if key:
            canonical_uri += "/" + urllib.parse.quote(key.lstrip("/"), safe="/-_.~")
        pairs = [
            (
                urllib.parse.quote(str(name), safe="-_.~"),
                urllib.parse.quote(str(value), safe="-_.~"),
            )
            for name, value in sorted((query or {}).items())
        ]
        canonical_query = "&".join(f"{name}={value}" for name, value in pairs)
        payload_hash = hashlib.sha256(b"").hexdigest()
        headers = {
            "host": self.endpoint.netloc,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in sorted(headers))
        signed_headers = ";".join(sorted(headers))
        canonical_request = "\n".join(
            [method, canonical_uri or "/", canonical_query, canonical_headers, signed_headers, payload_hash]
        )
        scope = f"{day}/auto/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signature = hmac.new(
            self._signing_key(day),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        authorization = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key_id}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        request_headers = {name.title(): value for name, value in headers.items()}
        request_headers["Authorization"] = authorization
        url = urllib.parse.urlunsplit(
            (self.endpoint.scheme, self.endpoint.netloc, canonical_uri, canonical_query, "")
        )
        request = urllib.request.Request(url, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return response.read(), response.headers
        except urllib.error.HTTPError as exc:
            detail = exc.read(500).decode("utf-8", errors="replace")
            raise RuntimeError(f"R2 {method} returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"R2 {method} failed: {exc.reason}") from exc

    def list_objects(self, prefix: str) -> list[str]:
        objects: list[str] = []
        continuation = ""
        while True:
            query = {"list-type": "2", "prefix": prefix}
            if continuation:
                query["continuation-token"] = continuation
            payload, _ = self._request("GET", query=query)
            root = ET.fromstring(payload)
            for item in root.findall(".//{*}Contents"):
                key = item.findtext("{*}Key")
                if key:
                    objects.append(key)
            truncated = root.findtext("{*}IsTruncated", "false").lower() == "true"
            continuation = root.findtext("{*}NextContinuationToken", "")
            if not truncated or not continuation:
                return objects

    def download(self, object_key: str, output: Path) -> None:
        payload, headers = self._request("GET", object_key)
        expected_sha = str(headers.get("x-amz-meta-sha256", "")).strip().lower()
        actual_sha = hashlib.sha256(payload).hexdigest()
        if expected_sha and expected_sha != actual_sha:
            raise RuntimeError(f"R2 download checksum verification failed: {object_key}")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(output)
