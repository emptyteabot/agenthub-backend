# AgentHub AI Native 协作开发记录与规范文档

## 0. 文档定位

AgentHub 是一个面向代码生产、搜索协作、运行校验与人工接管的多智能体工程系统。系统目标不是把大模型包装成单轮聊天机器人，而是把自然语言任务转化为可路由、可执行、可审计、可回滚、可恢复的事件流。

本文沉淀 AgentHub 的 Specification、Skill Sets 与 Rules，用于说明系统如何遵循 Coze/Eino 式的图编排思想：Agent 是可注册的执行节点，节点之间通过结构化契约握手；运行过程以线程事件日志记录；失败不是自由文本重试，而是进入沙箱校验、失败引理压缩、检查点回滚与 HITL 恢复链路。

## 1. Specification

### 1.1 结构化协作契约

AgentHub 禁止多智能体之间以不受约束的自由文本互相传递任务状态。系统内部所有关键边界必须经过以下契约之一：

- OpenAI Function Calling 路由契约。
- Pydantic v2 Structured Outputs 产物契约。
- WebSocket MessageStep 实时事件帧契约。
- SQLite Message 与 Artifact 持久化契约。
- Workspace 文件系统产物契约。

代码节点必须返回 `CoderOutput`，字段为 `code`、`explanation`、`language`。搜索节点必须返回 `SearchOutput`，字段为 `summary`、`sources`。编排器工具参数必须返回 `DynamicAgentArgs`，字段为 `thought` 与 `task_description`。这些模型共同切断幻觉传播链：模型可以产生建议，但系统只接受可验证的结构化对象。

### 1.2 线程事件日志

系统使用 SQLite + SQLAlchemy 2.0 异步连接维护三类核心实体：

- `Session`：会话元数据、标题、创建时间、最后活跃时间。
- `Message`：用户输入、Agent thought、flow、review、stdout、stderr、code_diff、HITL 控制帧。
- `Artifact`：代码版本、真实代码内容、文件路径与关联消息。

每个 WebSocket 推送帧在发送给前端的同时写入数据库。前端通过 `GET /api/sessions` 获取会话列表，通过 `GET /api/messages/{session_id}` 重放历史事件，并通过 `GET /api/workspace/{session_id}/files` 恢复工作区文件树。刷新页面不会丢失推理图、审查结果和代码产物。

### 1.3 动态 Agent 注册表

AgentHub 将智能体定义为数据库实体：

- `name`：展示名称。
- `avatar`：前端图标或头像。
- `system_prompt`：能力边界。
- `tags`：能力索引与 driver 标识。
- `is_custom`：区分内置节点与用户节点。

编排器每次路由前读取 AgentRepository，并动态构造 `agent_{id}` 形式的 Tool Calling 矩阵。模型命中某个工具后，编排器从数据库回表读取目标 Agent 的 system prompt 与 tags，再执行对应节点。这使业务角色与底层代码解耦，新增智能体不需要改写路由器。

### 1.4 多平台适配器层

系统新增统一 Platform Adapter：

- `BaseAgentAdapter`：定义 `execute_task(prompt, system_prompt)` 抽象接口。
- `CodexAdapter`：接入当前本地 OpenAI 兼容模型通道。
- `ClaudeCodeAdapter`：模拟 Claude Code 外部平台响应。
- `OpenCodeAdapter`：模拟 OpenCode 外部平台响应。

Agent 的 `tags` 可携带 `driver:codex`、`driver:claude`、`driver:opencode`。编排器不直接绑定供应商 SDK，而是先解析 driver，再实例化对应 Adapter。该设计满足比赛对多平台协作能力的要求，也降低单一供应商异常导致系统整体不可演示的风险。

### 1.5 WebSocket 实时协议

系统废弃单轮 HTTP POST 聊天，使用 `/api/ws/chat` 长连接协议。核心事件帧包括：

- `session`：声明当前会话 ID。
- `thought`：编排器计划摘要。
- `flow`：Plan、Action、Review 三阶段进度。
- `code_diff`：代码产物帧。
- `text`：普通说明或搜索摘要。
- `review`：沙箱校验与自省结果。
- `run`：启动工作区执行。
- `stdout` 与 `stderr`：真实子进程输出。
- `run.requires_human`：人工接管控制帧。
- `done`：当前任务流完成。

前端复用同一个全局 WebSocket，并在每个数据帧携带最新 `session_id`。切换会话时只更新客户端状态、拉取历史与刷新工作区，不重新创建连接，从而避免连接级死锁与双写。

### 1.6 工作区与 Iframe 预览契约

每个会话拥有独立目录 `workspaces/session_{id}`，内部包含 `src/` 与 `tests/`。Coder 产物会写入对应工作区：Python 默认落盘为 `src/main.py`，HTML 默认落盘为 `src/index.html`。

FastAPI 将工作区挂载为 `/workspaces` 静态目录。前端文件树点击 `.html` 文件时同时展示源码与 Iframe，地址为 `/workspaces/session_{id}/{path}`。当 WebSocket 收到 HTML 的 `code_diff` 帧时，前端延迟 200ms 重新加载 Iframe，实现聊天流驱动的实时页面预览。

## 2. Skill Sets

### 2.1 @编排器

@编排器是中心调度节点，但不直接替代子 Agent 产生产物。其能力边界为：

