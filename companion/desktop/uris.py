# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which URIs may be opened, and what "the same URI" means afterwards.

Opening a URI hands a string to whatever program the desktop has registered for
its scheme, and that program will do what the string says. So this module's job
is to make the set of strings that can get that far as small as it can be, and
to make the *comparison* that binds an approval exact.

**The scheme allowlist is positive and total.** Four schemes, named in
:data:`ALLOWED_SCHEMES`; everything else is refused, including every scheme
nobody has thought of. A denylist here would be the wrong shape: ``javascript``
and ``data`` are the two everyone remembers, and the one that matters is the
handler somebody installs next year.

**The scheme is taken from the string, not from a claim about it.** A caller
states the scheme it expects and the parse must agree; a mismatch is a refusal
rather than a correction. That check is what catches the case where a
presentation layer showed one thing and the opener received another.

**Normalisation happens before the approval is built, not after.** What is
shown to a user, what is digested into the binding, and what is handed to the
adapter are one string produced once. The alternative — normalising on the way
to the backend — means the user approved a URI that was never opened and a URI
was opened that nobody approved, which is a difference no audit can see.

Three specific refusals worth naming, each of which is a real trick:

* **credentials in the authority.** ``https://user:token@host/`` is a URI whose
  effect is to authenticate. §4.8 forbids opening one automatically and §13
  forbids storing it, so it is refused outright rather than stripped — stripping
  would open a *different* URI from the one that was proposed.
* **whitespace and control characters inside the scheme.** ``java\\tscript:`` and
  ``java\\nscript:`` are parsed as ``javascript:`` by some handlers and as a
  relative path by others. Any control character anywhere in the string is a
  refusal; there is no legitimate URI that needs one, because they are supposed
  to be percent-encoded.
* **an empty or wildcard host.** ``https:///path`` and ``http://`` have no
  destination to bind an approval to.

Redirects are outside this module's reach and inside its contract:
:func:`destination_class` and :func:`normalise` describe the URI that was
approved, and a handler that follows a redirect has gone somewhere nobody
approved. That is stated in the descriptor's limitations and is why the result
of opening a URI is never ``confirmed``.
"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from .errors import DesktopRefused

__all__ = [
    "ALLOWED_SCHEMES",
    "DESTINATION_CLASSES",
    "MAX_URI_LENGTH",
    "ParsedUri",
    "destination_class",
    "parse_uri",
]

#: §4.8's four. Positive, total, and short. Adding one is a decision somebody
#: has to make in this file, which is the point.
ALLOWED_SCHEMES: tuple[str, ...] = ("https", "http", "mailto", "file")

#: What kind of place a URI leads to. Bound into the approval alongside the URI
#: itself so that a change of *kind* — a web page becoming a local file — is
#: caught even in the impossible case where the strings compared equal.
DESTINATION_CLASSES = ("web", "mail", "local-file")

#: Long enough for a real deep link, short enough that a megabyte of query
#: string cannot be smuggled past a person reading an approval prompt.
MAX_URI_LENGTH = 2048

#: mailto parameters that some clients act on rather than merely pre-fill.
#: ``attach`` is the dangerous one: a composer that honours it attaches a local
#: file the user never chose, which turns "open a composer" into "disclose a
#: file". Refused rather than dropped, for the same reason credentials are.
_MAILTO_FORBIDDEN_PARAMETERS = frozenset({"attach", "attachment", "x-attach"})

#: mailto parameters that only ever pre-fill a visible field.
_MAILTO_ALLOWED_PARAMETERS = frozenset({"subject", "body", "cc", "bcc", "to", "in-reply-to"})

#: Anything in the C0 or C1 ranges, plus the space and the delete character. A
#: URI containing one of these has either been assembled wrongly or is trying
#: to be parsed twice, differently.
_CONTROL = re.compile(r"[\x00-\x20\x7f-\x9f]")

#: A conservative reading of RFC 3986's ``scheme`` production. Matched against
#: the *raw* prefix of the string rather than against a parser's opinion, so
#: that a scheme a parser would have normalised is seen as it was written.
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):")

#: Hosts that are syntactically fine and are not destinations.
_EMPTY_HOSTS = frozenset({"", ".", ".."})


