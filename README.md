# Module 9 Assignment: Fault Tolerance & Observability

CMPE-273 – A small distributed application (Python, standard library only) that uses **logs, metrics, and request tracing** to diagnose a failure.

- **Checkout Service** (`checkout_service.py`, port 8001) processes an order and calls the Payment Service, with a **1 second timeout**.
- **Payment Service** (`payment_service.py`, port 8002) charges the order. A delay can be injected into it and removed again at runtime.
- The two services are **independent processes** that talk over HTTP.

## Architecture

```
               POST /checkout             POST /pay
 ┌────────┐   {order_id, amount}   ┌──────────────────┐  X-Trace-Id: <id>  ┌──────────────────┐
 │ Client │ ─────────────────────▶ │ Checkout  :8001  │ ─────────────────▶ │ Payment   :8002  │
 │        │ ◀───────────────────── │  creates trace ID│ ◀───────────────── │  optional delay  │
 └────────┘   200 confirmed /      │  timeout = 1s    │    200 paid        │  (injected fault)│
              504 failed           └──────────────────┘                    └──────────────────┘
                                     │ logs  │ GET /metrics                  │ logs  │ GET /metrics
                                     ▼       ▼                               ▼       ▼
                              checkout_service.log                    payment_service.log
                              success / failure count                 success / failure count
                              latency                                 latency
                                     └──────── same trace_id in both logs ───────┘
```

## Observability

| Signal | How it is recorded |
|---|---|
| Request logs | Each service logs every request when it is received and when it finishes, with status and `latency_ms` |
| Request latency | Measured per request in both services; `/metrics` reports last, average, recent average, and max |
| Success / failure count | `success_count`, `failure_count`, `error_rate_pct` on `GET /metrics` of each service |
| Trace ID | Checkout creates an 8-character `trace_id`, logs it, sends it to Payment in the `X-Trace-Id` header, and returns it to the client. Payment logs the same ID |

`recent_*` metrics cover only the last 5 requests, so they show the current health of the service; the plain values cover everything since the service started.

## Running it

Requirements: Python 3.9+. No dependencies to install.

### 1. Start both services (two terminals)

```bash
python3 payment_service.py --port 8002
python3 checkout_service.py --port 8001 --payment-url http://localhost:8002 --timeout 1.0
```

### 2. Use the client (third terminal)

```bash
python3 client.py checkout       # place one order (Checkout -> Payment)
python3 client.py checkout 6     # place six orders
python3 client.py metrics        # metrics from both services
python3 client.py health         # check that both services are running
```

### Reproduce the failure and recovery by hand

```bash
python3 client.py delay 3        # Payment now takes 3s, longer than Checkout's 1s timeout
python3 client.py checkout 3     # each one fails with HTTP 504
python3 client.py metrics        # error rate and latency go up
python3 client.py delay 0        # remove the delay
python3 client.py checkout 6     # requests succeed again
python3 client.py metrics
```

The same things with `curl`:

```bash
curl -X POST localhost:8001/checkout -d '{"order_id": "ORD-1", "amount": 25}'
curl -X POST localhost:8002/admin/delay -d '{"seconds": 3}'
curl localhost:8001/metrics
```

### Or run every scenario automatically

```bash
./scripts/run_demo.sh
```

This writes each service's own log (`logs/checkout_service.log`, `logs/payment_service.log`) and one file per scenario with the client output and metrics.

Run the tests:

```bash
python3 -m unittest -v
```

## Evidence

Full logs are in [`logs/`](logs/). Excerpts below. (Timestamps are `HH:MM:SS.mmm`.)

### 1. Successful request

One Checkout → Payment request ([`logs/1_successful_request.log`](logs/1_successful_request.log)):

```
[client] ORD-548651 -> HTTP 200 status=confirmed trace_id=826fa6a3 latency_ms=57
```

Searching both service logs for that trace ID (`grep 826fa6a3 logs/*_service.log`) shows the whole request, in order, across the two services:

