"""Optional, lookup-only URL reputation. Never connect to a message URL.

No networking occurs unless AI_URL_REPUTATION_ENABLED=1 and a Web Risk key
are configured. An empty provider match means NOT_FOUND, never "safe".
"""
from __future__ import annotations

from copy import deepcopy
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import http.client
import hashlib
import ipaddress
import json
import os
import re
import socket
import threading
import time
from typing import Callable, Mapping
from urllib.parse import urlencode, urlsplit, urlunsplit


PROVIDER_HOST = "webrisk.googleapis.com"
PROVIDER_PATH = "/v1/uris:search"
POLICY_VERSION = "url-reputation-lookup-v1"
THREAT_TYPES = ("MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE")
MAX_RESPONSE_BYTES = 65_536
# Conservative ASCII URL extraction: do not repair OCR or consume adjacent
# Korean instructions as part of an address. IDN/Unicode URLs require review.
URL_PATTERN = re.compile(
    r"(?i)(?:https?://|www\.)[a-z0-9._~:/?#\[\]@!$&'()*+,;=%+-]+"
)
HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z", re.I)


@dataclass(frozen=True)
class LookupRequest:
    host: str
    path: str
    headers: Mapping[str, str] = field(repr=False)
    method: str = "GET"


@dataclass(frozen=True)
class LookupResponse:
    status: int
    body: bytes = b""


def extract_urls(text: str) -> list[str]:
    """Return original URL substrings; the message text is never modified."""
    urls = []
    seen = set()
    for match in URL_PATTERN.finditer(text):
        original = match.group().rstrip(".,;!?")
        # Drop surrounding punctuation, retaining balanced path parentheses.
        while original.endswith(")") and original.count(")") > original.count("("):
            original = original[:-1]
        if original and original not in seen:
            seen.add(original)
            urls.append(original)
    return urls


def prepare_lookup_url(original: str) -> tuple[str | None, str | None, bool]:
    """Validate syntax without resolving the supplied host or opening it."""
    inferred = original.lower().startswith("www.")
    uri = "https://" + original if inferred else original
    if len(uri) > 2048 or any(ord(char) < 33 or ord(char) > 126 for char in uri):
        return None, "UNSUPPORTED_OR_LONG_URL", inferred
    try:
        parts = urlsplit(uri)
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
        if parts.scheme.lower() not in {"http", "https"} or not host:
            return None, "UNSUPPORTED_URL", inferred
        if parts.username is not None or parts.password is not None:
            return None, "URL_CONTAINS_CREDENTIALS", inferred
        if port is not None and port not in {80, 443}:
            return None, "NONSTANDARD_PORT", inferred
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            # Block local names and noncanonical numeric IP spellings without
            # doing DNS lookups on attacker-controlled hostnames.
            if "." not in host or re.fullmatch(r"[0-9.]+", host):
                return None, "LOCAL_OR_INVALID_HOST", inferred
            if host.endswith((".localhost", ".local", ".internal", ".home.arpa")):
                return None, "LOCAL_OR_INVALID_HOST", inferred
            if len(host) > 253 or not all(HOST_LABEL.fullmatch(x) for x in host.split(".")):
                return None, "LOCAL_OR_INVALID_HOST", inferred
        else:
            if not address.is_global:
                return None, "NONPUBLIC_IP", inferred
        # Fragments are client-side data. Keep them in originalUrl, omit only
        # from the provider lookup; path/query are sent unchanged.
        return urlunsplit((parts.scheme.lower(), parts.netloc, parts.path,
                           parts.query, "")), None, inferred
    except (ValueError, UnicodeError):
        return None, "INVALID_URL", inferred


