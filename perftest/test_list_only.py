"""
单接口压测: 分页查询筛查人员 /screen/record/list
启动: locust -f perftest/test_list_only.py --headless -u 100 -r 10 -t 5m --host http://your-api-server:8082 --html report/screen_list_report.html
tags: --tags screen-list (仅此接口), 所有参数全覆盖
"""
import json, os, random, string
from locust import HttpUser, TaskSet, task, tag, between, events

REAL_DATA = {}

def fetch_real_data():
    global REAL_DATA
    data_file = os.path.join(os.path.dirname(__file__), "real_data.json")
    if os.path.exists(data_file):
        with open(data_file, "r", encoding="utf-8") as f:
            REAL_DATA.update(json.load(f))

class ListOnlyTasks(TaskSet):
    """
    分页查询筛查人员 — 参数全覆盖设计
    API参数 (10个): pageNum, pageSize, patientName, gender, regionId,
                    hospitalIds, organizationId, screenProjectId,
                    bindDateStart, bindDateEnd
    数据池字段:    id, patientId, screenProjectId, patientName,
                    gender, regionId, hospitalIds, organizationId,
                    bindCardDate, screenDate
    每个参数都会被独立和组合使用, 确保覆盖所有筛选维度.
    """

    def _rand_rec(self):
        """随机取一条数据池记录"""
        pool = REAL_DATA.get("screenRecordPool", [])
        return random.choice(pool) if pool else {}

    def _rand_page(self):
        return random.randint(1, 100)

    def _rand_size(self):
        return random.choice([5, 10, 15, 20, 30, 50])

    def _has(self, rec, key):
        v = rec.get(key)
        if v is None:
            return False
        if isinstance(v, list):
            return len(v) > 0
        if isinstance(v, str):
            return len(v) > 0
        return True

    @tag('screen-list')
    @task(4)
    def pure_pagination(self):
        """纯分页 — 仅 pageNum + pageSize, 无筛选"""
        self.client.post("/screen/record/list",
                         data=json.dumps({"pageNum": self._rand_page(), "pageSize": self._rand_size()}),
                         headers={"Content-Type": "application/json"},
                         name="POST /screen/record/list")

    # ── 单条件筛选: 每种参数独立覆盖 ──

    @tag('screen-list')
    @task(1)
    def filter_by_patient_name(self):
        """单条件: patientName"""
        rec = self._rand_rec()
        self.client.post("/screen/record/list",
                         data=json.dumps({"pageNum": self._rand_page(), "pageSize": self._rand_size(),
                                          "patientName": rec.get("patientName", "")}),
                         headers={"Content-Type": "application/json"},
                         name="POST /screen/record/list")

    @tag('screen-list')
    @task(1)
    def filter_by_gender(self):
        """单条件: gender (0未知/1男/2女)"""
        rec = self._rand_rec()
        g = rec.get("gender")
        if g is not None:
            self.client.post("/screen/record/list",
                             data=json.dumps({"pageNum": self._rand_page(), "pageSize": self._rand_size(),
                                              "gender": str(g)}),
                             headers={"Content-Type": "application/json"},
                             name="POST /screen/record/list")

    @tag('screen-list')
    @task(1)
    def filter_by_region(self):
        """单条件: regionId"""
        rec = self._rand_rec()
        if self._has(rec, "regionId"):
            self.client.post("/screen/record/list",
                             data=json.dumps({"pageNum": self._rand_page(), "pageSize": self._rand_size(),
                                              "regionId": rec["regionId"]}),
                             headers={"Content-Type": "application/json"},
                             name="POST /screen/record/list")

    @tag('screen-list')
    @task(1)
    def filter_by_hospital(self):
        """单条件: hospitalIds (数组)"""
        rec = self._rand_rec()
        if self._has(rec, "hospitalIds"):
            self.client.post("/screen/record/list",
                             data=json.dumps({"pageNum": self._rand_page(), "pageSize": self._rand_size(),
                                              "hospitalIds": rec["hospitalIds"]}),
                             headers={"Content-Type": "application/json"},
                             name="POST /screen/record/list")

    @tag('screen-list')
    @task(1)
    def filter_by_organization(self):
        """单条件: organizationId"""
        rec = self._rand_rec()
        if self._has(rec, "organizationId"):
            self.client.post("/screen/record/list",
                             data=json.dumps({"pageNum": self._rand_page(), "pageSize": self._rand_size(),
                                              "organizationId": rec["organizationId"]}),
                             headers={"Content-Type": "application/json"},
                             name="POST /screen/record/list")

    @tag('screen-list')
    @task(1)
    def filter_by_project(self):
        """单条件: screenProjectId"""
        rec = self._rand_rec()
        if self._has(rec, "screenProjectId"):
            self.client.post("/screen/record/list",
                             data=json.dumps({"pageNum": self._rand_page(), "pageSize": self._rand_size(),
                                              "screenProjectId": rec["screenProjectId"]}),
                             headers={"Content-Type": "application/json"},
                             name="POST /screen/record/list")

    @tag('screen-list')
    @task(1)
    def filter_by_bind_date_range(self):
        """单条件: bindDateStart + bindDateEnd (日期范围)"""
        rec = self._rand_rec()
        date_val = rec.get("bindCardDate") or rec.get("screenDate") or ""
        if date_val:
            self.client.post("/screen/record/list",
                             data=json.dumps({"pageNum": self._rand_page(), "pageSize": self._rand_size(),
                                              "bindDateStart": date_val[:10], "bindDateEnd": date_val[:10]}),
                             headers={"Content-Type": "application/json"},
                             name="POST /screen/record/list")

    # ── 组合筛选: 多个参数混合使用 ──

    @tag('screen-list')
    @task(2)
    def combo_two_params(self):
        """双条件组合: 随机选2个筛选参数"""
        rec = self._rand_rec()
        body = {"pageNum": self._rand_page(), "pageSize": self._rand_size()}
        # 从所有可能的筛选字段中随机选2个
        candidates = []
        if self._has(rec, "patientName"):   candidates.append(("patientName", rec["patientName"]))
        if rec.get("gender") is not None:   candidates.append(("gender", str(rec["gender"])))
        if self._has(rec, "regionId"):      candidates.append(("regionId", rec["regionId"]))
        if self._has(rec, "hospitalIds"):   candidates.append(("hospitalIds", rec["hospitalIds"]))
        if self._has(rec, "organizationId"):candidates.append(("organizationId", rec["organizationId"]))
        if self._has(rec, "screenProjectId"):candidates.append(("screenProjectId", rec["screenProjectId"]))
        chosen = random.sample(candidates, min(2, len(candidates)))
        for k, v in chosen:
            body[k] = v
        self.client.post("/screen/record/list",
                         data=json.dumps(body),
                         headers={"Content-Type": "application/json"},
                         name="POST /screen/record/list")

    @tag('screen-list')
    @task(1)
    def combo_all_params(self):
        """全参数组合: 尽可能多的筛选参数一起使用"""
        rec = self._rand_rec()
        body = {"pageNum": self._rand_page(), "pageSize": self._rand_size()}
        if self._has(rec, "patientName"):      body["patientName"] = rec["patientName"]
        if rec.get("gender") is not None:       body["gender"] = str(rec["gender"])
        if self._has(rec, "regionId"):          body["regionId"] = rec["regionId"]
        if self._has(rec, "hospitalIds"):       body["hospitalIds"] = rec["hospitalIds"]
        if self._has(rec, "organizationId"):    body["organizationId"] = rec["organizationId"]
        if self._has(rec, "screenProjectId"):   body["screenProjectId"] = rec["screenProjectId"]
        date_val = rec.get("bindCardDate") or rec.get("screenDate") or ""
        if date_val:
            body["bindDateStart"] = date_val[:10]
            body["bindDateEnd"] = date_val[:10]
        self.client.post("/screen/record/list",
                         data=json.dumps(body),
                         headers={"Content-Type": "application/json"},
                         name="POST /screen/record/list")

