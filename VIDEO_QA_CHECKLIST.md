# AgentHub Demo 视频验收清单

## 基础要求

- [ ] 视频时长控制在 150-180 秒。
- [ ] 画面清晰，浏览器缩放建议为 100% 或 90%。
- [ ] 字幕使用简洁中文关键点字幕，避免整段堆叠。
- [ ] 声音自然、拟人，避免机械念稿。
- [ ] 开头 10 秒讲明产品定位：AgentHub 是 IM 聊天式多 Agent 协作平台。
- [ ] 视频链接上传后确认评委无需登录即可访问。

## 必须展示流程

- [ ] 左侧 Session 切换，并展示聊天历史恢复。
- [ ] 快排任务中展示 `thought`、`flow`、`code_diff`、`review`。
- [ ] 点击 Run，展示 `stdout` 运行输出。
- [ ] HTML 产物展示 iframe 实时预览。
- [ ] HITL 场景展示三轮失败或连续失败后的人工接管。
- [ ] 展示黄色联锁/黄色呼吸边框状态。
- [ ] 输入 resume 指令后恢复执行，并最终展示 Done 或通过状态。

## 录制前检查

- [ ] 使用本地 Mock 模式启动：`MOCK_MODE=true`、`LLM_DRIVER=mock`。
- [ ] 打开 `http://127.0.0.1:8000/frontend/code.html`。
- [ ] 不展示 `.env`、API Key、云服务器密码或任何真实凭据。
- [ ] 不展示浏览器历史、个人账号后台或无关隐私信息。
- [ ] 本地工作区 `workspaces/` 在正式演示前为空。

## 提交包排除项

- [ ] `.env`
- [ ] `.git`
- [ ] `__pycache__`
- [ ] `.pytest_cache`
- [ ] `.ruff_cache`
- [ ] `.venv`
- [ ] `*.pyc`
- [ ] `*.log`
- [ ] `.uvicorn.pid`
- [ ] `agenthub.db-shm`
- [ ] `agenthub.db-wal`

