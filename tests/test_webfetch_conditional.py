"""Conditional GET — ETag/If-None-Match with 304 short-circuit."""

import contextlib
import unittest

from tools.webfetch import WebFetcher


class FakeContent:
    def __init__(self, body: bytes):
        self._body = body

    async def read(self, _limit):
        return self._body


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200, etag: str | None = None):
        self.status = status
        self.headers = {"Content-Type": "text/html"}
        if etag:
            self.headers["ETag"] = etag
        self.content = FakeContent(body)

    def get_encoding(self):
        return "utf-8"


class FakeSession:
    def __init__(self):
        self.responses: list[FakeResponse] = []
        self.requests: list[dict] = []
        self.closed = False

    def push(self, response: FakeResponse) -> None:
        self.responses.append(response)

    def get(self, url, allow_redirects=False, headers=None):
        self.requests.append({"url": url, "headers": headers or {}})
        response = self.responses.pop(0)

        @contextlib.asynccontextmanager
        async def cm():
            yield response
        return cm()


def make_fetcher(session: FakeSession) -> WebFetcher:
    fetcher = WebFetcher(allowed_ports=[80, 443], max_chars=6000)
    fetcher._session = session
    return fetcher


PAGE = "<p>stable docs page about gardening</p>"


class ConditionalGetTests(unittest.IsolatedAsyncioTestCase):
    async def test_revalidation_sends_if_none_match(self):
        session = FakeSession()
        session.push(FakeResponse(PAGE.encode(), etag='"v1"'))
        session.push(FakeResponse(b"", status=304))
        fetcher = make_fetcher(session)
        url = "http://8.8.8.8/page"

        first = await fetcher.fetch(url)
        self.assertEqual(first["status"], 200)
        second = await fetcher.fetch(url)

        self.assertEqual(session.requests[1]["headers"].get("If-None-Match"),
                         '"v1"')
        self.assertTrue(second["not_modified"])
        self.assertEqual(second["text"], first["text"])
        self.assertEqual(fetcher.cache_hits, 1)

    async def test_changed_content_updates_cache(self):
        session = FakeSession()
        session.push(FakeResponse(PAGE.encode(), etag='"v1"'))
        session.push(FakeResponse(b"", status=304))
        session.push(FakeResponse("<p>new content</p>".encode(),
                                  etag='"v2"'))
        session.push(FakeResponse(b"", status=304))
        fetcher = make_fetcher(session)
        url = "http://8.8.8.8/page"

        await fetcher.fetch(url)
        await fetcher.fetch(url)                      # 304 on v1
        changed = await fetcher.fetch(url)            # server returns new body
        self.assertFalse(changed.get("not_modified", False))
        self.assertIn("new content", changed["text"])

        again = await fetcher.fetch(url)              # 304 on v2
        self.assertTrue(again["not_modified"])
        self.assertIn("new content", again["text"])
        self.assertEqual(session.requests[3]["headers"].get("If-None-Match"),
                         '"v2"')

    async def test_no_etag_never_conditional(self):
        session = FakeSession()
        session.push(FakeResponse(PAGE.encode()))
        session.push(FakeResponse(PAGE.encode()))
        fetcher = make_fetcher(session)
        url = "http://8.8.8.8/page"
        await fetcher.fetch(url)
        await fetcher.fetch(url)
        self.assertNotIn("If-None-Match", session.requests[1]["headers"])
        self.assertEqual(fetcher.cache_hits, 0)

    async def test_redirect_then_cache_key_is_final_url(self):
        session = FakeSession()
        redirect = FakeResponse(b"", status=302)
        redirect.headers["Location"] = "http://8.8.8.8/final"
        session.push(redirect)
        session.push(FakeResponse(PAGE.encode(), etag='"v1"'))
        # every fetch re-follows the redirect: second call needs it again
        session.push(redirect)
        session.push(FakeResponse(b"", status=304))
        fetcher = make_fetcher(session)
        await fetcher.fetch("http://8.8.8.8/start")

        # conditional check goes to the final URL, not the original
        second = await fetcher.fetch("http://8.8.8.8/start")
        self.assertTrue(second["not_modified"])
        self.assertEqual(session.requests[3]["url"], "http://8.8.8.8/final")
        self.assertEqual(session.requests[3]["headers"].get("If-None-Match"),
                         '"v1"')


if __name__ == "__main__":
    unittest.main()