```
18:37:17.149 [checkout] trace_id=826fa6a3 POST /checkout received order_id=ORD-548651 amount=25.0
18:37:17.149 [checkout] trace_id=826fa6a3 calling payment service (timeout=1.0s)
18:37:17.156 [payment] trace_id=826fa6a3 POST /pay received order_id=ORD-548651 amount=25.0
18:37:17.206 [payment] trace_id=826fa6a3 POST /pay completed status=200 latency_ms=50
18:37:17.207 [checkout] trace_id=826fa6a3 payment service responded status=200
18:37:17.207 [checkout] trace_id=826fa6a3 POST /checkout completed status=200 latency_ms=57
```

Metrics after the request:

```
[metrics] checkout requests=1 success=1 failure=0 error_rate=0.0% recent_error_rate=0.0% | latency_ms last=57.5 avg=57.5 recent_avg=57.5 max=57.5
[metrics] payment  requests=1 success=1 failure=0 error_rate=0.0% recent_error_rate=0.0% | latency_ms last=50.2 avg=50.2 recent_avg=50.2 max=50.2
```

### 2. Timeout failure

A 3 second delay is added to the Payment Service, which is longer than the Checkout Service's 1 second timeout ([`logs/2_timeout_failure.log`](logs/2_timeout_failure.log)):

```
[client] payment service injected delay = 3.0s
```

**Checkout detects the timeout.** Each request fails with HTTP 504 after about 1 second instead of hanging for 3:

```
[client] ORD-4b8975 -> HTTP 504 status=failed trace_id=d54a3f3b latency_ms=1002 error="payment service TIMEOUT after 1.0s"
[client] ORD-003717 -> HTTP 504 status=failed trace_id=f3a72f74 latency_ms=1002 error="payment service TIMEOUT after 1.0s"
[client] ORD-bbf453 -> HTTP 504 status=failed trace_id=cddc39db latency_ms=1002 error="payment service TIMEOUT after 1.0s"
```

**The service remains running.** Both services still answer right after the failures:

```
[health] checkout HTTP 200 status=ok
[health] payment  HTTP 200 status=ok
```

**Logs clearly show the failed requests** ([`logs/checkout_service.log`](logs/checkout_service.log)):

```
18:37:18.373 [checkout] trace_id=d54a3f3b ERROR payment service TIMEOUT after 1.0s
18:37:18.373 [checkout] trace_id=d54a3f3b POST /checkout FAILED status=504 latency_ms=1002
18:37:19.376 [checkout] trace_id=f3a72f74 ERROR payment service TIMEOUT after 1.0s
18:37:19.376 [checkout] trace_id=f3a72f74 POST /checkout FAILED status=504 latency_ms=1002
18:37:20.379 [checkout] trace_id=cddc39db ERROR payment service TIMEOUT after 1.0s
18:37:20.379 [checkout] trace_id=cddc39db POST /checkout FAILED status=504 latency_ms=1002
```

**The trace ID follows the request across both services** (`grep d54a3f3b logs/*_service.log`). Payment received the request and was still sleeping when Checkout gave up after 1 second; Payment finished 2 seconds later:

```
18:37:17.371 [checkout] trace_id=d54a3f3b POST /checkout received order_id=ORD-4b8975 amount=25.0
18:37:17.371 [checkout] trace_id=d54a3f3b calling payment service (timeout=1.0s)
18:37:17.372 [payment] trace_id=d54a3f3b POST /pay received order_id=ORD-4b8975 amount=25.0
18:37:17.372 [payment] trace_id=d54a3f3b SLOW: sleeping 3.0s (injected delay)
18:37:18.373 [checkout] trace_id=d54a3f3b ERROR payment service TIMEOUT after 1.0s
18:37:18.373 [checkout] trace_id=d54a3f3b POST /checkout FAILED status=504 latency_ms=1002
18:37:20.422 [payment] trace_id=d54a3f3b POST /pay completed status=200 latency_ms=3050
```

**Metrics show the failure.** Checkout's error rate went from 0% to 75% (1 success, 3 failures), and its latency rose from about 57 ms to about 1000 ms. Payment reports no failures but a latency of about 3050 ms, which points to Payment being slow as the cause:

