"""
共享认证 Token 模块 — 所有测试框架（pytest / k6 / Locust）统一读取。

Token 文件:
  .auth_token.yaml  — YAML 格式，供 Python 框架使用
  .auth_token.json  — JSON 格式，供 k6 使用（k6 不原生支持 YAML）

工作流:
  1. python scripts/auth_helper.py        # 发送验证码 → 输入 → 登录 → 保存 token
  2. python scripts/auth_helper.py --check # 检查 token 是否有效
  3. 所有测试自动从 .auth_token.yaml 读取 token
  4. token 过期后，重新运行 scripts/auth_helper.py
"""
import json
import os
import time

import requests
import yaml

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_YAML_PATH = os.path.join(PROJECT_DIR, ".auth_token.yaml")
TOKEN_JSON_PATH = os.path.join(PROJECT_DIR, ".auth_token.json")
BASE_URL = "http://your-api-server:8082"
LOGIN_PHONE = "13800000000"


def load_token():
    """从 .auth_token.yaml 加载 token 信息，文件不存在返回 None"""
    if not os.path.exists(TOKEN_YAML_PATH):
        return None
    with open(TOKEN_YAML_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_token(token_data):
    """
    保存 token 到 .auth_token.yaml 和 .auth_token.json
    token_data: {"token": "...", "tokenType": "Bearer", "phone": "...", "expiresAt": "..."}
    """
    # YAML (for Python)
    with open(TOKEN_YAML_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(token_data, f, allow_unicode=True)

    # JSON (for k6)
    with open(TOKEN_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(token_data, f, ensure_ascii=False, indent=2)

    print(f"  [OK] token 已保存到 .auth_token.yaml / .auth_token.json")


def get_token():
    """获取有效的 token 字符串，过期或不存在则返回 None"""
    data = load_token()
    if not data or not data.get("token"):
        return None
    if is_expired(data):
        return None
    return data["token"]


def get_token_type():
    """获取 token 类型（默认 Bearer）"""
    data = load_token()
    if not data:
        return "Bearer"
    return data.get("tokenType", "Bearer")


def get_auth_headers():
    """获取带 Authorization 的请求头，token 无效时返回空字典"""
    token = get_token()
    if not token:
        return {}
    return {"Authorization": f"{get_token_type()} {token}"}


def is_expired(data=None):
    """检查 token 是否已过期（留 5 分钟缓冲）"""
    if data is None:
        data = load_token()
    if not data or not data.get("expiresAt"):
        return True
    expires_at = data["expiresAt"]
    # expiresAt 格式: "2026-06-18T10:00:00"
    try:
        expiry = time.mktime(time.strptime(expires_at, "%Y-%m-%dT%H:%M:%S"))
        return time.time() + 300 > expiry  # 5 分钟缓冲
    except (ValueError, OSError):
        return True


def check_token_valid():
    """
    通过调用一个轻量级公开接口检查 token 是否有效。
    返回 (valid: bool, message: str)
    """
    token = get_token()
    if not token:
        return False, "token 不存在或已过期，请运行: python scripts/auth_helper.py"

    try:
        headers = get_auth_headers()
        resp = requests.get(f"{BASE_URL}/hardware-manage/all", headers=headers, timeout=10)
        if resp.status_code == 401 or resp.status_code == 403:
            return False, f"token 已失效 (HTTP {resp.status_code})，请运行: python scripts/auth_helper.py"
        if resp.status_code == 200:
            return True, "token 有效"
        return True, f"token 验证通过 (HTTP {resp.status_code})"
    except requests.RequestException as e:
        # 网络问题不算 token 失效
        return True, f"无法验证 token (网络: {e})"


def get_phone():
    """获取当前登录手机号"""
    data = load_token()
    if not data:
        return LOGIN_PHONE
    return data.get("phone", LOGIN_PHONE)
