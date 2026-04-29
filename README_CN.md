# 扁鹊助手

<p align="left">
        中文 | <a href="README.md">English</a>
</p>
<br>

> 扁鹊助手：面向运维场景的 LLM 驱动智能 Skill 执行框架

扁鹊助手是一个开源的运维 AI 框架，核心思路是：**以文件描述运维分析 Skill（技能），由 LLM 驱动自动生成和执行,支持反馈更新，覆盖告警分析、巡检、阻断等场景**。

框架基于Flask启动运行，框架本身不绑定任何内部数据源或特定 LLM，所有接入点均以接口形式提供，开发者只需实现自己的数据获取逻辑与 LLM 接入即可跑通完整链路。

**本框架提供的是 Skill 执行的工作流骨架**（解析 → 查找 → 数据获取 → Prompt 组合 → LLM 推理 → 后处理 → 反馈更新），而非完整的 Agent 系统。对于上下文管理、多轮对话、工具调用编排等 Agent 能力（如长上下文压缩、沙箱执行、RAG 检索增强等），需使用者按自身场景自行实现或对接第三方 Agent 框架。

---

## 核心特性

- 见论文：Bian Que: An Agentic Framework with Flexible Skill Arrangement for Online System Operations

---

## 目录结构

```
BianQue_Assistant/
├── run_demo.sh                              # 一键启动 Demo 脚本
├── run_flask.sh                             # 一键启动 Flask 服务脚本
├── set_env.sh                               # LLM 环境变量配置模板
├── run_demo.py                              # 本地 Demo 运行脚本（无需启动 Flask）
├── requirements.txt
├── src/
│   ├── main.py                              # Flask 服务入口，HTTP 路由
│   └── app/
│       ├── framework/
│       │   ├── model/
│       │   │   └── llm.py                   # LLM 统一调用层（接入点，支持 OpenAI 兼容接口）
│       │   ├── data/
│       │   │   ├── providers.py             # 数据获取函数实现（TODO: 接入自有数据源）
│       │   │   ├── data_provider_registry.py  # 数据能力注册中心（自动加载 providers.py）
│       │   │   ├── data_fetcher.py          # 并行数据拉取引擎
│       │   │   ├── data_lake.yaml           # 数据能力声明配置（type / handler / 描述）
│       │   │   └── demo_data/               # Demo 示例数据目录
│       │   │       ├── performance.json     # Demo 服务性能指标数据
│       │   │       ├── knowledge.json       # Demo 知识库数据
│       │   │       └── mock_alert_request.json  # Demo 告警请求体示例
│       │   ├── knowledge/
│       │   │   └── get_knowlege.py          # 知识库检索接口（TODO: 接入自有知识库）
│       │   └── conf/
│       │       └── conf_manager.py         # 本地配置管理（Skill 文件读写，支持 Local/远程）
│       ├── skill_explore/
│       │   ├── skill_explore_main.py        # 各场景主入口（run_warning / run_inspect…）
│       │   ├── input_parser.py              # 请求解析适配层（TODO: 实现自有告警解析逻辑）
│       │   ├── skill_create.py              # LLM 驱动 Skill 自动生成（两阶段：Schema → Prompt）
│       │   ├── skill_executor.py            # Skill 执行引擎（4步 Workflow）
│       │   ├── skill_search.py              # Skill 检索（business + scene 匹配）
│       │   ├── skill_md_manager.py          # Skill Markdown 文件读写管理
│       │   └── skill_feedback.py            # Skill 内容反馈更新
│       ├── local_config/                    # 本地配置文件目录（自动生成，无需手动编辑）
│       │   ├── bianque_skill_registry.txt   # Skill 注册表（key → 文件路径映射）（首次运行后产生）
│       │   ├── bianque_skill_biz_classify.txt   # 业务分类配置（用于 Skill 匹配）
│       │   ├── bianque_skill_data_lake_summary.txt  # 数据能力摘要（供 skill_create 用）
│       │   ├── stage2_prompt_usability_warning.txt  # 可用性告警场景 Stage2 System Prompt
│       │   ├── stage2_prompt_coredump_warning.txt   # Coredump 告警场景 Stage2 System Prompt
│       │   ├── stage2_prompt_inspect.txt            # 巡检场景 Stage2 System Prompt
│       │   └── skill_*.txt                          # 自动生成的 Skill 文件（首次运行后产生）
│       ├── business/                    # 业务目录（按需添加业务特有逻辑）
│       │   ├── ad/
│       │   ├── reco/
│       │   └── search/
│       └── util/
│           └── logger.py                    # 日志工具（info_log / error_log / business_log）
```

---

## 快速开始

> **只需配置 LLM 环境变量，即可通过 `run_demo.py` 在 mock 数据下运行完整系统，无需任何额外开发。**
> 以下步骤 4~7 是将框架接入自有系统能力的工作，按需实现。

### 1. 安装依赖

```bash
cd BianQue_Assistant
pip3 install -r requirements.txt
```

### 2. 配置 LLM（必须）

框架内置 `OpenAICompatibleClient`，编辑 `set_env.sh` 填入配置即可：

```bash
# set_env.sh
export LLM_API_BASE="https://your-api-endpoint/v1"
export LLM_API_KEY="your_api_key"
export LLM_MODEL="your_model_name"   # 默认 qwen3
```

### 3. 启动

**Demo 模式**（本地直接运行，无需 Flask）：

```bash
bash run_demo.sh
```

**Flask 服务模式**：

```bash
bash run_flask.sh
```

两个脚本均会自动加载 `set_env.sh`（如果 LLM 环境变量未提前导出）。

若需接入自定义 LLM 后端，继承 `BaseLLMClient` 并在 `main.py` 启动时注册：

