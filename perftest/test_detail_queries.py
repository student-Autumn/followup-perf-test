"""
详情查询接口压测
================
测试 5 个按ID查询详情的接口:

  GET /screen/record/detail/{id}           获取筛查记录详情
  GET /followup/record/detail/{id}         获取随访记录详情
  GET /hardware-manage/detail/{id}         查询硬件管理详情
  GET /user/detail/{id}                    获取用户详情
  GET /role/detail/{id}                    查询角色详情

启动方式:
  locust -f perftest/test_detail_queries.py --headless -u 50 -r 5 -t 10m --host http://your-api-server:8082

Tags:
  --tags screen-detail      仅筛查记录详情
  --tags followup-detail    仅随访记录详情
  --tags hardware-detail    仅硬件管理详情
  --tags user-detail        仅用户详情
  --tags role-detail        仅角色详情
"""

import json
import os
import random
from iniconfig import IniConfig
from locust import HttpUser, TaskSet, task, tag, between, events

REAL_DATA = {}
TOKEN = None
TOKEN_TYPE = "Bearer"


def pool_get(pool_key, field):
    pool = REAL_DATA.get(pool_key, [])
    if pool:
        return random.choice(pool).get(field)
    return None


def fetch_real_data():
    global REAL_DATA
    data_file = os.path.join(os.path.dirname(__file__), "real_data.json")
    if os.path.exists(data_file):
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                REAL_DATA.update(json.load(f))
            for k in ['screenRecordPool', 'followupPool', 'hardwarePool', 'userPool', 'rolePool']:
                v = REAL_DATA.get(k, [])
                if isinstance(v, list):
                    print(f"  {k}: {len(v)} 条")
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


def get_json(client, url, name=None):
    with client.get(url, headers=auth_headers(),
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


class DetailQueriesTasks(TaskSet):
    """5 个详情查询接口"""

    @tag('screen-detail')
    @task(3)
    def screen_record_detail(self):
        """获取筛查记录详情 — 含病人+筛查+随访关联数据"""
        rid = pool_get('screenRecordPool', 'id')
        if rid:
            get_json(self.client, f"/screen/record/detail/{rid}",
                     name="GET /screen/record/detail/{id}")

    @tag('followup-detail')
    @task(2)
    def followup_detail(self):
        """获取随访记录详情"""
        rid = pool_get('followupPool', 'reportId')
        if rid:
            get_json(self.client, f"/followup/record/detail/{rid}",
                     name="GET /followup/record/detail/{id}")

    @tag('hardware-detail')
    @task(3)
    def hardware_detail(self):
        """查询硬件管理详情"""
        hid = pool_get('hardwarePool', 'id')
        if hid:
            get_json(self.client, f"/hardware-manage/detail/{hid}",
                     name="GET /hardware-manage/detail/{id}")

    @tag('user-detail')
    @task(2)
    def user_detail(self):
        """获取用户详情 — 含角色/权限/机构关联"""
        uid = pool_get('userPool', 'id')
        if uid:
            get_json(self.client, f"/user/detail/{uid}",
                     name="GET /user/detail/{id}")

    @tag('role-detail')
    @task(2)
    def role_detail(self):
        """查询角色详情"""
        rid = pool_get('rolePool', 'id')
        if rid:
            get_json(self.client, f"/role/detail/{rid}",
                     name="GET /role/detail/{id}")


class DetailQueriesUser(HttpUser):
    """详情查询接口压测

    CLI 示例:
      # 全量
      locust -f perftest/test_detail_queries.py --headless -u 50 -r 5 -t 10m --host http://your-api-server:8082 --html report/detail_queries.html

      # 仅筛查详情
      locust -f perftest/test_detail_queries.py --headless -u 50 -r 5 -t 5m --host http://your-api-server:8082 --tags screen-detail
    """
    wait_time = between(0.3, 1)
    tasks = [DetailQueriesTasks]


@events.init.add_listener
def on_locust_init(environment, **kwargs):
    print(f"\n  {'='*55}")
    print(f"  详情查询接口压测")
    print(f"  接口: 5个详情查询接口")
    print(f"  标签: screen-detail, followup-detail, hardware-detail, user-detail, role-detail")
    print(f"  {'='*55}\n")
    load_shared_token()
    fetch_real_data()