- 加载会话历史上下文。
- 读取 Agent 注册表。
- 动态构建 Tool Calling 矩阵。
- 输出 `thought` 计划事件。
- 选择目标 Agent 与 Adapter。
- 创建 Checkpoint。
- 管理 AST、Runner、Review 与 Failure Lemma。
- 触发 Rollback 与 HITL Resume。

@编排器不直接生成代码、不直接伪造搜索事实、不绕过子节点结构化输出契约。

### 2.2 @代码专家

@代码专家只接收编排器委派的 `task_description`，输出 `CoderOutput`。其原子能力为：

- 生成 Python、HTML、前端或后端代码。
- 根据 Failure Lemma 修复上一轮失败。
- 返回完整代码、简短解释、语言类型。
- 将产物交由 WorkspaceManager 落盘。

@代码专家无权修改其他 Agent 的 Prompt、会话状态机或数据库结构。

### 2.3 @搜索者

@搜索者只负责外部资料检索和摘要，输出 `SearchOutput`。其原子能力为：

- 处理文档、资料、事实、新闻、价格等时效性查询。
- 返回 summary 与 sources。
- 保持结果可追踪。

@搜索者不生成可执行代码，不参与沙箱运行，不把无来源文本升级为系统事实。

### 2.4 外部平台节点

Claude Code 与 OpenCode 在当前阶段作为高保真 Mock Adapter 接入统一接口。它们用于证明系统具备多平台编排拓扑，而不是把所有能力硬编码到一个模型调用里。未来将 Mock Adapter 替换为真实 CLI、MCP 或远程 API 时，Orchestrator 的路由逻辑无需改变。

## 3. Rules

### 3.1 双轨代码校验

代码产物通过两层确定性校验：

第一层是 AST 静态语法沙箱。`PythonSandbox` 使用 Python 内置 `ast.parse` 编译传入代码。若出现 `SyntaxError`，系统提取错误类型、行号与原因，判定失败。

第二层是隔离子进程运行沙箱。`AsyncCodeRunner` 在 `workspaces/session_{id}` 作为 cwd 执行 `python src/main.py`，捕获 stdout、stderr 与 exit code，并设置 timeout 防止死循环。只有 AST 通过且子进程退出码为 0，代码才被判定为成功。

### 3.2 Failure Lemma 压缩

系统不把原始 Traceback 直接整段喂回模型，而是压缩为 Failure Lemma：

`[Failure Lemma] 语法/执行由于 {err_type} 在 {line_no} 行失败。不可重复此错误模式。`

该格式保留最小必要失败模式，避免上下文污染、Token 膨胀和模型复述堆栈。Failure Lemma 进入 durable notes，作为下一轮修复的硬约束。

### 3.3 Checkpoint 与 T-minus Rollback

每次调用子 Agent 前，编排器创建检查点，保存最近上下文与当前工作区主产物。若 AST 或 Runner 失败，系统执行 Rollback：丢弃失败分支，将内存上下文与工作区代码恢复到上一个安全检查点，再注入 Failure Lemma 进行下一轮修复。

该机制让 AgentHub 的自省不是线性“错了再问一次”，而是图式执行流中的分支回滚与状态恢复。

### 3.4 三维语义循环断路器

系统维护最近三轮执行快照，包含：

- `tool_args_json`：工具参数序列化结果。
- `ast_hash`：代码 AST 结构哈希。
- `raw_text`：原始产物文本。

相邻轮次比较时，工具参数哈希相同计 1 分，AST 结构哈希相同计 1 分。当累计得分达到阈值且连续停滞，系统判定进入语义循环。达到最大重试次数或语义停滞后，系统不抛异常、不继续盲目消耗模型，而是发送 `run.requires_human` 控制帧。

### 3.5 HITL 状态联锁

后端维护会话级状态机：

- `IDLE`：可接收新任务。
- `PROCESSING`：当前任务流运行中。
- `WAITING_HUMAN`：等待人工反馈恢复。

当编排器推送 `run.requires_human` 后，后端将会话状态置为 `WAITING_HUMAN`，前端将状态胶囊变为 amber，并给输入框添加呼吸边框。用户下一次输入不再作为普通消息，而是作为 `human_feedback` 帧塞入对应会话的异步反馈队列，恢复挂起的自省协程。

### 3.6 安全与合规

项目 `.gitignore` 屏蔽 `.env`、SQLite 数据库、工作区目录、缓存与日志文件。API Key、云服务器密码、ENDPOINT_ID 等敏感信息不得写入代码、文档、前端文件或提交包。Mock Mode 用于前端与演示联调，真实模型只在受控环境变量中启用。

## 4. 交付闭环

AgentHub 当前形成以下端到端闭环：

1. 用户通过前端发送任务。
2. WebSocket 绑定 session_id 并推送用户事件。
3. 后端加载会话历史与 Agent 注册表。
4. 编排器输出 thought 并通过 Function Calling 选择 Agent。
5. Adapter 执行目标节点并返回结构化产物。
6. WorkspaceManager 将产物落盘。
7. AST 与 Runner 对代码做确定性校验。
8. 成功则推送 `done`，失败则进入 Failure Lemma、Rollback、Retry。
9. 语义循环或超限时触发 HITL。
10. 前端恢复历史、文件树、终端输出和 Iframe 实时预览。

该架构把 AI 协作从“聊天式回答”升级为“事件驱动的可审计生产链路”，满足比赛对 Specs、Skill、Rules、可恢复性、多平台协作与实时演示能力的高权重要求。
