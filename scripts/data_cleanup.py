"""
测试数据清理工具 — 删除测试过程中产生的 [AUTO] 标记数据。

两种清理策略:
  1. tracked  — 读取 .test_created_ids.json，精确删除已追踪的 ID（快、安全）
  2. query    — 查询各模块 list 接口，扫描 [AUTO] 前缀的数据并删除（兜底，慢但全面）

用法:
  python scripts/data_cleanup.py --dry-run                    # 预览待清理数据
  python scripts/data_cleanup.py --mode tracked               # 仅按追踪文件清理
  python scripts/data_cleanup.py --mode query                 # 仅按 [AUTO] 扫描清理
  python scripts/data_cleanup.py --mode all                   # 两种策略都跑
  python scripts/data_cleanup.py --scenario perf              # 仅清理指定场景
  python scripts/data_cleanup.py --module patient,hardware    # 仅清理指定模块
"""
import json
import os
import sys
import time
import argparse
import requests
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from commons.auth_token import get_auth_headers, get_token
from commons.data_tag import DataTag
from commons.data_tracker import DataTracker

BASE_URL = "http://your-api-server:8082"
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 每个模块的 list 接口、delete 接口、以及用于识别 [AUTO] 数据的字段名
MODULE_CONFIG = {
    "patient": {
        "list": ("post", "/patient/list", {}),
        "delete": "/patient/delete/{id}",
        "idField": "patientId",
        "nameField": "name",
    },
    "organization": {
        "list": ("post", "/organization/list", {}),
        "delete": "/organization/delete/{id}",
        "idField": "id",
        "nameField": "orgName",
    },
    "project": {
        "list": ("post", "/project/list", {}),
        "delete": "/project/delete/{id}",
        "idField": "id",
        "nameField": "projectName",
    },
    "role": {
        "list": ("post", "/role/list", {}),
        "delete": "/role/delete/{id}",
        "idField": "id",
        "nameField": "roleName",
    },
    "hardwareManage": {
        "list": ("post", "/hardware-manage/list", {}),
        "delete": "/hardware-manage/delete/{id}",
        "idField": "id",
        "nameField": "hardwareNo",
    },
    "survey": {
        "list": ("post", "/survey/list", {}),
        "delete": "/survey/delete/{id}",
        "idField": "id",
        "nameField": "title",
    },
    "user": {
        "list": ("get", "/user/list?pageNum=1&pageSize=100", None),
        "delete": "/user/delete/{id}",
        "idField": "id",
        "nameField": "username",
    },
    "screenRecord": {
        "list": ("post", "/screen/record/list", {}),
        "delete": "/screen/record/delete/{id}",
        "idField": "id",
        "nameField": "patientName",
    },
    "operationLog": {
        "list": ("post", "/operation-log/list", {}),
        "delete": "/operation-log/delete/{id}",
        "idField": "id",
        "nameField": "operator",
    },
}


def get_headers():
    """获取认证请求头"""
    h = {"Content-Type": "application/json"}
    h.update(get_auth_headers())
    return h


def api_post(url, body=None, need_auth=True):
    """POST 请求"""
    headers = get_headers() if need_auth else {"Content-Type": "application/json"}
    try:
        resp = requests.post(f"{BASE_URL}{url}",
                            json=body or {}, headers=headers, timeout=30)
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException as e:
        print(f"  [ERR] POST {url}: {e}")
    return None


def api_get(url, need_auth=True):
    """GET 请求"""
    headers = get_headers() if need_auth else {}
    try:
        resp = requests.get(f"{BASE_URL}{url}", headers=headers, timeout=30)
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException as e:
        print(f"  [ERR] GET {url}: {e}")
    return None


def api_delete(url, need_auth=True):
    """POST 删除（本项目删除接口都是 POST）"""
    return api_post(url, {}, need_auth)


def check_token():
    """检查 token 是否有效"""
    # TODO(2026-09-12): 接口未做权限认证，无需登录即可调用，暂时注释掉 token 校验
    # token = get_token()
    # if not token:
    #     print("[FAIL] Token 不存在或已过期，请先运行: python scripts/auth_helper.py")
    #     return False
    return True


# ==================== 策略 A: 按追踪文件清理 ====================

def clean_tracked(modules=None, scenario=None, dry_run=False):
    """读取 .test_created_ids.json，逐个删除追踪的 ID"""
    all_data = DataTracker.get_all()
    if not all_data:
        print("  .test_created_ids.json 为空或不存在，无需清理")
        return 0, 0

    success = 0
    fail = 0

    for module, ids in all_data.items():
        if modules and module not in modules:
            continue
        if module not in MODULE_CONFIG:
            print(f"  [SKIP] 未知模块: {module}")
            continue

        config = MODULE_CONFIG[module]
        delete_url = config["delete"]

        for rid in ids:
            url = delete_url.format(id=rid)
            if dry_run:
                print(f"  [DRY-RUN] 将删除 {module}({rid}): POST {url}")
                success += 1
            else:
                result = api_delete(url)
                if result and result.get("success"):
                    print(f"  [OK] 已删除 {module}({rid})")
                    success += 1
                else:
                    print(f"  [FAIL] 删除失败 {module}({rid})")
                    fail += 1
                time.sleep(0.05)  # 避免请求过快

    if not dry_run and success > 0:
        DataTracker.clear()
        print(f"  [OK] .test_created_ids.json 已清空")

    return success, fail


# ==================== 策略 B: 按 [AUTO] 扫描清理 ====================

