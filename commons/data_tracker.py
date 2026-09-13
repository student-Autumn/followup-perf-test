"""
测试数据追踪器 — 记录所有测试过程中创建的记录 ID。

用于测试结束后的自动清理。线程安全，支持 pytest + k6 + Locust 并发场景。

输出文件: <project_root>/.test_created_ids.json
"""
import json
import os
import threading
from datetime import datetime


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACKER_PATH = os.path.join(PROJECT_DIR, ".test_created_ids.json")

_lock = threading.Lock()


def _read_tracker():
    """读取当前追踪文件内容"""
    if not os.path.exists(TRACKER_PATH):
        return {}
    try:
        with open(TRACKER_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (json.JSONDecodeError, IOError):
        pass
    return {}


def _write_tracker(data):
    """写入追踪文件"""
    os.makedirs(os.path.dirname(TRACKER_PATH), exist_ok=True)
    with open(TRACKER_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class DataTracker:
    """线程安全的测试数据 ID 注册表"""

    # 模块名到删除路径的映射
    MODULE_DELETE_PATHS = {
        "patient":        "/patient/delete/{id}",
        "organization":   "/organization/delete/{id}",
        "project":        "/project/delete/{id}",
        "role":           "/role/delete/{id}",
        "hardwareManage": "/hardware-manage/delete/{id}",
        "survey":         "/survey/delete/{id}",
        "user":           "/user/delete/{id}",
        "screenRecord":   "/screen/record/delete/{id}",
        "operationLog":   "/operation-log/delete/{id}",
    }

    @staticmethod
    def track(module, record_id, scenario="unknown"):
        """记录一个创建的 ID"""
        if record_id is None:
            return
        with _lock:
            data = _read_tracker()

            if module not in data:
                data[module] = []
            rid = str(record_id)
            if rid not in data[module]:
                data[module].append(rid)

            meta = data.setdefault("_meta", {})
            meta["updatedAt"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            meta["scenario"] = scenario

            _write_tracker(data)

    @staticmethod
    def track_batch(module, ids, scenario="unknown"):
        """批量记录多个 ID"""
        if not ids:
            return
        with _lock:
            data = _read_tracker()

            if module not in data:
                data[module] = []
            for rid in ids:
                rid_s = str(rid)
                if rid_s not in data[module]:
                    data[module].append(rid_s)

            meta = data.setdefault("_meta", {})
            meta["updatedAt"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            meta["scenario"] = scenario

            _write_tracker(data)

    @staticmethod
    def get_module(module):
        """返回某个模块下所有已追踪的 ID"""
        data = _read_tracker()
        return data.get(module, [])

    @staticmethod
    def get_all():
        """返回完整的追踪字典（不含 _meta）"""
        data = _read_tracker()
        return {k: v for k, v in data.items() if not k.startswith("_")}

    @staticmethod
    def total():
        """返回已追踪的总记录数"""
        data = _read_tracker()
        return sum(len(v) for k, v in data.items()
                   if isinstance(v, list) and not k.startswith("_"))

    @staticmethod
    def summary():
        """返回各模块追踪数量的摘要"""
        data = _read_tracker()
        result = {}
        for k, v in data.items():
            if isinstance(v, list) and not k.startswith("_"):
                result[k] = len(v)
        return result

    @staticmethod
    def clear(keep_backup=True):
        """清空追踪文件"""
        with _lock:
            if keep_backup and os.path.exists(TRACKER_PATH):
                bak = TRACKER_PATH + ".bak"
                try:
                    os.replace(TRACKER_PATH, bak)
                except OSError:
                    pass
            else:
                if os.path.exists(TRACKER_PATH):
                    os.remove(TRACKER_PATH)
