"""
从 API 获取真实数据，写入 extract.yaml 供 YAML 测试用例使用，
同时写入 perftest/real_data.json 数据池供压测脚本使用。

使用方式: python scripts/fetch_real_data.py

流程:
  1. 从共享 .auth_token.yaml 加载 token（需先执行 python scripts/auth_helper.py）
  2. 调用公开 list 接口，自动翻页拉取全部数据
  3. 提取关键 ID/字段写入 extract.yaml（取第一条，兼容 YAML 测试）
  4. 完整数据池写入 perftest/real_data.json（压测脚本用）
"""
import json
import os
import sys
import time
import requests
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from commons.auth_token import get_auth_headers, get_token

# 配置
BASE_URL = "http://your-api-server:8082"
LOGIN_PHONE = "13800000000"
PAGE_SIZE = 100  # 每页拉取条数，拉完全部页

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRACT_PATH = os.path.join(PROJECT_DIR, "extract.yaml")
REAL_DATA_PATH = os.path.join(PROJECT_DIR, "testcase", "_real_data.json")
PERFTEST_DATA_PATH = os.path.join(PROJECT_DIR, "perftest", "real_data.json")

real_data = {}       # 完整数据快照
extract_data = {}    # 写入 extract.yaml 的键值（单条，兼容 YAML 测试）
pool_data = {}       # 数据池（多条，供压测脚本随机选取）
_MAX_RECORDS = 0     # 命令行 --max 参数，0 表示不限制
INCREMENTAL = False  # 命令行 --incremental，仅拉取有新增数据的模块

CACHE_PATH = os.path.join(PROJECT_DIR, ".fetch_cache.json")


def _read_cache():
    """读取增量拉取缓存"""
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _write_cache(data):
    """写入增量拉取缓存"""
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _check_incremental(module_key, total_check_func):
    """增量模式检查：如果模块的 total 未变化则跳过。

    Args:
        module_key: 缓存中的键名
        total_check_func: 无参函数，返回当前 total 数量，返回 0 表示跳过

    Returns:
        (should_skip, current_total): should_skip=True 表示跳过该模块
    """
    if not INCREMENTAL:
        return False, 0

    cache = _read_cache()
    cached = cache.get(module_key, {})
    cached_total = cached.get("total", -1)

    try:
        current_total = total_check_func()
        if current_total == 0:
            return True, 0
        if current_total == cached_total:
            print(f"    增量: total={current_total} 未变化，跳过")
            return True, current_total
        print(f"    增量: total {cached_total} → {current_total}，拉取新增数据")
        return False, current_total
    except Exception as e:
        print(f"    增量检查失败: {e}，回退到全量拉取")
        return False, 0


