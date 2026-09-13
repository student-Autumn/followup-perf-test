import pytest
from commons.yaml_util import clear_yaml

# TODO: 短信服务恢复后取消下面注释
# from commons.auth_token import check_token_valid


@pytest.fixture(scope="session", autouse=True)
def manage_data_lifecycle():
    """测试会话生命周期管理：开始前清理 extract.yaml，结束后报告数据追踪"""
    clear_yaml()
    yield
    # 会话结束后：输出本次测试创建的数据追踪摘要
    try:
        from commons.data_tracker import DataTracker
        total = DataTracker.total()
        if total > 0:
            summary = DataTracker.summary()
            print(f"\n  [DATA] 本次测试共创建 {total} 条记录")
            for mod, count in summary.items():
                print(f"    {mod}: {count} 条")
            print(f"  [DATA] 清理命令: python scripts/data_cleanup.py --mode tracked")
    except ImportError:
        pass


# TODO: 短信服务恢复后取消下面注释
# def pytest_sessionstart(session):
#     """测试会话开始前检查 token 有效性"""
#     valid, msg = check_token_valid()
#     if not valid:
#         print(f"\n  [WARN] {msg}")
#     else:
#         print(f"\n  [OK] {msg}")