import httpx

from app.production_origin import verify_origin


def test_production_origin_verifier_accepts_safe_dotascope_edge() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://dotascope.com/":
            return httpx.Response(
                200,
                text=(
                    '<html><head><link rel="canonical" '
                    'href="https://dotascope.com/" /></head><body>DotaScope</body></html>'
                ),
            )
        if url == "https://dotascope.com/robots.txt":
            return httpx.Response(
                200,
                text="Sitemap: https://dotascope.com/sitemap.xml\n",
            )
        if url == "https://dotascope.com/sitemap.xml":
            return httpx.Response(
                200,
                text="<urlset><url><loc>https://dotascope.com/</loc></url></urlset>",
            )
        if url == "https://dotascope.com/health":
            return httpx.Response(200, json={"status": "ok"})
        if url in {"https://dotascope.com/ready", "https://dotascope.com/metrics"}:
            return httpx.Response(404)
        if url in {"https://www.dotascope.com/", "http://dotascope.com/"}:
            return httpx.Response(
                308,
                headers={"Location": "https://dotascope.com/"},
            )
        return httpx.Response(500)

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    )
    checks = verify_origin("https://dotascope.com", client=client)
    client.close()

    assert checks
    assert all(check.passed for check in checks), [
        (check.name, check.detail) for check in checks if not check.passed
    ]


def test_production_origin_verifier_rejects_non_https_origin() -> None:
    checks = verify_origin("http://dotascope.com")

    assert len(checks) == 1
    assert checks[0].name == "canonical_https"
    assert checks[0].passed is False


def test_production_origin_verifier_rejects_public_diagnostics() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://dotascope.com/":
            return httpx.Response(
                200,
                text=('<link rel="canonical" href="https://dotascope.com/" />DotaScope'),
            )
        if url == "https://dotascope.com/robots.txt":
            return httpx.Response(200, text="Sitemap: https://dotascope.com/sitemap.xml")
        if url == "https://dotascope.com/sitemap.xml":
            return httpx.Response(200, text="<loc>https://dotascope.com/</loc>")
        if url == "https://dotascope.com/health":
            return httpx.Response(200)
        if url in {"https://dotascope.com/ready", "https://dotascope.com/metrics"}:
            return httpx.Response(200, text="sensitive diagnostics")
        if url in {"https://www.dotascope.com/", "http://dotascope.com/"}:
            return httpx.Response(308, headers={"Location": "https://dotascope.com/"})
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    checks = verify_origin("https://dotascope.com", client=client)
    client.close()

    failed_names = {check.name for check in checks if not check.passed}
    assert failed_names == {"private_ready", "private_metrics"}
