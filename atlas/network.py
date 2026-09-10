"""Bounded public HTTP reads. Local sites require an explicit operator setting."""

import ipaddress
import os
import socket
from urllib.parse import urljoin, urlsplit

import httpx


def validate_url(url: str, *, resolve: bool = True) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or any(c in url for c in '\r\n\t"\\<>`')
        or any(ord(c) < 33 for c in url)
    ):
        raise ValueError("Expected an HTTP(S) URL without credentials or control characters")
    if parts.port is not None and not 1 <= parts.port <= 65535:
        raise ValueError("Invalid URL port")
    if resolve and os.getenv("ATLAS_ALLOW_PRIVATE_URLS", "false").lower() != "true":
        addresses = socket.getaddrinfo(parts.hostname, parts.port or 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError("Private, loopback and reserved network addresses are disabled")
    return url


def safe_get(url: str, *, timeout: float = 15, max_bytes: int = 2_000_000) -> httpx.Response:
    """Validate each redirect and cap decompressed response bytes."""
    with httpx.Client(
        timeout=timeout, follow_redirects=False, headers={"User-Agent": "AtlasSEOBot/1.0"}
    ) as client:
        for _ in range(6):
            validate_url(url)
            with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError(f"Response exceeds {max_bytes} bytes")
                    chunks.append(chunk)
                # Body is already decompressed; do not decode it a second time.
                headers = dict(response.headers)
                headers.pop("content-encoding", None)
                headers.pop("content-length", None)
                return httpx.Response(
                    response.status_code,
                    headers=headers,
                    content=b"".join(chunks),
                    request=response.request,
                )
    raise ValueError("Too many redirects")
