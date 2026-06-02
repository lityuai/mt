# 外呼任务对话 Agent 自动评测系统

本项目面向数字人外呼场景，构建了一套“任务型外呼 Agent + 自动化指令遵循评测”的完整原型系统。系统不仅可以根据给定任务指令生成外呼坐席回复，还可以自动模拟用户对话、覆盖关键业务分支，并生成可解释、可量化的评测报告。

## 项目定位

赛题关注的是：在复杂外呼任务中，如何低成本、可解释地评估对话模型是否真正遵循了任务指令。

本项目围绕这个目标做了三层设计：

1. 对话执行层：根据任务流程、知识点和约束生成坐席回复。
2. 用户模拟层：自动构造不同类型用户，主动触发正常、异常和边界分支。
3. 自动评测层：对每轮回复进行量化检查，并输出带证据的评测报告。

## 核心功能

- 任务型外呼 Agent
  支持骑手合同提醒、课程直播升级通知两类外呼任务。每类任务包含角色、目标、开场白、变量、流程、知识点、约束和快捷回复。

- 自动用户模拟器
  针对任务自动生成模拟用户脚本，例如身份询问、愿意配合、拒绝配送、错号、价格追问、忙碌、开车、第三方入口不可见等场景。

- 自动化评测报告
  系统会逐轮驱动 Agent 对话，并统计任务覆盖、流程控制、约束遵守、回复可靠性等维度分数。

- 企业级评测配置
  支持快速评测、全量评测、压力评测三种范围；支持自定义任务覆盖、流程控制、约束遵守、可靠性等维度权重；支持设置优秀线和合格线。

- 对比评测
  支持规则基线与 LLM 模式对比，输出各模式分数、相对基线差异和对比结论。

- 报告导出
  前端可一键导出 Markdown 评测报告，报告包含总分、原始分、维度分、场景证据和失败项。

- 可解释证据链
  每个评测场景都会保留用户输入、坐席回复、命中意图、状态变化和失败检查项，方便定位模型或规则没有遵循哪条指令。

- 本地规则模式与 LLM 模式
  默认可在无外部依赖的规则模式下运行；配置兼容 OpenAI Chat Completions 的模型服务后，可启用 LLM 生成自然话术。

- 企业级前端工作台
  页面包含任务选择、通话参数配置、手动对话、自动评测和报告展示，便于演示和人工复核。

## 系统架构

```text
前端工作台 static/
  ├─ 手动外呼对话
  └─ 自动评测报告展示

HTTP 服务 app.py
  ├─ 任务接口
  ├─ 会话接口
  ├─ 模型配置接口
  └─ 自动评测接口

核心模块 outbound_agent/
  ├─ AgentEngine        任务决策与回复生成
  ├─ EvaluationRunner   用户模拟与评测报告
  ├─ LLMClient          OpenAI 兼容模型调用
  ├─ SessionStore       会话状态存储
  └─ Models             任务、变量、消息、会话数据结构

任务数据 data/tasks.json
  └─ 结构化任务指令、流程、知识点、约束和变量
```

## 评测方法

自动评测模块位于 [outbound_agent/evaluation.py](outbound_agent/evaluation.py)。

评测流程：

1. 为指定任务加载一组模拟用户场景。
2. 创建独立会话并触发 Agent 开场。
3. 按脚本逐轮发送用户输入。
4. 记录每轮 Agent 回复、命中意图、会话状态。
5. 对回复进行规则化检查。
6. 汇总总分、维度分、场景分和失败证据。

当前评测维度：

- 任务覆盖：是否命中预期意图，是否覆盖关键业务信息。
- 流程控制：是否正确继续、结束或进入引导分支。
- 约束遵守：是否遵守字数、禁止话术、挂断策略等约束。
- 可靠性：是否出现模型调用失败或异常回复。

报告示例字段：

```json
{
  "summary": {
    "score": 100.0,
    "task_count": 1,
    "scenario_count": 5,
    "check_count": 51,
    "passed_count": 51,
    "conclusion": "整体遵循任务指令，关键流程和约束表现稳定。"
  },
  "task_reports": [
    {
      "task_id": "rider_flying_leg",
      "dimensions": [],
      "scenarios": []
    }
  ]
}
```

## 内置任务

```text
rider_flying_leg
  骑手飞毛腿合同提醒。重点评测合同生效通知、单量要求、退出规则、拒绝配送挽留、错号处理等分支。

course_live_upgrade
  课程直播选项升级通知。重点评测标准直播与低延迟直播差异、费用说明、忙碌挽留、开车挂断、第三方入口引导等分支。
```

