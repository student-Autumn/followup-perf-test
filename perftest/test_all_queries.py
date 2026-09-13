"""
高风险接口压测: 查询所有（无分页全量返回）
==========================================
测试 4 个无分页的全量查询接口, 这些接口在高并发/大数据量下有 OOM 和打爆数据库的风险:

  GET /hardware-manage/all    查询所有硬件管理   (数据量: 12万+)
  GET /organization/all        获取所有机构       (数据量: ~22)
  GET /role/all                查询所有角色       (数据量: ~200)
  GET /project/all             获取所有项目       (数据量: 未知)

启动方式:
  locust -f perftest/test_all_queries.py --headless -u 50 -r 5 -t 5m --host http://your-api-server:8082

Tags:
  --tags hardware-all    仅硬件全量查询
  --tags org-all         仅机构全量查询
  --tags role-all        仅角色全量查询
  --tags project-all     仅项目全量查询
"""

import json
import os
import random
from iniconfig import IniConfig
from locust import HttpUser, TaskSet, task, tag, between, events

REAL_DATA = {}
TOKEN = None
TOKEN_TYPE = "Bearer"


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


class AllQueriesTasks(TaskSet):
    """
    4 个全量查询接口 — 等权重压测
    重点关注: max_response_time, avg_content_length, 是否有超时/连接重置
    """

    @tag('hardware-all')
    @task(3)
    def hardware_all(self):
        """查询所有硬件管理 — 数据量最大(12万+), 风险最高"""
        with self.client.get("/hardware-manage/all",
                             headers=auth_headers(),
                             name="GET /hardware-manage/all",
                             catch_response=True) as resp:
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if data.get("success"):
                        resp.success()
                    else:
                        resp.failure(f"业务失败: {data.get('message', '')}")
                except Exception:
                    resp.failure("响应非JSON")
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @tag('org-all')
    @task(3)
    def org_all(self):
        """获取所有机构 — 数据量小(~22条), 验证基准性能"""
        with self.client.get("/organization/all",
                             headers=auth_headers(),
                             name="GET /organization/all",
                             catch_response=True) as resp:
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if data.get("success"):
                        resp.success()
                    else:
                        resp.failure(f"业务失败: {data.get('message', '')}")
                except Exception:
                    resp.failure("响应非JSON")
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @tag('role-all')
    @task(3)
    def role_all(self):
        """查询所有角色 — 数据量中等(~200条)"""
        with self.client.get("/role/all",
                             headers=auth_headers(),
                             name="GET /role/all",
                             catch_response=True) as resp:
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if data.get("success"):
                        resp.success()
                    else:
                        resp.failure(f"业务失败: {data.get('message', '')}")
                except Exception:
                    resp.failure("响应非JSON")
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @tag('project-all')
    @task(2)
    def project_all(self):
        """获取所有项目 — 验证项目列表接口性能"""
        with self.client.get("/project/all",
                             headers=auth_headers(),
                             name="GET /project/all",
                             catch_response=True) as resp:
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if data.get("success"):
                        resp.success()
                    else:
                        resp.failure(f"业务失败: {data.get('message', '')}")
                except Exception:
                    resp.failure("响应非JSON")
            else:
                resp.failure(f"HTTP {resp.status_code}")


class AllQueriesUser(HttpUser):
    """高风险全量查询压测用户

    CLI 示例:
      # 全量压测
      locust -f perftest/test_all_queries.py --headless -u 50 -r 5 -t 5m --host http://your-api-server:8082 --html report/all_queries.html

      # 仅硬件全量 (最高风险)
      locust -f perftest/test_all_queries.py --headless -u 20 -r 2 -t 5m --host http://your-api-server:8082 --tags hardware-all

      # 排除硬件全量
      locust -f perftest/test_all_queries.py --headless -u 50 -r 5 -t 5m --host http://your-api-server:8082 --exclude-tags hardware-all
    """
    wait_time = between(1, 3)
    tasks = [AllQueriesTasks]


@events.init.add_listener
def on_locust_init(environment, **kwargs):
    print(f"\n  {'='*55}")
    print(f"  高风险压测: 查询所有（无分页全量返回）")
    print(f"  接口: hardware-manage/all, organization/all, role/all, project/all")
    print(f"  标签: hardware-all, org-all, role-all, project-all")
    print(f"  {'='*55}\n")
    load_shared_token()
    fetch_real_data()
    hw = len(REAL_DATA.get("hardwarePool", []))
    org = len(REAL_DATA.get("orgPool", []))
    role = len(REAL_DATA.get("rolePool", []))
    print(f"  数据池: hardware={hw}, org={org}, role={role}")
    if hw > 50000:
        print(f"  ⚠ WARNING: 硬件数据量 {hw} 条, 全量查询有 OOM 风险, 建议从低 VU 开始!")
