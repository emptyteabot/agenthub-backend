# AgentHub 最终提交核对清单

## 1. 官方交付物映射

| 官方交付物 | 项目文件 |
| --- | --- |
| 产品设计文档 | `PRODUCT_DESIGN.md` |
| 技术文档 | `TECHNICAL_DOCUMENT.md` |
| 可运行 Demo | `app/`、`frontend/`、`pyproject.toml`、`agenthub.db`、`workspaces/`、`run_agenthub.bat` |
| AI 协作开发记录 | `AI_Collaboration.md` |
| 3 分钟 Demo 视频 | 按 `DEMO_VIDEO_SCRIPT.md` 录制 |
| 飞书交付文档正文 | `FEISHU_DELIVERY_DOC.md` |
| 飞书多维表格填写模板 | `FEISHU_SUBMISSION_TEMPLATE.md` |

## 2. 必须包含

- `app/`
- `pyproject.toml`
- `agenthub.db`
- `workspaces/`
- `AI_Collaboration.md`
- `PRODUCT_DESIGN.md`
- `TECHNICAL_DOCUMENT.md`
- `DEMO_VIDEO_SCRIPT.md`
- `FEISHU_DELIVERY_DOC.md`
- `FEISHU_SUBMISSION_TEMPLATE.md`
- `SUBMISSION_CHECKLIST.md`
- `frontend/code.html`
- `run_agenthub.bat`

## 3. 严禁包含

- `.env`
- API Key
- 云服务器密码
- `uvicorn*.log`
- `.uvicorn.pid`
- `__pycache__/`
- `.pytest_cache/`
- `.ruff_cache/`
- `.venv/`
- `*.pyc`

## 4. 本地启动

```powershell
cd C:\Users\cyh\projects\agenthub-backend
$env:MOCK_MODE='true'
run_agenthub.bat
```

打开：

```text
http://127.0.0.1:8000/frontend/code.html
```

## 5. 最终验证命令

```powershell
python -m compileall app
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/api/sessions
Invoke-RestMethod http://127.0.0.1:8000/api/agents
```

密钥扫描：

```powershell
rg -n "sk-[A-Za-z0-9_-]+|API_KEY\s*=|ARK_API_KEY\s*=|ENDPOINT_ID\s*=|newapi_channel_conn|Bearer\s+[A-Za-z0-9]" . -g "!agenthub.db" -g "!*.pyc" -g "!SUBMISSION_CHECKLIST.md"
```

预期：无输出。

## 6. Demo 验证路径

### 6.1 快排

输入：

```text
帮我写一个快速排序算法
```

预期：

- 出现 thought、flow、code_diff、review。
- 文件树出现 `src/main.py`。
- 点击 Run，出现 stdout。

### 6.2 HTML 预览

输入：

```text
写一个 HTML 网页用于 AgentHub 演示
```

预期：

- 文件树出现 `src/index.html`。
- 点击文件，源码和 iframe 同屏展示。

### 6.3 HITL

输入：

```text
hitl loop test fail repeatedly in python
```

预期：

- 触发 `run.requires_human`。
- 状态胶囊 amber。
- 输入框黄色呼吸边框。

继续输入：

```text
resume fix syntax failure with a runnable print statement
```

预期：协程恢复并通过 review。

## 7. 飞书多维表格提交

GitHub 主页：

```text
https://github.com/emptyteabot
```

提交前需要完成：

- 将本项目上传到 GitHub 仓库。
- 新建一个飞书交付文档，正文直接复制 `FEISHU_DELIVERY_DOC.md`。
- 在飞书交付文档中填入最终 GitHub 仓库地址。
- 在飞书交付文档中填入 Demo 视频链接。
- 按 `DEMO_VIDEO_SCRIPT.md` 录制 150-180 秒 Demo 视频并上传到可访问链接。
- 飞书多维表格的“交付文档/完成作品链接”栏只粘贴这个飞书交付文档链接。
- 参考 `FEISHU_SUBMISSION_TEMPLATE.md` 填写其他表单字段。

## 8. 云端部署说明

群内口径显示 Demo 可简单录屏讲清主流程，部署不是硬性前置条件。若后续选择部署到腾讯云，仍应使用环境变量或服务器 `.env`，不得把密钥写入代码仓库或文档。
