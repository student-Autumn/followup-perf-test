"""
CI 数据准备 — 一站式数据准备，供 CI/CD 流水线调用。

流程:
  1. 检查 token 有效性
  2. 增量拉取真实数据（快速，跳过无变化的模块）
  3. 检查数据池是否完整，缺失的用 data_factory 补充
  4. 输出数据池状态摘要

用法:
  python scripts/ci_data_prep.py                  # 默认：增量拉取 + 检查
  python scripts/ci_data_prep.py --full            # 全量拉取
  python scripts/ci_data_prep.py --scenario perf   # 为压测准备数据
  python scripts/ci_data_prep.py --check-only      # 仅检查数据池状态
  python scripts/ci_data_prep.py --factory-count 5 # 工厂补充数量
"""
import json
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from commons.auth_token import get_token, check_token_valid
from commons.data_tracker import DataTracker

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_DATA_PATH = os.path.join(PROJECT_DIR, "perftest", "real_data.json")

# 压测必需的数据池（缺失会导致压测脚本 fallback 到默认值）
REQUIRED_POOLS = [
    "patientPool", "screenRecordPool", "opLogPool", "sysLogPool",
    "followupPool", "hardwarePool", "orgPool", "rolePool",
    "projectPool", "surveyPool", "userPool",
]

# 各场景下池子的最小条数
POOL_MIN_SIZE = {
    "smoke": 2,
    "regression": 5,
    "perf": 20,
}


def check_pools(min_size=2):
    """检查 real_data.json 中各数据池的状态"""
    if not os.path.exists(REAL_DATA_PATH):
        print(f"  [WARN] real_data.json 不存在")
        return {"missing": REQUIRED_POOLS, "low": [], "ok": []}

    with open(REAL_DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    status = {"missing": [], "low": [], "ok": []}
    for pool in REQUIRED_POOLS:
        items = data.get(pool, [])
        if not items:
            status["missing"].append(pool)
        elif len(items) < min_size:
            status["low"].append(pool)
        else:
            status["ok"].append(pool)

    return status


def print_pool_status(status):
    """打印数据池状态"""
    if status["missing"]:
        print(f"  [MISS] 缺失: {', '.join(status['missing'])}")
    if status["low"]:
        print(f"  [LOW]  不足: {', '.join(status['low'])}")
    if status["ok"]:
        print(f"  [OK]   正常: {', '.join(status['ok'])}")

    all_bad = len(status["missing"]) + len(status["low"])
    if all_bad == 0:
        print(f"  所有 {len(status['ok'])} 个数据池状态正常")
    return all_bad


def run_fetch(incremental=True, max_records=50, only_modules=None):
    """运行增量数据拉取"""
    import subprocess
    fetch_script = os.path.join(PROJECT_DIR, "scripts", "fetch_real_data.py")
    cmd = [sys.executable, fetch_script]
    if incremental:
        cmd.append("--incremental")
    if max_records:
        cmd.extend(["--max", str(max_records)])
    if only_modules:
        cmd.extend(["--only", only_modules])

    print(f"  执行: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=PROJECT_DIR)
    return result.returncode == 0


def run_factory(scenario="smoke", count=3):
    """运行数据工厂补充缺失数据"""
    import subprocess
    factory_script = os.path.join(PROJECT_DIR, "scripts", "data_factory.py")
    cmd = [
        sys.executable, factory_script,
        "--scenario", scenario,
        "--count", str(count),
        "--update-extract",
    ]
    print(f"  执行: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=PROJECT_DIR)
    return result.returncode == 0


def clean_tracked_data():
    """清理上次运行可能遗留的追踪数据"""
    total = DataTracker.total()
    if total > 0:
        print(f"  [DATA] 上次运行遗留 {total} 条追踪记录，正在清理...")
        import subprocess
        cleanup_script = os.path.join(PROJECT_DIR, "scripts", "data_cleanup.py")
        cmd = [sys.executable, cleanup_script, "--mode", "tracked"]
        subprocess.run(cmd, cwd=PROJECT_DIR, capture_output=True)


def main():
    parser = argparse.ArgumentParser(
        description="CI 数据准备 — 一站式准备测试数据",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--full", action="store_true",
                       help="全量拉取（否则默认增量）")
    parser.add_argument("--scenario", default="smoke",
                       choices=["smoke", "regression", "perf"],
                       help="场景标识 (默认: smoke)")
    parser.add_argument("--check-only", action="store_true",
                       help="仅检查数据池状态，不拉取/不补充")
    parser.add_argument("--factory-count", type=int, default=3,
                       help="工厂补充时的每个模块创建数量 (默认: 3)")
    parser.add_argument("--skip-cleanup", action="store_true",
                       help="跳过历史数据清理")

    args = parser.parse_args()

    print("=" * 55)
    print("  CI 数据准备")
    print(f"  场景: {args.scenario}")
    if args.check_only:
        print("  模式: 仅检查")
    else:
        print(f"  模式: {'全量拉取' if args.full else '增量拉取'} + 工厂补充")
    print("=" * 55)

    # Step 1: 检查 token
    print("\n[1/4] 检查认证 Token...")
    token = get_token()
    if not token:
        print("  [FAIL] Token 不存在，尝试从缓存加载...")
        # 最后尝试 — 也许 token 刚过期但能通过 check
        valid, msg = check_token_valid()
        if not valid:
            print(f"  [FATAL] Token 无效: {msg}")
            print("  请先在本地运行: python scripts/auth_helper.py")
            sys.exit(1)
    print("  [OK] Token 已就绪")

    # Step 2: 清理上次遗留数据
    if not args.skip_cleanup:
        print("\n[2/4] 清理历史数据...")
        clean_tracked_data()
    else:
        print("\n[2/4] 跳过历史数据清理")

    # Step 3: 拉取数据
    if args.check_only:
        print("\n[3/4] 检查数据池状态...")
        min_size = POOL_MIN_SIZE.get(args.scenario, 2)
        status = check_pools(min_size)
        bad = print_pool_status(status)
        if bad > 0:
            print(f"  [WARN] {bad} 个数据池需要补充，运行不带 --check-only 以自动修复")
            sys.exit(1)
        else:
            print("  [OK] 数据池状态正常")
            sys.exit(0)

    print("\n[3/4] 拉取真实数据...")
    incremental = not args.full
    ok = run_fetch(incremental=incremental, max_records=50)
    if not ok:
        print("  [WARN] 数据拉取返回非零状态")

    # Step 4: 检查并补充
    print("\n[4/4] 检查数据池完整度...")
    min_size = POOL_MIN_SIZE.get(args.scenario, 2)
    status = check_pools(min_size)
    bad = print_pool_status(status)

    if bad > 0:
        print(f"\n  {bad} 个数据池不完整，启动数据工厂补充...")
        run_factory(scenario=args.scenario, count=args.factory_count)

        # 再次检查
        print("\n  补充后检查...")
        status = check_pools(min_size)
        bad = print_pool_status(status)
        if bad > 0:
            print(f"\n  [WARN] 仍有 {bad} 个数据池不完整，但测试可继续")
    else:
        print("\n  数据池状态正常，无需补充")

    print("\n" + "=" * 55)
    print(f"  CI 数据准备完成")
    print(f"  接下来可以运行: python run.py / locust / k6")
    print("=" * 55)


if __name__ == "__main__":
    main()
