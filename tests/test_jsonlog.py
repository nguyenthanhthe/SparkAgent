import json
import logging
import unittest

from kernel.correlation import trace
from kernel.jsonlog import (JsonFormatter, looks_like_json_log,
                            use_json_logging)
from kernel.logging import setup_logging


class CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(self.format(record))


class JsonLoggingTests(unittest.TestCase):
    def make_logger(self):
        logger = logging.getLogger("sparkagent.jsonlog.test")
        logger.handlers.clear()
        logger.propagate = False
        logger.setLevel(logging.INFO)
        capture = CaptureHandler()
        capture.setFormatter(JsonFormatter())
        logger.addHandler(capture)
        return logger, capture

    def test_basic_shape(self):
        logger, capture = self.make_logger()
        logger.info("hello %s", "world")
        payload = json.loads(capture.records[0])
        self.assertEqual(payload["message"], "hello world")
        self.assertEqual(payload["level"], "info")
        self.assertEqual(payload["logger"], "sparkagent.jsonlog.test")
        self.assertIn("ts", payload)

    def test_trace_id_included_inside_span(self):
        logger, capture = self.make_logger()
        with trace("episode") as span:
            logger.info("inside a span")
        payload = json.loads(capture.records[0])
        self.assertEqual(payload["trace_id"], span.trace_id)
        self.assertEqual(payload["span"], "episode")

    def test_no_trace_id_outside_span(self):
        logger, capture = self.make_logger()
        logger.info("no span here")
        payload = json.loads(capture.records[0])
        self.assertNotIn("trace_id", payload)

    def test_exception_serialized(self):
        logger, capture = self.make_logger()
        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("it failed")
        payload = json.loads(capture.records[0])
        self.assertIn("ValueError: boom", payload["exception"])

    def test_extra_fields_merged(self):
        logger, capture = self.make_logger()
        capture.setFormatter(JsonFormatter({"service": "sparkagent"}))
        logger.info("msg")
        payload = json.loads(capture.records[0])
        self.assertEqual(payload["service"], "sparkagent")

    def test_structured_extra_attribute(self):
        logger, capture = self.make_logger()
        logger.info("with extras", extra={"episode_id": 7})
        payload = json.loads(capture.records[0])
        self.assertEqual(payload["episode_id"], 7)

    def test_line_classifier(self):
        self.assertTrue(looks_like_json_log(
            '{"ts": "2026-10-24", "message": "x", "level": "info"}'))
        self.assertFalse(looks_like_json_log("2026-10-24 INFO plain line"))
        self.assertFalse(looks_like_json_log('{"no": "message key"}'))

    def test_use_json_logging_swaps_console_handler(self):
        import io
        logger = logging.getLogger("sparkagent.jsonlog.swap")
        logger.handlers.clear()
        logger.propagate = False
        logger.setLevel(logging.INFO)
        stream = io.StringIO()
        console = logging.StreamHandler(stream)
        console.setFormatter(logging.Formatter("plain %(message)s"))
        logger.addHandler(console)
        use_json_logging(logger)
        logger.info("json please")
        self.assertTrue(looks_like_json_log(stream.getvalue().strip()))


if __name__ == "__main__":
    unittest.main()
