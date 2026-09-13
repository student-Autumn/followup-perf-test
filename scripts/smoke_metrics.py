#!/usr/bin/env python3
"""
冒烟测试指标上报 — 将 pytest 结果推送到 Prometheus Pushgateway。

用法:
  python scripts/smoke_metrics.py --exit-code 0 --duration 45.2 --total 30 --passed 28 --failed 2
  python scripts/smoke_metrics.py --exit-code 1 --duration 120.3 --total 30 --passed 25 --failed 5 --skipped 0

Grafana 查询示例:
  smoke_test_last_status      → 最后一次运行是否通过 (1/0)
  smoke_test_last_duration_sec → 最后一次运行耗时
  smoke_test_failed_cases      → 失败用例数
"""
import argparse
import time
import urllib.request
import urllib.error


# Pushgateway 地址（服务器上 pushgateway 监听 9092，容器内 9091）
PUSHGATEWAY_URL = "http://localhost:9092"


def push_to_gateway(metrics, job="smoke-test", instance=None):
    """
    把指标推送到 Pushgateway。
    Pushgateway 协议就是 Prometheus text format 的 HTTP POST。
    """
    now_ts = int(time.time() * 1000)

    lines = [
        "# HELP smoke_test_last_status 最后一次运行状态 (1=通过, 0=失败)",
        "# TYPE smoke_test_last_status gauge",
        "# HELP smoke_test_last_duration_sec 最后一次运行耗时(秒)",
        "# TYPE smoke_test_last_duration_sec gauge",
        "# HELP smoke_test_total_cases 总用例数",
        "# TYPE smoke_test_total_cases gauge",
        "# HELP smoke_test_passed_cases 通过用例数",
        "# TYPE smoke_test_passed_cases gauge",
        "# HELP smoke_test_failed_cases 失败用例数",
        "# TYPE smoke_test_failed_cases gauge",
        "# HELP smoke_test_skipped_cases 跳过用例数",
        "# TYPE smoke_test_skipped_cases gauge",
        "# HELP smoke_test_last_run_ts 最后一次运行时间戳",
        "# TYPE smoke_test_last_run_ts gauge",
    ]

    label_pairs = f'job="{job}"'
    if instance:
        label_pairs += f',instance="{instance}"'

    lines.extend([
        f"smoke_test_last_status{{{label_pairs}}} {metrics['status']}",
        f"smoke_test_last_duration_sec{{{label_pairs}}} {metrics['duration']}",
        f"smoke_test_total_cases{{{label_pairs}}} {metrics['total']}",
        f"smoke_test_passed_cases{{{label_pairs}}} {metrics['passed']}",
        f"smoke_test_failed_cases{{{label_pairs}}} {metrics['failed']}",
        f"smoke_test_skipped_cases{{{label_pairs}}} {metrics['skipped']}",
        f"smoke_test_last_run_ts{{{label_pairs}}} {now_ts}",
    ])

    body = "\n".join(lines) + "\n"

    # Pushgateway API: PUT /metrics/job/<jobname>
    url = f"{PUSHGATEWAY_URL}/metrics/job/{job}"
    if instance:
        url += f"/instance/{instance}"

    try:
        req = urllib.request.Request(
            url,
            data=body.encode("utf-8"),
            method="PUT",
        )
        urllib.request.urlopen(req, timeout=10)
        print(f"  [OK] 指标已推送到 {url}")
    except urllib.error.URLError as e:
        print(f"  [WARN] Pushgateway 不可达 ({e})，指标未推送")
        # 写到本地文件兜底
        with open(f"/tmp/smoke_{job}.prom", "w") as f:
            f.write(body)
        print(f"  [INFO] 已写入 /tmp/smoke_{job}.prom")


def main():
    parser = argparse.ArgumentParser(description="推送冒烟测试指标到 Pushgateway")
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--total", type=int, default=0)
    parser.add_argument("--passed", type=int, default=0)
    parser.add_argument("--failed", type=int, default=0)
    parser.add_argument("--skipped", type=int, default=0)
    parser.add_argument("--job", type=str, default="smoke-test")
    parser.add_argument("--instance", type=str, default=None,
                        help="实例标识（如服务器 hostname）")

    args = parser.parse_args()

    metrics = {
        "status": 1 if args.exit_code == 0 else 0,
        "duration": args.duration,
        "total": args.total,
        "passed": args.passed,
        "failed": args.failed,
        "skipped": args.skipped,
    }

    print(f"\n  {'='*50}")
    print(f"  冒烟测试指标上报")
    print(f"  状态 : {'PASS' if metrics['status'] == 1 else 'FAIL'}")
    print(f"  耗时 : {metrics['duration']}s")
    print(f"  用例 : 总{metrics['total']}  通过{metrics['passed']}  失败{metrics['failed']}  跳过{metrics['skipped']}")
    print(f"  {'='*50}")

    push_to_gateway(metrics, job=args.job, instance=args.instance)


if __name__ == "__main__":
    main()