def fixed_provider_transport(request: LookupRequest, timeout: float) -> LookupResponse:
    """HTTPS to one fixed provider only; http.client never follows redirects."""
    if (request.host != PROVIDER_HOST or request.method != "GET"
            or not request.path.startswith(PROVIDER_PATH + "?")):
        raise ValueError("Only the fixed Web Risk lookup endpoint is permitted")
    started = time.monotonic()
    connection = http.client.HTTPSConnection(PROVIDER_HOST, port=443, timeout=timeout)
    try:
        connection.request("GET", request.path, headers=dict(request.headers))
        response = connection.getresponse()
        if response.status != 200:
            # Ignore error bodies and Location; they can contain credentials or
            # redirects. There is no retry, browser fallback, or target fetch.
            return LookupResponse(response.status)
        chunks, total = [], 0
        while True:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("Lookup deadline")
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            chunk = response.read1(min(8192, MAX_RESPONSE_BYTES + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise ValueError("Oversized provider response")
            chunks.append(chunk)
        return LookupResponse(200, b"".join(chunks))
    finally:
        connection.close()


class UrlReputationLookup:
    def __init__(self, *, enabled: bool = False, api_key: str = "",
                 max_urls: int = 3, timeout_seconds: float = 1.5,
                 total_budget_seconds: float = 3.0,
                 transport: Callable[[LookupRequest, float], LookupResponse] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time):
        if not (1 <= max_urls <= 5 and 0.1 <= timeout_seconds <= 5
                and 0.1 <= total_budget_seconds <= 10):
            raise ValueError("Invalid bounded lookup limits")
        self.enabled = bool(enabled)
        self._key = api_key.strip()
        if any(ord(character) < 33 or ord(character) > 126 for character in self._key):
            raise ValueError("Invalid lookup API key format")
        self.max_urls = max_urls
        self.timeout_seconds = timeout_seconds
        self.total_budget_seconds = total_budget_seconds
        self._transport = transport or fixed_provider_transport
        self._clock = clock
        self._wall_clock = wall_clock
        self._cache = OrderedDict()
        self._cache_lock = threading.Lock()

    def _cached(self, uri):
        digest = hashlib.sha256(uri.encode("utf-8")).hexdigest()
        with self._cache_lock:
            value = self._cache.get(digest)
            if value is None:
                return None
            if value[0] <= self._wall_clock():
                del self._cache[digest]
                return None
            self._cache.move_to_end(digest)
            return deepcopy(value[1])

    def _cache_match(self, uri, item):
        expires = item.get("providerExpireTime")
        try:
            expire_time = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if expire_time.tzinfo is None or expire_time.timestamp() <= self._wall_clock():
                return
        except (AttributeError, TypeError, ValueError, OverflowError):
            return
        value = {key: deepcopy(item[key]) for key in
                 ("status", "reasonCode", "threatTypes", "providerExpireTime", "lookupCheckedAt")}
        digest = hashlib.sha256(uri.encode("utf-8")).hexdigest()
        with self._cache_lock:
            self._cache[digest] = (expire_time.timestamp(), value)
            self._cache.move_to_end(digest)
            while len(self._cache) > 1000:
                self._cache.popitem(last=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "UrlReputationLookup":
        env = os.environ if env is None else env
        return cls(enabled=env.get("AI_URL_REPUTATION_ENABLED", "0") == "1",
                   api_key=env.get("AI_WEBRISK_API_KEY", ""))

    def assess(self, text: str) -> dict:
        if not isinstance(text, str) or len(text) > 4000:
            raise ValueError("Expected at most 4000 text characters")
        originals = extract_urls(text)
        started = self._clock()
        results, submitted = [], 0
        checked_at = datetime.fromtimestamp(self._wall_clock(), timezone.utc).isoformat().replace("+00:00", "Z")
        for original in originals:
            lookup_uri, validation_error, inferred = prepare_lookup_url(original)
            item = {"originalUrl": original, "lookupUrl": lookup_uri,
                    "schemeInferred": inferred, "status": "disabled",
                    "reasonCode": None, "threatTypes": [], "cacheHit": False}
            results.append(item)
            if validation_error:
                item.update(status="skipped", reasonCode=validation_error)
                continue
            if not self.enabled:
                item["reasonCode"] = "LOOKUP_DISABLED"
                continue
            if not self._key:
                item.update(status="unavailable", reasonCode="LOOKUP_KEY_NOT_CONFIGURED")
                continue
            cached = self._cached(lookup_uri)
            if cached is not None:
                item.update(cached, cacheHit=True)
                continue
            if submitted >= self.max_urls:
                item.update(status="skipped", reasonCode="LOOKUP_URL_LIMIT")
                continue
            remaining = self.total_budget_seconds - (self._clock() - started)
            if remaining <= 0:
                item.update(status="unavailable", reasonCode="LOOKUP_BUDGET_EXCEEDED")
                continue
            parameters = [("uri", lookup_uri)]
            parameters += [("threatTypes", threat) for threat in THREAT_TYPES]
            request = LookupRequest(PROVIDER_HOST,
                                    PROVIDER_PATH + "?" + urlencode(parameters),
                                    {"X-Goog-Api-Key": self._key,
                                     "Accept": "application/json"})
            submitted += 1
            try:
                response = self._transport(request, min(self.timeout_seconds, remaining))
                if response.status != 200:
                    item.update(status="unavailable", reasonCode="LOOKUP_HTTP_ERROR")
                    continue
                item["lookupCheckedAt"] = datetime.fromtimestamp(
                    self._wall_clock(), timezone.utc).isoformat().replace("+00:00", "Z")
                if len(response.body) > MAX_RESPONSE_BYTES:
                    item.update(status="unavailable", reasonCode="LOOKUP_INVALID_RESPONSE")
                    continue
                payload = json.loads(response.body)
                if not isinstance(payload, dict):
                    raise ValueError("Expected provider object")
                threat = payload.get("threat")
                if threat is None:
                    if payload:
                        raise ValueError("Unexpected provider fields")
                    item.update(status="not_found", reasonCode="NO_KNOWN_THREAT_MATCH")
                    continue
                if not isinstance(threat, dict):
                    raise ValueError("Expected threat object")
                types = threat.get("threatTypes")
                if (not isinstance(types, list) or not types
                        or any(value not in THREAT_TYPES for value in types)):
                    raise ValueError("Invalid threat types")
                item.update(status="malicious", reasonCode="KNOWN_MALICIOUS_URL",
                            threatTypes=sorted(set(types)))
                expires = threat.get("expireTime")
                if isinstance(expires, str) and len(expires) <= 64:
                    # Only serialize a parsed timestamp, never an arbitrary
                    # provider string that could reflect credentials.
                    try:
                        expiry = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                        if expiry.tzinfo is not None:
                            item["providerExpireTime"] = expiry.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                            self._cache_match(lookup_uri, item)
                    except (ValueError, OverflowError):
                        pass
            except (TimeoutError, socket.timeout):
                item.update(status="unavailable", reasonCode="LOOKUP_TIMEOUT")
            except Exception:
                # Never return/log exception strings: provider, key and URL
                # query data may appear in them. The caller keeps text output.
                item.update(status="unavailable", reasonCode="LOOKUP_FAILED")
        statuses = {item["status"] for item in results}
        if not results:
            status = "no_urls"
        elif not self.enabled:
            status = "disabled"
        elif "malicious" in statuses:
            status = "malicious"
        elif statuses <= {"not_found"}:
            status = "not_found"
        else:
            status = "incomplete"
        return {"provider": "GOOGLE_WEB_RISK_LOOKUP", "policyVersion": POLICY_VERSION,
                "enabled": self.enabled, "status": status, "checkedAt": checked_at,
                "urlCount": len(originals), "submittedCount": submitted,
                "targetVisited": False,
                "notFoundMeaning": "NO_KNOWN_THREAT_MATCH_NOT_A_SAFETY_GUARANTEE",
                "results": results}


def apply_reputation(text_result: dict, reputation: dict) -> dict:
    """Positive match can warn; absence/failure never lowers text risk.

    Keep the original classifier score: a list match is not a calibrated score.
    This helper returns new data and does not mutate the caller's result.
    """
    output = deepcopy(text_result)
    output["textDecision"] = output["decision"]
    output["urlReputation"] = deepcopy(reputation)
    matches = [item for item in reputation.get("results", [])
               if item.get("status") == "malicious"]
    if matches:
        output["decision"] = "phishing"
        output["decisionSource"] = "KNOWN_MALICIOUS_URL"
        output.setdefault("evidence", []).append(
            "Google Web Risk 위험 목록과 일치하는 URL이 있습니다.")
    else:
        output["decisionSource"] = "TEXT_CLASSIFIER"
    return output