def _update_cache(module_key, total, records_count):
    """更新增量缓存"""
    cache = _read_cache()
    cache[module_key] = {
        "total": total,
        "records": records_count,
        "lastFetch": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _write_cache(cache)


def _post_first_page(url, body_template=None):
    """仅拉取第一页，返回 total 数量（用于增量检查）"""
    body = dict(body_template or {})
    body["pageNum"] = 1
    body["pageSize"] = 1
    data = post_json(url, body)
    if not data:
        return 0
    return safe_get(data, "data", "total") or 0


def _get_first_page(url_template):
    """仅拉取 GET 接口第一页，返回 total 数量"""
    sep = "&" if "?" in url_template else "?"
    url = f"{url_template}{sep}pageNum=1&pageSize=1"
    data = get_json(url)
    if not data:
        return 0
    return safe_get(data, "data", "total") or 0


# ==================== 工具函数 ====================

def post_json(url, body, need_auth=False):
    headers = {"Content-Type": "application/json"}
    if need_auth:
        headers.update(get_auth_headers())
    try:
        resp = requests.post(f"{BASE_URL}{url}", json=body, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                return data
            else:
                print(f"  [业务失败] {url}: {data.get('message', '')}")
        else:
            print(f"  [HTTP {resp.status_code}] {url}")
    except Exception as e:
        print(f"  [异常] {url}: {e}")
    return None


def get_json(url, need_auth=False):
    headers = {}
    if need_auth:
        headers.update(get_auth_headers())
    try:
        resp = requests.get(f"{BASE_URL}{url}", headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                return data
            else:
                print(f"  [业务失败] {url}: {data.get('message', '')}")
        else:
            print(f"  [HTTP {resp.status_code}] {url}")
    except Exception as e:
        print(f"  [异常] {url}: {e}")
    return None


def safe_get(data, *keys):
    """安全获取嵌套字典值"""
    for k in keys:
        if isinstance(data, dict):
            data = data.get(k)
        elif isinstance(data, list) and len(data) > 0:
            data = data[0] if isinstance(k, int) else data[0].get(k)
        else:
            return None
    return data


def fetch_all_pages_post(url, body_template=None, page_size=PAGE_SIZE, max_records=None, module_key=None):
    """POST 分页接口全量拉取，自动翻页直到拿完所有记录或达到 max_records。

    Args:
        url: 接口路径
        body_template: 请求体模板
        page_size: 每页条数
        max_records: 最大拉取条数，None 表示不限制
        module_key: 增量缓存键名（用于 --incremental 模式）

    Returns:
        (all_records, total_count) 或 (None, 0)
    """
    # 增量模式：先查 total，与缓存对比
    should_skip = False
    if INCREMENTAL and module_key:
        should_skip, _ = _check_incremental(module_key, lambda: _post_first_page(url, body_template))
        if should_skip:
            return [], 0

    body = dict(body_template or {})
    body["pageNum"] = 1
    body["pageSize"] = page_size

    data = post_json(url, body)
    if not data:
        return None, 0

    records = safe_get(data, "data", "records") or []
    total = safe_get(data, "data", "total") or len(records)

    if total == 0:
        return [], 0

    total_pages = (total + page_size - 1) // page_size
    all_records = list(records)
    if max_records and len(all_records) > max_records:
        all_records = all_records[:max_records]
        print(f"    总计 {total} 条, 已达上限 {max_records} 条, 停止拉取")
        return all_records, total

    print(f"    总计 {total} 条, 共 {total_pages} 页, 正在拉取", end="", flush=True)

    for p in range(2, total_pages + 1):
        print(".", end="", flush=True)
        body["pageNum"] = p
        page_data = post_json(url, body)
        if not page_data:
            break
        page_records = safe_get(page_data, "data", "records") or []
        all_records.extend(page_records)
        if max_records and len(all_records) >= max_records:
            all_records = all_records[:max_records]
            break

    print(f" 完成 ({len(all_records)} 条)")
    if INCREMENTAL and module_key:
        _update_cache(module_key, total, len(all_records))
    return all_records, total


def fetch_all_pages_get(url_template, page_size=PAGE_SIZE, module_key=None):
    """GET 分页接口全量拉取，自动翻页直到拿完所有记录。

    Args:
        url_template: URL 模板，不含 pageNum/pageSize（如 "/user/list"）
        page_size: 每页条数
        module_key: 增量缓存键名（用于 --incremental 模式）

    Returns:
        (all_records, total_count) 或 (None, 0)
    """
    # 增量模式：先查 total，与缓存对比
    if INCREMENTAL and module_key:
        should_skip, _ = _check_incremental(module_key, lambda: _get_first_page(url_template))
        if should_skip:
            return [], 0

    sep = "&" if "?" in url_template else "?"
    url = f"{url_template}{sep}pageNum=1&pageSize={page_size}"

    data = get_json(url)
    if not data:
        return None, 0

    records = safe_get(data, "data", "records") or []
    total = safe_get(data, "data", "total") or len(records)

    if total == 0:
        return [], 0

    total_pages = (total + page_size - 1) // page_size
    all_records = list(records)
    print(f"    总计 {total} 条, 共 {total_pages} 页, 正在拉取", end="", flush=True)

    for p in range(2, total_pages + 1):
        print(".", end="", flush=True)
        page_url = f"{url_template}{sep}pageNum={p}&pageSize={page_size}"
        page_data = get_json(page_url)
        if not page_data:
            break
        page_records = safe_get(page_data, "data", "records") or []
        all_records.extend(page_records)

    print(" 完成")
    if INCREMENTAL and module_key:
        _update_cache(module_key, total, len(all_records))
    return all_records, total


# ==================== 步骤1: 检查 Token ====================

def step_check_token():
    print("\n[1/14] 检查认证 Token...")
    token = get_token()
    if not token:
        print("  [FAIL] Token 不存在或已过期！")
        print("  请先运行: python scripts/auth_helper.py")
        return False
    print(f"  [OK] Token 已就绪 ({token[:20]}...)")
    return True


# ==================== 步骤2: 查询筛查记录列表 ====================

def step_screening():
    print("\n[2/14] 查询筛查记录列表（全量翻页）...")
    records, total = fetch_all_pages_post("/screen/record/list", module_key="screening")
    if not records:
        print("  查询失败或返回空列表")
        return

    real_data["screening"] = records
    pool = []
    for rec in records:
        pool.append({
            "id": rec.get("id"),
            "patientId": rec.get("patientId"),
            "screenProjectId": rec.get("screenProjectId"),
            "patientName": rec.get("patientName"),
            "gender": rec.get("gender"),
            "regionId": rec.get("regionId"),
            "hospitalIds": rec.get("hospitalIds", []),
            "organizationId": rec.get("organizationId"),
            "bindCardDate": rec.get("bindCardDate", ""),
            "screenDate": rec.get("screenDate", ""),
        })
    pool_data["screenRecordPool"] = pool
    print(f"  screenRecordPool  = {len(pool)} 条 (总计 {total})")

    rec = records[0]
    if rec.get("patientId"):
        extract_data["realPatientId"] = rec["patientId"]
    if rec.get("id"):
        extract_data["realScreenRecordId"] = rec["id"]
    if rec.get("screenProjectId"):
        extract_data["realScreenProjectId"] = rec["screenProjectId"]
    if rec.get("patientName"):
        extract_data["realPatientName"] = rec["patientName"]


# ==================== 步骤3: 查询操作日志列表 ====================

def step_operation_log():
    print("\n[3/14] 查询操作日志列表（全量翻页）...")
    records, total = fetch_all_pages_post("/operation-log/list", module_key="operationLog")
    if not records:
        print("  查询失败")
        return

    real_data["operationLog"] = records
    pool = []
    for rec in records:
        pool.append({
            "id": rec.get("id"),
            "operatorId": rec.get("operatorId"),
            "patientId": rec.get("patientId"),
        })
    pool_data["opLogPool"] = pool
    print(f"  opLogPool         = {len(pool)} 条 (总计 {total})")

    rec = records[0]
    if rec.get("id"):
        extract_data["realOpLogId"] = rec["id"]
    if rec.get("operatorId"):
        extract_data["realOperatorId"] = rec["operatorId"]


# ==================== 步骤4: 查询系统日志列表 ====================

def step_system_log():
    print("\n[4/14] 查询系统日志列表（全量翻页）...")
    records, total = fetch_all_pages_post("/system/log/list", module_key="systemLog")
    if not records:
        print("  查询失败")
        return

    real_data["systemLog"] = records
    pool = []
    for rec in records:
        pool.append({
            "id": rec.get("id"),
            "type": rec.get("type"),
        })
    pool_data["sysLogPool"] = pool
    print(f"  sysLogPool        = {len(pool)} 条 (总计 {total})")

    rec = records[0]
    if rec.get("id"):
        extract_data["realSysLogId"] = rec["id"]


# ==================== 步骤5: 查询随访记录列表 ====================

def step_followup():
    print("\n[5/14] 查询随访记录列表（全量翻页）...")
    records, total = fetch_all_pages_post("/followup/record/list", module_key="followup")
    if not records:
        print("  查询失败")
        return

    real_data["followup"] = records
    pool = []
    for rec in records:
        pool.append({
            "reportId": rec.get("reportId"),
            "patientId": rec.get("patientId"),
            "name": rec.get("name", ""),
            "idNo": rec.get("idNo", ""),
            "gender": rec.get("gender"),
            "positiveLevel": rec.get("positiveLevel", ""),
            "screenProjectId": rec.get("screenProjectId"),
            "bindCardNo": rec.get("bindCardNo", ""),
            "emergencyPhone": rec.get("emergencyPhone", ""),
            "regionId": rec.get("regionId"),
            "organizationId": rec.get("organizationId"),
            "hospitalIds": rec.get("hospitalIds", []),
            "screenDateStart": rec.get("screenDateStart", ""),
            "screenDateEnd": rec.get("screenDateEnd", ""),
        })
    pool_data["followupPool"] = pool
    print(f"  followupPool      = {len(pool)} 条 (总计 {total})")

    rec = records[0]
    if rec.get("reportId"):
        extract_data["realReportId"] = rec["reportId"]
    if rec.get("patientId"):
        extract_data["realFollowupPatientId"] = rec["patientId"]
    if rec.get("patientId") and "realPatientId" not in extract_data:
        extract_data["realPatientId"] = rec["patientId"]


# ==================== 步骤6: 查询硬件管理列表 ====================

def step_hardware_manage():
    print("\n[6/14] 查询硬件管理列表（全量翻页）...")
    max_r = _MAX_RECORDS if _MAX_RECORDS > 0 else None
    records, total = fetch_all_pages_post("/hardware-manage/list", max_records=max_r, module_key="hardwareManage")
    if not records:
        print("  查询失败")
        return

    real_data["hardwareManage"] = records
    pool = []
    for rec in records:
        pool.append({
            "id": rec.get("id"),
            "hardwareNo": rec.get("hardwareNo"),
            "hardwareType": rec.get("hardwareType"),
        })
    pool_data["hardwarePool"] = pool
    print(f"  hardwarePool      = {len(pool)} 条 (总计 {total})")

    rec = records[0]
    if rec.get("id"):
        extract_data["realHardwareManageId"] = rec["id"]
    if rec.get("hardwareNo"):
        extract_data["realHardwareNo"] = rec["hardwareNo"]


# ==================== 步骤7: 查询机构列表 ====================

def step_organization():
    print("\n[7/14] 查询机构列表（全量翻页）...")
    records, total = fetch_all_pages_post("/organization/list", module_key="organization")
    if not records:
        print("  查询失败")
        return

    real_data["organization"] = records
    pool = []
    for rec in records:
        pool.append({
            "id": rec.get("id"),
            "orgName": rec.get("orgName"),
            "orgType": rec.get("orgType"),
        })
    pool_data["orgPool"] = pool
    print(f"  orgPool           = {len(pool)} 条 (总计 {total})")

    rec = records[0]
    if rec.get("id"):
        extract_data["realOrgId"] = rec["id"]
    if rec.get("orgName"):
        extract_data["realOrgName"] = rec["orgName"]


# ==================== 步骤8: 查询角色列表 ====================

def step_role():
    print("\n[8/14] 查询角色列表（全量翻页）...")
    records, total = fetch_all_pages_post("/role/list", module_key="role")
    if not records:
        print("  查询失败")
        return

    real_data["role"] = records
    pool = []
    for rec in records:
        pool.append({
            "id": rec.get("id"),
            "roleName": rec.get("roleName"),
            "roleKey": rec.get("roleKey"),
        })
    pool_data["rolePool"] = pool
    print(f"  rolePool          = {len(pool)} 条 (总计 {total})")

    rec = records[0]
    if rec.get("id"):
        extract_data["realRoleId"] = rec["id"]
    if rec.get("roleName"):
        extract_data["realRoleName"] = rec["roleName"]


# ==================== 步骤9: 查询仪表盘统计 ====================

def step_dashboard():
    print("\n[9/14] 查询仪表盘筛查统计...")
    data = get_json("/dashboard/statistics/screen")
    if not data:
        print("  查询失败")
        return

    stats = data.get("data")
    if stats:
        real_data["dashboardScreenStats"] = stats
        print(f"  totalCount    = {stats.get('totalCount', 'N/A')}")
        print(f"  thisWeekCount = {stats.get('thisWeekCount', 'N/A')}")
        print(f"  lastWeekCount = {stats.get('lastWeekCount', 'N/A')}")


# ==================== 步骤10: 查询病人列表 ====================

def step_patient():
    print("\n[10/14] 查询病人列表（全量翻页）...")
    records, total = fetch_all_pages_post("/patient/list", module_key="patient")
    if not records:
        print("  查询失败")
        return

    real_data["patient"] = records
    pool = []
    for rec in records:
        pool.append({
            "patientId": rec.get("patientId"),
            "idNo": rec.get("idNo"),
            "name": rec.get("name"),
            "age": rec.get("age"),
            "gender": rec.get("gender"),
        })
    pool_data["patientPool"] = pool
    print(f"  patientPool       = {len(pool)} 条 (总计 {total})")

    rec = records[0]
    if rec.get("patientId"):
        extract_data["realPatientId"] = rec["patientId"]
    if rec.get("idNo"):
        extract_data["realIdNo"] = rec["idNo"]


# ==================== 步骤11: 查询项目列表 ====================

def step_project():
    print("\n[11/14] 查询项目列表（全量翻页）...")
    records, total = fetch_all_pages_post("/project/list", module_key="project")
    if not records:
        print("  查询失败")
        return

    real_data["project"] = records
    pool = []
    for rec in records:
        pool.append({
            "id": rec.get("id"),
            "projectName": rec.get("projectName"),
            "organizationId": rec.get("organizationId"),
            "hospitalIds": rec.get("hospitalIds", []),
            "regionId": rec.get("regionId"),
        })
    pool_data["projectPool"] = pool
    print(f"  projectPool       = {len(pool)} 条 (总计 {total})")

    rec = records[0]
    if rec.get("id"):
        extract_data["realProjectId"] = rec["id"]
    if rec.get("projectName"):
        extract_data["realProjectName"] = rec["projectName"]
    if rec.get("organizationId"):
        extract_data["realProjectOrgId"] = rec["organizationId"]
    if rec.get("hospitalIds"):
        extract_data["realHospitalIds"] = rec["hospitalIds"]
    if rec.get("regionId"):
        extract_data["realRegionId"] = rec["regionId"]


# ==================== 步骤12: 查询安全测试答题记录 ====================

def step_security_test():
    print("\n[12/14] 查询安全测试答题记录...")
    patient_id = extract_data.get("realPatientId")
    if not patient_id:
        print("  缺少 realPatientId，跳过")
        return

    data = get_json(f"/security-test/answers/{patient_id}")
    if not data:
        print("  查询失败（可能该病人尚无答题记录）")
        return

    answer_data = data.get("data")
    if answer_data:
        real_data["securityTestAnswer"] = answer_data
        if answer_data.get("patientId"):
            print(f"  patientId   = {answer_data['patientId']}")
        if answer_data.get("patientName"):
            print(f"  patientName = {answer_data['patientName']}")
        answers = answer_data.get("answers", [])
        print(f"  answers     = {len(answers)} 条记录")
    else:
        print("  该病人暂无安全测试答题记录")


# ==================== 步骤13: 查询调查问卷列表 ====================

def step_survey():
    print("\n[13/14] 查询调查问卷列表（全量翻页）...")
    records, total = fetch_all_pages_post("/survey/list", module_key="survey")
    if not records:
        print("  查询失败")
        return

    real_data["survey"] = records
    pool = []
    for rec in records:
        pool.append({
            "id": rec.get("id"),
            "title": rec.get("title"),
        })
    pool_data["surveyPool"] = pool
    print(f"  surveyPool        = {len(pool)} 条 (总计 {total})")

    rec = records[0]
    if rec.get("id"):
        extract_data["realSurveyId"] = rec["id"]
    if rec.get("title"):
        extract_data["realSurveyTitle"] = rec["title"]


# ==================== 步骤14: 查询用户列表 ====================

def step_user():
    print("\n[14/14] 查询用户列表（全量翻页）...")
    records, total = fetch_all_pages_get("/user/list", module_key="user")
    if not records:
        print("  查询失败")
        return

    real_data["user"] = records
    pool = []
    for rec in records:
        pool.append({
            "id": rec.get("id"),
            "username": rec.get("username"),
            "phone": rec.get("phone"),
            "loginAccount": rec.get("loginAccount"),
        })
    pool_data["userPool"] = pool
    print(f"  userPool          = {len(pool)} 条 (总计 {total})")

    rec = records[0]
    if rec.get("id"):
        extract_data["realUserId"] = rec["id"]
    if rec.get("username"):
        extract_data["realUsername"] = rec["username"]
    if rec.get("phone"):
        extract_data["realUserPhone"] = rec["phone"]


def write_files(merge=False):
    # --- 写入 extract.yaml（保持 YAML 测试兼容，仍用单条数据）---
    if extract_data and not merge:
        existing = {}
        if os.path.exists(EXTRACT_PATH):
            with open(EXTRACT_PATH, "r", encoding="utf-8") as f:
                try:
                    existing = yaml.safe_load(f) or {}
                except Exception:
                    existing = {}

        for k, v in extract_data.items():
            existing[k] = v

        with open(EXTRACT_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(existing, f, allow_unicode=True, default_flow_style=False)
        print(f"\n[OK] extract.yaml 已更新 ({len(extract_data)} 个新键)")

    # --- 写入 perftest/real_data.json（数据池 + 默认单值）---
    key_map = {
        "realPatientId": "patientId", "realPatientName": "patientName",
        "realOperatorId": "operatorId", "realOpLogId": "opLogId",
        "realScreenRecordId": "screenRecordId", "realScreenProjectId": "screenProjectId",
        "realReportId": "reportId", "realFollowupPatientId": "followupPatientId",
        "realHardwareManageId": "hardwareManageId", "realHardwareNo": "hardwareNo",
        "realOrgId": "orgId", "realOrgName": "orgName",
        "realRoleId": "roleId", "realRoleName": "roleName",
        "realIdNo": "idNo",
        "realProjectId": "projectId", "realProjectName": "projectName",
        "realProjectOrgId": "projectOrgId", "realHospitalIds": "hospitalIds",
        "realRegionId": "regionId",
        "realSysLogId": "sysLogId",
        "realSurveyId": "surveyId", "realSurveyTitle": "surveyTitle",
        "realUserId": "userId", "realUsername": "username", "realUserPhone": "userPhone",
    }

    # merge 模式：读取现有文件，只更新本次拉取的池
    perftest_data = {}
    if merge and os.path.exists(PERFTEST_DATA_PATH):
        with open(PERFTEST_DATA_PATH, "r", encoding="utf-8") as f:
            try:
                perftest_data = json.load(f)
            except Exception:
                perftest_data = {}

    for ek, pk in key_map.items():
        if ek in extract_data:
            perftest_data[pk] = extract_data[ek]

    # 写入数据池（merge 时只更新本次拉取的池，保留其他池不变）
    for pool_key, pool_items in pool_data.items():
        perftest_data[pool_key] = pool_items

    if perftest_data:
        os.makedirs(os.path.dirname(PERFTEST_DATA_PATH), exist_ok=True)
        with open(PERFTEST_DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(perftest_data, f, ensure_ascii=False, indent=2)
        print(f"[OK] perftest/real_data.json 已更新 ({len(perftest_data)} 个键, "
              f"含 {len(pool_data)} 个数据池)")

    # --- 写入完整数据快照 ---
    if not merge:
        real_data["_fetchedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        real_data["_baseUrl"] = BASE_URL
        with open(REAL_DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(real_data, f, ensure_ascii=False, indent=2)
        print(f"[OK] _real_data.json 已保存 ({len(real_data) - 2} 个模块)")


def step_data_permission():
    print("\n[15/15] 查询数据权限列表（全量翻页）...")
    records, total = fetch_all_pages_post("/permission/data/list", module_key="dataPermission")
    if not records:
        print("  查询失败")
        return

    real_data["dataPermission"] = records
    pool = []
    for rec in records:
        pool.append({
            "id": rec.get("id"),
            "permissionName": rec.get("permissionName"),
            "regionId": rec.get("regionId"),
            "status": rec.get("status"),
        })
    pool_data["dataPermissionPool"] = pool
    print(f"  dataPermissionPool = {len(pool)} 条 (总计 {total})")

    rec = records[0]
    if rec.get("id"):
        extract_data["realDataPermissionId"] = rec["id"]


# ==================== 主流程 ====================

# 步骤名到函数的映射
STEP_MAP = {
    "screening": step_screening,
    "operation-log": step_operation_log,
    "system-log": step_system_log,
    "followup": step_followup,
    "hardware": step_hardware_manage,
    "organization": step_organization,
    "role": step_role,
    "dashboard": step_dashboard,
    "patient": step_patient,
    "project": step_project,
    "security-test": step_security_test,
    "survey": step_survey,
    "user": step_user,
    "data-permission": step_data_permission,
}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="API 真实数据抓取工具")
    parser.add_argument("--only", type=str, default="",
                        help="只更新指定数据池，如: hardware, patient, screening")
    parser.add_argument("--max", type=int, default=0, dest="max_records",
                        help="最大拉取条数，0 表示不限制")
    parser.add_argument("--incremental", action="store_true",
                        help="增量模式：仅拉取 total 有变化的模块（首次运行拉全量）")
    args = parser.parse_args()

    only_keys = set()
    if args.only:
        only_keys = set(k.strip() for k in args.only.split(","))
        print("=" * 55)
        print(f"  API 数据抓取 — 仅更新: {', '.join(only_keys)}")
        print(f"  目标: {BASE_URL}")
        if args.max_records:
            print(f"  上限: {args.max_records} 条")
        print("=" * 55)
    else:
        print("=" * 55)
        print("  API 真实数据抓取工具（全量翻页 v3）")
        print(f"  目标: {BASE_URL}")
        print(f"  账号: {LOGIN_PHONE}")
        print(f"  每页: {PAGE_SIZE} 条，自动翻页拉取全部")
        if args.incremental:
            print(f"  模式: 增量（仅拉取新增数据）")
        print("=" * 55)

    # 全局变量注入
    global _MAX_RECORDS, INCREMENTAL
    _MAX_RECORDS = args.max_records
    INCREMENTAL = args.incremental

    token_ok = step_check_token()
    if not token_ok:
        print("  Token 无效，认证接口将被跳过...")

    if only_keys:
        for key, step_func in STEP_MAP.items():
            if key in only_keys:
                step_func()
        write_files(merge=True)
    else:
        for step_func in STEP_MAP.values():
            step_func()
        write_files(merge=False)

    total_pool = sum(len(v) for v in pool_data.values())
    print("\n" + "=" * 55)
    print(f"  数据池总记录数: {total_pool}")
    if not args.only:
        print(f"  提取到 extract.yaml 的键 ({len(extract_data)} 个):")
        for k, v in extract_data.items():
            print(f"    {k}: {v}")
    print(f"\n  写入 perftest 的数据池 ({len(pool_data)} 个):")
    for pk, pv in pool_data.items():
        print(f"    {pk}: {len(pv)} 条记录")
    print("=" * 55)
    if not args.only:
        print("\n现在可以运行: python run.py")


if __name__ == "__main__":
    main()