class ListOnlyUser(HttpUser):
    wait_time = between(0.3, 1)
    tasks = [ListOnlyTasks]

@events.init.add_listener
def on_init(environment, **kwargs):
    fetch_real_data()
    pool = REAL_DATA.get("screenRecordPool", [])
    total = len(pool)
    # 统计可用字段覆盖情况
    fields = ["patientName","gender","regionId","hospitalIds","organizationId","screenProjectId","bindCardDate"]
    covered = {}
    for f in fields:
        cnt = sum(1 for r in pool if r.get(f) not in (None, "", []))
        covered[f] = cnt
    print(f"\n  {'='*55}")
    print(f"  单接口压测: POST /screen/record/list (筛查人员分页查询)")
    print(f"  screenRecordPool: {total} 条")
    print(f"  参数覆盖率:")
    print(f"    patientName:     {covered.get('patientName',0)}/{total}")
    print(f"    gender:          {covered.get('gender',0)}/{total}")
    print(f"    regionId:        {covered.get('regionId',0)}/{total}")
    print(f"    hospitalIds:     {covered.get('hospitalIds',0)}/{total}")
    print(f"    organizationId:  {covered.get('organizationId',0)}/{total}")
    print(f"    screenProjectId: {covered.get('screenProjectId',0)}/{total}")
    print(f"    bindCardDate:    {covered.get('bindCardDate',0)}/{total}")
    print(f"  Tag: screen-list (可用 --tags screen-list 筛选)")
    print(f"  权重: 纯分页4 / 7种单条件各1 / 双条件组合2 / 全参数1 = 15")
    print(f"  {'='*55}\n")
