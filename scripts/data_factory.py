"""
测试数据工厂 — 通过 API 按需创建带 [AUTO] 标签的测试数据。

不依赖 fetch_real_data.py 的 API 拉取，而是直接调用各模块的 create 接口
生成可控的、带标签的测试数据。

创建的依赖顺序:
  1. organization  (机构 — 被项目/用户依赖)
  2. role          (角色 — 被用户依赖)
  3. project       (项目 — 依赖机构)
  4. patient       (病人 — 独立)
  5. user          (用户 — 依赖机构+角色)
  6. hardware      (硬件 — 独立)
  7. survey        (问卷 — 独立)

用法:
  python scripts/data_factory.py --scenario smoke --count 3           # 生成冒烟测试数据
  python scripts/data_factory.py --scenario regression --count 10     # 生成回归测试数据
  python scripts/data_factory.py --scenario perf --count 50           # 生成压测数据
  python scripts/data_factory.py --module patient --count 5           # 仅生成病人
  python scripts/data_factory.py --module patient,org --count 3       # 生成病人+机构
  python scripts/data_factory.py --dry-run                            # 预览，不真正创建
  python scripts/data_factory.py --update-extract                     # 更新 extract.yaml
"""
import json
import os
import sys
import time
import random
import argparse
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from commons.auth_token import get_auth_headers, get_token
from commons.data_tag import DataTag
from commons.data_tracker import DataTracker

BASE_URL = "http://your-api-server:8082"
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_headers():
    h = {"Content-Type": "application/json"}
    h.update(get_auth_headers())
    return h


def post_api(url, body=None):
    try:
        resp = requests.post(f"{BASE_URL}{url}", json=body or {},
                            headers=get_headers(), timeout=30)
        if resp.status_code == 200:
            return resp.json()
        print(f"  [HTTP {resp.status_code}] {url}: {resp.text[:100]}")
    except requests.RequestException as e:
        print(f"  [ERR] POST {url}: {e}")
    return None