@dataclass(frozen=True)
class ParsedUri:
    """One URI, fully parsed, normalised once, and safe to compare.

    ``normalised`` is the only form that travels: it is what a user is shown,
    what the binding digests, and what the adapter opens. ``display`` is the
    same string with any query removed, because §13 forbids putting private
    query parameters into a log line and a presentation layer that had to
    remember to do that would eventually forget.
    """

    normalised: str
    scheme: str
    destination_class: str
    #: The host for web URIs, the domain for mailto, empty for file.
    host: str = ""
    #: The absolute local path for ``file:``; empty otherwise.
    path: str = ""
    #: ``True`` when a query string was present. The *fact* is recorded because
    #: it changes what an approval means; the contents are not, because §13
    #: says a query can carry a token and a log line lasts longer than one.
    has_query: bool = False

    @property
    def display(self) -> str:
        """The form safe to write into a diagnostic record."""
        if not self.has_query:
            return self.normalised
        head, _, _ = self.normalised.partition("?")
        return head + "?…"

    def to_json(self) -> dict[str, Any]:
        return {
            "uri": self.normalised,
            "scheme": self.scheme,
            "destinationClass": self.destination_class,
            "host": self.host,
            "path": self.path,
            "hasQuery": self.has_query,
        }


def destination_class(scheme: str) -> str:
    if scheme in ("https", "http"):
        return "web"
    if scheme == "mailto":
        return "mail"
    if scheme == "file":
        return "local-file"
    raise DesktopRefused(f"{scheme!r} is not an allowlisted URI scheme")


def _refuse(reason: str) -> "DesktopRefused":
    return DesktopRefused(f"the URI was refused: {reason}")


def _raw_scheme(value: str) -> str:
    """The scheme as written, before any parser has had an opinion about it.

    Read here rather than from :func:`urllib.parse.urlsplit` because that
    function lowercases, strips leading control characters and tolerates
    embedded tabs and newlines — all of which are *normalisations*, and a
    normalisation applied before the allowlist check is a way past it.
    """
    match = _SCHEME.match(value)
    if match is None:
        raise _refuse("it has no scheme; only absolute URIs from the allowlist may be opened")
    return match.group(1).lower()


def _check_host(host: str) -> str:
    lowered = host.lower()
    if lowered in _EMPTY_HOSTS:
        raise _refuse("it names no host, so there is no destination to approve")
    if "*" in lowered:
        raise _refuse("a host containing a wildcard is not a destination")
    # An IP literal is allowed and is normalised to its canonical form, so that
    # 127.0.0.1, 127.1 and 0177.0.0.1 cannot be three approvals for one place.
    try:
        return str(ipaddress.ip_address(lowered.strip("[]")))
    except ValueError:
        pass
    try:
        # IDNA, so that a Unicode host and its punycode are one destination and
        # a homograph cannot be approved as if it were a different site.
        encoded = lowered.encode("idna").decode("ascii")
    except (UnicodeError, UnicodeDecodeError):
        raise _refuse("its host is not a valid domain name") from None
    return encoded


def _normalise_path(path: str) -> str:
    """Resolve ``.`` and ``..`` inside a URI path, keeping percent-encoding.

    Done on the *encoded* form. Decoding first and re-encoding afterwards would
    turn ``%2e%2e%2f`` into a traversal that this function then resolves, which
    is the encoding confusion the whole exercise is meant to avoid: a segment
    that arrived percent-encoded stays one segment.
    """
    segments: list[str] = []
    for segment in path.split("/"):
        if segment == "." or (segment == "" and segments):
            continue
        if segment == "..":
            if segments:
                segments.pop()
            continue
        segments.append(segment)
    resolved = "/".join(segments)
    if path.startswith("/") and not resolved.startswith("/"):
        resolved = "/" + resolved.lstrip("/")
    if path.endswith("/") and not resolved.endswith("/") and resolved not in ("", "/"):
        resolved += "/"
    return resolved or "/"


def _parse_web(value: str, scheme: str) -> ParsedUri:
    parts = urlsplit(value)
    if parts.username is not None or parts.password is not None:
        # Refused, not stripped. Stripping would open a different URI from the
        # one proposed, and the proposal is what a person would have approved.
        raise _refuse(
            "it carries credentials in its authority; §4.8 forbids automatically "
            "authenticating and the URI is refused rather than rewritten"
        )
    host = _check_host(parts.hostname or "")
    port = parts.port
    if port is not None and not 1 <= port <= 65535:
        raise _refuse("its port is outside the valid range")
    default_port = 443 if scheme == "https" else 80
    authority = host if port in (None, default_port) else f"{host}:{port}"
    path = _normalise_path(parts.path or "/")
    # The fragment is dropped: it never reaches a server, it is not part of the
    # destination, and keeping it would make two approvals for one place.
    normalised = urlunsplit((scheme, authority, path, parts.query, ""))
    return ParsedUri(
        normalised=normalised,
        scheme=scheme,
        destination_class="web",
        host=host,
        has_query=bool(parts.query),
    )


