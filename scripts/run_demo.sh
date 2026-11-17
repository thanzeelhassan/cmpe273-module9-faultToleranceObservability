#!/usr/bin/env bash
# Starts both services, runs the three scenarios, and writes everything to logs/.
#   logs/checkout_service.log, logs/payment_service.log   each service's own request log
#   logs/1_*.log, logs/2_*.log, logs/3_*.log               client output + metrics per scenario
# Uses ports 8001 (checkout) and 8002 (payment).
set -u
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
mkdir -p logs

"$PY" -u payment_service.py --port 8002 > logs/payment_service.log 2>&1 & PAY=$!
"$PY" -u checkout_service.py --port 8001 --timeout 1.0 > logs/checkout_service.log 2>&1 & CO=$!
trap 'kill $PAY $CO 2>/dev/null' EXIT
sleep 1

client() { "$PY" -u client.py "$@" 2>&1 | tee -a "$L"; }
step() { echo "--- $*" | tee -a "$L"; }
# Follow one request across both services using its trace ID.
trace() {
  local id; id=$(grep -o 'trace_id=[0-9a-f]*' "$L" | "$1" -1 | cut -d= -f2)
  step "follow trace_id=$id across both services: grep $id logs/*_service.log"
  sleep "${2:-0}"   # let the slow Payment Service finish writing its log line
  grep -h "trace_id=$id" logs/checkout_service.log logs/payment_service.log | sort -s -k1,1 | tee -a "$L"
}

# ---------------------------------------------------------------- 1
echo "== Scenario 1: observability, one successful Checkout -> Payment request"
L=logs/1_successful_request.log; : > "$L"
step "one checkout request"
client checkout
trace tail
step "metrics"
client metrics

# ---------------------------------------------------------------- 2
echo "== Scenario 2: failure test, Payment delay (3s) longer than Checkout timeout (1s)"
L=logs/2_timeout_failure.log; : > "$L"
step "add a 3s delay to the Payment Service (Checkout timeout is 1s)"
client delay 3
step "three checkout requests"
client checkout 3
step "both services are still running"
client health
trace head 3
step "metrics"
client metrics

# ---------------------------------------------------------------- 3
echo "== Scenario 3: recovery after the delay is removed"
L=logs/3_recovery.log; : > "$L"
step "remove the Payment Service delay"
client delay 0
step "six checkout requests"
client checkout 6
step "metrics"
client metrics

echo "Done. See logs/"
