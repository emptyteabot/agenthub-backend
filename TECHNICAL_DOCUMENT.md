# AgentHub 技术文档

## 1. 架构总览

AgentHub 采用 FastAPI 后端、SQLite 持久化、WebSocket 实时通信、Pydantic 结构化契约和工作区文件系统组合实现。

核心链路为：

1. 前端通过 WebSocket 发送用户消息。
2. 后端创建或恢复 Session。
3. MessageRepository 加载最近历史上下文。
4. DynamicOrchestrator 读取 Agent 注册表。
5. LLM Function Calling 选择目标 Agent。
6. Adapter 执行目标 Agent。
7. 子 Agent 返回 Pydantic 结构化产物。
8. WorkspaceManager 写入工作区。
9. PythonSandbox 与 AsyncCodeRunner 校验代码。
10. 后端将每一步推送给前端并写入 SQLite。

## 2. 目录结构

```text
app/
  agents/
    coder.py
    schemas.py
    searcher.py
  core/
    adapters.py
    llm_client.py
    orchestrator.py
    runner.py
    sandbox.py
    workspace.py
  db/
    database.py
    models.py
    repositories.py
  main.py
frontend/
  code.html
workspaces/
agenthub.db
AI_Collaboration.md
PRODUCT_DESIGN.md
TECHNICAL_DOCUMENT.md
run_agenthub.bat
```

## 3. 后端模块

### 3.1 app.main

`app.main` 是 FastAPI 入口，负责：

- CORS 配置。
- `/workspaces` 静态目录挂载。
- `/frontend` 静态目录挂载。
- Agent REST API。
- Session 与 Message REST API。
- Workspace 文件 API。
- `/api/ws/chat` WebSocket 状态机。

WebSocket 内部维护 `SESSION_STATES`：

- `IDLE`：空闲。
- `PROCESSING`：任务运行中。
- `WAITING_HUMAN`：等待人工反馈。

### 3.2 AsyncLLMClient

`AsyncLLMClient` 使用 Python `openai` 库，支持：

- OpenAI 兼容 Base URL。
- Doubao Ark Endpoint。
- Mock Mode。

Mock Mode 用于比赛演示和 UI 联调。它可稳定生成快排、HTML 产物和 HITL 失败场景，避免外部模型服务不可用导致演示中断。

### 3.3 DynamicOrchestrator

`DynamicOrchestrator` 是系统大脑，负责：

- 加载 AgentRepository。
- 动态构造 Tool Calling tools。
- 执行 Plan、Action、Review。
- 管理 Checkpoint。
- 生成 Failure Lemma。
- 检测语义循环。
- 触发 HITL。

Orchestrator 不硬编码具体 Agent 名称，而使用 `agent_{id}` 作为工具名，命中后回表读取 Agent 实体。

### 3.4 Adapter Layer

`app/core/adapters.py` 定义统一接口：

```python
class BaseAgentAdapter(ABC):
    async def execute_task(self, prompt: str, system_prompt: str) -> str:
        raise NotImplementedError
```

实现包括：

- `CodexAdapter`
- `ClaudeCodeAdapter`
- `OpenCodeAdapter`

Agent 的 `tags` 可携带 driver 信息，例如 `driver:codex`、`driver:claude`、`driver:opencode`。

### 3.5 PythonSandbox

`PythonSandbox` 使用 `ast.parse` 对 Python 代码做静态语法检查。语法错误会被压缩为可读错误详情，进入 Review 阶段。

### 3.6 AsyncCodeRunner

`AsyncCodeRunner` 使用 `asyncio.create_subprocess_exec` 在会话工作区执行代码：

```text
cwd = workspaces/session_{id}
command = python src/main.py
```

它捕获 stdout、stderr 和 exit code，并设置 timeout 防止死循环。

### 3.7 WorkspaceManager

`WorkspaceManager` 为每个会话创建隔离目录：

```text
workspaces/session_{id}/
  src/
  tests/
```

支持安全写入、读取和文件树扫描。路径解析会检查目标是否逃逸工作区。

## 4. 数据模型

### 4.1 Session

保存会话标题、创建时间和最后活跃时间。

### 4.2 Message

保存聊天流事件：

- sender
- role
- content
- type
- session_id
- created_at

### 4.3 Artifact

保存 Agent 产物：

- version
- code_content
- diff_info
- message_id

### 4.4 Agent