```
[metrics] checkout requests=4 success=1 failure=3 error_rate=75.0% recent_error_rate=75.0% | latency_ms last=1001.6 avg=765.6 recent_avg=765.6 max=1001.7
[metrics] payment  requests=4 success=4 failure=0 error_rate=0.0% recent_error_rate=0.0% | latency_ms last=3050.3 avg=2300.3 recent_avg=2300.3 max=3050.4
```

One thing the trace also shows: Payment still completed the charge after Checkout had already told the client the order failed. A timeout only tells the caller that it stopped waiting, not what happened on the other side. A real system would need something like an idempotency key or a status check before retrying.

### 3. Recovery

The delay is removed and six more orders are placed ([`logs/3_recovery.log`](logs/3_recovery.log)):

```
[client] payment service injected delay = 0.0s
[client] ORD-c2c758 -> HTTP 200 status=confirmed trace_id=f46f2c71 latency_ms=51
[client] ORD-08c201 -> HTTP 200 status=confirmed trace_id=97814035 latency_ms=51
[client] ORD-ec4b41 -> HTTP 200 status=confirmed trace_id=4e24a13a latency_ms=51
[client] ORD-01124a -> HTTP 200 status=confirmed trace_id=6e5bc1cc latency_ms=51
[client] ORD-3e555e -> HTTP 200 status=confirmed trace_id=a4d6dd05 latency_ms=51
[client] ORD-cc587b -> HTTP 200 status=confirmed trace_id=7ba1a03b latency_ms=51
```

```
[metrics] checkout requests=10 success=7 failure=3 error_rate=30.0% recent_error_rate=0.0% | latency_ms last=51.3 avg=337.0 recent_avg=51.3 max=1001.7
[metrics] payment  requests=10 success=10 failure=0 error_rate=0.0% recent_error_rate=0.0% | latency_ms last=50.2 avg=950.2 recent_avg=50.2 max=3050.4
```

- **Requests succeed again:** all six return HTTP 200.
- **Error rate decreases:** overall 75% → 30%, and the recent error rate (last 5 requests) is 0%.
- **Request latency returns to normal:** about 51 ms per checkout, down from about 1000 ms during the failure.

| Checkout metrics | After scenario 1 | During failure | After recovery |
|---|---|---|---|
| success / failure | 1 / 0 | 1 / 3 | 7 / 3 |
| error rate (overall) | 0% | 75% | 30% |
| error rate (last 5 requests) | 0% | 75% | 0% |
| last request latency | ~57 ms | ~1000 ms | ~51 ms |

### Tests

```
$ python3 -m unittest
....
----------------------------------------------------------------------
Ran 4 tests in 4.034s

OK
```

The tests start both services on free ports and check a successful checkout, that both services log the same trace ID, that a timeout is detected while the service keeps running, and that requests recover after the delay is removed.

## Reflection

**How do logs, traces, and metrics help diagnose failures in a distributed system?**

Each of the three answers a different question, and I needed all of them to understand this failure. Metrics showed that something was wrong and when: Checkout's error rate jumped to 75% and its latency went from about 57 ms to 1000 ms, and after the fix the same numbers showed the system had recovered. Logs showed what happened to each request, such as the `ERROR payment service TIMEOUT after 1.0s` line in the Checkout log. The trace ID connected the two services, because searching for one ID showed that Payment had received the request and was sleeping for 3 seconds while Checkout gave up after 1, which is how I could tell the root cause was in Payment and not in Checkout. Without a shared ID, the lines in the two separate log files could not be matched reliably, especially with many requests running at the same time.

## Repository layout

```
checkout_service.py    Checkout Service: creates the trace ID, calls Payment with a timeout
payment_service.py     Payment Service: charges orders, supports an injected delay
common.py              logging, metrics and HTTP helpers shared by both services
client.py              places orders, injects/removes the delay, shows metrics
test_services.py       tests against real services
scripts/run_demo.sh    runs all scenarios and writes logs/
logs/                  captured evidence
```
