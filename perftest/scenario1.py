"""
压测场景1: 日间高峰混合压测（排除用户登录 + 提交问卷）
=====================================================
按文档定义, 聚焦 5 个核心接口:

  PT-MIX-002  创建筛查记录    /screen/record/create         25%  → 权重5
  PT-MIX-003  查询病人信息    /patient/list                 20%  → 权重4
  PT-MIX-004  分页查询筛查记录 /screen/record/list          15%  → 权重3
  PT-MIX-006  查看仪表盘统计  /dashboard/statistics/screen  10%  → 权重2
  PT-MIX-007  查询机构信息    /organization/search           5%  → 权重1

启动方式:
  locust -f perftest/scenario1.py                          (Web UI, 手动设 VU)
  locust -f perftest/scenario1.py --headless -u 200 -r 10 -t 10m --host http://your-api-server:8082

数据准备: 启动前先运行 python scripts/fetch_real_data.py

VU 配置 (参考文档):
  起始 50 VU, 爬升至 200 VU, 持续 10 分钟
  建议: locust -f perftest/scenario1.py --headless -u 200 -r 15 -t 10m --host http://your-api-server:8082
"""

import json
import os
import random
import string
from iniconfig import IniConfig
from locust import HttpUser, TaskSet, task, between, events

# ==================== 工具函数 ====================

def random_str(length=6):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


def random_phone():
    return f"138{''.join(random.choices(string.digits, k=8))}"


def random_name(prefix=""):
    surnames = ["张", "李", "王", "赵", "陈", "刘", "黄", "周", "吴", "郑"]
    return f"{random.choice(surnames)}{prefix}{random_str(2)}"


def pool_get(pool_key, field, fallback_key=None):
    pool = REAL_DATA.get(pool_key, [])
    if pool:
        return random.choice(pool).get(field)
    if fallback_key:
        return REAL_DATA.get(fallback_key)
    return REAL_DATA.get(field)


def pool_item(pool_key):
    pool = REAL_DATA.get(pool_key, [])
    if pool:
        return random.choice(pool)
    return {}


# ==================== 配置 ====================

def get_base_url():
    ini_path = os.path.join(os.path.dirname(__file__), "..", "pytest.ini")
    ini = IniConfig(ini_path)
    if "base_url" in ini:
        return dict(ini["base_url"].items())["base_url"]
    return "http://your-api-server:8082"


TOKEN = None
TOKEN_TYPE = "Bearer"

REAL_DATA = {
    "patientId": 1, "patientName": "",
    "screenRecordId": 1, "screenProjectId": 1,
    "orgId": 1, "orgName": "",
    "patientPool": [], "screenRecordPool": [], "orgPool": [],
}

CREATED_IDS = {}


# ==================== 数据加载 ====================

def fetch_real_data():
    global REAL_DATA
    data_file = os.path.join(os.path.dirname(__file__), "real_data.json")
    if os.path.exists(data_file):
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            REAL_DATA.update(loaded)
            pool_info = ", ".join(
                f"{k}={len(v)}条" for k, v in loaded.items() if k.endswith("Pool") and isinstance(v, list)
            )
            print(f"  [OK] 已加载 real_data.json ({len(loaded)} 字段)")
            print(f"  数据池: {pool_info}")
        except Exception as e:
            print(f"  [WARN] 读取 real_data.json 失败: {e}")
    else:
        print(f"  [WARN] real_data.json 不存在，请先运行: python scripts/fetch_real_data.py")


# ==================== 认证 ====================

def load_shared_token():
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
            except Exception:
                pass
    except FileNotFoundError:
        pass
    print("  [WARN] 无有效 token，创建筛查将失败。请运行: python scripts/auth_helper.py")


# ==================== 请求工具 ====================

def auth_headers():
    if TOKEN:
        return {"Authorization": f"{TOKEN_TYPE} {TOKEN}"}
    return {}


def post_api(client, url, body, need_auth=False, name=None):
    headers = {"Content-Type": "application/json"}
    if need_auth:
        headers.update(auth_headers())
    with client.post(url, data=json.dumps(body), headers=headers,
                     name=name or url, catch_response=True) as resp:
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


def get_api(client, url, name=None):
    with client.get(url, name=name or url, catch_response=True) as resp:
        if resp.status_code == 200:
            try:
                data = resp.json()
                if data.get("success"):
                    resp.success()
                    return data
            except Exception:
                resp.failure("响应非JSON")
        else:
            resp.failure(f"HTTP {resp.status_code}")
    return None


# ==================== 场景1 任务集 ====================

