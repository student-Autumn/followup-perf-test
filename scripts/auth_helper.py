"""
交互式登录工具 — 发送短信验证码 → 用户输入 → 登录 → 保存 token

用法:
  python scripts/auth_helper.py           # 完整登录流程
  python scripts/auth_helper.py --check   # 仅检查 token 是否有效
  python scripts/auth_helper.py --force   # 强制重新登录（不检查现有 token）

所有测试框架（pytest / k6 / Locust）共用 .auth_token.yaml 中的 token。
"""
import json
import os
import sys
import time
import requests

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

from commons.auth_token import (
    load_token,
    save_token,
    check_token_valid,
    BASE_URL,
    LOGIN_PHONE,
)


def send_sms_code(phone, device_type="PC"):
    """发送短信验证码"""
    print(f"\n[1/3] 发送验证码到 {phone} ...")
    try:
        resp = requests.post(
            f"{BASE_URL}/auth/sms/code",
            json={"phone": phone, "deviceType": device_type},
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                print("  [OK] 验证码已发送，请查收短信")
                return True
            else:
                print(f"  [FAIL] 发送失败: {data.get('message', '')}")
                return False
        else:
            print(f"  [FAIL] HTTP {resp.status_code}")
            return False
    except requests.RequestException as e:
        print(f"  [FAIL] 网络错误: {e}")
        return False


def login_with_code(phone, code, device_type="PC"):
    """用验证码登录，返回 token 数据"""
    print(f"\n[2/3] 正在登录 ...")
    try:
        resp = requests.post(
            f"{BASE_URL}/auth/sms/login",
            json={"phone": phone, "code": code, "deviceType": device_type},
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success") and data.get("data"):
                token_data = data["data"]
                print(f"  [OK] 登录成功")
                return {
                    "token": token_data.get("token"),
                    "tokenType": token_data.get("tokenType", "Bearer"),
                    "phone": phone,
                    "deviceType": token_data.get("deviceType", device_type),
                    "expiresIn": token_data.get("expiresIn", 0),
                }
            else:
                print(f"  [FAIL] 登录失败: {data.get('message', '')}")
                return None
        else:
            print(f"  [FAIL] HTTP {resp.status_code}")
            return None
    except requests.RequestException as e:
        print(f"  [FAIL] 网络错误: {e}")
        return None


def calc_expiry_time(expires_in_seconds):
    """根据过期秒数计算过期时间字符串，默认 24 小时"""
    if not expires_in_seconds or expires_in_seconds <= 0:
        expires_in_seconds = 86400  # 默认 24h
    expiry_ts = time.time() + expires_in_seconds
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(expiry_ts))


def do_login():
    """完整登录流程：发送验证码 → 等待输入 → 登录 → 保存"""
    phone = LOGIN_PHONE

    # Step 1: 发送验证码
    if not send_sms_code(phone):
        sys.exit(1)

    # Step 2: 等待用户输入验证码
    print(f"\n[2/3] 请输入收到的短信验证码")
    try:
        code = input("  验证码: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  已取消")
        sys.exit(1)

    if not code:
        print("  [FAIL] 验证码不能为空")
        sys.exit(1)

    # Step 3: 登录
    token_data = login_with_code(phone, code)
    if not token_data:
        sys.exit(1)

    # Step 4: 保存（添加过期时间）
    print(f"\n[3/3] 保存 token ...")
    token_data["expiresAt"] = calc_expiry_time(token_data.pop("expiresIn", 0))
    save_token(token_data)

    # 显示摘要
    print(f"\n  {'='*50}")
    print(f"  手机号  : {phone}")
    print(f"  Token   : {token_data['token'][:20]}...")
    print(f"  类型    : {token_data['tokenType']}")
    print(f"  过期    : {token_data.get('expiresAt', 'N/A')}")
    print(f"  {'='*50}")
    print(f"\n  现在可以运行测试了:")
    print(f"    python run.py")
    print(f"    k6 run perftest/k6-script.js")
    print(f"    locust -f perftest/locustfile.py")


def main():
    print(f"\n  {'='*50}")
    print(f"  API 认证助手")
    print(f"  服务器 : {BASE_URL}")
    print(f"  账号   : {LOGIN_PHONE}")
    print(f"  {'='*50}")

    force = "--force" in sys.argv

    if "--check" in sys.argv:
        valid, msg = check_token_valid()
        print(f"\n  Token 状态: {msg}")
        return

    if not force:
        existing = load_token()
        if existing and existing.get("token"):
            valid, msg = check_token_valid()
            print(f"\n  现有 Token 状态: {msg}")
            if valid:
                answer = input("\n  Token 仍然有效，是否重新登录？(y/N): ").strip().lower()
                if answer != "y":
                    print("  已跳过登录")
                    return

    do_login()


if __name__ == "__main__":
    main()
