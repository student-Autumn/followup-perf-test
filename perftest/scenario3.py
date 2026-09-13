"""
压测场景3: 管理后台混合压测（排除管理员登录 + 操作日志 + 系统日志）
=============================================================
按文档定义, 聚焦 5 个核心接口:

  PT-MIX-016  分页查询用户列表  /user/list                 20% → 权重4
  PT-MIX-017  更新角色权限      /role/update               15% → 权重3
  PT-MIX-018  机构管理操作      /organization/list         15% → 权重3
  PT-MIX-019  硬件绑定操作      /hardware-manage/create    15% → 权重3
  PT-MIX-022  数据权限配置      /permission/data/update     5% → 权重1

启动方式:
  locust -f perftest/scenario3.py --headless -u 100 -r 5 -t 10m --host http://your-api-server:8082 --html report/scenario3_report.html --csv report/scenario3

VU 配置 (参考文档):
  起始 20 VU, 爬升至 100 VU, 持续 10 分钟
"""

import json
import os
import random
import string
from iniconfig import IniConfig
from locust import HttpUser, TaskSet, task, between, events


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

REAL_DATA = {}

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
    print("  [WARN] 无有效 token，认证接口将失败。请运行: python scripts/auth_helper.py")


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


def get_api(client, url, need_auth=False, name=None):
    headers = {}
    if need_auth:
        headers.update(auth_headers())
    with client.get(url, headers=headers, name=name or url, catch_response=True) as resp:
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


# ==================== 场景3 任务集 ====================

