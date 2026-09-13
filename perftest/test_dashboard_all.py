"""
仪表盘统计接口压测 — 7 个接口全部覆盖
=====================================
依据 API 文档 -v3-api-docs.md 的接口定义编写。

  接口列表:
    GET /dashboard/statistics/screen              总筛查统计 (无需参数)
    GET /dashboard/statistics/screen-daily        筛查人员日统计 (startDate, endDate)
    GET /dashboard/statistics/registration        总报名数量统计 (无需参数)
    GET /dashboard/statistics/org-ranking         机构筛查排行 (rankType: 1=月, 2=季度)
    GET /dashboard/statistics/hardware-bind       总绑卡数量统计 (无需参数)
    GET /dashboard/statistics/hardware-bind-daily 硬件绑定日统计 (startDate, endDate)
    GET /dashboard/statistics/gender-ratio        性别比例统计 (无需参数)

启动方式:
  # 全量 (7接口)
  locust -f perftest/test_dashboard_all.py --headless -u 50 -r 5 -t 10m --host http://your-api-server:8082

  # 仅无参接口 (4个, tag: dashboard-no-param)
  locust -f perftest/test_dashboard_all.py --headless -u 50 -r 5 -t 10m --host http://your-api-server:8082 --tags dashboard-no-param

  # 仅有参接口 (3个, tag: dashboard-with-param)
  locust -f perftest/test_dashboard_all.py --headless -u 50 -r 5 -t 10m --host http://your-api-server:8082 --tags dashboard-with-param
"""

import json
import os
import random
from datetime import datetime, timedelta
from locust import HttpUser, TaskSet, task, tag, between, events

TOKEN = None
TOKEN_TYPE = "Bearer"


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
    print("  [WARN] 无有效 token，仪表盘接口为公开接口，无需认证也可压测")


def auth_headers():
    if TOKEN:
        return {"Authorization": f"{TOKEN_TYPE} {TOKEN}"}
    return {}


# ==================== 参数构造 ====================

def random_date_range(max_months=3):
    """生成随机日期范围 (最大跨度 max_months 个月)"""
    end_date = datetime.now() - timedelta(days=random.randint(0, 30))
    # 随机跨度: 短(7天/15天/30天) 或 长(60天/90天)
    span = random.choice([7, 15, 30, 60, 90])
    span = min(span, max_months * 30)
    start_date = end_date - timedelta(days=span)
    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


# ==================== 请求工具 ====================

def get_api(client, url, name=None):
    """GET 请求, 自动解析业务响应"""
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


# ==================== 任务集 ====================

