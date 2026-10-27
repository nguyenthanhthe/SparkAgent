"""web_fetch 304 drill demo: two rounds against a local server.

Runs a throwaway HTTP server that serves one page with a stable ETag,
then fetches it twice through the real WebFetcher: round one downloads
and caches the validator, round two sends If-None-Match and gets a 304
short-circuit (ADR-0008). The SSRF guard is bypassed *only* for this
demo's own loopback server — production fetches keep the guard.

    python examples/webfetch_304_demo.py
"""

import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.webfetch as webfetch   # noqa: E402
from tools.webfetch import WebFetcher   # noqa: E402

PAGE = ("<html><head><title>304 drill</title></head>"
        "<body>stable page served with a strong ETag</body></html>")
ETAG = '"demo-etag-v1"'


class DemoHandler(BaseHTTPRequestHandler):
    def do_GET(self):   # noqa: N802 — stdlib naming
        if self.headers.get("If-None-Match") == ETAG:
            self.send_response(304)
            self.end_headers()
            return
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("ETag", ETAG)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):   # silence the drill console
        pass


async def main() -> None:
    server = HTTPServer(("127.0.0.1", 0), DemoHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/"

    fetcher = WebFetcher(allowed_ports=[port], max_chars=2000)
    # demo-only: loopback is exactly the address the SSRF guard exists
    # to block; neutralize validation for our own throwaway server
    webfetch.validate_url = lambda u, ports: (u, "127.0.0.1", port)
    try:
        first = await fetcher.fetch(url)
        print(f"round 1  : status={first['status']} "
              f"not_modified={first.get('not_modified', False)}")
        print(f"         : {first['title']!r} · {first['text'][:50]}")

        second = await fetcher.fetch(url)
        print(f"round 2  : status=304 short-circuit, "
              f"not_modified={second.get('not_modified')}")
        print(f"         : text identical={second['text'] == first['text']}"
              f" · cache_hits={fetcher.cache_hits}")
    finally:
        await fetcher.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
