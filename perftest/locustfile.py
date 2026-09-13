"""
API 全量压测脚本 - Locust（含认证，覆盖全部13个模块83个接口）
启动: locust -f perftest/locustfile.py
Web:  http://localhost:8089    Host 填 http://your-api-server:8082

标签过滤 (注意: 多个 tag 用空格分隔, 不是逗号):
  排除删除接口:   locust -f perftest/locustfile.py --exclude-tags delete
  排除多个模块:   locust -f perftest/locustfile.py --exclude-tags delete system-log survey operation-log
  仅测删除接口:   locust -f perftest/locustfile.py --tags delete

可用模块 tag: operation-log, system-log, survey
  (delete tag 覆盖所有模块的删除接口)

数据准备: 启动前先运行 python scripts/fetch_real_data.py 获取最新真实数据

模块覆盖:
  操作日志管理   6 个接口
  筛查管理       6 个接口
  系统日志管理   2 个接口
  随访管理       6 个接口
  硬件管理       8 个接口
  机构管理       8 个接口
  角色管理       9 个接口
  仪表盘管理     7 个接口
  病人管理       6 个接口
  项目管理       8 个接口
  安全测试管理   2 个接口
  调查问卷管理  10 个接口
  用户管理       5 个接口
"""

import json
import os
import random
import string
import threading
from iniconfig import IniConfig
from locust import HttpUser, TaskSet, task, tag, between, events
from prometheus_client import start_http_server, Counter, Histogram, Gauge, CollectorRegistry


def random_str(length=6):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


def random_phone():
    """随机生成 138 手机号"""
    return f"138{''.join(random.choices(string.digits, k=8))}"


def random_name(prefix="用户"):
    """随机生成姓名"""
    surnames = ["张", "李", "王", "赵", "陈", "刘", "黄", "周", "吴", "郑"]
    return f"{random.choice(surnames)}{prefix}"


def pool_get(pool_key, field, fallback_key=None):
    """从数据池随机取一条记录，返回指定字段值。池为空时回退到 REAL_DATA[fallback_key]"""
    pool = REAL_DATA.get(pool_key, [])
    if pool:
        return random.choice(pool).get(field)
    if fallback_key:
        return REAL_DATA.get(fallback_key)
    return REAL_DATA.get(field)


def pool_item(pool_key):
    """从数据池随机取一条完整记录，返回 dict。池为空返回 {}"""
    pool = REAL_DATA.get(pool_key, [])
    if pool:
        return random.choice(pool)
    return {}