class DashboardAllTasks(TaskSet):
    """7 个仪表盘统计接口

    权重分配思路:
      - screen / screen-daily 是核心业务看板, 权重最高
      - hardware-bind / hardware-bind-daily 是硬件管理看板, 中等权重
      - registration / org-ranking / gender-ratio 是辅助看板, 权重较低
    """

    # ─── 无参接口 (4个) ───

    @tag('dashboard-no-param')
    @task(4)
    def screen_statistics(self):
        """GET /dashboard/statistics/screen
        总筛查统计: totalCount + thisWeekCount + lastWeekCount + 周环比
        API文档行 4555"""
        get_api(self.client, "/dashboard/statistics/screen",
                name="GET /dashboard/statistics/screen")

    @tag('dashboard-no-param')
    @task(3)
    def registration_statistics(self):
        """GET /dashboard/statistics/registration
        总报名数量统计: 匿名答题记录的 totalCount + 周环比
        API文档行 4695"""
        get_api(self.client, "/dashboard/statistics/registration",
                name="GET /dashboard/statistics/registration")

    @tag('dashboard-no-param')
    @task(3)
    def hardware_bind_statistics(self):
        """GET /dashboard/statistics/hardware-bind
        总绑卡统计: 硬件表已绑卡记录的 totalCount + 周环比
        API文档行 4848"""
        get_api(self.client, "/dashboard/statistics/hardware-bind",
                name="GET /dashboard/statistics/hardware-bind")

    @tag('dashboard-no-param')
    @task(2)
    def gender_ratio_statistics(self):
        """GET /dashboard/statistics/gender-ratio
        性别比例: maleCount/femaleCount/unknownCount + 各自占比(%)
        API文档行 5008"""
        get_api(self.client, "/dashboard/statistics/gender-ratio",
                name="GET /dashboard/statistics/gender-ratio")

    # ─── 有参接口 (3个) ───

    @tag('dashboard-with-param')
    @task(4)
    def screen_daily_statistics(self):
        """GET /dashboard/statistics/screen-daily
        筛查日统计: 按日期范围统计每天筛查数, 最大3个月跨度
        参数: startDate, endDate (必填, string(date))
        API文档行 4621

        随机覆盖3种时间跨度: 7天 / 30天 / 90天"""
        from urllib.parse import urlencode
        start, end = random_date_range(max_months=3)
        params = urlencode({"startDate": start, "endDate": end})
        get_api(self.client, f"/dashboard/statistics/screen-daily?{params}",
                name="GET /dashboard/statistics/screen-daily")

    @tag('dashboard-with-param')
    @task(3)
    def org_ranking_statistics(self):
        """GET /dashboard/statistics/org-ranking
        机构筛查排行: 按月/季度统计筛查数量, 返回前5名
        参数: rankType (必填, int, 1=最近一个月, 2=最近一个季度)
        API文档行 4761"""
        rank_type = random.choice([1, 2])
        get_api(self.client, f"/dashboard/statistics/org-ranking?rankType={rank_type}",
                name="GET /dashboard/statistics/org-ranking")

    @tag('dashboard-with-param')
    @task(3)
    def hardware_bind_daily_statistics(self):
        """GET /dashboard/statistics/hardware-bind-daily
        硬件绑定日统计: 按日期范围统计每天绑定数+新增数, 含本月/本周环比
        参数: startDate, endDate (必填, string(date))
        API文档行 4914"""
        from urllib.parse import urlencode
        start, end = random_date_range(max_months=3)
        params = urlencode({"startDate": start, "endDate": end})
        get_api(self.client, f"/dashboard/statistics/hardware-bind-daily?{params}",
                name="GET /dashboard/statistics/hardware-bind-daily")


# ==================== 用户类 ====================

class DashboardAllUser(HttpUser):
    """仪表盘全部统计接口压测用户

    CLI 示例:
      # 50并发, 10分钟, 全量7接口
      locust -f perftest/test_dashboard_all.py --headless -u 50 -r 5 -t 10m --host http://your-api-server:8082 --html report/dashboard_all.html

      # 100→200爬升, 20分钟
      locust -f perftest/test_dashboard_all.py --headless -u 200 -r 5 -t 20m --host http://your-api-server:8082 --html report/dashboard_all_200vu.html

      # 仅测无参4接口 (更快识别瓶颈)
      locust -f perftest/test_dashboard_all.py --headless -u 50 -r 5 -t 5m --host http://your-api-server:8082 --tags dashboard-no-param

      # 仅测有参3接口 (日统计+排行)
      locust -f perftest/test_dashboard_all.py --headless -u 50 -r 5 -t 5m --host http://your-api-server:8082 --tags dashboard-with-param
    """
    wait_time = between(1, 2)
    tasks = [DashboardAllTasks]


# ==================== 启动事件 ====================

@events.init.add_listener
def on_locust_init(environment, **kwargs):
    print(f"\n  {'='*60}")
    print(f"  仪表盘统计接口压测 — 7 个接口")
    print(f"  无参接口 (4): screen / registration / hardware-bind / gender-ratio")
    print(f"  有参接口 (3): screen-daily / org-ranking / hardware-bind-daily")
    print(f"  标签: dashboard-no-param, dashboard-with-param")
    print(f"  {'='*60}\n")
    load_shared_token()
