import unittest

from tools.webfetch import (BlockedURLError, check_ip_literal, html_to_text,
                            validate_url)

ALLOWED = {80, 443, 8080, 8443}


class IpLiteralTests(unittest.TestCase):
    def assert_blocked(self, host):
        reason = check_ip_literal(host)
        self.assertIsNotNone(reason, f"{host} should be blocked")

    def test_loopback(self):
        self.assert_blocked("127.0.0.1")
        self.assert_blocked("::1")

    def test_private_ranges(self):
        self.assert_blocked("10.0.0.1")
        self.assert_blocked("172.16.0.1")
        self.assert_blocked("192.168.1.1")
        self.assert_blocked("fd00::1")

    def test_cloud_metadata(self):
        self.assert_blocked("169.254.169.254")

    def test_cgnat_and_reserved(self):
        self.assert_blocked("100.64.0.1")
        self.assert_blocked("198.18.0.5")
        self.assert_blocked("240.0.0.1")
        self.assert_blocked("0.0.0.0")

    def test_ipv4_mapped_ipv6(self):
        self.assert_blocked("::ffff:127.0.0.1")
        self.assert_blocked("::ffff:192.168.0.1")

    def test_public_addresses_pass(self):
        self.assertIsNone(check_ip_literal("8.8.8.8"))
        self.assertIsNone(check_ip_literal("2606:4700:4700::1111"))


class UrlValidationTests(unittest.TestCase):
    def test_non_http_scheme_rejected(self):
        for url in ("file:///etc/passwd", "ftp://example.com/x",
                    "gopher://x", "javascript:alert(1)"):
            with self.assertRaises(BlockedURLError):
                validate_url(url, ALLOWED)

    def test_loopback_hostnames_rejected(self):
        for url in ("http://localhost/x", "http://127.0.0.1/x",
                    "http://[::1]/x", "https://127.0.0.1:443/x"):
            with self.assertRaises(BlockedURLError):
                validate_url(url, ALLOWED)

    def test_private_ip_url_rejected(self):
        with self.assertRaises(BlockedURLError):
            validate_url("http://192.168.1.10/admin", ALLOWED)

    def test_disallowed_port_rejected(self):
        with self.assertRaises(BlockedURLError):
            validate_url("http://8.8.8.8:22/", ALLOWED)
        with self.assertRaises(BlockedURLError):
            validate_url("http://8.8.8.8:9200/", ALLOWED)

    def test_no_hostname_rejected(self):
        with self.assertRaises(BlockedURLError):
            validate_url("http:///path", ALLOWED)

    def test_public_ip_allowed_port_passes(self):
        url, host, port = validate_url("http://8.8.8.8/", ALLOWED)  # literal, no DNS
        self.assertEqual((url, host, port), ("http://8.8.8.8/", "8.8.8.8", 80))
        validate_url("https://8.8.8.8/", ALLOWED)
        validate_url("http://8.8.8.8:8080/", ALLOWED)


class HtmlToTextTests(unittest.TestCase):
    def test_strips_scripts_and_tags(self):
        html = ("<html><head><title>T</title><script>evil()</script>"
                "<style>x{}</style></head><body><p>Hello &amp; welcome</p>"
                "</body></html>")
        title, text = html_to_text(html)
        self.assertEqual(title, "T")
        self.assertIn("Hello & welcome", text)
        self.assertNotIn("evil", text)
        self.assertNotIn("<", text)


if __name__ == "__main__":
    unittest.main()
