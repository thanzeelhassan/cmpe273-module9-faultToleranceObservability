"""Checkout Service: processes an order by calling the Payment Service.

  python3 checkout_service.py --port 8001 --payment-url http://localhost:8002 --timeout 1.0

  POST /checkout  {"order_id": "...", "amount": 25.0}   process an order
  GET  /metrics   success/failure counts and latency
  GET  /health

Every checkout gets a trace ID. It is logged here, sent to the Payment Service in
the X-Trace-Id header, and returned to the client, so one ID follows the request
through both services.
"""
import argparse
import socket
import threading
import time
import urllib.error
import uuid
from http.server import ThreadingHTTPServer

from common import PAYMENT_URL, TRACE_HEADER, JSONHandler, Metrics, http, log

SERVICE = "checkout"


def is_timeout(error):
    reason = getattr(error, "reason", error)
    return isinstance(reason, (socket.timeout, TimeoutError))


def make_handler(metrics, payment_url, timeout):
    class Handler(JSONHandler):
        def do_GET(self):
            if self.path == "/metrics":
                return self.reply(200, {"service": SERVICE, "payment_timeout_s": timeout,
                                        **metrics.snapshot()})
            if self.path == "/health":
                return self.reply(200, {"service": SERVICE, "status": "ok"})
            self.reply(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/checkout":
                return self.reply(404, {"error": "not found"})

            trace_id = self.headers.get(TRACE_HEADER) or uuid.uuid4().hex[:8]
            order = self.body()
            start = time.perf_counter()
            elapsed = lambda: (time.perf_counter() - start) * 1000
            log(SERVICE, trace_id, f"POST /checkout received order_id={order.get('order_id')} "
                                   f"amount={order.get('amount')}")
            log(SERVICE, trace_id, f"calling payment service (timeout={timeout}s)")
            try:
                status, _ = http("POST", payment_url + "/pay", order,
                                 headers={TRACE_HEADER: trace_id}, timeout=timeout)
                error = None if status == 200 else f"payment service returned {status}"
                code = 200 if status == 200 else 502
            except (urllib.error.URLError, OSError) as e:
                if is_timeout(e):
                    error, code = f"payment service TIMEOUT after {timeout}s", 504
                else:
                    error, code = f"payment service unreachable ({e})", 502

            latency = elapsed()
            metrics.record(error is None, latency)
            if error:
                log(SERVICE, trace_id, f"ERROR {error}")
                log(SERVICE, trace_id, f"POST /checkout FAILED status={code} "
                                       f"latency_ms={latency:.0f}")
                return self.reply(code, {"status": "failed", "error": error,
                                         "order_id": order.get("order_id"), "trace_id": trace_id,
                                         "latency_ms": round(latency)})
            log(SERVICE, trace_id, f"payment service responded status=200")
            log(SERVICE, trace_id, f"POST /checkout completed status=200 latency_ms={latency:.0f}")
            self.reply(200, {"status": "confirmed", "order_id": order.get("order_id"),
                             "trace_id": trace_id, "latency_ms": round(latency)})

    return Handler


def start(port, payment_url, timeout):
    metrics = Metrics()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(metrics, payment_url, timeout))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, metrics


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8001)
    p.add_argument("--payment-url", default=PAYMENT_URL)
    p.add_argument("--timeout", type=float, default=1.0,
                   help="seconds to wait for the Payment Service")
    a = p.parse_args()
    start(a.port, a.payment_url, a.timeout)
    log(SERVICE, None, f"listening on port {a.port} (payment={a.payment_url}, "
                       f"timeout={a.timeout}s)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