class Scenario1Tasks(TaskSet):
    """
    日间高峰混合压测 — 5 个核心接口
    权重分配 (对应文档 PT-MIX-002~007，排除001/005):
      create_screen  33%  @task(5)
      patient_list   27%  @task(4)
      screen_list    20%  @task(3)
      dashboard       13%  @task(2)
      org_search      7%   @task(1)
    """

    # ── PT-MIX-002: 创建筛查记录 (33%) ──
    @task(5)
    def create_screen_record(self):
        """创建筛查记录 - 需认证, 参数全覆盖"""
        import time
        ts = int(time.time() * 1000)
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        patient_name = random_name()
        id_no = f"ID{ts}{suffix}"
        age = random.randint(18, 85)
        gender = random.choice([0, 1, 2])
        screen_project_id = pool_get('screenRecordPool', 'screenProjectId', 'screenProjectId')
        from datetime import datetime, timedelta
        today = datetime.now()
        screen_date = (today - timedelta(days=random.randint(0, 30))).strftime("%Y-%m-%d")
        data = post_api(self.client, "/screen/record/create", {
            "patientName": patient_name, "idNo": id_no, "gender": gender,
            "age": age, "screenNo": f"SC{ts}{suffix}",
            "screenProjectId": screen_project_id,
            "screenDate": screen_date, "bindCardDate": screen_date,
            "bindCardNo": f"CARD{ts}{suffix}",
            "securityTestAnswerId": 0, "screenItemAnswerId": 0,
        }, need_auth=True, name="POST /screen/record/create")
        if data and data.get("data"):
            CREATED_IDS["screenRecordId"] = data["data"]

    # ── PT-MIX-003: 查询病人信息 (27%) ──
    @task(4)
    def query_patient_list(self):
        """分页查询病人 - 公开, 多页+多size"""
        page = random.randint(1, 5)
        size = random.choice([5, 10, 15, 20])
        get_api(self.client,
                f"/patient/list?pageNum={page}&pageSize={size}",
                name="GET /patient/list")

    # ── PT-MIX-004: 分页查询筛查记录 (20%) ──
    @task(3)
    def query_screen_list(self):
        """分页查询筛查记录 - 公开, 多页+多size"""
        page = random.randint(1, 5)
        size = random.choice([5, 10, 15, 20])
        post_api(self.client, "/screen/record/list",
                 {"pageNum": page, "pageSize": size},
                 name="POST /screen/record/list")

    # ── PT-MIX-006: 查看仪表盘统计 (13%) ──
    @task(2)
    def query_dashboard_screen(self):
        """筛查统计 - 公开"""
        get_api(self.client, "/dashboard/statistics/screen",
                name="GET /dashboard/statistics/screen")

    # ── PT-MIX-007: 查询机构信息 (7%) ──
    @task(1)
    def query_org_search(self):
        """按名称搜索机构 - 公开, 随机搜索词"""
        from urllib.parse import quote
        # 随机选取搜索策略: 60%用真实机构名, 40%用随机关键词
        if random.random() < 0.6:
            org = pool_item('orgPool')
            keyword = org.get('orgName', REAL_DATA.get('orgName', '医院'))
        else:
            keyword = random.choice(["医院", "中心", "卫生院", "社区", "机构", "text"])
        get_api(self.client,
                f"/organization/search?orgName={quote(str(keyword))}",
                name="GET /organization/search")


# ==================== 用户类 ====================

class DaytimePeakUser(HttpUser):
    """日间高峰混合压测用户 (场景1)

    CLI 示例:
      locust -f perftest/scenario1.py --headless -u 200 -r 15 -t 10m --host http://your-api-server:8082
    """

    wait_time = between(1, 2)
    tasks = [Scenario1Tasks]

    def on_start(self):
        print(f"  [场景1] VU 启动")
        # 注: 登录认证在压测场景中已排除(auth/sms/login),
        # 创建筛查记录的 token 由 auth_helper.py 预获取的共享 token 提供


# ==================== 启动事件 ====================

@events.init.add_listener
def on_locust_init(environment, **kwargs):
    base = get_base_url()
    print(f"\n  {'='*55}")
    print(f"  压测场景1: 日间高峰混合 (排除登录+提交问卷)")
    print(f"  目标服务器: {base}")
    print(f"  接口数量: 5 个 (创建筛查/查病人/查筛查/仪表盘/查机构)")
    print(f"  推荐命令: locust -f perftest/scenario1.py --headless -u 200 -r 15 -t 10m --host {base}")
    print(f"  {'='*55}\n")
    load_shared_token()
    fetch_real_data()
