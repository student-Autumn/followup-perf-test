#!/bin/bash
# ============================================================
# 冒烟测试 - 服务器端执行脚本 (可用于 cron / 手动执行)
# ============================================================
# 用法:
#   ./run_smoke.sh           # 运行冒烟测试 + 指标上报
#   ./run_smoke.sh smoke     # 同上
#   ./run_smoke.sh regression # 运行回归测试
#
# cron 示例 (每天 8:00 执行):
#   0 8 * * * cd /opt/练习3 && bash run_smoke.sh >> /var/log/smoke_test.log 2>&1
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

TEST_TYPE="${1:-smoke}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
REPORT_FILE="report_${TEST_TYPE}_${TIMESTAMP}.html"

echo "========================================"
echo "  测试类型 : $TEST_TYPE"
echo "  时间     : $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# 激活虚拟环境
if [ -f venv/bin/activate ]; then
    source venv/bin/activate
elif [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi

# ---- 步骤 1: 运行测试 ----
START_TIME=$(date +%s)

set +e  # 允许 pytest 失败，我们需要知道退出码
python -m pytest -vs -k "$TEST_TYPE" \
    --html="$REPORT_FILE" \
    --self-contained-html \
    --tb=short 2>&1 | tee "/tmp/smoke_output_${TIMESTAMP}.log"
PYTEST_EXIT=$?
set -e

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo "========================================"
echo "  测试完成: $(date '+%Y-%m-%d %H:%M:%S')"
echo "  耗时    : ${DURATION}s"
echo "  退出码  : $PYTEST_EXIT"
echo "  报告    : $SCRIPT_DIR/$REPORT_FILE"
echo "========================================"

# ---- 步骤 2: 解析测试结果 ----
# 从 pytest 输出中提取用例数
TOTAL=$(grep -oP '\d+ selected' "/tmp/smoke_output_${TIMESTAMP}.log" 2>/dev/null | grep -oP '\d+' || echo 0)
PASSED=$(grep -c "PASSED" "/tmp/smoke_output_${TIMESTAMP}.log" 2>/dev/null || echo 0)
FAILED=$(grep -c "FAILED" "/tmp/smoke_output_${TIMESTAMP}.log" 2>/dev/null || echo 0)

# 更准确的统计: 从 HTML 报告的 summary 提取 (fallback)
if [ "$TOTAL" = "0" ]; then
    TOTAL=$((PASSED + FAILED))
fi

echo ""
echo " 用例统计: 总$TOTAL 通过$PASSED 失败$FAILED"

# ---- 步骤 3: 推送指标到 Pushgateway ----
echo ""
echo "[3/4] 推送指标..."

if command -v python3 &> /dev/null; then
    python3 scripts/smoke_metrics.py \
        --exit-code "$PYTEST_EXIT" \
        --duration "$DURATION" \
        --total "$TOTAL" \
        --passed "$PASSED" \
        --failed "$FAILED" \
        --job "$TEST_TYPE" \
        --instance "$(hostname)" 2>&1 || echo "  [WARN] 指标推送失败(继续)"
else
    echo "  [WARN] python3 不可用，跳过指标推送"
fi

# ---- 步骤 4: 清理测试数据 ----
echo ""
echo "[4/4] 清理测试数据..."

if [ -f scripts/data_cleanup.py ]; then
    python3 scripts/data_cleanup.py --mode query --dry-run 2>&1 | tail -5
    echo ""
    # 实际清理（非 dry-run）
    python3 scripts/data_cleanup.py --mode query 2>&1 | tail -10 || echo "  [WARN] 部分数据清理失败"
else
    echo "  [WARN] data_cleanup.py 不存在，跳过清理"
fi

echo ""
echo "========================================"
echo "  流程完成: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# 返回 pytest 的真实退出码
exit $PYTEST_EXIT
