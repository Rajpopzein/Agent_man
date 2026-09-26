import ipaddress
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)

from app.core.permissions import Permission, require

MAX_RESPONSE_BYTES = 250_000
USER_AGENT = "AgentMan/0.1 (+local autonomous runtime)"


def _validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only public http/https URLs are allowed")
    if not parsed.hostname:
        raise ValueError("URL must include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("Credentials in URLs are not allowed")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".local"):
        raise ValueError("Local network destinations are blocked")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host: {hostname}") from exc

    if not addresses:
        raise ValueError(f"Could not resolve host: {hostname}")

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError(
                f"Blocked non-public destination: {hostname} ({ip})"
            )
    return url


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        target = urljoin(req.full_url, newurl)
        _validate_public_url(target)
        return super().redirect_request(
            req,
            fp,
            code,
            msg,
            headers,
            target,
        )


class InternetClient:
    def get(
        self,
        url: str,
        approvals: set[str] | None = None,
    ) -> dict[str, object]:
        require(Permission.NETWORK_ACCESS, approvals)
        safe_url = _validate_public_url(url)

        request = Request(
            safe_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": (
                    "text/html,application/json,text/plain,"
                    "application/xml,text/xml;q=0.9,*/*;q=0.2"
                ),
            },
            method="GET",
        )
        opener = build_opener(_SafeRedirectHandler())

        try:
            with opener.open(request, timeout=20) as response:
                content_type = (
                    response.headers.get_content_type()
                    or "application/octet-stream"
                )
                textual = (
                    content_type.startswith("text/")
                    or content_type
                    in {
                        "application/json",
                        "application/xml",
                        "application/javascript",
                        "application/xhtml+xml",
                    }
                )
                if not textual:
                    raise ValueError(
                        f"Binary internet content is not exposed to agents: "
                        f"{content_type}"
                    )

                raw = response.read(MAX_RESPONSE_BYTES + 1)
                truncated = len(raw) > MAX_RESPONSE_BYTES
                raw = raw[:MAX_RESPONSE_BYTES]
                charset = (
                    response.headers.get_content_charset()
                    or "utf-8"
                )
                text = raw.decode(
                    charset,
                    errors="replace",
                )
                return {
                    "url": response.geturl(),
                    "status": response.status,
                    "content_type": content_type,
                    "truncated": truncated,
                    "text": text,
                }
        except HTTPError as exc:
            detail = exc.read(2048).decode(
                "utf-8",
                errors="replace",
            )
            raise RuntimeError(
                f"Internet request returned HTTP {exc.code}: "
                f"{detail[:1000]}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(
                f"Internet request failed: {exc.reason}"
            ) from exc


internet = InternetClient()