class DataFactory:
    def __init__(self, scenario="smoke", count=3, dry_run=False, update_extract=False):
        self.scenario = scenario
        self.count = count
        self.dry_run = dry_run
        self.update_extract = update_extract
        self.created = {}       # module → [ids]
        self.extract_updates = {}  # 需要写入 extract.yaml 的键

    def _tag(self, base_name):
        return DataTag.make_name(base_name, self.scenario)

    def create_organizations(self):
        print(f"\n[{DataFactory._step_num()}] 创建机构 (×{self.count})...")
        ids = []
        for i in range(self.count):
            name = self._tag(f"测试机构-{i+1:03d}")
            if self.dry_run:
                print(f"  DRY-RUN: POST /organization/create {name}")
                ids.append(f"dry-{i}")
                continue

            data = post_api("/organization/create", {
                "orgName": name,
                "orgType": random.choice([1, 2, 3]),
                "regionId": random.choice([1, 2, 3]),
                "address": random.choice([
                    "浙江省杭州市西湖区某某街道100号",
                    "北京市朝阳区某某路200号",
                    "上海市浦东新区某某大道300号",
                    "广东省广州市天河区某某路400号",
                ]),
                "contactPerson": self._tag("联系人"),
                "contactInfo": DataTag.make_unique_phone(),
            })
            if data and data.get("success"):
                rid = data.get("data")
                ids.append(rid)
                DataTracker.track("organization", rid, self.scenario)
                print(f"  [OK] {name} → id={rid}")
            else:
                print(f"  [FAIL] {name}")
            time.sleep(0.1)

        self.created["organization"] = ids
        if ids and self.update_extract:
            self.extract_updates["realOrgId"] = ids[0]
            self.extract_updates["realOrgName"] = self._tag(f"测试机构-001")

    def create_roles(self):
        print(f"\n[{DataFactory._step_num()}] 创建角色 (×{self.count})...")
        ids = []
        for i in range(self.count):
            name = self._tag(f"测试角色-{i+1:03d}")
            if self.dry_run:
                print(f"  DRY-RUN: POST /role/add {name}")
                ids.append(f"dry-{i}")
                continue

            data = post_api("/role/add", {
                "roleName": name,
                "roleKey": f"auto_role_{int(time.time()*1000)}_{i}",
                "description": f"数据工厂{self.scenario}场景生成",
                "dataScope": random.choice([1, 2, 3]),
                "status": 1,
                "isDefault": 0,
                "sort": i,
            })
            if data and data.get("success"):
                rid = data.get("data")
                ids.append(rid)
                DataTracker.track("role", rid, self.scenario)
                print(f"  [OK] {name} → id={rid}")
            else:
                print(f"  [FAIL] {name}")
            time.sleep(0.1)

        self.created["role"] = ids
        if ids and self.update_extract:
            self.extract_updates["realRoleId"] = ids[0]

    def create_patients(self):
        print(f"\n[{DataFactory._step_num()}] 创建病人 (×{self.count})...")
        ids = []
        id_nos = []
        for i in range(self.count):
            name = self._tag(f"病人-{i+1:03d}")
            if self.dry_run:
                print(f"  DRY-RUN: POST /patient/create {name}")
                ids.append(f"dry-{i}")
                continue

            gender = random.choice([0, 1])
            id_no = DataTag.make_unique_id_no(gender=gender)
            age = DataTag.age_from_id_no(id_no)
            data = post_api("/patient/create", {
                "name": name,
                "age": age,
                "gender": gender,
                "idNo": id_no,
                "address": random.choice([
                    "浙江省杭州市西湖区某某街道100号",
                    "北京市朝阳区某某路200号",
                    "上海市浦东新区某某大道300号",
                    "广东省广州市天河区某某路400号",
                ]),
                "emergencyContact": self._tag("紧急联系人"),
                "emergencyPhone": DataTag.make_unique_phone(),
            })
            if data and data.get("success"):
                pid = data.get("data")
                ids.append({"id": pid, "name": name, "gender": gender, "idNo": id_no})
                id_nos.append(id_no)
                DataTracker.track("patient", pid, self.scenario)
                print(f"  [OK] {name} → patientId={pid}")
            else:
                print(f"  [FAIL] {name}")
            time.sleep(0.1)

        self.created["patient"] = ids
        if ids and self.update_extract:
            self.extract_updates["realPatientId"] = ids[0]["id"]
            if id_nos:
                self.extract_updates["realIdNo"] = id_nos[0]

    def create_projects(self, org_ids=None):
        if not org_ids:
            org_ids = self.created.get("organization", [])
        if not org_ids:
            print(f"\n[{DataFactory._step_num()}] 跳过：需要先创建机构")
            return

        print(f"\n[{DataFactory._step_num()}] 创建项目 (×{self.count})...")
        ids = []
        for i in range(self.count):
            name = self._tag(f"测试项目-{i+1:03d}")
            if self.dry_run:
                print(f"  DRY-RUN: POST /project/create {name}")
                ids.append(f"dry-{i}")
                continue

            hospital_id = random.choice(org_ids) if org_ids else 18
            data = post_api("/project/create", {
                "projectName": name,
                "projectStatus": random.choice([0, 1]),
                "screenDate": time.strftime("%Y-%m-%d"),
                "hospitalIds": [hospital_id],
                "organizationId": random.choice(org_ids),
                "regionId": random.choice([1, 2, 3]),
                "description": f"数据工厂{self.scenario}场景生成的测试项目",
                "contactPerson": self._tag("项目负责人"),
                "contactPhone": DataTag.make_unique_phone(),
            })
            if data and data.get("success"):
                pid = data.get("data")
                ids.append(pid)
                DataTracker.track("project", pid, self.scenario)
                print(f"  [OK] {name} → id={pid}")
            else:
                print(f"  [FAIL] {name}")
            time.sleep(0.1)

        self.created["project"] = ids
        if ids and self.update_extract:
            self.extract_updates["realProjectId"] = ids[0]

    def create_users(self, org_ids=None, role_ids=None):
        if not org_ids:
            org_ids = self.created.get("organization", [])
        if not role_ids:
            role_ids = self.created.get("role", [])
        if not org_ids or not role_ids:
            print(f"\n[{DataFactory._step_num()}] 跳过：需要先创建机构和角色")
            return

        print(f"\n[{DataFactory._step_num()}] 创建用户 (×{self.count})...")
        ids = []
        for i in range(self.count):
            name = self._tag(f"用户-{i+1:03d}")
            phone = DataTag.make_unique_phone()
            if self.dry_run:
                print(f"  DRY-RUN: POST /user/create {name}")
                ids.append(f"dry-{i}")
                continue

            data = post_api("/user/create", {
                "username": name,
                "loginAccount": phone,
                "phone": phone,
                "orgId": random.choice(org_ids),
                "status": 1,
                "roleIds": [random.choice(role_ids)],
                "gender": random.choice([0, 1]),
            })
            if data and data.get("success"):
                uid = data.get("data")
                ids.append(uid)
                DataTracker.track("user", uid, self.scenario)
                print(f"  [OK] {name} → id={uid}")
            else:
                print(f"  [FAIL] {name}")
            time.sleep(0.1)

        self.created["user"] = ids
        if ids and self.update_extract:
            self.extract_updates["realUserId"] = ids[0]
            self.extract_updates["realUsername"] = self._tag("用户-001")
            self.extract_updates["realUserPhone"] = f"199xxxxxxxx"

    def create_hardware(self):
        print(f"\n[{DataFactory._step_num()}] 创建硬件 (×{self.count})...")
        ids = []
        org_ids = self.created.get("organization", [])
        for i in range(self.count):
            hw_no = self._tag(f"HW-{int(time.time()*1000)}-{i:03d}")
            hw_type = random.choice([1, 2])  # 1=智能卡 2=PDA
            if self.dry_run:
                print(f"  DRY-RUN: POST /hardware-manage/create {hw_no}")
                ids.append(f"dry-{i}")
                continue

            body = {
                "hardwareNo": hw_no,
                "hardwareType": hw_type,
            }
            # PDA 可在创建时绑定机构，绑定后直接视为已绑定状态
            if hw_type == 2 and org_ids:
                body["organizationId"] = random.choice(org_ids)

            data = post_api("/hardware-manage/create", body)
            if data and data.get("success"):
                hid = data.get("data")
                ids.append(hid)
                DataTracker.track("hardwareManage", hid, self.scenario)
                print(f"  [OK] {hw_no} → id={hid}")
            else:
                print(f"  [FAIL] {hw_no}")
            time.sleep(0.1)

        self.created["hardwareManage"] = ids
        if ids and self.update_extract:
            self.extract_updates["realHardwareManageId"] = ids[0]

    def create_surveys(self):
        print(f"\n[{DataFactory._step_num()}] 创建问卷 (×{self.count})...")
        ids = []
        for i in range(self.count):
            title = self._tag(f"测试问卷-{i+1:03d}")
            if self.dry_run:
                print(f"  DRY-RUN: POST /survey/create {title}")
                ids.append(f"dry-{i}")
                continue

            questions = [
                {"content": "您是否有吸烟史？", "questionType": 1,
                 "options": [{"key": "A", "label": "是"},
                            {"key": "B", "label": "否"}],
                 "sortOrder": 1},
                {"content": "直系亲属中是否有人患过肿瘤？", "questionType": 1,
                 "options": [{"key": "A", "label": "是"},
                            {"key": "B", "label": "否"},
                            {"key": "C", "label": "不清楚"}],
                 "sortOrder": 2},
                {"content": "最近一个月是否有咳嗽、胸痛等症状？", "questionType": 1,
                 "options": [{"key": "A", "label": "无"},
                            {"key": "B", "label": "偶尔"},
                            {"key": "C", "label": "经常"}],
                 "sortOrder": 3},
            ]
            data = post_api("/survey/create", {
                "title": title,
                "questions": questions,
            })
            if data and data.get("success"):
                sid = data.get("data")
                ids.append(sid)
                DataTracker.track("survey", sid, self.scenario)
                print(f"  [OK] {title} → id={sid}")
            else:
                print(f"  [FAIL] {title}")
            time.sleep(0.1)

        self.created["survey"] = ids
        if ids and self.update_extract:
            self.extract_updates["realSurveyId"] = ids[0]

    def create_screening_records(self, patient_ids=None):
        if not patient_ids:
            patient_ids = self.created.get("patient", [])
        if not patient_ids:
            print(f"\n[{DataFactory._step_num()}] 跳过：需要先创建病人")
            return

        project_ids = self.created.get("project", [])
        if not project_ids:
            print(f"\n[{DataFactory._step_num()}] 跳过：需要先创建项目")
            return

        print(f"\n[{DataFactory._step_num()}] 创建筛查记录 (×{self.count})...")
        ids = []
        for i in range(self.count):
            ts = int(time.time() * 1000)
            # 兼容 dict(含id/name/gender/idNo) 和纯 ID 两种格式
            patient = random.choice(patient_ids)
            if isinstance(patient, dict):
                pid = patient["id"]
                pname = patient["name"]
                pgender = patient["gender"]
                pid_no = patient["idNo"]
            else:
                pid = patient
                pname = self._tag(f"筛查病人-{i+1:03d}")
                pgender = random.choice([0, 1])
                pid_no = DataTag.make_unique_id_no()

            screen_project_id = random.choice(project_ids)
            if isinstance(screen_project_id, dict):
                screen_project_id = screen_project_id["id"]

            if self.dry_run:
                print(f"  DRY-RUN: POST /screen/record/create #{i+1}")
                ids.append(f"dry-{i}")
                continue

            data = post_api("/screen/record/create", {
                "patientId": pid,
                "patientName": pname,
                "gender": pgender,
                "idNo": pid_no,
                "screenNo": f"SC{ts}",
                "screenProjectId": screen_project_id,
                "bindCardNo": f"CARD{ts}",
                "bindCardDate": time.strftime("%Y-%m-%d"),
                "screenDate": time.strftime("%Y-%m-%d"),
                "securityTestAnswerId": 0,
                "screenItemAnswerId": 0,
            })
            if data and data.get("success"):
                sid = data.get("data")
                ids.append(sid)
                DataTracker.track("screenRecord", sid, self.scenario)
                print(f"  [OK] 筛查记录#{i+1} → id={sid}")
            else:
                print(f"  [FAIL] 筛查记录#{i+1}")
            time.sleep(0.1)

        self.created["screenRecord"] = ids
        if ids and self.update_extract:
            self.extract_updates["realScreenRecordId"] = ids[0]

    # --- 批量方法 ---

    def create_dependency_chain(self):
        """按依赖顺序创建完整数据链"""
        self.create_organizations()
        self.create_roles()
        self.create_projects()
        self.create_patients()
        self.create_users()
        self.create_hardware()
        self.create_surveys()
        self.create_screening_records()

    def create_all(self):
        """创建所有模块（无依赖顺序要求）"""
        self.create_organizations()
        self.create_roles()
        self.create_patients()
        self.create_projects()
        self.create_users()
        self.create_hardware()
        self.create_surveys()
        self.create_screening_records()

    # --- 工具 ---

    _step_counter = 0

    @classmethod
    def _step_num(cls):
        cls._step_counter += 1
        return cls._step_counter

    @classmethod
    def reset_counter(cls):
        cls._step_counter = 0

    def write_extract(self):
        """将创建的数据更新到 extract.yaml"""
        if not self.extract_updates:
            return
        import yaml
        extract_path = os.path.join(PROJECT_DIR, "extract.yaml")
        existing = {}
        if os.path.exists(extract_path):
            with open(extract_path, "r", encoding="utf-8") as f:
                try:
                    existing = yaml.safe_load(f) or {}
                except Exception:
                    existing = {}
        existing.update(self.extract_updates)
        with open(extract_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(existing, f, allow_unicode=True, default_flow_style=False)
        print(f"\n[OK] extract.yaml 已更新 ({len(self.extract_updates)} 个键)")

    def print_summary(self):
        print("\n" + "=" * 55)
        total = sum(len(v) for v in self.created.values())
        print(f"  创建摘要 ({self.scenario}, {'DRY-RUN' if self.dry_run else '正式'})")
        print(f"  总计: {total} 条记录")
        for mod, ids in self.created.items():
            if ids:
                print(f"    {mod}: {len(ids)} 条")
        if not self.dry_run:
            print(f"  追踪文件: .test_created_ids.json")
            if self.update_extract:
                print(f"  extract.yaml 已更新")
        print("=" * 55)


# ==================== 模块名映射 ====================

MODULE_MAP = {
    "org":          "organizations",
    "organization": "organizations",
    "role":         "roles",
    "patient":      "patients",
    "project":      "projects",
    "user":         "users",
    "hardware":     "hardware",
    "survey":       "surveys",
    "screening":    "screening_records",
}

DEPENDENCY_CHAIN = [
    "organizations",
    "roles",
    "projects",
    "patients",
    "users",
    "hardware",
    "surveys",
    "screening_records",
]


def main():
    parser = argparse.ArgumentParser(
        description="测试数据工厂 — 按需创建带 [AUTO] 标签的测试数据",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/data_factory.py --scenario smoke --count 3         # 冒烟测试数据
  python scripts/data_factory.py --scenario regression --count 10   # 回归测试数据
  python scripts/data_factory.py --scenario perf --count 50         # 压测数据
  python scripts/data_factory.py --module patient --count 5         # 仅创建病人
  python scripts/data_factory.py --dry-run                          # 预览
  python scripts/data_factory.py --update-extract                   # 同时更新 extract.yaml
""",
    )
    parser.add_argument("--scenario", default="smoke",
                       choices=["smoke", "regression", "perf", "yaml"],
                       help="场景标识 (默认: smoke)")
    parser.add_argument("--count", type=int, default=3,
                       help="每个模块创建的数量 (默认: 3)")
    parser.add_argument("--module", type=str, default="",
                       help="仅创建指定模块，逗号分隔")
    parser.add_argument("--dry-run", action="store_true",
                       help="预览模式，不真正创建")
    parser.add_argument("--update-extract", action="store_true",
                       help="同步更新 extract.yaml 的 real* 键")

    args = parser.parse_args()

    # 检查 token
    if not args.dry_run:
        token = get_token()
        if not token:
            print("[FAIL] Token 不存在或已过期！")
            print("请先运行: python scripts/auth_helper.py")
            sys.exit(1)
        print(f"[OK] Token 已就绪 ({token[:20]}...)")

    DataFactory.reset_counter()
    factory = DataFactory(
        scenario=args.scenario,
        count=args.count,
        dry_run=args.dry_run,
        update_extract=args.update_extract,
    )

    print("=" * 55)
    print(f"  测试数据工厂")
    print(f"  服务器 : {BASE_URL}")
    print(f"  场景   : {args.scenario}")
    print(f"  数量   : {args.count} / 模块")
    if args.dry_run:
        print(f"  模式   : DRY-RUN (预览)")
    if args.update_extract:
        print(f"  extract: 同步更新")
    print("=" * 55)

    if args.module:
        modules = [m.strip() for m in args.module.split(",") if m.strip()]
        method_names = []
        for m in modules:
            method_name = MODULE_MAP.get(m)
            if not method_name:
                print(f"[WARN] 未知模块: {m}，已跳过")
                continue
            method_names.append(method_name)

        if not method_names:
            print("[FAIL] 没有可创建的有效模块")
            sys.exit(1)

        # 按依赖顺序排列
        ordered = [m for m in DEPENDENCY_CHAIN if m in method_names]
        for m in ordered:
            getattr(factory, f"create_{m}")()
    else:
        factory.create_dependency_chain()

    factory.print_summary()

    if args.update_extract and not args.dry_run:
        factory.write_extract()

    if not args.dry_run:
        total = sum(len(v) for v in factory.created.values())
        if total > 0:
            print(f"\n清理数据: python scripts/data_cleanup.py --mode tracked")


if __name__ == "__main__":
    main()
