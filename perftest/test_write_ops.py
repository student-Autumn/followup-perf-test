"""
新增类写接口压测
================
测试 4 个核心新增接口:

  POST /user/add              新增用户
  POST /organization/add       新增机构
  POST /role/add              添加角色
  POST /patient/create        创建病人信息

启动方式:
  locust -f perftest/test_write_ops.py --headless -u 50 -r 5 -t 10m --host http://your-api-server:8082

Tags:
  --tags user-add        仅新增用户
  --tags org-add         仅新增机构
  --tags role-add        仅添加角色
  --tags patient-add     仅创建病人
"""

import json
import os
import random
import string
from iniconfig import IniConfig
from locust import HttpUser, TaskSet, task, tag, between, events

REAL_DATA = {}
TOKEN = None
TOKEN_TYPE = "Bearer"
CREATED_IDS = {}


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


def fetch_real_data():
    global REAL_DATA
    data_file = os.path.join(os.path.dirname(__file__), "real_data.json")
    if os.path.exists(data_file):
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                REAL_DATA.update(json.load(f))
            print(f"  [OK] 已加载 real_data.json")
        except Exception as e:
            print(f"  [WARN] 读取 real_data.json 失败: {e}")


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
    print("  [WARN] 无有效 token")


def auth_headers():
    if TOKEN:
        return {"Authorization": f"{TOKEN_TYPE} {TOKEN}"}
    return {}


def post_json(client, url, body, name=None):
    headers = {"Content-Type": "application/json"}
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


class WriteOpsTasks(TaskSet):
    """4 个新增类写接口"""

    @tag('user-add')
    @task(3)
    def add_user(self):
        """新增用户 — 需认证, 11个参数覆盖"""
        import time
        ts = str(int(time.time() * 1000))[-8:]
        suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
        org_id = pool_get('orgPool', 'id', 'orgId')
        role_id = pool_get('rolePool', 'id', 'roleId')
        body = {
            "username": f"perf_{ts}_{suffix}",
            "loginAccount": f"perf_{ts}_{suffix}",
            "password": "Test123456",
            "phone": f"138{ts[-4:]}{suffix}",
            "email": f"perf_{ts}@test.com",
            "orgId": org_id,
            "orgName": pool_get('orgPool', 'orgName', 'orgName') or "压测机构",
            "roleId": role_id,
            "status": random.choice([0, 1]),
            "gender": random.choice([0, 1, 2]),
            "remark": f"压测用户-{random_str(3)}",
        }
        data = post_json(self.client, "/user/add", body, name="POST /user/add")
        if data and data.get("data"):
            CREATED_IDS["userId"] = data["data"]

    @tag('org-add')
    @task(2)
    def add_org(self):
        """新增机构 — 需认证, 8个参数覆盖"""
        import time
        ts = str(int(time.time() * 1000))[-8:]
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        region_id = pool_get('orgPool', 'regionId', 'regionId')
        body = {
            "orgName": f"压测机构_{ts}_{suffix}",
            "orgType": random.choice([1, 2, 3]),
            "regionId": region_id,
            "contactPerson": random_name("联系人"),
            "contactPhone": f"139{ts[-4:]}{suffix[:2]}",
            "address": f"压测地址_{suffix}",
            "status": random.choice([0, 1]),
            "remark": f"压测机构-{random_str(3)}",
        }
        data = post_json(self.client, "/organization/add", body, name="POST /organization/add")
        if data and data.get("data"):
            CREATED_IDS["orgId"] = data["data"]

    @tag('role-add')
    @task(2)
    def add_role(self):
        """添加角色 — 需认证, 7个参数覆盖"""
        import time
        ts = str(int(time.time() * 1000))[-8:]
        suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        body = {
            "roleName": f"压测角色_{ts}_{suffix}",
            "roleKey": f"perf_role_{suffix}",
            "description": random.choice([
                "压测-系统管理员角色",
                "压测-机构管理员角色",
                "压测-普通筛查员角色",
                "压测-随访员角色",
                "压测-数据查看员角色",
            ]),
            "dataScope": random.choice([1, 2, 3]),
            "isDefault": random.choice([0, 0, 0, 1]),
            "status": random.choice([0, 1]),
            "functionPermissionIds": [],
        }
        data = post_json(self.client, "/role/add", body, name="POST /role/add")
        if data and data.get("data"):
            CREATED_IDS["roleId"] = data["data"]

    @tag('patient-add')
    @task(3)
    def add_patient(self):
        """创建病人信息 — 需认证, 直接创建病人(区别于通过筛查创建)"""
        import time
        ts = int(time.time() * 1000)
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        body = {
            "patientName": random_name(),
            "idNo": f"PT{ts}{suffix}",
            "gender": random.choice([0, 1, 2]),
            "age": random.randint(18, 85),
            "phone": f"159{''.join(random.choices(string.digits, k=8))}",
            "address": f"压测地址_{suffix}",
        }
        data = post_json(self.client, "/patient/create", body, name="POST /patient/create")
        if data and data.get("data"):
            CREATED_IDS["patientId"] = data["data"]


class WriteOpsUser(HttpUser):
    """新增类写接口压测用户

    CLI 示例:
      # 全量
      locust -f perftest/test_write_ops.py --headless -u 50 -r 5 -t 10m --host http://your-api-server:8082 --html report/write_ops.html

      # 仅新增用户
      locust -f perftest/test_write_ops.py --headless -u 30 -r 3 -t 5m --host http://your-api-server:8082 --tags user-add
    """
    wait_time = between(0.5, 1.5)
    tasks = [WriteOpsTasks]


@events.init.add_listener
def on_locust_init(environment, **kwargs):
    print(f"\n  {'='*55}")
    print(f"  新增类写接口压测")
    print(f"  接口: /user/add, /organization/add, /role/add, /patient/create")
    print(f"  标签: user-add, org-add, role-add, patient-add")
    print(f"  {'='*55}\n")
    load_shared_token()
    fetch_real_data()
