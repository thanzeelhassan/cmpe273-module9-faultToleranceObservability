"""Client for driving the demo.

  python3 client.py checkout [N]    place N orders through the Checkout Service (default 1)
  python3 client.py delay SECONDS   add a delay to the Payment Service (0 removes it)
  python3 client.py metrics         show metrics from both services
  python3 client.py health          check that both services are running
"""
import sys
import uuid

from common import CHECKOUT_URL, PAYMENT_URL, http

def checkout():
    order = {"order_id": f"ORD-{uuid.uuid4().hex[:6]}", "amount": 25.0}
    status, r = http("POST", CHECKOUT_URL + "/checkout", order)
    detail = f" error=\"{r['error']}\"" if status != 200 else ""
    print(f"[client] {order['order_id']} -> HTTP {status} status={r['status']} "
          f"trace_id={r['trace_id']} latency_ms={r['latency_ms']}{detail}", flush=True)


def metrics():
    for url in (CHECKOUT_URL, PAYMENT_URL):
        _, m = http("GET", url + "/metrics")
        print(f"[metrics] {m['service']:<8} requests={m['requests_total']} "
              f"success={m['success_count']} failure={m['failure_count']} "
              f"error_rate={m['error_rate_pct']}% "
              f"recent_error_rate={m['recent_error_rate_pct']}% | "
              f"latency_ms last={m['last_latency_ms']} avg={m['avg_latency_ms']} "
              f"recent_avg={m['recent_avg_latency_ms']} max={m['max_latency_ms']}", flush=True)


def health():
    for url in (CHECKOUT_URL, PAYMENT_URL):
        status, h = http("GET", url + "/health")
        print(f"[health] {h['service']:<8} HTTP {status} status={h['status']}", flush=True)


def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "checkout":
        for _ in range(int(argv[1]) if len(argv) > 1 else 1):
            checkout()
    elif cmd == "delay" and len(argv) == 2:
        _, r = http("POST", PAYMENT_URL + "/admin/delay", {"seconds": float(argv[1])})
        print(f"[client] payment service injected delay = {r['injected_delay_s']}s", flush=True)
    elif cmd == "metrics":
        metrics()
    elif cmd == "health":
        health()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
