# AgentHub 产品设计文档

## 1. 产品定位

AgentHub 是一个以 IM 聊天为核心交互范式的多 Agent 协作平台。用户像使用飞书或微信一样创建对话、选择 Agent、发送任务，并在聊天流中获得代码、网页、搜索摘要、运行日志和人工接管控制帧。

平台不是单一聊天机器人，而是一个面向产物生成的协作工作台：每个 Agent 是一个聊天对象，每个会话是一个可持久化任务线程，每个产物都能在工作区中落盘并被预览、运行和二次修改。

## 2. 目标用户

### 2.1 参赛演示用户

评委需要在 3 分钟内理解系统如何从自然语言生成可运行产物，并看到多 Agent 调度、历史恢复、预览和 HITL 的端到端闭环。

### 2.2 真实业务用户

产品经理、开发者、运营同学可以通过聊天创建网页、脚本、Workflow、文档和自动化任务，并在同一会话中持续迭代。

## 3. 核心场景

### 3.1 新建对话

用户在左侧会话列表中进入新任务，输入需求后系统自动创建 Session。后端返回 `session_id`，前端将后续消息、运行请求和人工反馈都绑定到该 Session。

### 3.2 多会话并行

左侧会话列表通过 `/api/sessions` 加载，按最近活跃排序。切换会话时，前端调用 `/api/messages/{session_id}` 重放历史消息，并调用 `/api/workspace/{session_id}/files` 恢复对应工作区文件树。

### 3.3 群聊协作

在一个会话中，用户可以输入复杂需求。Orchestrator 会根据 Agent 注册表动态选择 `代码专家`、`搜索者` 或自建 Agent，并以 `thought`、`flow`、`code_diff`、`review` 等消息帧模拟群聊成员依次回复的体验。

### 3.4 上下文连续

每次进入 Orchestrator 前，系统从 MessageRepository 加载最近消息作为上下文。失败记录、审查结果和用户反馈都会进入持久化链路，后续 Agent 能基于历史状态继续修复。

### 3.5 产物内联

Agent 回复不仅是文本，还包括：

- `code_diff`：代码产物卡片。
- `review`：沙箱审查卡片。
- `stdout` / `stderr`：运行日志卡片。
- HTML iframe：网页实时预览卡片。
- `run.requires_human`：人工接管控制卡片。

## 4. 信息架构

### 4.1 左侧：会话与联系人

左侧区域承担 IM 会话列表职责，展示会话标题、活跃状态和会话 ID。后续可扩展置顶、归档、搜索和 Agent 联系人列表。

### 4.2 中间：聊天流

中间区域是主交互面。所有系统事件按时间顺序追加，用户可以看到 Agent 的计划、执行、审查和产物。

### 4.3 右侧：工作区

右侧区域是产物操作面，包含：

- 文件树 Explorer。
- 源码查看器。
- HTML Iframe Live Preview。
- Run 按钮。

当用户切换 Session 时，右侧工作区同步切换到对应的 `workspaces/session_{id}`。

## 5. 关键交互

### 5.1 发送任务

用户输入需求并回车，前端通过全局 WebSocket 发送：

```json
{
  "type": "message",
  "content": "帮我写一个快速排序算法",
  "session_id": 20
}
```

后端创建或复用 Session，随后流式返回 Agent 步骤。

### 5.2 运行代码

用户点击右侧 Run 按钮，前端发送：

```json
{
  "action": "run",
  "session_id": 20
}
```

后端在当前会话工作区执行 `python src/main.py`，并推送 `stdout` 或 `stderr`。

### 5.3 HTML 实时预览

当 Agent 生成 HTML 代码时，系统写入 `src/index.html` 并推送：

```json
{
  "type": "code_diff",
  "filename": "src/index.html"
}
```

前端收到后刷新 iframe，地址为：

`/workspaces/session_{id}/src/index.html`

### 5.4 HITL 人工接管

当 Orchestrator 检测到语义循环或重试超限时，推送：

```json
{
  "type": "run.requires_human",
  "checkpoint_id": "ckpt_xxx"
}
```

前端将状态胶囊变为 amber，并给输入框添加黄色呼吸边框。用户下一条输入会作为 `human_feedback` 发送，恢复挂起协程。

## 6. Agent 体系

### 6.1 内置 Agent

- 编排器：负责路由、计划、自省、回滚和 HITL。
- 代码专家：生成结构化代码产物。
- 搜索者：生成结构化搜索摘要。

### 6.2 外部平台 Agent

平台通过统一 Adapter 对接 Codex、Claude Code、OpenCode。当前版本提供 Codex 真实通道与 Claude Code/OpenCode 高保真 Mock 通道，满足多平台架构演示要求。

### 6.3 自建 Agent

前端可通过 `/api/agents` 创建自定义 Agent，配置名称、头像、System Prompt 和 tags。Orchestrator 会在下一轮路由时自动读取新 Agent。

## 7. 功能覆盖矩阵

| 官方要求 | 当前实现 |
| --- | --- |
| 对话列表 | `/api/sessions` + 前端 Session 切换 |
| 单聊模式 | 单会话绑定单任务与目标 Agent |
| 群聊模式 | Orchestrator 动态分派多个 Agent 帧 |
| 消息类型 | text、thought、flow、code_diff、review、stdout、stderr、HITL |
| 上下文管理 | SQLite MessageRepository 加载最近消息 |
| 多 Agent 接入 | Codex、Claude Code Mock、OpenCode Mock |
| 自建 Agent | `/api/agents` GET/POST |
| 产物预览 | 工作区文件树 + HTML iframe |
| 代码运行 | AsyncCodeRunner 子进程沙箱 |
| 失败自省 | AST + Runner + Failure Lemma + Checkpoint |
| HITL | WebSocket 状态机 + 人工反馈恢复 |

## 8. P2 路线

### 8.1 Diff 视图与版本历史

Artifact 表已保存 version、code_content 和 diff_info。后续可在前端加入 Monaco Diff Editor，按 Artifact 版本进行对比和回滚。

### 8.2 选区局部修改

前端代码查看器可扩展选中区域，将 selection range 与用户指令一起发送给 Orchestrator，由 Coder Agent 只修改局部片段。

### 8.3 部署发布

当前工作区已具备静态托管能力。下一步可增加 `deploy` action，将 `src/index.html` 或构建产物同步到云服务器 Nginx 子目录，并返回部署状态卡片与公网 URL。

### 8.4 多端支持

Web 端是主力端。桌面端可复用后端 API 管理本地文件和 Agent 进程；移动端可复用会话列表、消息历史和产物预览接口做轻量审批体验。