def fetch_page(method, url, body, page_num, page_size=50):
    """拉取一页数据"""
    if method == "post":
        paged_body = dict(body)
        paged_body["pageNum"] = page_num
        paged_body["pageSize"] = page_size
        return api_post(url, paged_body)
    else:
        sep = "&" if "?" in url else "?"
        full_url = f"{url}{sep}pageNum={page_num}&pageSize={page_size}"
        return api_get(full_url)


def extract_records(data):
    """从 API 响应中提取 records 列表"""
    if not data:
        return [], 0
    d = data.get("data", {})
    if isinstance(d, list):
        return d, len(d)
    records = d.get("records", [])
    total = d.get("total", len(records))
    return records, total


def find_auto_records(records, name_field):
    """从 records 中找出 name_field 包含 [AUTO] 的记录"""
    auto_records = []
    for rec in records:
        value = rec.get(name_field, "")
        if DataTag.is_auto(str(value)):
            auto_records.append(rec)
    return auto_records


def clean_by_query(modules=None, scenario=None, dry_run=False):
    """扫描所有模块的 [AUTO] 数据并删除"""
    if not check_token():
        return 0, 0

    success = 0
    fail = 0
    target_modules = modules or list(MODULE_CONFIG.keys())

    for module in target_modules:
        if module not in MODULE_CONFIG:
            continue

        config = MODULE_CONFIG[module]
        method, url, body = config["list"]
        id_field = config["idField"]
        name_field = config["nameField"]
        delete_url = config["delete"]

        print(f"\n[扫描] {module} ({name_field} 字段查找 [AUTO])...")

        # 翻页扫描
        page_num = 1
        found = []
        while True:
            data = fetch_page(method, url, body, page_num)
            records, total = extract_records(data)
            if not records:
                break

            auto_recs = find_auto_records(records, name_field)
            if scenario:
                auto_recs = [r for r in auto_recs
                            if DataTag.scenario_from(str(r.get(name_field, ""))) == scenario]
            found.extend(auto_recs)

            if len(records) < 50:  # 最后一页
                break
            page_num += 1
            time.sleep(0.1)

        if not found:
            print(f"  未发现 [AUTO] 数据")
            continue

        print(f"  发现 {len(found)} 条 [AUTO] 数据")

        for rec in found:
            rid = rec.get(id_field)
            label = rec.get(name_field, str(rid))

            if not rid:
                print(f"  [SKIP] 无法获取 ID: {label}")
                continue

            url = delete_url.format(id=rid)
            if dry_run:
                print(f"  [DRY-RUN] 将删除 {module}({rid}): {label}")
                success += 1
            else:
                result = api_delete(url)
                if result and result.get("success"):
                    print(f"  [OK] 已删除 {module}({rid}): {label}")
                    success += 1
                else:
                    print(f"  [FAIL] 删除失败 {module}({rid}): {label}")
                    fail += 1
                time.sleep(0.05)

    return success, fail


# ==================== 命令行入口 ====================

def main():
    parser = argparse.ArgumentParser(
        description="测试数据清理工具 — 删除 [AUTO] 标记的测试数据",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/data_cleanup.py --dry-run            # 预览待清理数据
  python scripts/data_cleanup.py --mode tracked       # 按追踪文件精确清理
  python scripts/data_cleanup.py --mode query         # 扫描 [AUTO] 数据清理
  python scripts/data_cleanup.py --mode all           # 两种策略都跑
  python scripts/data_cleanup.py --scenario perf      # 仅清理压测场景数据
  python scripts/data_cleanup.py --module patient,hardware  # 仅清理指定模块
        """,
    )
    parser.add_argument("--mode", choices=["tracked", "query", "all"],
                       default="tracked", help="清理模式 (默认: tracked)")
    parser.add_argument("--scenario", type=str, default=None,
                       help="仅清理指定场景 (smoke/regression/perf/yaml)")
    parser.add_argument("--module", type=str, default="",
                       help="仅清理指定模块，逗号分隔")
    parser.add_argument("--dry-run", action="store_true",
                       help="预览模式，不真正删除")

    args = parser.parse_args()
    modules = [m.strip() for m in args.module.split(",") if m.strip()] if args.module else None
    if modules:
        unknown = set(modules) - set(MODULE_CONFIG.keys())
        if unknown:
            print(f"[WARN] 未知模块将被跳过: {unknown}")

    total_ok = 0
    total_fail = 0

    print("=" * 55)
    print("  测试数据清理工具")
    print(f"  服务器 : {BASE_URL}")
    print(f"  模式   : {args.mode}")
    if args.scenario:
        print(f"  场景   : {args.scenario}")
    if modules:
        print(f"  模块   : {', '.join(modules)}")
    if args.dry_run:
        print(f"  预览   : DRY-RUN (不真正删除)")
    print("=" * 55)

    if args.mode in ("tracked", "all"):
        print("\n--- 策略 A: 按追踪文件清理 ---")
        if not args.dry_run and not check_token():
            print("  [SKIP] Token 无效，跳过 tracked 清理")
        else:
            ok, fail = clean_tracked(modules, args.scenario, args.dry_run)
            total_ok += ok
            total_fail += fail

    if args.mode in ("query", "all"):
        print("\n--- 策略 B: 按 [AUTO] 扫描清理 ---")
        ok, fail = clean_by_query(modules, args.scenario, args.dry_run)
        total_ok += ok
        total_fail += fail

    print("\n" + "=" * 55)
    prefix = "[DRY-RUN] 将" if args.dry_run else ""
    print(f"  {prefix}清理完成: 成功 {total_ok}, 失败 {total_fail}")
    print("=" * 55)


if __name__ == "__main__":
    main()
