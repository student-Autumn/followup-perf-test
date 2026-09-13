#!/bin/bash
# ============================================================
# k6 压测 + Prometheus 导出
# 用法: ./perftest/run_k6_monitored.sh [script] [options]
#
# 示例:
#   ./perftest/run_k6_monitored.sh                    # 默认跑 k6-script.js
#   ./perftest/run_k6_monitored.sh k6-script.js       # 指定脚本
#   ./perftest/run_k6_monitored.sh k6-script.js -u 20 -d 5m  # 自定义参数
# ============================================================

SCRIPT="${1:-k6-script.js}"
shift 2>/dev/null || true

PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090/api/v1/write}"

echo "============================================"
echo "  k6 压测（Prometheus 导出）"
echo "  脚本       : perftest/${SCRIPT}"
echo "  Prometheus : ${PROMETHEUS_URL}"
echo "============================================"

K6_PROMETHEUS_RW_SERVER_URL="${PROMETHEUS_URL}" \
K6_PROMETHEUS_RW_TREND_STATS="p(50),p(95),p(99),avg,min,max" \
K6_PROMETHEUS_RW_PUSH_INTERVAL="5s" \
k6 run \
  -o experimental-prometheus-rw \
  "perftest/${SCRIPT}" \
  "$@"