def _parse_mailto(value: str) -> ParsedUri:
    body = value[len("mailto:"):]
    address, _, query = body.partition("?")
    address = unquote(address).strip()
    if not address:
        raise _refuse("it names no recipient")
    if "," in address or ";" in address:
        raise _refuse(
            "it names more than one recipient; a composer opened for several people is "
            "a disclosure a single approval cannot describe"
        )
    local, separator, domain = address.rpartition("@")
    if not separator or not local or not domain:
        raise _refuse("its recipient is not an address")
    domain = _check_host(domain)

    parameters: list[tuple[str, str]] = []
    if query:
        for item in query.split("&"):
            if not item:
                continue
            name, _, raw = item.partition("=")
            lowered = unquote(name).strip().lower()
            if lowered in _MAILTO_FORBIDDEN_PARAMETERS:
                raise _refuse(
                    f"it carries a {lowered!r} parameter, which attaches a local file to a "
                    "message; opening a composer is approved here and disclosing a file is not"
                )
            if lowered not in _MAILTO_ALLOWED_PARAMETERS:
                raise _refuse(f"it carries an unrecognised parameter {lowered!r}")
            parameters.append((lowered, raw))
    parameters.sort()
    rebuilt = f"mailto:{quote(local, safe='')}@{domain}"
    if parameters:
        rebuilt += "?" + "&".join(f"{name}={raw}" for name, raw in parameters)
    return ParsedUri(
        normalised=rebuilt,
        scheme="mailto",
        destination_class="mail",
        host=domain,
        has_query=bool(parameters),
    )


def _parse_file(value: str) -> ParsedUri:
    parts = urlsplit(value)
    if parts.netloc and parts.netloc.lower() != "localhost":
        raise _refuse(
            f"it names host {parts.netloc!r}; a file URI may only refer to this machine"
        )
    if parts.query or parts.fragment:
        raise _refuse("a file URI carries no query or fragment")
    path = unquote(parts.path or "")
    if not path.startswith("/"):
        raise _refuse("its path is not absolute")
    if "\x00" in path:
        raise _refuse("its path contains a null byte")
    # Left unresolved here on purpose. Whether this path is *approved* is a
    # filesystem question with symlinks in it, and it is answered by
    # companion.desktop.paths against the task's approved roots — not by string
    # inspection, which is how a traversal gets past a check that looked right.
    return ParsedUri(
        normalised="file://" + quote(path, safe="/"),
        scheme="file",
        destination_class="local-file",
        path=path,
    )


def parse_uri(value: str, *, expected_scheme: str = "") -> ParsedUri:
    """Parse, check and normalise a URI, or refuse it and say why.

    ``expected_scheme`` is the caller's statement of what it believes it has.
    Checked rather than trusted, and checked *after* the allowlist so that a
    caller stating ``javascript`` is refused for the scheme rather than for the
    disagreement — the first is the security answer and the second would read
    like a typo.
    """
    if not isinstance(value, str):
        raise _refuse("it is not a string")
    if not value:
        raise _refuse("it is empty")
    if len(value) > MAX_URI_LENGTH:
        raise _refuse(
            f"it is {len(value)} characters against a limit of {MAX_URI_LENGTH}; a URI too "
            "long to read is a URI nobody can approve"
        )
    control = _CONTROL.search(value)
    if control is not None:
        raise _refuse(
            f"it contains the control character {control.group(0)!r} at position "
            f"{control.start()}; two parsers disagree about such a string and the one that "
            "matters is the handler's"
        )

    scheme = _raw_scheme(value)
    if scheme not in ALLOWED_SCHEMES:
        raise _refuse(
            f"the scheme {scheme!r} is not allowlisted; this build opens only "
            f"{', '.join(ALLOWED_SCHEMES)}"
        )
    if expected_scheme and expected_scheme.lower() != scheme:
        raise _refuse(
            f"it was presented as {expected_scheme!r} and parses as {scheme!r}; the string "
            "shown and the string opened must be the same string"
        )

    if scheme in ("https", "http"):
        return _parse_web(value, scheme)
    if scheme == "mailto":
        return _parse_mailto(value)
    return _parse_file(value)
