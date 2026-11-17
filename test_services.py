"""Tests against real services on local ports. Run with: python3 -m unittest -v"""
import contextlib
import io
import unittest

import checkout_service
import payment_service
from common import TRACE_HEADER, http


class ServicesTest(unittest.TestCase):
    def setUp(self):
        self.out = io.StringIO()
        quiet = contextlib.redirect_stdout(self.out)
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        self.pay_srv, self.pay = payment_service.start(0)
        self.pay_url = f"http://127.0.0.1:{self.pay_srv.server_port}"
        self.co_srv, self.metrics = checkout_service.start(0, self.pay_url, timeout=0.3)
        self.co_url = f"http://127.0.0.1:{self.co_srv.server_port}"
        self.addCleanup(self.pay_srv.shutdown)
        self.addCleanup(self.co_srv.shutdown)

    def checkout(self, **headers):
        return http("POST", self.co_url + "/checkout", {"order_id": "ORD-1", "amount": 5},
                    headers=headers)

    def delay(self, seconds):
        http("POST", self.pay_url + "/admin/delay", {"seconds": seconds})

    def test_successful_checkout(self):
        status, body = self.checkout()
        self.assertEqual((status, body["status"]), (200, "confirmed"))
        m = self.metrics.snapshot()
        self.assertEqual((m["success_count"], m["failure_count"]), (1, 0))

    def test_trace_id_is_shared_by_both_services(self):
        _, body = self.checkout(**{TRACE_HEADER: "trace-abc"})
        self.assertEqual(body["trace_id"], "trace-abc")
        logs = self.out.getvalue()
        self.assertIn("[checkout] trace_id=trace-abc", logs)
        self.assertIn("[payment] trace_id=trace-abc", logs)

    def test_timeout_is_detected_and_service_keeps_running(self):
        self.delay(1.0)
        status, body = self.checkout()
        self.assertEqual(status, 504)
        self.assertIn("TIMEOUT", body["error"])
        self.assertLess(body["latency_ms"], 900)          # gave up at the timeout, not after 1s
        self.assertEqual(http("GET", self.co_url + "/health")[0], 200)
        self.assertEqual(self.metrics.snapshot()["failure_count"], 1)

    def test_recovery_after_delay_removed(self):
        self.delay(1.0)
        self.checkout()
        self.delay(0)
        for _ in range(5):
            self.assertEqual(self.checkout()[0], 200)
        m = self.metrics.snapshot()
        self.assertEqual((m["success_count"], m["failure_count"]), (5, 1))
        self.assertLess(m["error_rate_pct"], 100)
        self.assertEqual(m["recent_error_rate_pct"], 0.0)
        self.assertLess(m["last_latency_ms"], 300)


if __name__ == "__main__":
    unittest.main()