保存可注册 Agent：

- name
- avatar
- system_prompt
- tags
- is_custom

系统初始化时自动创建编排器、代码专家、搜索者三个基础节点。

## 5. API 设计

### 5.1 Health

`GET /health`

返回服务状态和 Mock Mode 状态。

### 5.2 Agents

`GET /api/agents`

返回所有注册 Agent。

`POST /api/agents`

创建自定义 Agent。

### 5.3 Sessions

`GET /api/sessions`

按最后活跃时间倒序返回会话列表。

### 5.4 Messages

`GET /api/messages/{session_id}`

返回某个会话的完整消息流。`code_diff` 消息会附带 `filename` 与 `artifact_code`，用于前端重放产物卡片。

### 5.5 Workspace

`GET /api/workspace/{session_id}/files`

返回工作区文件树。

`GET /api/workspace/{session_id}/file?path=src/main.py`

读取指定文件。

### 5.6 Static Preview

`GET /workspaces/session_{id}/src/index.html`

返回工作区静态产物，用于 iframe 预览。

## 6. WebSocket 协议

### 6.1 Endpoint

`/api/ws/chat`

### 6.2 输入帧

普通消息：

```json
{
  "type": "message",
  "content": "帮我写一个快速排序算法",
  "session_id": 20
}
```

运行代码：

```json
{
  "action": "run",
  "session_id": 20
}
```

人工反馈：

```json
{
  "type": "human_feedback",
  "content": "请修复语法错误并继续",
  "session_id": 20
}
```

### 6.3 输出帧

关键输出类型：

- `session`
- `thought`
- `flow`
- `code_diff`
- `text`
- `review`
- `run`
- `stdout`
- `stderr`
- `run.requires_human`
- `done`

## 7. 自省循环

### 7.1 Plan

模型通过 Function Calling 选择目标 Agent，并输出 `thought` 与 `task_description`。

### 7.2 Action

Orchestrator 根据 Agent tags 选择 Adapter，执行任务并解析结构化结果。

### 7.3 Review

如果是 Python 代码：

1. 使用 AST 静态检查。
2. 使用子进程运行检查。
3. 检查语义要求。

如果失败，生成 Failure Lemma 并回滚到检查点。

### 7.4 HITL

当连续语义停滞或达到最大重试次数，Orchestrator 推送 `run.requires_human`。后端状态机进入 `WAITING_HUMAN`，直到前端发送 `human_feedback`。

## 8. 前端接入

当前前端文件：

`frontend/code.html`

前端 runtime 实现：

- 全局 WebSocket 长连接。
- Session 切换与历史重放。
- 文件树加载。
- HTML 文件 iframe 预览。
- Run 按钮执行工作区代码。
- HITL amber 状态胶囊与输入框呼吸边框。

## 9. 启动方式

在项目根目录执行：

```powershell
run_agenthub.bat
```

打开前端：

```text
http://127.0.0.1:8000/frontend/code.html
```

## 10. 验证路径

### 10.1 快排与 Runner

输入：

```text
帮我写一个快速排序算法
```

预期：

- 聊天流出现 thought、flow、code_diff、review。
- 右侧文件树出现 `src/main.py`。
- 点击 Run，终端卡片输出排序结果。

### 10.2 HTML Live Preview

输入：

```text
写一个 HTML 网页用于 AgentHub 演示
```

预期：

- 右侧文件树出现 `src/index.html`。
- 点击文件后源码和 iframe 同时展示。
- 后续 HTML code_diff 会自动刷新 iframe。

### 10.3 HITL

输入：

```text
hitl loop test fail repeatedly in python
```

预期：

- 三轮失败 review 后出现 `run.requires_human`。
- 输入框出现 amber 呼吸边框。
- 输入 `resume fix syntax failure with a runnable print statement` 后协程恢复并通过 review。

## 11. 技术风险与处理

### 11.1 外部模型不稳定

通过 Mock Mode 与 Adapter Layer 降低风险。

### 11.2 WebSocket 多会话串流

所有帧携带 `session_id`，前端只渲染当前会话帧。

### 11.3 代码执行风险

当前使用子进程、cwd 隔离和 timeout。后续可替换为 Docker 或 Pyodide。

### 11.4 敏感信息泄露

`.gitignore` 屏蔽 `.env`、数据库、工作区和日志。密钥只通过环境变量读取。
