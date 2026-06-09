# AgentHub 3 分钟 Demo 视频脚本

## 0:00 - 0:20 开场定位

画面：打开 AgentHub 前端页面。

讲解：

AgentHub 是一个 IM 聊天式多 Agent 协作平台。每个 Agent 都像一个聊天对象，用户通过会话发送需求，系统自动调度 Codex、Claude Code、OpenCode 和自建 Agent，生成代码、网页等产物，并在聊天流中实时预览和运行。

## 0:20 - 0:50 会话历史恢复

操作：

1. 点击左侧不同 Session。
2. 展示中间聊天历史立即恢复。
3. 展示右侧工作区文件树同步刷新。

讲解：

这里不是普通前端状态缓存。每一条消息、Agent thought、review、code_diff 和运行日志都已经落到 SQLite。切换 Session 时，前端通过 `/api/messages/{session_id}` 重放历史，通过 `/api/workspace/{session_id}/files` 恢复物理工作区。

## 0:50 - 1:25 多 Agent 动态调度

操作：

输入：

```text
帮我写一个快速排序算法
```

观察聊天流出现：

- thought
- flow
- code_diff
- review

讲解：

用户只输入自然语言，Orchestrator 会读取数据库中的 Agent 注册表，动态构建 Function Calling 工具矩阵。模型选择 `代码专家` 后，子 Agent 返回 Pydantic 结构化 `CoderOutput`。系统不接受自由文本产物，必须通过结构化契约。

## 1:25 - 1:50 运行沙箱

操作：

点击右侧 Run。

观察：

聊天流出现 Runner 的 `stdout` 卡片，输出排序结果。

讲解：

代码生成后会落盘到当前会话工作区 `workspaces/session_{id}/src/main.py`。点击 Run 时后端不会跑假逻辑，而是用独立子进程在该工作区执行 `python src/main.py`，捕获 stdout、stderr 和 exit code。

## 1:50 - 2:20 HTML Live Preview

操作：

输入：

```text
写一个 HTML 网页用于 AgentHub 演示
```

观察：

1. 右侧文件树出现 `src/index.html`。
2. 点击文件。
3. 右侧同时展示源码和 iframe 预览。

讲解：

HTML 产物会被写入当前 Session 工作区，FastAPI 将 `workspaces` 挂载为静态目录。前端收到 HTML `code_diff` 后自动刷新 iframe，实现聊天流驱动的实时网页预览。

## 2:20 - 2:45 HITL 人工接管

操作：

输入：

```text
hitl loop test fail repeatedly in python
```

观察：

1. 连续失败 review。
2. 出现 `run.requires_human`。
3. 输入框出现黄色呼吸边框。

继续输入：

```text
resume fix syntax failure with a runnable print statement
```

观察协程恢复并通过 review。

讲解：

这展示的是自省循环断路器。系统先做 AST 静态检查和子进程运行检查，失败后压缩成 Failure Lemma 并回滚到 Checkpoint。连续停滞后不再盲目消耗模型，而是触发人工接管。用户反馈会进入挂起协程，恢复执行。

## 2:45 - 3:00 交付资产收束

画面：

展示项目根目录：

- `app/`
- `workspaces/`
- `agenthub.db`
- `PRODUCT_DESIGN.md`
- `TECHNICAL_DOCUMENT.md`
- `AI_Collaboration.md`
- `DEMO_VIDEO_SCRIPT.md`

讲解：

最终交付包含可运行 Demo、产品设计文档、技术文档和 AI 协作开发记录。AI 协作记录沉淀了 Spec、Skill、Rules，包括结构化输出契约、Adapter 多平台接入、AST 与 Runner 双轨校验、Checkpoint Rollback、Failure Lemma 和 HITL 状态机。
