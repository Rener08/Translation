# Translation Workbench — 项目规范

> 与全局 `~/.claude/CLAUDE.md` 配合阅读。本文件只描述项目特有的事实、约定和约束。

## 1. 项目本质

本地优先（macOS-first）的中文写作工作台，把 YouTube 视频或上传音频转成中文改写文章。
单租户、单进程部署。Web UI 是唯一活跃前端（PyQt 桌面版已废弃）。

完整产品契约见 `docs/PRODUCT_CONTRACT.md`，架构见 `docs/ARCHITECTURE.md`。

## 2. 技术栈

- **后端**：Python 3.11 / FastAPI 0.116 / uvicorn 0.35 / pytest 8.4
- **前端**：Next.js 16 / React 19 / TypeScript 5.8 / Turbopack
- **外部依赖**：yt-dlp、faster-whisper、pyannote、ffmpeg
- **LLM provider**：OpenAI、DeepSeek、LM Studio、Ollama（在 `.env` 切换）

## 3. 目录约定

```
backend/app/         核心业务（services / api / repositories / config / main）
backend/tests/       pytest 测试，conftest.py 隔离 17 个 ENV
frontend/app/        Next.js App Router（components / hooks / lib）
docs/                产品文档（ARCHITECTURE / PRODUCT_CONTRACT 等）
scripts/             一次性脚本
skills/              写作风格 markdown（运行时读取）
writer-skill/        Writer skill 配置（kazix / latepost）
tmp/                 运行时产物：日志、缓存、SQLite，不 commit
```

**不要往这里放**：
- 仓库根目录新增 `*.md`（除非是产品级文档，AGENTS.md 是工具产物已 .gitignore）
- `tmp/` 之外存放生成内容
- `backend/app/services/` 继续追加逻辑到已超 1000 行的文件（translation_service 待拆）

## 4. 开发命令

```bash
# 启动
./start-dev.sh                   # 同时启动后端 + 前端
./status-dev.sh                  # 查看运行状态
./stop-dev.sh                    # 停止

# 后端测试（conftest.py 自动隔离 ENV，不需要 source .env）
cd backend && pytest -q
cd backend && pytest tests/test_translate.py -q   # 单文件

# 前端
cd frontend && npm run lint      # --max-warnings=0，不容忍 warning
cd frontend && npm run build
```

**改完必跑（验证基线）**：

| 改动范围 | 验证命令 |
|----------|----------|
| 后端 | `cd backend && pytest -q` |
| 前端 | `npm --prefix frontend run lint && npm --prefix frontend run build` |
| 两者都改 | 上面两条都跑 |

## 5. 环境配置

- `.env` **绝对不 commit**（含真实密钥）。`.env.example` 同步变量名，不带值
- `DEPLOYMENT_PROFILE` 三档：`development`（默认）/ `test` / `production`
- `production` 必须显式设 `API_AUTH_TOKEN` 和 `TRUST_ACCOUNT_HEADERS=false`
- 切 LLM provider：改 `TRANSLATION_PROVIDER` + 对应 `*_API_KEY`、`*_BASE_URL`、`*_TRANSLATION_MODEL`
- yt-dlp cookie 优先级：`YTDLP_COOKIES_FILE` > `YTDLP_COOKIES_FROM_BROWSER` > `YTDLP_COOKIE_HEADER` > 默认文件

## 6. 工程约定（硬性）

- **错误处理**：service 异常必须经 `app/api/error_mapping.py:classify_service_error` 转 HTTPException。新增异常类型时同步更新该文件
- **subprocess 调用**：`subprocess.run` 必须在 `run_in_threadpool` 或 `asyncio.to_thread` 内执行。当前已有 27 处 `run_in_threadpool`，P3.8 待验证是否全覆盖
- **配置访问**：通过 `app.config.get_settings()`，不要直接 `os.getenv`
- **服务依赖注入**：需要 monkeypatch 的服务函数从 `app.service_bindings` 走（main.py 用 metaclass 同步，见 service_bindings.py）
- **请求 ID**：错误响应必须带 `request_id`，使用 `_standard_error_response`，不要自己拼 JSONResponse

## 7. 已知约束（不要试图绕过）

- **单进程部署**：限流是 module-level dict + threading.Lock，多 worker 不准。production 必须 `uvicorn -w 1` 或单容器
- **yt-dlp 错误分类靠字符串匹配**：`error_mapping.py` 用 "video unavailable" 等小写匹配。升级 yt-dlp 后必须跑 `pytest backend/tests/test_youtube_access_service.py`
- **translation_service.py 1747 行待拆**：拆分计划落地前，不要继续往里加新模块逻辑，新功能放独立文件

## 8. 文件信任度

| 文件 | 状态 |
|------|------|
| `docs/PRODUCT_CONTRACT.md`、`docs/ARCHITECTURE.md` | 真相源 |
| `README.md` | 项目结构段过时（实际 35+ services，README 只列 7 个） |
| `AGENTS.md` | claude-mem 工具产物，忽略 |
| `TODO.md` | Jack 个人备忘，AI 不要主动改 |

## 9. AI 协作约束

- 大改动前先看 `docs/CODE_REVIEW_FIXES_2026-05-15.md` 的待办，避免与重构计划冲突
- 不在已知 plan 内的改动，先和 Jack 对齐再动手
- 红线遵守全局 `~/.claude/CLAUDE.md`（删文件、改 .env、git push 等需先确认）
