"""Web fetcher with a strict SSRF guard.

Policy (enforced on every request AND every redirect hop):

- Only ``http``/``https`` schemes.
- Only configured ports (default 80/443/8080/8443).
- The hostname is resolved *immediately before* connecting, and every
  resolved address must be public: loopback, private, link-local (including
  cloud metadata 169.254.169.254), reserved, multicast, unspecified,
  carrier-grade NAT (100.64/10), benchmarking (198.18/15) and IPv4-mapped
  IPv6 ranges are all rejected.
- Redirects are followed manually (max 3) with full re-validation.
- Responses are size-capped; HTML is converted to readable text.

DNS-rebinding residual risk is mitigated — not eliminated — by resolving
right before the connect on the same event loop tick. For hostile
multi-tenant environments put SparkAgent behind an egress proxy instead.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlsplit

import aiohttp

from kernel.logging import get_logger
from openshell.vault import SecretVault
from tools.registry import Tool, ToolContext, ToolRegistry

logger = get_logger("webfetch")

_EXTRA_BLOCKED_NETS = tuple(ipaddress.ip_network(n) for n in (
    "100.64.0.0/10",    # carrier-grade NAT
    "198.18.0.0/15",    # benchmarking
    "192.0.0.0/24",     # IETF protocol assignments
    "240.0.0.0/4",      # reserved (explicit, for older stdlib)
))

MAX_REDIRECTS = 3
USER_AGENT = "SparkAgent/0.1 (personal local agent)"


class BlockedURLError(Exception):
    pass


def _address_problem(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    for check, reason in (
        (address.is_loopback, "loopback"),
        (address.is_private, "private/internal"),
        (address.is_link_local, "link-local (includes cloud metadata)"),
        (address.is_reserved, "reserved"),
        (address.is_multicast, "multicast"),
        (address.is_unspecified, "unspecified"),
    ):
        if check:
            return reason
    for net in _EXTRA_BLOCKED_NETS:
        if address.version == net.version and address in net:
            return f"blocked range {net}"
    return None


def check_ip_literal(host: str) -> str | None:
    """If host is an IP literal, return a rejection reason or None."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return None
    return _address_problem(address)


def resolve_host(host: str) -> list[str]:
    """Blocking DNS resolution used by validate_url (run in a thread)."""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return sorted({info[4][0] for info in infos})


def validate_url(url: str, allowed_ports: set[int]) -> tuple[str, str, int]:
    """Validate scheme/host/port + resolved addresses.

    Returns the (url, hostname, port) triple; raises BlockedURLError.
    """
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        raise BlockedURLError(f"scheme {parts.scheme!r} is not allowed "
                              "(only http/https)")
    host = parts.hostname
    if not host:
        raise BlockedURLError("URL has no hostname")
    try:
        port = parts.port
    except ValueError as exc:
        raise BlockedURLError(f"invalid port in URL: {url}") from exc
    port = port or (443 if parts.scheme.lower() == "https" else 80)
    if port not in allowed_ports:
        raise BlockedURLError(f"port {port} is not in the allowed ports "
                              f"{sorted(allowed_ports)}")

    reason = check_ip_literal(host)
    if reason:
        raise BlockedURLError(f"host {host} is a blocked address ({reason})")
    for address in resolve_host(host):
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            raise BlockedURLError(f"unparseable resolved address {address!r}")
        problem = _address_problem(parsed)
        if problem:
            raise BlockedURLError(
                f"host {host} resolves to {address} ({problem}) — blocked")
    return url, host, port


# --------------------------------------------------------------- HTML to text
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]*\n[ \t]*\n[ \t]*")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>",
                              re.IGNORECASE | re.DOTALL)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def html_to_text(raw: str) -> tuple[str, str]:
    title_match = _TITLE_RE.search(raw)
    title = html_lib.unescape(title_match.group(1)).strip() if title_match else ""
    body = _SCRIPT_STYLE_RE.sub(" ", raw)
    body = _TAG_RE.sub(" ", body)
    body = html_lib.unescape(body)
    body = re.sub(r"[ \t]+", " ", body)
    body = _WS_RE.sub("\n", body)
    return title, body.strip()


class WebFetcher:
    def __init__(self, allowed_ports: list[int], max_bytes: int = 2097152,
                 timeout: float = 30.0, max_chars: int = 6000,
                 vault: SecretVault | None = None):
        self.allowed_ports = set(allowed_ports)
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.max_chars = max_chars
        self.vault = vault
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers={"User-Agent": USER_AGENT,
                         "Accept": "text/html,application/xhtml+xml,"
                                   "application/json;q=0.9,text/plain;q=0.8,*/*;q=0.5"})
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------ fetch
    async def fetch(self, url: str) -> dict[str, Any]:
        session = await self._ensure_session()
        current = url
        redirects = 0
        while True:
            await asyncio.to_thread(validate_url, current, self.allowed_ports)
            async with session.get(current, allow_redirects=False) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location")
                    if not location:
                        raise BlockedURLError(f"redirect without Location from {current}")
                    if redirects >= MAX_REDIRECTS:
                        raise BlockedURLError("too many redirects")
                    redirects += 1
                    current = urljoin(current, location)
                    logger.debug("webfetch redirect -> %s", current)
                    continue
                return await self._read_response(current, resp)

    async def _read_response(self, url: str,
                             resp: aiohttp.ClientResponse) -> dict[str, Any]:
        raw = await resp.content.read(self.max_bytes + 1)
        truncated = len(raw) > self.max_bytes
        if truncated:
            raw = raw[: self.max_bytes]
        try:
            charset = resp.get_encoding()
        except (LookupError, RuntimeError):
            charset = "utf-8"
        try:
            text = raw.decode(charset, errors="replace")
        except LookupError:
            text = raw.decode("utf-8", errors="replace")

        content_type = resp.headers.get("Content-Type", "")
        title = ""
        if "html" in content_type or "<html" in text[:512].lower():
            title, text = html_to_text(text)
        if truncated:
            text += "\n...[download truncated]"

        result: dict[str, Any] = {"url": url, "status": resp.status,
                                  "content_type": content_type.split(";")[0],
                                  "title": title, "text": text[: self.max_chars],
                                  "truncated": truncated or len(text) > self.max_chars}
        if self.vault is not None:
            result["text"] = self.vault.redact(result["text"])
            result["title"] = self.vault.redact(result["title"])
        return result


# ------------------------------------------------------------------- tool API
def register_tools(registry: ToolRegistry, fetcher: WebFetcher) -> None:
    async def web_fetch(ctx: ToolContext, url: str) -> dict[str, Any]:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("url must be a non-empty string")
        return await fetcher.fetch(url.strip())

    registry.register(Tool(
        name="web_fetch",
        description=("Fetch a public http(s) URL and return its readable text "
                     "(HTML is converted to plain text). Only public hosts on "
                     "ports 80/443/8080/8443 are reachable; internal addresses "
                     "are blocked. Use for research, docs, and public APIs."),
        parameters={"url": {"type": "string", "required": True,
                            "desc": "absolute http(s) URL to fetch"}},
        handler=web_fetch))
