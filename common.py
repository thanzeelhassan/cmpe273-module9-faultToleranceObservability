"""Shared observability helpers: logging, metrics and a small HTTP layer."""
import json
import os
import threading
import urllib.request
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler

CHECKOUT_URL = os.getenv("CHECKOUT_URL", "http://localhost:8001")
PAYMENT_URL = os.getenv("PAYMENT_URL", "http://localhost:8002")
TRACE_HEADER = "X-Trace-Id"


def log(service, trace_id, message):
    """Request log line: 'HH:MM:SS.mmm [service] trace_id=<id> message'."""
    now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"{now} [{service}] trace_id={trace_id or '-'} {message}", flush=True)


class Metrics:
    """Success/failure counts and request latency, kept in memory.

    'recent' values cover only the last RECENT requests, so they show the
    current health of the service rather than its whole history.
    """
    RECENT = 5

    def __init__(self):
        self.lock = threading.Lock()
        self.success = 0
        self.failure = 0
        self.latencies = []
        self.recent = deque(maxlen=self.RECENT)   # (ok, latency_ms)

    def record(self, ok, latency_ms):
        with self.lock:
            if ok:
                self.success += 1
            else:
                self.failure += 1
            self.latencies.append(latency_ms)
            self.recent.append((ok, latency_ms))

    def snapshot(self):
        with self.lock:
            total = self.success + self.failure
            recent = list(self.recent)
            pct = lambda bad, n: round(100 * bad / n, 1) if n else 0.0
            avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else 0.0
            return {
                "requests_total": total,
                "success_count": self.success,
                "failure_count": self.failure,
                "error_rate_pct": pct(self.failure, total),
                "recent_error_rate_pct": pct(sum(not ok for ok, _ in recent), len(recent)),
                "last_latency_ms": round(self.latencies[-1], 1) if self.latencies else 0.0,
                "avg_latency_ms": avg(self.latencies),
                "recent_avg_latency_ms": avg([ms for _, ms in recent]),
                "max_latency_ms": round(max(self.latencies), 1) if self.latencies else 0.0,
            }


class JSONHandler(BaseHTTPRequestHandler):
    """Base handler with JSON helpers; the default access log is silenced."""

    def reply(self, code, body):
        data = json.dumps(body).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            pass    # the caller already gave up (e.g. it timed out)

    def body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

    def log_message(self, *args):
        pass


def http(method, url, body=None, headers=None, timeout=10):
    """Send a JSON request. Returns (status, json). Raises on timeout/connection error."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:      # 4xx/5xx still carry a JSON body
        return e.code, json.loads(e.read())
