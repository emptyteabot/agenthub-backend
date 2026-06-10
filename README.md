# AgentHub - 多 Agent 协作平台

AgentHub 是一个 IM 聊天式多 Agent 协作平台。用户在会话里发送需求，后端 Orchestrator 动态调度代码专家、搜索者和可扩展 Agent Adapter，产出代码、运行日志、HTML 预览和 HITL 人工接管状态。

## Demo

- Demo 视频：https://github.com/emptyteabot/agenthub-backend/releases/download/demo-final/AgentHub_Demo_Final.mp4
- Release 页面：https://github.com/emptyteabot/agenthub-backend/releases/tag/demo-final
- 飞书交付正文：见 `FEISHU_DELIVERY_DOC.md`

## 核心能力

- IM 式会话工作台：左侧 Session，中间消息流，右侧 workspace。
- 多 Agent 动态调度：基于 Agent 注册表构建 Function Calling 工具矩阵。
- 结构化产物：Pydantic Structured Outputs 约束 `CoderOutput` / `SearchOutput`。
- 真实运行链路：代码写入 `workspaces/session_{id}`，Runner 子进程执行并返回 `stdout` / `stderr`。
- HTML 预览：FastAPI 挂载 `/workspaces`，前端 iframe 实时预览生成页面。
- HITL 闭环：AST + Runner 校验失败后生成 Failure Lemma、Checkpoint Rollback，并通过人工反馈 Resume。

## Quick Start

```powershell
cd C:\Users\cyh\projects\agenthub-backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
$env:MOCK_MODE = "true"
$env:LLM_DRIVER = "mock"
python -m uvicorn app.main:app --port 8000
```

打开：

```text
http://127.0.0.1:8000/frontend/code.html
```

也可以直接运行：

```powershell
.\run_agenthub.bat
```

## 技术结构

```text
app/
  main.py              FastAPI / REST / WebSocket / 静态挂载
  core/
    orchestrator.py    动态路由、自省、HITL、Checkpoint
    runner.py          子进程运行代码并捕获输出
    workspace.py       会话隔离工作区
    llm_client.py      Mock / OpenAI 兼容模型客户端
  db/                  SQLAlchemy 2.0 + SQLite
frontend/code.html     单页 Demo 工作台
agenthub.db            初始化 SQLite 数据库
workspaces/            会话工作区根目录
```

## 提交说明

仓库不包含 `.env`、真实 API Key、云服务器密码、日志、缓存或本地虚拟环境。评审可使用 Mock Mode 直接复现 Demo 主流程，真实模型通道通过环境变量切换。
