"""Payment Service: charges an order. Called by the Checkout Service.

  python3 payment_service.py --port 8002

  POST /pay          {"order_id": "...", "amount": 25.0}   charge the order
  POST /admin/delay  {"seconds": 3}    add an artificial delay to every /pay (0 removes it)
  GET  /metrics      success/failure counts and latency
  GET  /health
"""
import argparse
import threading
import time
from http.server import ThreadingHTTPServer

from common import TRACE_HEADER, JSONHandler, Metrics, log

SERVICE = "payment"
WORK_SECONDS = 0.05     # normal time to "charge the card"


class PaymentState:
    def __init__(self):
        self.metrics = Metrics()
        self.delay = 0.0    # injected fault, in seconds


def make_handler(state):
    class Handler(JSONHandler):
        def do_GET(self):
            if self.path == "/metrics":
                return self.reply(200, {"service": SERVICE, "injected_delay_s": state.delay,
                                        **state.metrics.snapshot()})
            if self.path == "/health":
                return self.reply(200, {"service": SERVICE, "status": "ok"})
            self.reply(404, {"error": "not found"})

        def do_POST(self):
            if self.path == "/admin/delay":
                state.delay = float(self.body().get("seconds", 0))
                log(SERVICE, None, f"FAULT INJECTION delay set to {state.delay}s" if state.delay
                    else "FAULT INJECTION delay removed")
                return self.reply(200, {"injected_delay_s": state.delay})
            if self.path != "/pay":
                return self.reply(404, {"error": "not found"})

            trace_id = self.headers.get(TRACE_HEADER)   # same ID the Checkout Service logged
            order = self.body()
            start = time.perf_counter()
            log(SERVICE, trace_id, f"POST /pay received order_id={order.get('order_id')} "
                                   f"amount={order.get('amount')}")
            if state.delay:
                log(SERVICE, trace_id, f"SLOW: sleeping {state.delay}s (injected delay)")
                time.sleep(state.delay)
            time.sleep(WORK_SECONDS)
            latency = (time.perf_counter() - start) * 1000
            state.metrics.record(True, latency)
            log(SERVICE, trace_id, f"POST /pay completed status=200 latency_ms={latency:.0f}")
            self.reply(200, {"status": "paid", "order_id": order.get("order_id"),
                             "trace_id": trace_id})

    return Handler


def start(port):
    state = PaymentState()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, state


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8002)
    a = p.parse_args()
    start(a.port)
    log(SERVICE, None, f"listening on port {a.port}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