## 快速运行

项目仅依赖 Python 标准库，默认不需要安装额外依赖。

```powershell
python app.py --port 8000
```

打开：

```text
http://127.0.0.1:8000
```

页面使用方式：

1. 左侧选择任务模板。
2. 填写或保留默认通话参数。
3. 点击“开始通话”进行手动对话。
4. 点击“运行评测”生成自动评测报告。

## LLM 模式

默认规则模式可直接运行。若希望让大模型负责自然话术生成，可配置：

```text
config/llm.json
```

示例：

```json
{
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o-mini",
  "api_key": "sk-..."
}
```

也可以使用环境变量：

```powershell
$env:OPENAI_API_KEY="你的密钥"
$env:OPENAI_MODEL="你的模型名"
$env:OPENAI_BASE_URL="https://your-endpoint.example.com/v1"
```

LLM 模式下，系统仍会先由 `AgentEngine` 生成确定性的 `ReplyPlan`，再由 `LLMClient` 将计划改写为自然电话话术，避免模型随意跳流程或新增承诺。

## API 说明

```text
GET  /api/health
GET  /api/llm/config
GET  /api/tasks
GET  /api/tasks/{task_id}
GET  /api/sessions/{session_id}

POST /api/llm/test
POST /api/sessions
POST /api/sessions/{session_id}/messages
POST /api/evaluations/run
POST /api/evaluations/compare
```

创建会话：

```json
{
  "task_id": "rider_flying_leg",
  "mode": "rule",
  "variables": {
    "rider_name": "张师傅",
    "X": "20",
    "Y": "12"
  }
}
```

运行评测：

```json
{
  "task_id": "rider_flying_leg",
  "mode": "rule",
  "variables": {
    "rider_name": "张师傅"
  },
  "settings": {
    "scope": "full",
    "weights": {
      "任务覆盖": 1.2,
      "流程控制": 1.2,
      "约束遵守": 1.0,
      "可靠性": 1.4
    },
    "thresholds": {
      "excellent": 90,
      "pass": 75,
      "risk": 60
    }
  }
}
```

如果不传 `task_id`，评测器会对全部内置任务运行评测。

对比评测：

```json
{
  "task_id": "rider_flying_leg",
  "modes": ["rule", "llm"],
  "settings": {
    "scope": "quick"
  }
}
```

## 测试

```powershell
python -m unittest discover -s tests
```

当前测试覆盖：

- Agent 关键业务分支。
- 错号、身份询问、拒绝配送、开车、忙碌等场景。
- LLM 调用消息结构。
- 模型配置脱敏。
- 自动评测报告生成。
- 企业级评测配置和对比评测报告。
- HTTP 兼容模型接口调用。

## 文件结构

```text
.
├─ app.py
│  HTTP 服务入口，提供静态页面、会话接口、任务接口和自动评测接口。
│
├─ data/
│  └─ tasks.json
│     结构化任务指令配置，包含任务目标、变量、流程、知识点、约束和快捷回复。
│
├─ config/
│  └─ llm.json
│     可选的大模型配置文件，用于 OpenAI 兼容接口。
│
├─ outbound_agent/
│  ├─ __init__.py
│  ├─ config.py
│  │  读取模型配置和环境变量。
│  ├─ engine.py
│  │  Agent 核心逻辑，负责业务意图判断、流程控制和回复计划生成。
│  ├─ evaluation.py
│  │  用户模拟器与自动评测器，输出量化、可解释评测报告。
│  ├─ llm.py
│  │  OpenAI 兼容模型客户端，负责 prompt 拼装和接口调用。
│  ├─ models.py
│  │  Task、Session、Message 等核心数据结构。
│  └─ storage.py
│     内存会话存储。
│
├─ static/
│  ├─ index.html
│  │  前端页面结构。
│  ├─ app.js
│  │  前端交互逻辑，负责任务选择、手动对话和评测报告渲染。
│  └─ styles.css
│     企业级工作台样式。
│
├─ tests/
│  ├─ __init__.py
│  └─ test_agent.py
│     单元测试与回归测试。
│
└─ README.md
   项目说明文档。
```

## 项目亮点

- 不只展示对话结果，还评估对话模型是否遵循任务指令。
- 评测过程自动化，减少人工逐条检查成本。
- 报告有分数、有维度、有证据，便于解释和定位问题。
- 支持本地规则 Agent，也支持接入大模型生成更自然的话术。
- 任务配置与评测逻辑分离，后续可扩展更多外呼任务和用户模拟场景。
