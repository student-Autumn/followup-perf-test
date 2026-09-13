"""
测试数据标签 — 统一标记所有自动生成的测试数据。

所有通过 data_factory 或测试脚本创建的数据都带 [AUTO] 前缀，
方便查询和清理时识别。
"""
import random as _random
from datetime import datetime, timedelta


class DataTag:
    """自动生成数据的标签工具"""

    AUTO_PREFIX = "[AUTO]"

    # 场景常量
    SCENARIO_SMOKE = "smoke"
    SCENARIO_REGRESSION = "regression"
    SCENARIO_PERF = "perf"
    SCENARIO_YAML = "yaml"
    SCENARIO_UNKNOWN = "unknown"

    @staticmethod
    def make_name(base, scenario="smoke", suffix=None):
        """生成带标签的名称，如 '[AUTO]角色名称__smoke__20260716_143022'

        Args:
            base: 基础名称（如角色名、机构名）
            scenario: 场景标识
            suffix: 额外后缀，默认用时间戳
        """
        if suffix is None:
            suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{DataTag.AUTO_PREFIX}{base}__{scenario}__{suffix}"

    @staticmethod
    def is_auto(value):
        """判断一个值是否包含 [AUTO] 标签"""
        if not isinstance(value, str):
            return False
        return value.startswith(DataTag.AUTO_PREFIX)

    @staticmethod
    def parse(value):
        """解析标签，返回 {base, scenario, suffix} 或 None"""
        if not DataTag.is_auto(value):
            return None
        inner = value[len(DataTag.AUTO_PREFIX):]
        parts = inner.split("__", 2)
        return {
            "base": parts[0] if len(parts) > 0 else "",
            "scenario": parts[1] if len(parts) > 1 else "unknown",
            "suffix": parts[2] if len(parts) > 2 else "",
        }

    @staticmethod
    def scenario_from(value):
        """从标签值中提取场景名"""
        parsed = DataTag.parse(value)
        return parsed["scenario"] if parsed else None

    # 身份证号地区码池（杭州/北京/上海/广州）
    _ID_AREA_CODES = ["330102", "330103", "330104", "110101", "110102",
                      "310101", "310102", "440103", "440104"]

    @staticmethod
    def make_unique_id_no(gender=None):
        """生成合法的18位身份证号。

        结构: 6位地区码 + 8位出生日期 + 3位顺序码 + 1位校验码
        第17位(顺序码末位): 奇数为男性, 偶数为女性

        Args:
            gender: 0=女, 1=男, None=随机
        """
        area = _random.choice(DataTag._ID_AREA_CODES)
        # 随机出生日期 1940-2010
        start = datetime(1940, 1, 1)
        days_range = (datetime(2010, 12, 31) - start).days
        birth = start + timedelta(days=_random.randint(0, days_range))
        birth_str = birth.strftime("%Y%m%d")
        seq = _random.randint(0, 999)
        if gender is not None:
            # 确保第17位(顺序码末位)与性别匹配: 奇数男, 偶数女
            seq = (seq // 10) * 10 + _random.choice(
                [1, 3, 5, 7, 9] if gender == 1 else [0, 2, 4, 6, 8])
        body = f"{area}{birth_str}{seq:03d}"
        # 计算校验码
        weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
        check_codes = "10X98765432"
        total = sum(int(body[i]) * weights[i] for i in range(17))
        return body + check_codes[total % 11]

    @staticmethod
    def age_from_id_no(id_no):
        """从身份证号计算年龄"""
        birth = datetime(int(id_no[6:10]), int(id_no[10:12]), int(id_no[12:14]))
        today = datetime.now()
        age = today.year - birth.year
        if (today.month, today.day) < (birth.month, birth.day):
            age -= 1
        return age

    @staticmethod
    def gender_from_id_no(id_no):
        """从身份证号提取性别 (0=女, 1=男)"""
        return int(id_no[16]) % 2

    @staticmethod
    def make_unique_phone():
        """生成唯一的手机号"""
        return f"199{_random.randint(10000000, 99999999)}"
