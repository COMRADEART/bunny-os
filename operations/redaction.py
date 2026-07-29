"""Deterministic redaction for feedback, crashes, journals, and exports."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Mapping


EXCLUDED_CONTENT_KEYS = frozenset({
    "prompt", "prompts", "memory", "memories", "document", "documents", "usercontent",
    "usercontents", "attachmentcontent", "clipboard", "screenshot", "transcript",
})
SECRET_KEYS = frozenset({
    "password", "passphrase", "token", "accesstoken", "refreshtoken", "apikey", "secret",
    "recoverykey", "privatekey", "credential", "credentials", "wifipassword", "ssid",
})
IDENTIFIER_KEYS = frozenset({
    "email", "phone", "hostname", "username", "userid", "sessionid", "deviceid", "ipaddress",
    "macaddress", "serial", "uuid", "homepath",
})

PATTERNS = (
    (re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE), "[redacted-email]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[redacted-ip]"),
    (re.compile(r"\b(?:[0-9A-F]{2}[:-]){5}[0-9A-F]{2}\b", re.IGNORECASE), "[redacted-mac]"),
    (re.compile(r"(?i)\b(?:sk|pk|rk|ghp|github_pat)_[A-Za-z0-9_-]{12,}\b"), "[redacted-token]"),
    (re.compile(r"(?i)(?:/home/|C:\\Users\\)[^\\/\s]+"), "[redacted-home]"),
    (re.compile(r"\b(?:[A-Z0-9]{4}-){5,}[A-Z0-9]{4}\b", re.IGNORECASE), "[redacted-key]"),
    (re.compile(r"(?i)\b(?:phone|telephone)\s*[:=]\s*\+?[0-9() .-]{7,24}"), "phone=[redacted-phone]"),
    (re.compile(r"(?i)\b(?:host|hostname)\s*[:=]\s*[A-Za-z0-9][A-Za-z0-9.-]{0,252}"), "hostname=[redacted-hostname]"),
    (re.compile(r"(?i)\bssid\s*[:=]\s*(?:\"[^\"]{1,64}\"|'[^']{1,64}'|[^\s,;]{1,64})"), "ssid=[redacted-wifi-name]"),
    (re.compile(r"(?i)\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token)\s*[:=]\s*[^\s,;]{4,512}"), "token=[redacted-token]"),
)


def redact_text(value: str) -> str:
    clean = value[:4096]
    for pattern, replacement in PATTERNS:
        clean = pattern.sub(replacement, clean)
    if len(value) > 4096:
        clean += "[truncated]"
    return clean


def redact(value: object) -> object:
    if isinstance(value, Mapping):
        clean: dict[str, object] = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            folded = key.replace("_", "").replace("-", "").casefold()
            if folded in EXCLUDED_CONTENT_KEYS:
                clean[key] = "[excluded-user-content]"
            elif folded in SECRET_KEYS or folded in IDENTIFIER_KEYS:
                clean[key] = "[redacted]"
            else:
                clean[key] = redact(child)
        return clean
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return deepcopy(value)


def assert_no_forbidden_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            folded = str(raw_key).replace("_", "").replace("-", "").casefold()
            if folded in EXCLUDED_CONTENT_KEYS or folded in SECRET_KEYS:
                raise ValueError(f"forbidden content field: {raw_key}")
            assert_no_forbidden_keys(child)
    elif isinstance(value, (list, tuple)):
        for item in value:
            assert_no_forbidden_keys(item)
