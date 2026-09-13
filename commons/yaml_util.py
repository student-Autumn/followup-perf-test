import os
import yaml


def write_yaml(data):
    """写入 extract.yaml，会与已有数据合并（不会产生重复键）"""
    extract_path = "./extract.yaml"
    existing = {}
    if os.path.exists(extract_path):
        with open(extract_path, encoding="utf-8", mode="r") as f:
            try:
                existing = yaml.safe_load(f) or {}
            except Exception:
                existing = {}
    existing.update(data)
    with open(extract_path, encoding="utf-8", mode="w") as f:
        yaml.safe_dump(existing, stream=f, allow_unicode=True)

    # 自动追踪创建的 ID
    _auto_track(data)


def _auto_track(data):
    """自动检测并追踪写入 extract.yaml 的运行时 ID"""
    try:
        from commons.data_tracker import DataTracker
        # 运行时 ID 的键名映射
        id_module_map = {
            "opLogId": "operationLog",
            "screenRecordId": "screenRecord",
            "hardwareManageId": "hardwareManage",
            "orgId": "organization",
            "patientId": "patient",
            "projectId": "project",
            "surveyId": "survey",
            "userId": "user",
            "roleId": "role",
            "securityTestAnswerId": "securityTest",
        }
        for key, value in data.items():
            if key in id_module_map and value is not None:
                DataTracker.track(id_module_map[key], value, scenario="yaml")
    except ImportError:
        pass


def clear_yaml():
    """清除 extract.yaml 中的临时提取键（opLogId, screenRecordId），保留 real* 持久化数据"""
    extract_path = "./extract.yaml"
    if not os.path.exists(extract_path):
        return
    with open(extract_path, encoding="utf-8", mode="r") as f:
        try:
            data = yaml.safe_load(f) or {}
        except Exception:
            data = {}
    # 只清除临时键（create/update/delete 产生的运行时 ID）
    transient_keys = ["opLogId", "screenRecordId", "hardwareManageId", "orgId", "patientId", "projectId", "securityTestAnswerId", "surveyId", "userId"]
    for k in transient_keys:
        data.pop(k, None)
    with open(extract_path, encoding="utf-8", mode="w") as f:
        yaml.safe_dump(data, f, allow_unicode=True)