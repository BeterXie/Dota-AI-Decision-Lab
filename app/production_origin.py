from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit, urlunsplit

import httpx


@dataclass(frozen=True, slots=True)
class OriginCheck:
    name: str
    passed: bool
    detail: str


def verify_origin(base_url: str, *, client: httpx.Client | None = None) -> list[OriginCheck]:
    base = base_url.rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname:
        return [OriginCheck("canonical_https", False, "base URL must be an HTTPS origin")]

    owns_client = client is None
    http = client or httpx.Client(
        timeout=10.0,
        follow_redirects=False,
        headers={"User-Agent": "DotaScope-Production-Origin-Check/1.0"},
    )
    checks: list[OriginCheck] = []
    try:
        root = _get(http, f"{base}/")
        checks.append(_status_check("apex_home", root, {200}))
        if root is not None:
            canonical = f'<link rel="canonical" href="{base}/" />'
            checks.append(
                OriginCheck(
                    "canonical_metadata",
                    canonical in root.text,
                    "canonical tag matches production origin"
                    if canonical in root.text
                    else f"missing canonical tag for {base}/",
                )
            )
            checks.append(
                OriginCheck(
                    "public_brand",
                    "DotaScope" in root.text,
                    "DotaScope is present in the public HTML"
                    if "DotaScope" in root.text
                    else "DotaScope is missing from public HTML",
                )
            )

        robots = _get(http, f"{base}/robots.txt")
        checks.append(_status_check("robots", robots, {200}))
        if robots is not None:
            sitemap_line = f"Sitemap: {base}/sitemap.xml"
            checks.append(
                OriginCheck(
                    "robots_sitemap",
                    sitemap_line in robots.text,
                    "robots.txt points to the canonical sitemap"
                    if sitemap_line in robots.text
                    else f"robots.txt is missing {sitemap_line}",
                )
            )

        sitemap = _get(http, f"{base}/sitemap.xml")
        checks.append(_status_check("sitemap", sitemap, {200}))
        if sitemap is not None:
            loc = f"<loc>{base}/</loc>"
            checks.append(
                OriginCheck(
                    "sitemap_origin",
                    loc in sitemap.text,
                    "sitemap contains the canonical root"
                    if loc in sitemap.text
                    else f"sitemap is missing {loc}",
                )
            )

        health = _get(http, f"{base}/health")
        checks.append(_status_check("health", health, {200}))

        for path in ("/ready", "/metrics"):
            response = _get(http, f"{base}{path}")
            checks.append(_status_check(f"private_{path[1:]}", response, {403, 404}))

        www_origin = _www_origin(parsed)
        www = _get(http, f"{www_origin}/")
        checks.append(_redirect_check("www_redirect", www, f"{base}/"))

        insecure_origin = urlunsplit(("http", parsed.netloc, "", "", ""))
        insecure = _get(http, f"{insecure_origin}/")
        checks.append(_redirect_check("http_redirect", insecure, f"{base}/"))
    finally:
        if owns_client:
            http.close()
    return checks


def _get(client: httpx.Client, url: str) -> httpx.Response | None:
    try:
        return client.get(url)
    except httpx.HTTPError:
        return None


def _status_check(
    name: str,
    response: httpx.Response | None,
    accepted: set[int],
) -> OriginCheck:
    if response is None:
        return OriginCheck(name, False, "request failed")
    passed = response.status_code in accepted
    return OriginCheck(
        name,
        passed,
        f"HTTP {response.status_code}; expected one of {sorted(accepted)}",
    )


def _redirect_check(
    name: str,
    response: httpx.Response | None,
    expected_location: str,
) -> OriginCheck:
    if response is None:
        return OriginCheck(name, False, "request failed")
    location = response.headers.get("location", "")
    passed = response.status_code in {301, 308} and location == expected_location
    return OriginCheck(
        name,
        passed,
        f"HTTP {response.status_code}; location={location or '<missing>'}; "
        f"expected permanent redirect to {expected_location}",
    )


def _www_origin(parsed: SplitResult) -> str:
    hostname = parsed.hostname or ""
    if hostname.startswith("www."):
        hostname = hostname[4:]
    port = f":{parsed.port}" if parsed.port else ""
    return f"https://www.{hostname}{port}"
