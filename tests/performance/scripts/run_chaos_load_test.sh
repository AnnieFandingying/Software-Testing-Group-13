#!/usr/bin/env bash
set -euo pipefail

# Run JMeter load while a ChaosMesh experiment is active.
#
# Required tools on the test runner machine:
#   jmeter, kubectl, python3
#
# Important environment variables:
#   FRONTEND_HOST=127.0.0.1
#   FRONTEND_PORT=8080
#   CHAOS_FILE=tests/chaosmesh/network-delay-checkout-to-discount.yaml
#   THREADS=10 RAMP_SECONDS=120 DURATION_SECONDS=1800

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TEST_PLAN="${TEST_PLAN:-${ROOT_DIR}/tests/performance/online_boutique_checkout_pressure.jmx}"
RESULTS_DIR="${RESULTS_DIR:-${ROOT_DIR}/results/testing/jmeter}"
RUN_NAME="${RUN_NAME:-chaos-$(date +%Y%m%d-%H%M%S)}"
JTL_FILE="${JTL_FILE:-${RESULTS_DIR}/${RUN_NAME}.jtl}"
CHAOS_FILE="${CHAOS_FILE:-${ROOT_DIR}/tests/chaosmesh/network-delay-checkout-to-discount.yaml}"
CHAOS_DELAY_SECONDS="${CHAOS_DELAY_SECONDS:-120}"
THREADS="${THREADS:-10}"
RAMP_SECONDS="${RAMP_SECONDS:-120}"
DURATION_SECONDS="${DURATION_SECONDS:-1800}"
CONNECT_TIMEOUT_MS="${CONNECT_TIMEOUT_MS:-5000}"
RESPONSE_TIMEOUT_MS="${RESPONSE_TIMEOUT_MS:-30000}"
SUMMARISER_INTERVAL_SECONDS="${SUMMARISER_INTERVAL_SECONDS:-10}"
FRONTEND_SCHEME="${FRONTEND_SCHEME:-http}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-8080}"
PRODUCT_ID="${PRODUCT_ID:-1YMWWN1N4O}"
PRODUCT_QUANTITY="${PRODUCT_QUANTITY:-2}"
CURRENCY_CODE="${CURRENCY_CODE:-USD}"
JMETER_BIN="${JMETER_BIN:-jmeter}"
ANALYZE_LABEL="${ANALYZE_LABEL:-E2E Browse And Checkout}"

mkdir -p "${RESULTS_DIR}"

command -v "${JMETER_BIN}" >/dev/null 2>&1 || {
  echo "jmeter not found. Set JMETER_BIN or install Apache JMeter." >&2
  exit 127
}
command -v kubectl >/dev/null 2>&1 || {
  echo "kubectl not found." >&2
  exit 127
}
command -v python3 >/dev/null 2>&1 || {
  echo "python3 not found." >&2
  exit 127
}

cleanup() {
  if [[ -n "${JMETER_PID:-}" ]] && kill -0 "${JMETER_PID}" >/dev/null 2>&1; then
    kill "${JMETER_PID}" >/dev/null 2>&1 || true
  fi
  kubectl delete -f "${CHAOS_FILE}" --ignore-not-found >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "[checkout-test] JMeter plan: ${TEST_PLAN}"
echo "[checkout-test] JTL output: ${JTL_FILE}"
echo "[checkout-test] Chaos file: ${CHAOS_FILE}"
echo "[checkout-test] Frontend: ${FRONTEND_SCHEME}://${FRONTEND_HOST}:${FRONTEND_PORT}"

"${JMETER_BIN}" -n \
  -t "${TEST_PLAN}" \
  -l "${JTL_FILE}" \
  -JRESULTS_FILE="${JTL_FILE}" \
  -JFRONTEND_SCHEME="${FRONTEND_SCHEME}" \
  -JFRONTEND_HOST="${FRONTEND_HOST}" \
  -JFRONTEND_PORT="${FRONTEND_PORT}" \
  -JTHREADS="${THREADS}" \
  -JRAMP_SECONDS="${RAMP_SECONDS}" \
  -JDURATION_SECONDS="${DURATION_SECONDS}" \
  -JCONNECT_TIMEOUT_MS="${CONNECT_TIMEOUT_MS}" \
  -JRESPONSE_TIMEOUT_MS="${RESPONSE_TIMEOUT_MS}" \
  -Jsummariser.interval="${SUMMARISER_INTERVAL_SECONDS}" \
  -JPRODUCT_ID="${PRODUCT_ID}" \
  -JPRODUCT_QUANTITY="${PRODUCT_QUANTITY}" \
  -JCURRENCY_CODE="${CURRENCY_CODE}" &
JMETER_PID="$!"

echo "[checkout-test] Warm-up for ${CHAOS_DELAY_SECONDS}s before applying chaos."
sleep "${CHAOS_DELAY_SECONDS}"

echo "[checkout-test] Applying ChaosMesh experiment."
kubectl apply -f "${CHAOS_FILE}"

wait "${JMETER_PID}"
JMETER_PID=""

echo "[checkout-test] Deleting ChaosMesh experiment."
kubectl delete -f "${CHAOS_FILE}" --ignore-not-found

echo "[checkout-test] Analyzing JTL."
python3 "${ROOT_DIR}/tests/performance/scripts/analyze_jmeter_results.py" \
  --jtl "${JTL_FILE}" \
  --out-dir "${RESULTS_DIR}/${RUN_NAME}-analysis" \
  --label-filter "${ANALYZE_LABEL}"

echo "[checkout-test] Done. Analysis: ${RESULTS_DIR}/${RUN_NAME}-analysis"