```python
from app.framework.model.llm import BaseLLMClient, set_llm_client

class MyLLMClient(BaseLLMClient):
    def chat(self, user_prompt, system_prompt="", request_id=""):
        return my_api.call(system_prompt, user_prompt)

set_llm_client(MyLLMClient())
```

---

以下步骤用于将框架接入自己的系统能力，按需实现：

### 4. 实现请求解析（接入自有告警系统）

编辑 `src/app/skill_explore/input_parser.py`，实现 `parse_warning()` 方法，将原始告警请求解析为 `ParsedInput`。

Demo 实现通过扁平 JSON 中的 `_mock_biz_id` 字段推导业务 ID，接入真实系统时需替换为实际告警 payload 解析逻辑（如 Prometheus AlertManager、PagerDuty 或内部告警平台）。

需提取并映射的关键字段：
- `business_id` — 用于匹配正确的 Skill
- `scene_id` — 决定走哪个分析工作流（如 `usability_warning`、`coredump_warning`）
- `context` — 注入到数据获取调用的运行时变量（`service_name`、`timestamp` 等）

```python
def parse_warning(self, data, request_id: str = ""):
    business_id = ...   # 例如 "search"、"ad"
    scene_id    = ...   # 例如 "usability_warning"、"coredump_warning"
    context     = {...} # 供数据获取函数使用的运行时变量（service_name、timestamp 等）
    biz_list    = [business_id]

    return ParsedInput(
        request_id=request_id,
        business_id=business_id,
        biz_list=biz_list,
        scene_id=scene_id,
        context=context,
        source="warning",
        timestamp=int(time.time()),
        raw_data=data,
    )
```

Demo 请求体示例（`src/app/framework/data/demo_data/mock_alert_request.json`）：

```json
{
  "_mock_biz_id": "demo",
  "service_name": "demo-service-1",
  "scene_type": "usability_warning",
  "timestamp": 1745742000,
  "alert_rule_name": "CPU Usage Alert",
  "alert_level": "P1"
}
```

### 5. 接入数据源（接入自有监控数据）

在 `src/app/framework/data/providers.py` 中实现数据获取函数。Demo 函数 `_fetch_data_demo()` 从 `demo_data/performance.json` 读取本地数据，接入真实系统时需替换为监控系统、时序数据库或指标 API 调用。

函数签名必须保持不变：`(params: dict, context: dict) -> Any`

```python
def _fetch_my_metric(params: dict, context: dict) -> Any:
    service_name = context.get("service_name", "")
    result = my_monitoring_api.query(service_name)
    return result
```

接入后还需：
1. 在 `data_lake.yaml` 的 `capabilities` 下注册（type / handler / 描述）
2. 在 `data_provider_registry.py` 的 import 列表中加入新函数
3. 在 `data_lake_summary.txt` 中追加一行摘要描述（供 skill_create 选择数据源使用）

```yaml
capabilities:
  - type: my_metric
    handler: _fetch_my_metric
    description: "获取自定义数据"
    context_keys: [name, timestamp]
    return_type: "dict"
    return_default: "{}"
```

### 6. 接入知识库（接入自有知识系统）

在 `src/app/framework/knowledge/get_knowlege.py` 中实现 `get_knowledge()` 接口，对接自己的知识库（如向量数据库、BM25 检索、RAG 流水线等）。

Demo 实现从 `demo_data/knowledge.json` 读取本地数据，按 `service_name` 匹配后返回 `customized_feedback` 文本。

函数签名必须保持不变：`(service_name: str, topk: int) -> str`

### 7. 启动 Flask 服务

```bash
bash run_flask.sh
```

---

## Demo 执行

配置好 LLM 环境变量后，直接运行本地脚本即可跑通完整链路（使用 mock 数据，无需启动 Flask 服务）：

```bash
bash run_demo.sh
```

运行效果：

![Demo 运行输出](assets/demo_output.png)

---

## Skill 文件格式

Skill 以 Markdown 文件存储，包含 YAML Frontmatter（元数据）和两个固定 Section（LoadDataSchema、Prompt）。

Skill 文件存储在 `local_config/` 目录下（由 `conf_manager.py` 管理），首次运行时由 `skill_create` 自动生成。示例：

````markdown
---
name: demo|demo-service-1-usability_warning-skill
description: 自动生成：usability_warning 场景下的 ['demo', 'demo-service-1'] 业务 Skill
version: 1.0.0
business: [demo, demo-service-1]
tags: [usability_warning]
---

## 概述

由 skill_create 自动生成

---

## LoadDataSchema

> 以下 JSON 描述了本 Skill 需要调用的所有数据函数及其入参 Schema。

```json
[
  {
    "type": "demo",
    "params_list": [
      {
        "name": "获取demo示例数据用于分析CPU使用率告警"
      }
    ]
  }
]
```

---

## Prompt

> 以下文本在 Agent 调用本 Skill 时，会注入到对话上下文中，指导模型完成任务。

```
你是一名资深运维可用性告警分析专家，专注于服务可用性异常诊断。

## 输入数据

## 分析流程

请基于输入数据，严格按以下步骤逐步分析：

步骤1：数据提取与理解
步骤2：指标曲线趋势分析
步骤3：事件关联性分析
步骤4：综合评定

## 输出要求

请以JSON格式输出分析结论，直接输出纯JSON文本：
{
  "conclusion": "需要关注",
  "summary": "...",
  "metric_analysis": [...],
  "event_analysis": [...],
  "suggestions": {...}
}
```

---
````


---

## 依赖

- Python
- Flask
- PyYAML
- openai（可选，如使用 OpenAI 兼容 API）

---

## License

Apache 2.0