def random_page(max_page=20):
    """随机分页参数，模拟翻页行为。max_page 控制最大页码，确保能覆盖数据池全量"""
    page_num = random.randint(1, max_page)
    page_size = random.choice([5, 10, 20, 50])
    # 浅翻页(前1/3)概率更高，模拟真实用户行为
    if random.random() < 0.6:
        page_num = random.randint(1, max(1, max_page // 3))
    return {"pageNum": page_num, "pageSize": page_size}


def _skip_if_readonly(ts):
    """只读用户跳过写操作，返回 True 表示应跳过"""
    return getattr(ts.user, 'is_readonly', False)


# ==================== 配置 ====================

def get_base_url():
    ini_path = os.path.join(os.path.dirname(__file__), "..", "pytest.ini")
    ini = IniConfig(ini_path)
    if "base_url" in ini:
        return dict(ini["base_url"].items())["base_url"]
    return "http://your-api-server:8082"


LOGIN_PHONE = "13800000000"
LOGIN_CODE = "000000"
TOKEN = None
TOKEN_TYPE = "Bearer"

# 上次 create 类接口返回的 ID，供后续 update/delete/detail 使用
CREATED_IDS = {}

# ── Prometheus 指标注册 ──
_prom_registry = CollectorRegistry()
_locust_req_count = Counter(
    "locust_requests_total", "请求总数",
    ["method", "name", "status"],
    registry=_prom_registry,
)
_locust_req_duration = Histogram(
    "locust_request_duration_seconds", "请求耗时",
    ["method", "name"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 2.0, 5.0, 10.0, 30.0],
    registry=_prom_registry,
)
_locust_req_fail = Counter(
    "locust_requests_failed_total", "失败请求数",
    ["method", "name", "error"],
    registry=_prom_registry,
)
_locust_vus = Gauge(
    "locust_vus", "当前 VU 数",
    registry=_prom_registry,
)


@events.request.add_listener
def _on_request(request_type, name, response_time, response_length, exception, context, **kwargs):
    status = "error" if exception else "ok"
    _locust_req_count.labels(method=request_type, name=name, status=status).inc()
    _locust_req_duration.labels(method=request_type, name=name).observe(response_time / 1000.0)
    if exception:
        _locust_req_fail.labels(method=request_type, name=name, error=str(exception)[:80]).inc()


def _update_vus(environment):
    """后台线程：每 2 秒更新 VU 数"""
    import time
    while True:
        _locust_vus.set(environment.runner.user_count if environment.runner else 0)
        time.sleep(2)


_prom_started = False
_prom_lock = threading.Lock()

# 真实数据（从公开 list 接口自动抓取）
REAL_DATA = {
    "patientId": 1,
    "patientName": "",
    "operatorId": 1,
    "opLogId": 1,
    "screenRecordId": 1,
    "screenProjectId": 1,
    "reportId": 1,
    "followupPatientId": 1,
    "sysLogId": 1,
    "hardwareManageId": 1,
    "hardwareNo": "",
    "orgId": 1,
    "orgName": "",
    "roleId": 1,
    "roleName": "",
    "idNo": "",
    "projectId": 1,
    "projectName": "",
    "projectOrgId": 1,
    "hospitalIds": [],
    "regionId": 1,
    "securityTestAnswerId": 1,
    "surveyId": 1,
    "surveyTitle": "",
    "userId": 1,
    "username": "",
    "userPhone": "",
}


# ==================== 真实数据获取 ====================

def fetch_real_data(base_url):
    """从 perftest/real_data.json 加载真实数据（需先运行 python scripts/fetch_real_data.py）"""
    global REAL_DATA

    data_file = os.path.join(os.path.dirname(__file__), "real_data.json")

    if os.path.exists(data_file):
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            REAL_DATA.update(loaded)
            print(f"  [OK] 已从 {data_file} 加载 {len(loaded)} 个真实数据字段")
        except Exception as e:
            print(f"  [WARN] 读取 {data_file} 失败: {e}")
            print(f"  [WARN] 请先运行: python scripts/fetch_real_data.py")
    else:
        print(f"  [WARN] {data_file} 不存在！")
        print(f"  [WARN] 请先运行: python scripts/fetch_real_data.py")

    print(f"  真实数据: patientId={REAL_DATA['patientId']} reportId={REAL_DATA['reportId']} "
          f"screenRecordId={REAL_DATA['screenRecordId']} hardwareId={REAL_DATA['hardwareManageId']} orgId={REAL_DATA['orgId']} roleId={REAL_DATA['roleId']} idNo={REAL_DATA['idNo']} projectId={REAL_DATA['projectId']} userId={REAL_DATA['userId']}")


# ==================== 请求工具 ====================

def auth_headers():
    if TOKEN:
        return {"Authorization": f"{TOKEN_TYPE} {TOKEN}"}
    return {}


def post_api(client, url, body, need_auth=False, name=None):
    """POST JSON 请求"""
    headers = {"Content-Type": "application/json"}
    if need_auth:
        headers.update(auth_headers())
    with client.post(
        url,
        data=json.dumps(body),
        headers=headers,
        name=name or url,
        catch_response=True,
    ) as resp:
        if resp.status_code == 200:
            try:
                data = resp.json()
                if data.get("success"):
                    resp.success()
                    return data
                else:
                    resp.failure(f"业务失败: {data.get('message', '')}")
            except Exception:
                resp.failure("响应非JSON")
        else:
            resp.failure(f"HTTP {resp.status_code}")
    return None


def get_api(client, url, need_auth=False, name=None):
    """GET 请求"""
    headers = {}
    if need_auth:
        headers.update(auth_headers())
    with client.get(
        url,
        headers=headers,
        name=name or url,
        catch_response=True,
    ) as resp:
        if resp.status_code == 200:
            try:
                data = resp.json()
                if data.get("success"):
                    resp.success()
                    return data
                else:
                    resp.failure(f"业务失败: {data.get('message', '')}")
            except Exception:
                resp.failure("响应非JSON")
        else:
            resp.failure(f"HTTP {resp.status_code}")
    return None


# ==================== 认证 ====================

def load_shared_token():
    """从 .auth_token.yaml 加载共享 token（启动时调用一次）"""
    global TOKEN, TOKEN_TYPE
    import yaml

    token_path = os.path.join(os.path.dirname(__file__), "..", ".auth_token.yaml")
    try:
        with open(token_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if data.get("token") and data.get("expiresAt"):
            import time as _time
            try:
                expiry = _time.mktime(_time.strptime(data["expiresAt"], "%Y-%m-%dT%H:%M:%S"))
                if _time.time() + 300 < expiry:
                    TOKEN = data["token"]
                    TOKEN_TYPE = data.get("tokenType", "Bearer")
                    print(f"  [OK] 已加载共享 token")
                    return
                else:
                    print("  [WARN] 共享 token 已过期")
            except Exception:
                print("  [WARN] token 过期时间解析失败")
        else:
            print("  [WARN] .auth_token.yaml 中没有有效 token")
    except FileNotFoundError:
        print("  [WARN] 未找到 .auth_token.yaml")
    except Exception as e:
        print(f"  [WARN] 读取 token 文件失败: {e}")

    print("  请运行: python scripts/auth_helper.py")
    print("  认证接口将不可用")


def login(client):
    """每个用户启动时调用 —— 使用共享 token（无需真实登录）"""
    global TOKEN, TOKEN_TYPE
    if TOKEN:
        print(f"  [OK] 使用共享 token")
    else:
        print("  [WARN] 无可用 token，认证接口将失败")


# ==================== 任务集 ====================

class OperationLogTasks(TaskSet):
    """操作日志管理 (6 接口) — tag: operation-log, 排除: --exclude-tags operation-log"""

    @tag('operation-log')
    @task(4)
    def list_logs(self):
        """分页查询 - 公开"""
        post_api(self.client, "/operation-log/list",
                 {"pageNum": 1, "pageSize": 10})

    @tag('operation-log')
    @task(3)
    def query_by_patient(self):
        """按病人ID查询 - 公开"""
        pid = pool_get('patientPool', 'patientId', 'patientId')
        get_api(self.client, f"/operation-log/patient/{pid}")

    @tag('operation-log')
    @task(2)
    def create(self):
        """创建操作记录 - 需认证"""
        if _skip_if_readonly(self): return
        data = post_api(self.client, "/operation-log/create", {
            "operationTime": "2026-06-17 10:00:00",
            "operationType": random.choice(["巡检", "维修", "保养", "校准"]),
            "type": random.choice(["常规操作", "紧急操作", "定期操作"]),
            "operator": random_name("操作员"),
            "patientId": pool_get('patientPool', 'patientId', 'patientId'),
            "operatorId": pool_get('opLogPool', 'operatorId', 'operatorId'),
        }, need_auth=True)
        if data and data.get("data"):
            CREATED_IDS["opLogId"] = data["data"]

    @tag('operation-log')
    @task(2)
    def query_by_id(self):
        """按ID查询 - 需认证"""
        oid = CREATED_IDS.get("opLogId") or pool_get('opLogPool', 'id', 'opLogId')
        get_api(self.client, f"/operation-log/{oid}", need_auth=True)

    @tag('operation-log')
    @task(1)
    def update(self):
        """更新 - 需认证"""
        if _skip_if_readonly(self): return
        oid = CREATED_IDS.get("opLogId") or pool_get('opLogPool', 'id', 'opLogId')
        post_api(self.client, "/operation-log/update", {
            "id": oid,
            "operationTime": "2026-06-17 12:00:00",
            "operationType": random.choice(["巡检-已更新", "维修-已更新"]),
            "type": random.choice(["常规操作-已更新", "紧急操作-已更新"]),
            "operator": random_name("操作员"),
            "patientId": pool_get('patientPool', 'patientId', 'patientId'),
            "operatorId": pool_get('opLogPool', 'operatorId', 'operatorId'),
        }, need_auth=True)

    @tag('operation-log')
    @tag('delete')
    @task(1)
    def delete(self):
        """删除 - 需认证（仅删除本 VU 创建的记录）"""
        if _skip_if_readonly(self): return
        oid = CREATED_IDS.get("opLogId")
        if not oid:
            return
        post_api(self.client, f"/operation-log/delete/{oid}",
                 {}, need_auth=True)
        CREATED_IDS.pop("opLogId", None)


class ScreeningTasks(TaskSet):
    """筛查管理 (6 接口)"""

    @task(4)
    def list_records(self):
        """分页查询 - 公开"""
        post_api(self.client, "/screen/record/list", random_page())

    @task(3)
    def query_by_patient(self):
        """按病人ID查询 - 公开"""
        pid = pool_get('patientPool', 'patientId', 'patientId')
        get_api(self.client, f"/screen/record/list/patient/{pid}")

    @tag('screen-create')
    @task(2)
    def create(self):
        """创建筛查记录 - 需认证"""
        if _skip_if_readonly(self): return
        import time
        ts = int(time.time() * 1000)
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        data = post_api(self.client, "/screen/record/create", {
            "patientName": random_name(),
            "idNo": f"ID{ts}{suffix}",
            "gender": random.choice([0, 1, 2]),
            "age": random.randint(18, 85),
            "screenNo": f"SC{ts}{suffix}",
            "screenProjectId": pool_get('screenRecordPool', 'screenProjectId', 'screenProjectId'),
            "screenDate": "2026-07-07",
            "bindCardDate": "2026-07-07",
            "bindCardNo": f"CARD{ts}{suffix}",
            "securityTestAnswerId": 0,
            "screenItemAnswerId": 0,
        }, need_auth=True)
        if data and data.get("data"):
            CREATED_IDS["screenRecordId"] = data["data"]

    @task(2)
    def query_detail(self):
        """获取详情 - 需认证"""
        sid = CREATED_IDS.get("screenRecordId") or pool_get('screenRecordPool', 'id', 'screenRecordId')
        get_api(self.client, f"/screen/record/detail/{sid}", need_auth=True)

    @task(1)
    def update(self):
        """更新 - 需认证"""
        if _skip_if_readonly(self): return
        sid = CREATED_IDS.get("screenRecordId") or pool_get('screenRecordPool', 'id', 'screenRecordId')
        post_api(self.client, "/screen/record/update", {
            "patientId": pool_get('patientPool', 'patientId', 'patientId'),
            "address": random.choice(["浙江省杭州市西湖区", "北京市朝阳区", "上海市浦东新区", "广东省广州市天河区"]),
            "emergencyContact": random_name("联系人"),
            "emergencyPhone": random_phone(),
        }, need_auth=True)

    @tag('delete')
    @task(1)
    def delete(self):
        """删除 - 需认证（仅删除本 VU 创建的记录）"""
        if _skip_if_readonly(self): return
        sid = CREATED_IDS.get("screenRecordId")
        if not sid:
            return
        post_api(self.client, f"/screen/record/delete/{sid}",
                 {}, need_auth=True)
        CREATED_IDS.pop("screenRecordId", None)


class SystemLogTasks(TaskSet):
    """系统日志管理 (2 接口)"""

    @tag('system-log')
    @task(4)
    def list_logs(self):
        """分页查询(默认) - 公开"""
        post_api(self.client, "/system/log/list", random_page())

    @tag('system-log')
    @task(3)
    def list_logs_filtered(self):
        """分页查询(按类型) - 公开"""
        params = random_page()
        params["type"] = random.choice(["ERROR", "WARN", "INFO", "DEBUG"])
        post_api(self.client, "/system/log/list", params)

    @tag('system-log')
    @task(2)
    def list_logs_search(self):
        """分页查询(关键字) - 公开"""
        params = random_page()
        params["keyword"] = random.choice(["登录", "创建", "删除", "更新", "查询", "认证"])
        post_api(self.client, "/system/log/list", params)

    @tag('system-log')
    @task(1)
    def query_detail(self):
        """获取详情 - 公开"""
        sid = pool_get('sysLogPool', 'id', 'sysLogId')
        get_api(self.client, f"/system/log/{sid}")


class FollowupTasks(TaskSet):
    """随访管理 (6 接口)"""

    @task(4)
    def list_records(self):
        """分页查询 - 公开"""
        post_api(self.client, "/followup/record/list", random_page())

    @task(3)
    def query_detail(self):
        """获取详情 - 公开"""
        rid = pool_get('followupPool', 'reportId', 'reportId')
        get_api(self.client, f"/followup/record/detail/{rid}")

    @task(2)
    def report(self):
        """打印报告 - 公开"""
        rid = pool_get('followupPool', 'reportId', 'reportId')
        get_api(self.client, f"/followup/record/report/{rid}")

    @task(2)
    def send_notification(self):
        """发送通知 - 公开"""
        post_api(self.client, "/followup/record/send-notification", {
            "patientId": pool_get('patientPool', 'patientId', 'patientId'),
            "content": random.choice([
                "您的随访报告已生成，请及时查看",
                "请按时参加下一次随访",
                "您的检查结果已出，请联系医生",
            ]),
            "isUrgent": random.choice([True, False]),
        })

    @task(1)
    def call_records(self):
        """查询呼叫记录 - 需认证"""
        pid = pool_get('patientPool', 'patientId', 'patientId')
        get_api(self.client, f"/followup/record/call-records/{pid}",
                need_auth=True)

    @task(1)
    def update(self):
        """修改随访记录 - 需认证"""
        if _skip_if_readonly(self): return
        rid = pool_get('followupPool', 'reportId', 'reportId')
        pid = pool_get('followupPool', 'patientId', 'followupPatientId')
        post_api(self.client, "/followup/record/update", {
            "reportId": rid,
            "patientId": pid,
            "address": random.choice(["浙江省杭州市西湖区", "北京市朝阳区", "上海市浦东新区"]),
            "emergencyContact": random_name("联系人"),
            "emergencyPhone": random_phone(),
            "followupLevel": random.choice(["一级", "二级", "三级"]),
            "followupCycle": random.choice(["每月", "每季", "每年"]),
            "patientDisease": random.choice(["肠癌术后", "肺癌术后", "胃癌术后"]),
            "positiveLevel": random.choice(["阳性", "阴性", "疑似"]),
            "interventionMeasures": random.choice(["定期复查", "药物治疗", "手术治疗"]),
            "interpretationResult": random.choice(["建议进一步检查", "结果正常", "需持续观察"]),
        }, need_auth=True)


class HardwareManageTasks(TaskSet):
    """硬件管理 (8 接口)"""

    @tag('hardware-list')
    @task(3)
    def list_records(self):
        """分页查询 - 公开, 翻页覆盖全量数据"""
        # 根据硬件池大小动态计算最大页码 (最小pageSize=5时)
        pool_size = len(REAL_DATA.get('hardwarePool', []))
        max_page = max(1, (pool_size + 4) // 5)  # 向上取整
        post_api(self.client, "/hardware-manage/list", random_page(max_page))

    @task(3)
    def query_all(self):
        """查询所有 - 公开"""
        get_api(self.client, "/hardware-manage/all")

    @task(2)
    def query_detail(self):
        """查询详情 - 公开"""
        hw_id = pool_get('hardwarePool', 'id', 'hardwareManageId')
        get_api(self.client, f"/hardware-manage/{hw_id}")

    @task(2)
    def query_by_hardware_no(self):
        """按硬件编号查询 - 公开"""
        from urllib.parse import quote
        hw_no = pool_get('hardwarePool', 'hardwareNo', 'hardwareNo')
        get_api(self.client, f"/hardware-manage/by-hardware-no/{quote(hw_no)}")

    @tag('hardware-create')
    @task(1)
    def create(self):
        """创建硬件记录 - 需认证"""
        if _skip_if_readonly(self): return
        import time
        # hardwareType 有效值仅 1 和 2 (从现有数据确认)
        hw_type = random.choice([1, 2])
        # hardwareNo 长度限制30位, 加6位随机串防冲突
        ts = str(int(time.time() * 1000))
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        hw_no = f"HW-{ts}-{suffix}"[:30]
        data = post_api(self.client, "/hardware-manage/create", {
            "hardwareNo": hw_no,
            "hardwareType": hw_type,
            "organizationId": pool_get('orgPool', 'id', 'orgId'),
        }, need_auth=True)
        if data and data.get("data"):
            CREATED_IDS["hardwareManageId"] = data["data"]
            CREATED_IDS["hardwareNo"] = hw_no

    @task(1)
    def update(self):
        """更新 - 需认证"""
        if _skip_if_readonly(self): return
        hw_id = CREATED_IDS.get("hardwareManageId") or pool_get('hardwarePool', 'id', 'hardwareManageId')
        hw_no = CREATED_IDS.get("hardwareNo") or pool_get('hardwarePool', 'hardwareNo', 'hardwareNo')
        post_api(self.client, "/hardware-manage/update", {
            "id": hw_id,
            "hardwareNo": hw_no,
            "hardwareType": random.choice([1, 2, 3]),
            "organizationId": pool_get('orgPool', 'id', 'orgId'),
        }, need_auth=True)

    @tag('delete')
    @task(1)
    def delete(self):
        """删除 - 需认证（仅删除本 VU 创建的记录）"""
        if _skip_if_readonly(self): return
        hw_id = CREATED_IDS.get("hardwareManageId")
        if not hw_id:
            return
        post_api(self.client, f"/hardware-manage/delete/{hw_id}",
                 {}, need_auth=True)
        CREATED_IDS.pop("hardwareManageId", None)

    @tag('delete')
    @task(1)
    def batch_delete(self):
        """批量删除 - 需认证（仅删除本 VU 创建的记录）"""
        if _skip_if_readonly(self): return
        hw_id = CREATED_IDS.get("hardwareManageId")
        if not hw_id:
            return
        post_api(self.client, "/hardware-manage/batch/delete",
                 [hw_id], need_auth=True)
        CREATED_IDS.pop("hardwareManageId", None)


class OrganizationTasks(TaskSet):
    """机构管理 (8 接口)"""

    @task(3)
    def list_records(self):
        """分页查询 - 公开"""
        post_api(self.client, "/organization/list", random_page())

    @task(3)
    def query_all(self):
        """查询所有 - 公开"""
        get_api(self.client, "/organization/all")

    @task(2)
    def query_detail(self):
        """查询详情 - 公开"""
        oid = pool_get('orgPool', 'id', 'orgId')
        get_api(self.client, f"/organization/detail/{oid}")

    @task(2)
    def search(self):
        """按名称搜索 - 公开"""
        from urllib.parse import quote
        org = pool_item('orgPool')
        name = org.get('orgName', REAL_DATA.get('orgName', ''))
        get_api(self.client, f"/organization/search?orgName={quote(name)}")

    @task(1)
    def create(self):
        """新增机构 - 需认证"""
        if _skip_if_readonly(self): return
        import time
        data = post_api(self.client, "/organization/create", {
            "orgName": f"测试机构-PERF-{int(time.time() * 1000)}",
            "orgType": random.choice([1, 2]),
            "regionId": pool_get('orgPool', 'id', 'orgId'),
            "contactPerson": random_name("联系人"),
            "contactInfo": random_phone(),
        }, need_auth=True)
        if data and data.get("data"):
            CREATED_IDS["orgId"] = data["data"]

    @task(1)
    def update(self):
        """更新 - 需认证"""
        if _skip_if_readonly(self): return
        org_id = CREATED_IDS.get("orgId") or pool_get('orgPool', 'id', 'orgId')
        post_api(self.client, "/organization/update", {
            "id": org_id,
            "orgType": random.choice([1, 2]),
            "regionId": pool_get('orgPool', 'id', 'orgId'),
            "contactPerson": random_name("联系人"),
            "contactInfo": random_phone(),
        }, need_auth=True)

    @tag('delete')
    @task(1)
    def delete(self):
        """删除 - 需认证（仅删除本 VU 创建的记录）"""
        if _skip_if_readonly(self): return
        org_id = CREATED_IDS.get("orgId")
        if not org_id:
            return
        post_api(self.client, f"/organization/delete/{org_id}",
                 {}, need_auth=True)
        CREATED_IDS.pop("orgId", None)

    @tag('delete')
    @task(1)
    def batch_delete(self):
        """批量删除 - 需认证（仅删除本 VU 创建的记录）"""
        if _skip_if_readonly(self): return
        oid = CREATED_IDS.get("orgId")
        if not oid:
            return
        post_api(self.client, "/organization/batch/delete",
                 [oid], need_auth=True)
        CREATED_IDS.pop("orgId", None)


class RoleTasks(TaskSet):
    """角色管理 (9 接口)"""

    @task(3)
    def list_roles(self):
        """分页查询 - 公开"""
        post_api(self.client, "/role/list", random_page())

    @task(3)
    def query_all(self):
        """查询所有 - 公开"""
        get_api(self.client, "/role/all")

    @task(2)
    def query_detail(self):
        """查询详情 - 公开"""
        rid = pool_get('rolePool', 'id', 'roleId')
        get_api(self.client, f"/role/detail/{rid}")

    @task(2)
    def query_function_permissions(self):
        """获取菜单权限 - 公开"""
        rid = pool_get('rolePool', 'id', 'roleId')
        get_api(self.client, f"/role/function-permissions/{rid}")

    @task(1)
    def create(self):
        """添加角色 - 需认证"""
        if _skip_if_readonly(self): return
        data = post_api(self.client, "/role/add", {
            "roleName": f"perf_{random_str(6)}",
            "roleKey": f"perf_{random_str(6)}",
            "description": random.choice(["压测创建", "自动化测试角色", "临时角色"]),
            "dataScope": random.choice([1, 2]),
            "status": 1,
        }, need_auth=True)
        if data and data.get("data"):
            CREATED_IDS["roleId"] = data["data"]

    @task(1)
    def update(self):
        """更新 - 需认证"""
        if _skip_if_readonly(self): return
        rid = pool_get('rolePool', 'id', 'roleId')
        post_api(self.client, "/role/update", {
            "id": rid,
            "roleName": f"压测角色-{random_str(4)}",
            "roleKey": f"perf_role_{random_str(4)}",
            "description": random.choice(["压测更新", "已更新角色"]),
            "dataScope": random.choice([1, 2]),
            "status": 1,
        }, need_auth=True)

    @task(1)
    def update_function_permission(self):
        """更新菜单权限 - 需认证"""
        if _skip_if_readonly(self): return
        rid = pool_get('rolePool', 'id', 'roleId')
        post_api(self.client, "/role/function-permission/update", {
            "roleId": rid,
            "functionPermissionIds": [],
        }, need_auth=True)

    @task(1)
    def update_data_permission(self):
        """更新数据权限 - 需认证"""
        if _skip_if_readonly(self): return
        rid = pool_get('rolePool', 'id', 'roleId')
        post_api(self.client, "/role/data-permission/update", {
            "roleId": rid,
            "dataScope": random.choice([1, 2]),
        }, need_auth=True)

    @tag('delete')
    @task(1)
    def delete(self):
        """删除 - 需认证（仅删除本 VU 创建的记录）"""
        if _skip_if_readonly(self): return
        rid = CREATED_IDS.get("roleId")
        if not rid:
            return
        post_api(self.client, f"/role/delete/{rid}",
                 {}, need_auth=True)
        CREATED_IDS.pop("roleId", None)


class DashboardTasks(TaskSet):
    """仪表盘管理 (7 接口)"""

    @task(2)
    def screen_statistics(self):
        """总筛查数量统计 - 公开"""
        get_api(self.client, "/dashboard/statistics/screen")

    @task(2)
    def screen_daily(self):
        """筛查人员日统计 - 公开"""
        from datetime import datetime, timedelta
        end_date = datetime(2026, 6, 24) - timedelta(days=random.randint(0, 7))
        start_date = end_date - timedelta(days=random.randint(3, 30))
        end = end_date.strftime("%Y-%m-%d")
        start = start_date.strftime("%Y-%m-%d")
        get_api(self.client, f"/dashboard/statistics/screen-daily?startDate={start}&endDate={end}")

    @task(2)
    def registration_statistics(self):
        """总报名数量统计 - 公开"""
        get_api(self.client, "/dashboard/statistics/registration")

    @task(2)
    def org_ranking_month(self):
        """机构筛查排行(月) - 公开"""
        get_api(self.client, f"/dashboard/statistics/org-ranking?rankType={random.choice([1, 2])}")

    @task(1)
    def org_ranking_quarter(self):
        """机构筛查排行(季) - 公开"""
        get_api(self.client, f"/dashboard/statistics/org-ranking?rankType={random.choice([1, 2])}")

    @task(2)
    def hardware_bind_statistics(self):
        """总绑卡数量统计 - 公开"""
        get_api(self.client, "/dashboard/statistics/hardware-bind")

    @task(2)
    def hardware_bind_daily(self):
        """硬件绑定日统计 - 公开"""
        from datetime import datetime, timedelta
        end_date = datetime(2026, 6, 24) - timedelta(days=random.randint(0, 7))
        start_date = end_date - timedelta(days=random.randint(3, 30))
        end = end_date.strftime("%Y-%m-%d")
        start = start_date.strftime("%Y-%m-%d")
        get_api(self.client, f"/dashboard/statistics/hardware-bind-daily?startDate={start}&endDate={end}")

    @task(2)
    def gender_ratio(self):
        """性别比例统计 - 公开"""
        get_api(self.client, "/dashboard/statistics/gender-ratio")


class PatientTasks(TaskSet):
    """病人管理 (6 接口)"""

    @task(3)
    def list_patients(self):
        """分页查询 - 公开"""
        post_api(self.client, "/patient/list", random_page())

    @task(2)
    def query_detail(self):
        """查询详情 - 公开"""
        pid = pool_get('patientPool', 'patientId', 'patientId')
        get_api(self.client, f"/patient/{pid}")

    @task(2)
    def query_by_idcard(self):
        """根据身份证号查询 - 公开"""
        pat = pool_item('patientPool')
        id_no = pat.get('idNo', REAL_DATA.get('idNo', ''))
        get_api(self.client, f"/patient/by-idcard/{id_no}")

    @task(1)
    def create(self):
        """创建病人 - 需认证"""
        if _skip_if_readonly(self): return
        import time
        data = post_api(self.client, "/patient/create", {
            "name": random_name("病人"),
            "age": random.randint(18, 80),
            "gender": random.choice([0, 1]),
            "idNo": f"ID{int(time.time() * 1000)}",
            "address": random.choice(["浙江省杭州市西湖区", "北京市朝阳区", "上海市浦东新区"]),
            "emergencyContact": random_name("联系人"),
            "emergencyPhone": random_phone(),
        }, need_auth=True)
        if data and data.get("data"):
            CREATED_IDS["patientId"] = data["data"]

    @task(1)
    def update(self):
        """更新 - 需认证"""
        if _skip_if_readonly(self): return
        pid = pool_get('patientPool', 'patientId', 'patientId')
        post_api(self.client, "/patient/update", {
            "patientId": pid,
            "name": random_name("病人"),
            "age": random.randint(18, 80),
            "gender": random.choice([0, 1]),
            "address": random.choice(["更新后地址A", "更新后地址B", "更新后地址C"]),
            "emergencyContact": random_name("联系人"),
            "emergencyPhone": random_phone(),
        }, need_auth=True)

    @tag('delete')
    @task(1)
    def delete(self):
        """删除 - 需认证（仅删除本 VU 创建的记录）"""
        if _skip_if_readonly(self): return
        pid = CREATED_IDS.get("patientId")
        if not pid:
            return
        post_api(self.client, f"/patient/delete/{pid}",
                 {}, need_auth=True)
        CREATED_IDS.pop("patientId", None)


class ProjectTasks(TaskSet):
    """项目管理 (8 接口)"""

    @task(3)
    def list_records(self):
        """分页查询 - 公开"""
        post_api(self.client, "/project/list", random_page())

    @task(3)
    def query_all(self):
        """查询所有 - 公开"""
        get_api(self.client, "/project/all")

    @task(2)
    def query_detail(self):
        """查询详情 - 公开"""
        pid = pool_get('projectPool', 'id', 'projectId')
        get_api(self.client, f"/project/detail/{pid}")

    @task(1)
    def create(self):
        """创建项目 - 需认证"""
        if _skip_if_readonly(self): return
        import time
        proj = pool_item('projectPool')
        data = post_api(self.client, "/project/create", {
            "projectName": f"压测项目-{int(time.time() * 1000)}",
            "projectStatus": random.choice([0, 1]),
            "screenDate": "2026-06-23",
            "hospitalIds": proj.get('hospitalIds', REAL_DATA.get('hospitalIds', [])),
            "organizationId": proj.get('organizationId', REAL_DATA.get('projectOrgId', 1)),
            "regionId": proj.get('regionId', REAL_DATA.get('regionId', 1)),
        }, need_auth=True)
        if data and data.get("data"):
            CREATED_IDS["projectId"] = data["data"]

    @task(1)
    def update(self):
        """更新 - 需认证"""
        if _skip_if_readonly(self): return
        pid = CREATED_IDS.get("projectId") or pool_get('projectPool', 'id', 'projectId')
        proj = pool_item('projectPool')
        post_api(self.client, "/project/update", {
            "id": pid,
            "projectName": f"压测项目-已更新-{random_str(4)}",
            "projectStatus": random.choice([0, 1]),
            "screenDate": "2026-06-24",
            "hospitalIds": proj.get('hospitalIds', REAL_DATA.get('hospitalIds', [])),
            "organizationId": proj.get('organizationId', REAL_DATA.get('projectOrgId', 1)),
            "regionId": proj.get('regionId', REAL_DATA.get('regionId', 1)),
        }, need_auth=True)

    @task(1)
    def update_status(self):
        """更新状态 - 需认证"""
        if _skip_if_readonly(self): return
        pid = CREATED_IDS.get("projectId") or pool_get('projectPool', 'id', 'projectId')
        post_api(self.client, f"/project/update/status?id={pid}&status={random.choice([0, 1])}",
                 {}, need_auth=True)

    @tag('delete')
    @task(1)
    def delete(self):
        """删除 - 需认证（仅删除本 VU 创建的记录）"""
        if _skip_if_readonly(self): return
        pid = CREATED_IDS.get("projectId")
        if not pid:
            return
        post_api(self.client, f"/project/delete/{pid}",
                 {}, need_auth=True)
        CREATED_IDS.pop("projectId", None)

    @tag('delete')
    @task(1)
    def batch_delete(self):
        """批量删除 - 需认证（仅删除本 VU 创建的记录）"""
        if _skip_if_readonly(self): return
        pid = CREATED_IDS.get("projectId")
        if not pid:
            return
        post_api(self.client, "/project/delete/batch",
                 [pid], need_auth=True)
        CREATED_IDS.pop("projectId", None)


class SecurityTestTasks(TaskSet):
    """安全测试管理 (2 接口)"""

    @task(3)
    def query_answers(self):
        """查询答题记录 - 公开"""
        pid = pool_get('patientPool', 'patientId', 'patientId')
        get_api(self.client, f"/security-test/answers/{pid}")

    @task(2)
    def save_answers(self):
        """保存答题记录 - 需认证"""
        if _skip_if_readonly(self): return
        pid = pool_get('patientPool', 'patientId', 'patientId')
        post_api(self.client, "/security-test/answers", {
            "patientId": pid,
            "submitTime": "2026-06-23T10:00:00",
            "answers": [
                {"questionNo": 1, "question": "您是否有高血压病史？", "answer": random.choice([0, 1])},
                {"questionNo": 2, "question": "您是否有糖尿病病史？", "answer": random.choice([0, 1])},
                {"questionNo": 3, "question": "您是否有心脏病史？", "answer": random.choice([0, 1])},
            ],
        }, need_auth=True)


class SurveyTasks(TaskSet):
    """调查问卷管理 (10 接口)"""

    @tag('survey')
    @task(2)
    def list_surveys(self):
        """分页查询 - 公开"""
        post_api(self.client, "/survey/list", random_page())

    @tag('survey')
    @task(2)
    def list_enabled(self):
        """查询启用问卷 - 公开"""
        get_api(self.client, "/survey/list/enabled")

    @tag('survey')
    @task(2)
    def query_detail(self):
        """查询详情 - 公开"""
        sid = pool_get('surveyPool', 'id', 'surveyId')
        get_api(self.client, f"/survey/detail/{sid}")

    @tag('survey')
    @task(2)
    def query_questions(self):
        """查询题目列表 - 公开"""
        sid = pool_get('surveyPool', 'id', 'surveyId')
        get_api(self.client, f"/survey/questions/{sid}")

    @tag('survey')
    @task(1)
    def query_answers(self):
        """查询答卷 - 公开"""
        sid = pool_get('surveyPool', 'id', 'surveyId')
        get_api(self.client, f"/survey/answers/{sid}")

    @tag('survey')
    @task(1)
    def create(self):
        """创建问卷 - 需认证"""
        if _skip_if_readonly(self): return
        import time
        question_count = random.randint(2, 5)
        questions = []
        for i in range(question_count):
            questions.append({
                "content": f"问题{i+1}: 您对服务满意吗？",
                "questionType": random.choice([1, 2]),
                "options": [
                    {"key": "A", "label": random.choice(["非常满意", "是", "很好"])},
                    {"key": "B", "label": random.choice(["满意", "否", "一般"])},
                    {"key": "C", "label": random.choice(["一般", "不确定", "较差"])},
                    {"key": "D", "label": random.choice(["不满意", "", "很差"])},
                ],
                "sortOrder": i + 1,
            })
        data = post_api(self.client, "/survey/create", {
            "title": f"压测问卷-{int(time.time() * 1000)}",
            "questions": questions,
        }, need_auth=True)
        if data and data.get("data"):
            CREATED_IDS["surveyId"] = data["data"]

    @tag('survey')
    @task(1)
    def update(self):
        """更新 - 需认证"""
        if _skip_if_readonly(self): return
        sid = CREATED_IDS.get("surveyId") or pool_get('surveyPool', 'id', 'surveyId')
        post_api(self.client, "/survey/update", {
            "id": sid,
            "title": f"压测问卷-已更新-{random_str(4)}",
            "status": random.choice([0, 1]),
        }, need_auth=True)

    @tag('survey')
    @task(1)
    def update_status(self):
        """更新状态 - 需认证"""
        if _skip_if_readonly(self): return
        sid = CREATED_IDS.get("surveyId") or pool_get('surveyPool', 'id', 'surveyId')
        post_api(self.client, f"/survey/update/status?id={sid}&status={random.choice([0, 1])}",
                 {}, need_auth=True)

    @tag('survey')
    @task(1)
    def submit(self):
        """提交答卷 - 需认证"""
        if _skip_if_readonly(self): return
        sid = CREATED_IDS.get("surveyId") or pool_get('surveyPool', 'id', 'surveyId')
        uid = pool_get('patientPool', 'patientId', 'patientId')
        post_api(self.client, "/survey/submit", {
            "userId": uid,
            "surveyId": sid,
            "answerJson": {"q_1": ["A"], "q_2": ["B"]},
        }, need_auth=True)

    @tag('survey')
    @tag('delete')
    @task(1)
    def delete(self):
        """删除 - 需认证（仅删除本 VU 创建的记录）"""
        if _skip_if_readonly(self): return
        sid = CREATED_IDS.get("surveyId")
        if not sid:
            return
        post_api(self.client, f"/survey/delete/{sid}",
                 {}, need_auth=True)
        CREATED_IDS.pop("surveyId", None)

    @tag('survey')
    @tag('delete')
    @task(1)
    def batch_delete(self):
        """批量删除 - 需认证（仅删除本 VU 创建的记录）"""
        if _skip_if_readonly(self): return
        sid = CREATED_IDS.get("surveyId")
        if not sid:
            return
        post_api(self.client, "/survey/delete/batch",
                 [sid], need_auth=True)
        CREATED_IDS.pop("surveyId", None)


class UserTasks(TaskSet):
    """用户管理 (5 接口)"""

    @task(3)
    def list_users(self):
        """分页查询 - 公开"""
        get_api(self.client, f"/user/list?pageNum={random.randint(1,5)}&pageSize={random.choice([5,10,15,20])}")

    @task(3)
    def list_by_username(self):
        """按用户名查询 - 公开"""
        from urllib.parse import quote
        u = pool_item('userPool')
        name = u.get('username', REAL_DATA.get('username', ''))
        get_api(self.client, f"/user/list?pageNum=1&pageSize=10&username={quote(name)}")

    @task(2)
    def query_detail(self):
        """查询详情 - 公开"""
        uid = pool_get('userPool', 'id', 'userId')
        get_api(self.client, f"/user/detail/{uid}")

    @tag('user-create')
    @task(1)
    def create(self):
        """创建用户 - 需认证"""
        if _skip_if_readonly(self): return
        import time
        data = post_api(self.client, "/user/create", {
            "username": random_name("用户"),
            "loginAccount": f"perf_{int(time.time() * 1000)}",
            "phone": random_phone(),
            "orgId": pool_get('orgPool', 'id', 'orgId'),
            "status": random.choice([0, 1]),
            "roleIds": [pool_get('rolePool', 'id', 'roleId')],
        }, need_auth=True)
        if data and data.get("data"):
            CREATED_IDS["userId"] = data["data"]

    @task(1)
    def update(self):
        """更新 - 需认证"""
        if _skip_if_readonly(self): return
        uid = pool_get('userPool', 'id', 'userId')
        post_api(self.client, "/user/update", {
            "id": uid,
            "username": random_name("用户"),
            "loginAccount": REAL_DATA.get("userPhone", ""),
            "phone": REAL_DATA.get("userPhone", ""),
            "roleIds": [pool_get('rolePool', 'id', 'roleId')],
        }, need_auth=True)

    @tag('delete')
    @task(1)
    def delete(self):
        """删除 - 需认证（仅删除本 VU 创建的记录）"""
        if _skip_if_readonly(self): return
        uid = CREATED_IDS.get("userId")
        if not uid:
            return
        post_api(self.client, f"/user/delete/{uid}",
                 {}, need_auth=True)
        CREATED_IDS.pop("userId", None)


class ApiUser(HttpUser):
    """API 用户 —— 80% 只读 + 20% 读写，模拟真实流量比例"""

    wait_time = between(1, 3)

    READ_ONLY_RATIO = 0.8  # 只读用户占比

    tasks = {
        UserTasks: 2,
        SurveyTasks: 2,
        SecurityTestTasks: 2,
        ProjectTasks: 3,
        PatientTasks: 3,
        DashboardTasks: 3,
        FollowupTasks: 3,
        ScreeningTasks: 3,
        HardwareManageTasks: 3,
        OrganizationTasks: 3,
        RoleTasks: 3,
        SystemLogTasks: 2,
        OperationLogTasks: 2,
    }

    def on_start(self):
        self.is_readonly = random.random() < self.READ_ONLY_RATIO
        role = "只读" if self.is_readonly else "读写"
        print(f"  [{role}] VU 启动")
        login(self.client)


# ==================== 启动事件 ====================

@events.init.add_listener
def on_locust_init(environment, **kwargs):
    global _prom_started

    # 启动 Prometheus 指标服务 (端口 9091) — 必须在其他初始化之前启动
    if not _prom_started:
        with _prom_lock:
            if not _prom_started:
                try:
                    start_http_server(9091, registry=_prom_registry)
                    _prom_started = True
                    print(f"  [Prometheus] 指标端点: http://0.0.0.0:9091/metrics\n")
                except Exception as e:
                    print(f"  [Prometheus] 启动失败: {e}\n")

    base = get_base_url()
    print(f"\n  {'='*50}")
    print(f"  目标服务器 : {base}")
    print(f"  登录账号   : {LOGIN_PHONE}")
    print(f"  接口总数   : 83 个 (公开 + 认证)")
    print(f"  {'='*50}\n")
    load_shared_token()
    fetch_real_data(base)

    # 启动 VU 数更新线程
    if environment.runner:
        t = threading.Thread(target=_update_vus, args=(environment,), daemon=True)
        t.start()
