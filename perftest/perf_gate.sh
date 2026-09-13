#!/bin/bash
# ===================================================================
# CI 性能门禁 — 在 CI 中运行压测并根据指标判定通过/拦截
#
# 用法: ./perftest/perf_gate.sh [选项]
#
# 选项:
#   -u N      并发用户数   (默认: 20)
#   -d DUR    测试时长     (默认: 2m)
#   --p95 N   P95上限ms   (默认: 1000)
#   --fail N  失败率上限%  (默认: 5)
#   --host URL 目标地址    (默认: http://your-api-server:8082)
#
# 退出码:
#   0 = 通过, 1 = 测试执行失败, 2 = P95超标, 3 = 失败率超标
# ===================================================================

set -euo pipefail

# ---- 默认参数 ----
VUS=20
DURATION="2m"
P95_LIMIT=1000
FAIL_LIMIT=5
HOST="http://your-api-server:8082"
PROM_URL="http://localhost:9090"
K6_SCRIPT="${SCRIPT:-perftest/k6-script.js}"

# ---- 解析参数 ----
while [[ $# -gt 0 ]]; do
  case "$1" in
    -u) VUS="$2"; shift 2 ;;
    -d) DURATION="$2"; shift 2 ;;
    --p95) P95_LIMIT="$2"; shift 2 ;;
    --fail) FAIL_LIMIT="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --script) K6_SCRIPT="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

echo "============================================"
echo "  CI 性能门禁"
echo "  并发     : ${VUS} VUs"
echo "  时长     : ${DURATION}"
echo "  P95上限  : ${P95_LIMIT} ms"
echo "  失败率上限: ${FAIL_LIMIT}%"
echo "  目标     : ${HOST}"
echo "============================================"
echo ""

# ---- 步骤1: 运行 k6 压测 ----
echo "[1/3] 运行 k6 压测..."
START_TIME=$(date +%s)

K6_PROMETHEUS_RW_SERVER_URL="${PROM_URL}/api/v1/write" \
K6_PROMETHEUS_RW_TREND_STATS="p(50),p(95),p(99),avg,min,max" \
K6_PROMETHEUS_RW_PUSH_INTERVAL="5s" \
k6 run -o experimental-prometheus-rw \
  -u "${VUS}" -d "${DURATION}" \
  --no-summary \
  "${K6_SCRIPT}" 2>&1 | tail -5

K6_EXIT=$?
if [ $K6_EXIT -ne 0 ]; then
  echo "[FAIL] k6 测试执行失败 (exit=${K6_EXIT})"
  exit 1
fi
echo "[OK] 压测完成"
echo ""

# ---- 步骤2: 等待 Prometheus 数据落盘 ----
echo "[2/3] 等待指标数据落盘..."
sleep 10

# ---- 步骤3: 查询 Prometheus 检查指标 ----
echo "[3/3] 查询 Prometheus 指标..."

# 查询 P95 响应时间
P95_QUERY="histogram_quantile(0.95, sum(rate(k6_http_req_duration_seconds_bucket[${DURATION}])) by (le)) * 1000"
P95_RAW=$(curl -s --data-urlencode "query=${P95_QUERY}" "${PROM_URL}/api/v1/query" 2>/dev/null)
P95_VAL=$(echo "$P95_RAW" | python3 -c "
import sys,json
try:
    r = json.load(sys.stdin)
    v = float(r['data']['result'][0]['value'][1])
    print(round(v,1))
except: print('N/A')
" 2>/dev/null || echo "N/A")

# 查询失败率
FAIL_QUERY="sum(rate(k6_http_req_failed_total[${DURATION}])) / sum(rate(k6_http_reqs_total[${DURATION}])) * 100"
FAIL_RAW=$(curl -s --data-urlencode "query=${FAIL_QUERY}" "${PROM_URL}/api/v1/query" 2>/dev/null)
FAIL_VAL=$(echo "$FAIL_RAW" | python3 -c "
import sys,json
try:
    r = json.load(sys.stdin)
    v = float(r['data']['result'][0]['value'][1])
    print(round(v,2))
except: print('N/A')
" 2>/dev/null || echo "N/A")

echo ""
echo "============================================"
echo "  性能门禁结果"
echo "  P95 响应时间 : ${P95_VAL} ms  (上限 ${P95_LIMIT} ms)"
echo "  失败率       : ${FAIL_VAL} %     (上限 ${FAIL_LIMIT}%)"
echo "============================================"

# ---- 判定 ----
EXIT_CODE=0

if [ "$P95_VAL" != "N/A" ]; then
  P95_OK=$(python3 -c "print(1 if ${P95_VAL} <= ${P95_LIMIT} else 0)")
  if [ "$P95_OK" = "0" ]; then
    echo "[BLOCKED] P95 响应时间超标！"
    EXIT_CODE=2
  fi
fi

if [ "$FAIL_VAL" != "N/A" ]; then
  FAIL_OK=$(python3 -c "print(1 if ${FAIL_VAL} <= ${FAIL_LIMIT} else 0)")
  if [ "$FAIL_OK" = "0" ]; then
    echo "[BLOCKED] 失败率超标！"
    EXIT_CODE=3
  fi
fi

if [ $EXIT_CODE -eq 0 ]; then
  echo "[PASS] 性能门禁通过"
fi

exit $EXIT_CODE
