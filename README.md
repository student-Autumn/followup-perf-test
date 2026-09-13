# 筛查随访系统测试框架

接口自动化（pytest + YAML 数据驱动）与性能测试（Locust / k6）框架，针对「筛查随访系统」（PC 端 + 移动端）的接口层进行功能验证、回归与压测。

> ⚠️ 本仓库为脱敏版本：API 地址、服务器地址、域名、登录手机号均已替换为占位符，不含任何真实环境信息。运行前请替换为真实配置。

## 技术栈

- **接口自动化**：pytest + pytest-html + allure-pytest，YAML 数据驱动
- **性能测试**：Locust（HTTP 用户模型）、k6（JS 脚本）
- **数据管理**：测试数据工厂、`[AUTO]` 标签数据自动清理
- **指标上报**：Pushgateway / Prometheus（冒烟测试指标）

## 目录结构

```
├── commons/     # 框架核心：请求封装、YAML 解析、Token 管理、数据追踪
├── testcase/    # YAML 测试用例（按模块分类）+ pytest 入口
├── perftest/    # Locust / k6 性能测试脚本
├── scripts/     # 数据工厂、数据清理、登录、真实数据抓取、指标上报
├── hotload/     # YAML 中可热加载的自定义函数
├── configs/     # 全局配置
├── pytest.ini   # pytest 配置（含 base_url）
└── run.py       # 一键运行 + 生成 Allure 报告
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API 地址

编辑 `pytest.ini`，将 `base_url` 替换为真实环境地址：

```ini
[pytest]
base_url=http://your-api-server:8082
```

同时将 `commons/auth_token.py`、`perftest/locustfile.py` 等文件中的 `BASE_URL` / `LOGIN_PHONE` 替换为真实值。

### 3. 登录获取 Token

```bash
python scripts/auth_helper.py
```

### 4. 运行接口自动化测试

```bash
python run.py                  # 运行全部用例并生成 Allure 报告
python -m pytest -k smoke      # 只跑冒烟用例
```

### 5. 运行性能测试

```bash
# Locust
locust -f perftest/locustfile.py --host http://your-api-server:8082

# k6
k6 run perftest/k6-script.js
```

## 测试数据管理

```bash
python scripts/fetch_real_data.py   # 从 API 抓取真实数据
python scripts/data_factory.py      # 按需创建 [AUTO] 测试数据
python scripts/data_cleanup.py      # 清理 [AUTO] 测试数据
```

## 用例设计

测试用例以 YAML 描述，`testcase/test_all_case.py` 自动扫描 `testcase/**/*.yaml` 并生成 pytest 用例，支持参数化、断言、接口依赖提取与热加载函数（`hotload/debug_talk.py`）。
