"""
压测场景2: 午后随访混合压测（排除用户登录 + 打印随访报告）
=========================================================
按文档定义, 聚焦 5 个核心接口:

  PT-MIX-009  修改随访记录    /followup/record/update             25% → 权重5
  PT-MIX-010  分页查询随访记录 /followup/record/list              25% → 权重5
  PT-MIX-011  发送通知        /followup/record/send-notification  15% → 权重3
  PT-MIX-013  查询呼叫记录    /followup/record/call-records/{id}  10% → 权重2
  PT-MIX-014  查看仪表盘统计  /dashboard/statistics/screen        10% → 权重2

启动方式:
  locust -f perftest/scenario2.py --headless -u 150 -r 10 -t 10m --host http://your-api-server:8082 --html report/scenario2_report.html --csv report/scenario2

VU 配置 (参考文档):
  起始 30 VU, 爬升至 150 VU, 持续 10 分钟
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
    """从数据池随机取一整条记录"""
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


# ==================== 场景2 任务集 ====================

class Scenario2Tasks(TaskSet):
    """
    午后随访混合压测 — 5 个核心接口
    权重分配 (对应文档 PT-MIX-009~014，排除008/012):
      update             29%  @task(5)
      list               29%  @task(5)
      send-notification  18%  @task(3)
      call-records       12%  @task(2)
      dashboard          12%  @task(2)
    """

    # ── PT-MIX-009: 修改随访记录 (29%) ──
    @task(5)
    def update_followup_record(self):
        """修改随访记录 - 需认证, 参数全覆盖"""
        rec = pool_item('followupPool')
        rid = rec.get('reportId') or REAL_DATA.get('reportId')
        # followupPool 中部分病人已被删除，改用 patientPool 中确实存在的病人ID
        pid = pool_get('patientPool', 'patientId', 'followupPatientId')

        post_api(self.client, "/followup/record/update", {
            "reportId": rid,
            "patientId": pid,
            "address": random.choice([
                "浙江省杭州市西湖区", "北京市朝阳区", "上海市浦东新区",
                "广东省广州市天河区", "四川省成都市武侯区",
            ]),
            "emergencyContact": random_name("联系人"),
            "emergencyPhone": random_phone(),
            "followupLevel": random.choice(["一级", "二级", "三级"]),
            "followupCycle": random.choice(["每周", "每月", "每季", "每年"]),
            "patientDisease": random.choice([
                "肠癌术后", "肺癌术后", "胃癌术后", "肝癌术后", "乳腺癌术后",
            ]),
            "positiveLevel": random.choice(["阳性", "阴性", "疑似"]),
            "interventionMeasures": random.choice([
                "定期复查", "药物治疗", "手术治疗", "化疗", "放疗",
            ]),
            "interpretationResult": random.choice([
                "建议进一步检查", "结果正常", "需持续观察", "建议专科就诊",
            ]),
        }, need_auth=True, name="POST /followup/record/update")

    # ── PT-MIX-010: 分页查询随访记录 (29%) ──
    @task(5)
    def list_followup_records(self):
        """分页查询 - 公开, 14个筛选参数全覆盖, 4种搜索模式"""
        from datetime import datetime, timedelta
        body = {
            "pageNum": random.randint(1, 5),
            "pageSize": random.choice([5, 10, 15, 20]),
        }
        # 按概率选择搜索模式: 30%最小化 / 30%单条件 / 25%多条件 / 15%日期范围
        mode = random.random()
        if mode < 0.3:
            # 模式1: 仅分页，不加筛选条件
            pass
        elif mode < 0.6:
            # 模式2: 随机选1个筛选条件
            field = random.choice(["name", "idNo", "gender", "positiveLevel", "bindCardNo", "emergencyPhone"])
            rec = pool_item('followupPool')
            if field == "name" and rec.get("name"):
                body["name"] = rec["name"]
            elif field == "idNo" and rec.get("idNo"):
                body["idNo"] = rec["idNo"]
            elif field == "gender":
                body["gender"] = random.choice([0, 1, 2])
            elif field == "positiveLevel" and rec.get("positiveLevel"):
                body["positiveLevel"] = rec["positiveLevel"]
            elif field == "bindCardNo" and rec.get("bindCardNo"):
                body["bindCardNo"] = rec["bindCardNo"]
            elif field == "emergencyPhone" and rec.get("emergencyPhone"):
                body["emergencyPhone"] = rec["emergencyPhone"]
        elif mode < 0.85:
            # 模式3: 多条件组合 (2-4个筛选条件)
            rec = pool_item('followupPool')
            candidates = []
            if rec.get("name"):
                candidates.append(("name", rec["name"]))
            if rec.get("idNo"):
                candidates.append(("idNo", rec["idNo"]))
            candidates.append(("gender", random.choice([0, 1, 2])))
            if rec.get("positiveLevel"):
                candidates.append(("positiveLevel", rec["positiveLevel"]))
            if rec.get("screenProjectId"):
                candidates.append(("screenProjectId", rec["screenProjectId"]))
            if rec.get("organizationId"):
                candidates.append(("organizationId", rec["organizationId"]))
            if rec.get("regionId"):
                candidates.append(("regionId", rec["regionId"]))
            if rec.get("hospitalIds"):
                candidates.append(("hospitalIds", rec["hospitalIds"]))
            random.shuffle(candidates)
            for k, v in candidates[:random.randint(2, 4)]:
                body[k] = v
        else:
            # 模式4: 日期范围筛选
            today = datetime.now()
            end_date = today.strftime("%Y-%m-%d")
            start_date = (today - timedelta(days=random.randint(3, 30))).strftime("%Y-%m-%d")
            body["screenDateStart"] = start_date
            body["screenDateEnd"] = end_date
        post_api(self.client, "/followup/record/list", body,
                 name="POST /followup/record/list")

    # ── PT-MIX-011: 发送通知 (18%) ──
    @task(3)
    def send_notification(self):
        """发送通知 - 公开, 随机内容+紧急程度"""
        post_api(self.client, "/followup/record/send-notification", {
            "patientId": pool_get('patientPool', 'patientId', 'patientId'),
            "content": random.choice([
                "您的随访报告已生成，请及时查看",
                "请按时参加下一次随访",
                "您的检查结果已出，请联系医生",
                "随访时间已更改，请注意查看",
                "您有新的健康建议，请查收",
            ]),
            "isUrgent": random.choice([True, False]),
        }, name="POST /followup/record/send-notification")

    # ── PT-MIX-013: 查询呼叫记录 (12%) ──
    @task(2)
    def query_call_records(self):
        """查询呼叫记录 - 需认证, 从数据池随机取病人"""
        pid = pool_get('patientPool', 'patientId', 'patientId')
        get_api(self.client,
                f"/followup/record/call-records/{pid}",
                need_auth=True,
                name="GET /followup/record/call-records/{patientId}")

    # ── PT-MIX-014: 查看仪表盘统计 (12%) ──
    @task(2)
    def query_dashboard_screen(self):
        """筛查统计 - 公开"""
        get_api(self.client, "/dashboard/statistics/screen",
                name="GET /dashboard/statistics/screen")


# ==================== 用户类 ====================

class AfternoonFollowupUser(HttpUser):
    """午后随访混合压测用户 (场景2)

    CLI 示例:
      locust -f perftest/scenario2.py --headless -u 150 -r 10 -t 10m --host http://your-api-server:8082 --html report/scenario2_report.html --csv report/scenario2
    """

    wait_time = between(1, 2)
    tasks = [Scenario2Tasks]


# ==================== 启动事件 ====================

@events.init.add_listener
def on_locust_init(environment, **kwargs):
    base = get_base_url()
    print(f"\n  {'='*55}")
    print(f"  压测场景2: 午后随访混合 (排除登录+打印报告)")
    print(f"  目标服务器: {base}")
    print(f"  接口数量: 5 个 (修改随访/查随访/发通知/呼叫记录/仪表盘)")
    print(f"  推荐: locust -f perftest/scenario2.py --headless -u 150 -r 10 -t 10m --host {base}")
    print(f"  {'='*55}\n")
    load_shared_token()
    fetch_real_data()
