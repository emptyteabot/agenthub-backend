# AgentHub 飞书交付文档模板

## 1. 项目信息

项目名称：

AgentHub - 多 Agent 协作平台

参赛形式：

个人

提交人：

请填写你的个人姓名

GitHub 主页：

https://github.com/emptyteabot

代码仓库地址：

https://github.com/emptyteabot/agenthub-backend

Demo 视频链接：

https://github.com/emptyteabot/agenthub-backend/releases/download/demo-final/AgentHub_Demo_Final.mp4

## 2. 一句话介绍

AgentHub 是一个以 IM 聊天为核心交互范式的多 Agent 协作平台。用户通过新建会话和发送消息与不同 AI Agent 协作，系统可自动调度 Orchestrator、代码专家、搜索者以及 Codex、Claude Code、OpenCode 等统一适配器节点，生成代码、网页等产物，并在聊天流中实时展示代码 Diff、运行日志、Iframe 预览和 HITL 人工接管流程。

## 3. 产品设计说明

### 3.1 核心体验

AgentHub 将多 Agent 协作设计为类飞书/微信的 IM 体验：

- 左侧是会话列表，支持多会话并行。
- 中间是聊天流，展示用户消息、Agent thought、flow、code_diff、review、stdout、stderr 和 HITL 控制帧。
- 右侧是工作区，展示文件树、源码查看器、Run 按钮和 HTML Iframe 实时预览。

### 3.2 关键场景

新建对话：

用户输入需求后，后端自动创建 Session，并返回 session_id。后续消息、运行请求和人工反馈都绑定到该会话。

多会话恢复：

前端通过 `/api/sessions` 获取会话列表，通过 `/api/messages/{session_id}` 重放历史聊天流，通过 `/api/workspace/{session_id}/files` 恢复对应工作区文件树。

群聊协作：

Orchestrator 读取数据库中的 Agent 注册表，动态构造 Function Calling 工具矩阵，根据用户意图选择代码专家、搜索者或自建 Agent。

产物内联：

Agent 回复不仅是文本，还包括代码产物、审查卡片、运行日志、HTML iframe 预览和人工接管控制帧。

## 4. 技术架构说明

### 4.1 后端架构

后端采用 FastAPI + WebSocket + SQLAlchemy 2.0 + SQLite + Pydantic v2：

- FastAPI 提供 REST API、WebSocket 和静态文件托管。
- WebSocket `/api/ws/chat` 实现实时流式推送。
- SQLAlchemy 异步连接维护 Session、Message、Artifact、Agent。
- Pydantic v2 强制结构化输出，防止自由文本污染执行链路。
- WorkspaceManager 为每个会话创建隔离工作区。

### 4.2 多 Agent 适配层

系统定义统一 `BaseAgentAdapter`：

- `CodexAdapter`：接入当前 OpenAI 兼容通道。
- `ClaudeCodeAdapter`：模拟 Claude Code 平台响应。
- `OpenCodeAdapter`：模拟 OpenCode 平台响应。

Agent 的 tags 可携带 `driver:codex`、`driver:claude`、`driver:opencode`。Orchestrator 根据 driver 动态选择适配器，屏蔽外部平台 API 差异。

### 4.3 自省与沙箱

代码产物通过双轨校验：

- AST 静态语法沙箱：使用 Python 内置 `ast.parse` 检查语法。
- 子进程运行沙箱：在 `workspaces/session_{id}` 中执行 `python src/main.py`，捕获 stdout、stderr 和 exit code。

失败后，系统将错误压缩为 Failure Lemma，回滚到 Checkpoint，并进入下一轮修复。连续停滞或达到上限时触发 `run.requires_human`，等待人工反馈恢复协程。

## 5. AI 协作开发记录

本项目沉淀了 Spec、Skill、Rules 三层 AI 协作规范。

### 5.1 Specification

系统禁止多 Agent 之间以自由文本传递关键状态。所有关键边界必须通过：

- OpenAI Function Calling 路由契约。
- Pydantic Structured Outputs 产物契约。
- WebSocket MessageStep 事件帧契约。
- SQLite Message 与 Artifact 持久化契约。
- Workspace 文件系统产物契约。

### 5.2 Skill Sets

Orchestrator：

负责意图理解、任务拆解、Agent 路由、检查点、自省、HITL 和恢复。

代码专家：

负责生成结构化代码产物 `CoderOutput`，并由工作区落盘和沙箱验证。

搜索者：

负责生成结构化搜索摘要 `SearchOutput`。

Codex / Claude Code / OpenCode：

通过统一 Adapter 接入，作为可替换的外部 Agent 平台节点。

### 5.3 Rules

系统通过以下规则降低幻觉和循环风险：

- Pydantic 结构化输出阻断自由文本污染。
- AST + Runner 双轨校验拒绝纯模型自评。
- Failure Lemma 压缩错误，避免 Traceback 污染上下文。
- Checkpoint Rollback 在失败后恢复安全状态。
- 工具参数、AST Hash、语义历史共同构成循环断路器。
- HITL 状态机在语义死循环时交给人类接管。

## 6. Demo 录制说明

建议视频控制在 150 秒到 180 秒：

1. 打开 `http://127.0.0.1:8000/frontend/code.html`。
2. 展示左侧 Session 切换和历史恢复。
3. 输入“帮我写一个快速排序算法”，展示 thought、flow、code_diff、review。
4. 点击 Run，展示 stdout 真实运行结果。
5. 输入“写一个 HTML 网页用于 AgentHub 演示”，展示右侧 `src/index.html` 和 Iframe 预览。
6. 输入 `hitl loop test fail repeatedly in python`，展示三轮失败、`run.requires_human` 和黄色输入框联锁。
7. 输入 `resume fix syntax failure with a runnable print statement`，展示协程恢复并 Done。

## 7. 本地运行方式

Windows 本地运行：

```powershell
cd agenthub-backend
run_agenthub.bat
```

启动后访问：

```text
http://127.0.0.1:8000/frontend/code.html
```

## 8. 交付物清单

仓库内包含：

- `app/`：后端核心代码。
- `frontend/code.html`：前端单页 Demo。
- `agenthub.db`：初始化数据库，保留默认 Agent。
- `workspaces/`：会话工作区根目录。
- `PRODUCT_DESIGN.md`：产品设计文档。
- `TECHNICAL_DOCUMENT.md`：技术文档。
- `AI_Collaboration.md`：AI 协作开发记录。
- `DEMO_VIDEO_SCRIPT.md`：Demo 视频脚本。
- `run_agenthub.bat`：本地一键启动脚本。

## 9. 合规说明

项目不在代码仓库中保存真实 API Key、云服务器密码或其他密钥。Mock Mode 用于本地演示，真实模型通道通过环境变量切换。