class Scenario3Tasks(TaskSet):
    """
    管理后台混合压测 — 5 个核心接口
    权重分配 (对应文档 PT-MIX-016~022，排除015/020/021):
      user-list           29%  @task(4)
      role-update         21%  @task(3)
      org-list            21%  @task(3)
      hardware-create     21%  @task(3)
      permission-update    7%  @task(1)
    """

    # ── PT-MIX-016: 分页查询用户列表 (29%) ──
    @task(4)
    def query_user_list(self):
        """分页查询用户列表 - GET, 8个筛选参数全覆盖, 4种搜索模式"""
        from urllib.parse import quote
        # 根据用户池大小动态计算最大页码
        pool_size = len(REAL_DATA.get('userPool', []))
        max_page = max(1, (pool_size + 4) // 5)
        page = random.randint(1, max(1, max_page))
        size = random.choice([5, 10, 15, 20, 50])

        params = f"pageNum={page}&pageSize={size}"
        # 按概率选择搜索模式
        mode = random.random()
        if mode < 0.25:
            # 模式1: 仅分页
            pass
        elif mode < 0.5:
            # 模式2: 单条件筛选
            rec = pool_item('userPool')
            field = random.choice(["username", "loginAccount", "orgName", "status", "roleId"])
            if field == "username" and rec.get("username"):
                params += f"&username={quote(str(rec['username']))}"
            elif field == "loginAccount" and rec.get("loginAccount"):
                params += f"&loginAccount={quote(str(rec['loginAccount']))}"
            elif field == "orgName":
                org_name = pool_get('orgPool', 'orgName', 'orgName')
                if org_name:
                    params += f"&orgName={quote(str(org_name))}"
            elif field == "status":
                params += f"&status={random.choice([0, 1])}"
            elif field == "roleId":
                role_id = pool_get('rolePool', 'id', 'roleId')
                if role_id:
                    params += f"&roleId={role_id}"
        elif mode < 0.75:
            # 模式3: 组合筛选 (2-3个条件)
            rec = pool_item('userPool')
            count = 0
            if rec.get("username") and random.random() < 0.6:
                params += f"&username={quote(str(rec['username']))}"
                count += 1
            if random.random() < 0.5:
                params += f"&status={random.choice([0, 1])}"
                count += 1
            if count < 2:
                org_name = pool_get('orgPool', 'orgName', 'orgName')
                if org_name:
                    params += f"&orgName={quote(str(org_name))}"
        else:
            # 模式4: 角色筛选 + 状态
            role_id = pool_get('rolePool', 'id', 'roleId')
            if role_id:
                params += f"&roleId={role_id}"
            params += f"&status={random.choice([1, 1, 1, 0])}"  # 75%正常, 25%禁用

        get_api(self.client, f"/user/list?{params}",
                name="GET /user/list")

    # ── PT-MIX-017: 更新角色权限 (21%) ──
    @task(3)
    def update_role(self):
        """更新角色 - 需认证, 9个参数全覆盖"""
        rec = pool_item('rolePool')
        role_id = rec.get('id') or REAL_DATA.get('roleId')

        body = {
            "id": role_id,
            "roleName": rec.get('roleName') or f"压测角色{random_str(3)}",
            "roleKey": rec.get('roleKey') or f"perf_role_{random_str(4)}",
            "description": random.choice([
                "压测-系统管理员角色",
                "压测-机构管理员角色",
                "压测-普通筛查员角色",
                "压测-随访员角色",
                "压测-数据查看员角色",
            ]),
            "dataScope": random.choice([1, 2, 3]),
            "isDefault": random.choice([0, 0, 0, 1]),  # 75%非默认
            "status": random.choice([0, 1]),
            "dataPermissionId": random.randint(1, 100) if random.random() < 0.3 else 0,
            "functionPermissionIds": [],
        }
        post_api(self.client, "/role/update", body,
                 need_auth=True, name="POST /role/update")

    # ── PT-MIX-018: 机构管理操作 (21%) ──
    @task(3)
    def query_org_list(self):
        """分页查询机构列表 - POST, 6个筛选参数全覆盖, 4种搜索模式"""
        pool_size = len(REAL_DATA.get('orgPool', []))
        max_page = max(1, (pool_size + 4) // 5)
        body = {
            "pageNum": random.randint(1, max(1, max_page)),
            "pageSize": random.choice([5, 10, 15, 20, 50]),
        }
        mode = random.random()
        if mode < 0.25:
            # 模式1: 仅分页
            pass
        elif mode < 0.5:
            # 模式2: 单条件
            field = random.choice(["orgName", "orgType", "regionId", "contactPerson"])
            if field == "orgName":
                rec = pool_item('orgPool')
                if rec.get("orgName"):
                    body["orgName"] = rec["orgName"][:2]  # 模糊匹配
            elif field == "orgType":
                body["orgType"] = random.choice([1, 2, 3])
            elif field == "regionId":
                body["regionId"] = pool_get('projectPool', 'regionId', 'regionId')
            elif field == "contactPerson":
                body["contactPerson"] = random_name("联系人")
        elif mode < 0.75:
            # 模式3: 组合筛选
            rec = pool_item('orgPool')
            if rec.get("orgName") and random.random() < 0.5:
                body["orgName"] = rec["orgName"][:2]
            body["orgType"] = random.choice([1, 2, 3])
        else:
            # 模式4: 地区筛选
            body["regionId"] = pool_get('projectPool', 'regionId', 'regionId')

        post_api(self.client, "/organization/list", body,
                 name="POST /organization/list")

    # ── PT-MIX-019: 硬件绑定操作 (21%) ──
    @task(3)
    def create_hardware(self):
        """创建硬件记录 - 需认证, 3个参数全覆盖"""
        import time
        ts = str(int(time.time() * 1000))
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        body = {
            "hardwareNo": f"HW-S3-{ts}-{suffix}"[:30],
            "hardwareType": random.choice([1, 2]),
            "organizationId": pool_get('orgPool', 'id', 'orgId'),
        }
        data = post_api(self.client, "/hardware-manage/create", body,
                        need_auth=True, name="POST /hardware-manage/create")
        if data and data.get("data"):
            CREATED_IDS["hardwareManageId"] = data["data"]

    # ── PT-MIX-022: 数据权限配置 (7%) ──
    @task(1)
    def update_permission(self):
        """更新数据权限 - 需认证, 5个参数全覆盖"""
        perm_pool = REAL_DATA.get('dataPermissionPool', [])
        rec = random.choice(perm_pool) if perm_pool else {}
        perm_id = rec.get('id') or random.randint(1, 100)

        body = {
            "id": perm_id,
            "permissionName": rec.get('permissionName') or f"压测数据权限{random_str(4)}",
            "regionId": rec.get('regionId') or pool_get('projectPool', 'regionId', 'regionId') or 1,
            "status": random.choice([0, 1]),
            "description": random.choice([
                "压测-全部数据访问权限",
                "压测-所属机构数据权限",
                "压测-自定义区域权限",
                "压测-筛查数据只读权限",
                "压测-随访数据管理权限",
            ]),
        }
        post_api(self.client, "/permission/data/update", body,
                 need_auth=True, name="POST /permission/data/update")


# ==================== 用户类 ====================

class AdminBackendUser(HttpUser):
    """管理后台混合压测用户 (场景3)

    CLI 示例:
      locust -f perftest/scenario3.py --headless -u 100 -r 5 -t 10m --host http://your-api-server:8082 --html report/scenario3_report.html --csv report/scenario3
    """

    wait_time = between(1, 2)
    tasks = [Scenario3Tasks]


# ==================== 启动事件 ====================

@events.init.add_listener
def on_locust_init(environment, **kwargs):
    base = get_base_url()
    print(f"\n  {'='*55}")
    print(f"  压测场景3: 管理后台混合 (排除登录+操作日志+系统日志)")
    print(f"  目标服务器: {base}")
    print(f"  接口数量: 5 个 (查用户/改角色/查机构/绑硬件/改权限)")
    print(f"  推荐: locust -f perftest/scenario3.py --headless -u 100 -r 5 -t 10m --host {base} --html report/scenario3_report.html --csv report/scenario3")
    print(f"  {'='*55}\n")
    load_shared_token()
    fetch_real_data()
