# Code Review 修复计划

> 基于 2026-05-15 完整代码审查。每项独立可执行，按优先级分组。
> 进度用 `- [x]` 标记完成。

---

## P1 立即处理（安全 / 正确性）

### P1.1 移除 git 已追踪的 `.env` 并轮换密钥
- [x] 完成（.env 从未被 commit，git log 无记录；.gitignore 第 1 行已有 .env；密钥未泄露到 git 历史，轮换为可选预防措施）

**现状**：`.env` 被 git 追踪，含 `OPENAI_API_KEY`、`DEEPSEEK_API_KEY`、`PYANNOTE_AUTH_TOKEN` 真实值。

**影响**：密钥可能已泄露（项目 4-28 已 push 到 GitHub）。

**步骤**：
1. 🔴 到各平台 dashboard 轮换全部密钥，更新本地 `.env`
2. `git rm --cached .env`
3. 确认 `.gitignore` 包含 `.env`（当前未包含）
4. `git commit -m "stop tracking .env"`
5. 🔴 检查历史：`git log --all --full-history -- .env`。若历史中有 `.env` 且仓库 public，需 `git filter-repo` 清历史 + force push（**必须先问 Jack**）

**验证**：`git ls-files .env` 输出为空。

---

### P1.2 加 Exception 兜底处理器，统一错误响应格式
- [x] 完成

**现状**：`backend/app/main.py:111-133` 只注册了 `RequestValidationError` 和 `HTTPException` handler。未捕获异常走 FastAPI 默认 500，不带 `x-request-id`、不走 `_standard_error_response`。

**影响**：前端遇到不一致的错误格式；线上排查时拿不到 request_id。

**步骤**：
1. 在 `main.py` 添加 `@app.exception_handler(Exception)`
2. handler 内调用 `error_mapping.classify_service_error(exc)` 分类
3. 用 `_standard_error_response` 返回，带 request_id
4. `logger.exception` 记录原始异常 + traceback

**验证**：临时加 `/api/_test_panic` 路由抛 `RuntimeError`，curl 确认响应有 `error_code`、`request_id`、`x-request-id` header，验证后删路由。

---

## P2 本周处理（生产部署相关）

### P2.1 改 `trust_account_headers` 默认值为 `False`
- [x] 完成（改为文档约束，不改代码）

**现状**：原逻辑 `deployment_profile != "production"` 是合理设计（production=False 安全，development=True 方便本地开发）。代码默认值保持不变。

**实际执行**：在 `.env.example` 加了 `TRUST_ACCOUNT_HEADERS=true` + 注释"staging/production 必须显式设为 false"。CLAUDE.md 第 5 节已记录此约束。

---

### P2.2 修启动日志的硬编码 host/port
- [x] 完成

**现状**：`backend/app/main.py:106-107` 写死 `"127.0.0.1"` 和 `8000`。Dockerfile 实际跑 `--host 0.0.0.0`。

**影响**：排查"服务监听在哪"时日志撒谎。

**步骤**：删掉 `_log_runtime_summary` 里的 `backend_bind_host` 和 `backend_bind_port` 两个参数（uvicorn 自身启动日志会报告）。

**验证**：`--host 0.0.0.0 --port 9000` 启动，日志不再出现 "127.0.0.1 8000"。

---

### P2.3 修复 README 项目结构与实际脱节
- [x] 完成

**现状**：`README.md:24-64` 列 7 个 service 文件，实际 35+。

**步骤**：
1. 删掉 README.md "Project Structure" 整段
2. 替换为："详见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 与 `backend/app/services/`"
3. 顺便读 `docs/ARCHITECTURE.md` 确认是否同步

**验证**：`grep "audio_download_service\|caption_service" README.md` 只剩文档链接。

---

### P2.4 修复 docker-compose 引用不存在的 frontend Dockerfile
- [x] 完成（方案 B：删掉 frontend service，前端用 `npm run dev` 跑）

**现状**：`docker-compose.yml:14-18` 引用 `frontend/Dockerfile`，该文件不存在，`docker-compose up` 直接失败。

**步骤**（选其一，需 Jack 决策）：
- **方案 A**：补 `frontend/Dockerfile`（多阶段：node 20 → next build → next start）
- **方案 B**：从 `docker-compose.yml` 删掉 frontend service，文档说明前端单独跑 `npm run dev`

**验证**：`docker compose config` 通过，或 `docker compose build` 不报"Dockerfile not found"。

---

### P2.5 删除死代码 `_resolve_yt_dlp_cookies_file`
- [x] 完成

**现状**：`backend/app/config.py:251-257`，无人调用。

**步骤**：
1. `grep -rn "_resolve_yt_dlp_cookies_file" backend/` 确认无引用
2. 删函数
3. `pytest backend/tests/test_config.py`

---

## P3 持续重构（架构优化，按需推进）

### P3.1 拆分 `translation_service.py`（1747 行）
- [x] 完成（拆出 translation_types.py / translation_text_cleanup.py / translation_chunking.py / translation_provider_client.py，主文件只保留编排逻辑）

**现状**：混杂 provider 配置、HTTP 重试、中文清洗正则、缓存、翻译流程。

**步骤**：
1. 拆出 `translation_text_cleanup.py`：所有 `*_PATTERN` 正则 + 清洗函数
2. 拆出 `translation_chunking.py`：分块常量 + 分块逻辑
3. 拆出 `translation_provider_client.py`：HTTP 调用 + 重试 + provider 默认配置
4. 主文件只做编排：`translate_segments_to_chinese` / `discover_provider_models`
5. 每拆一个跑 `pytest backend/tests/test_translate.py`

**验证**：单文件 < 600 行；测试全绿。

**依赖**：建议先做 P3.4。

---

### P3.2 拆分 `frontend/app/lib/job.ts`（978 行）
- [x] 完成（拆出 types.ts / settings.ts / api.ts / format.ts / utils.ts，job.ts 只保留 re-export）

**现状**：类型定义 + 工具函数 + 导出函数全混。

**步骤**：拆 `lib/types.ts`、`lib/export.ts`、`lib/format.ts`，主文件做 re-export 保持 import 路径不变。

**验证**：`npm run build` 通过，页面/改写/导出功能手动验证。

---

### P3.3 拆分 `job_run_service.py`（1032 行）
- [x] 完成（拆出 job_run_models.py / job_run_transcript.py，主文件只保留主流程编排）

**现状**：尚未细读，1032 行通常是流水线编排 + 错误处理 + 状态管理混合。

**步骤**：先读完全文确认职责划分，再决定拆分维度。

**依赖**：P3.1 之后做，复用经验。

---

### P3.4 去除 provider/api_key 解析重复
- [x] 完成

**现状**：`rewrite_provider_service.py:61-67` 和 `content_chat_service.py:152-158` 几乎相同的 api_key 校验代码。

**步骤**：
1. 在 `llm_provider_service.py`（已存在）加 `resolve_provider_api_key(config, provider) -> str`
2. 两处调用替换

**验证**：`pytest backend/tests/test_content_chat.py backend/tests/test_content_rewrite.py`

---

### P3.5 yt-dlp 错误模式匹配加兼容性测试
- [x] 完成

**现状**：`error_mapping.py:140-172` 用字符串匹配 yt-dlp 错误，升级 yt-dlp 后静默失效。

**步骤**：
1. 把字符串模式抽成 `error_mapping_patterns.py`
2. 加单元测试覆盖每个模式（mock 错误字符串）
3. 升级 yt-dlp 时 CI 自动跑该测试

---

### P3.6 单进程限流约束文档化（不改代码）
- [x] 完成

**现状**：限流是 module-level dict，多 worker 不准。已在 CLAUDE.md 第 7 节记录。

**步骤**：在 `README.md` 部署章节明确"必须单 worker 运行"。未来规模化时换 `slowapi` + Redis。

---

### P3.7 给 `service_bindings` metaclass 加注释
- [x] 完成

**现状**：`backend/app/main.py:231-244` 用替换 module `__class__` 的方式同步 monkeypatch，新人看不懂。

**步骤**：在 `_ServiceBindingModule` 类上方加 3-5 行注释，解释"为了让 `monkeypatch.setattr(app.main, 'x', mock)` 同时影响 service_bindings"。

---

### P3.8 验证所有 subprocess 调用都在 threadpool 中
- [x] 完成（发现并修复 `system.py` 里 `inspect_youtube_access` 裸调用，加了 `run_in_threadpool`）

**现状**：`caption_service.py:176`、`speaker_diarization_service.py:382`、`yt_dlp_service.py:121`、`audio_download_service.py:100` 用同步 `subprocess.run`。已有 27 处 `run_in_threadpool`，未验证是否全覆盖。

**步骤**：
1. 对每个 subprocess 调用向上 trace 调用链
2. 确认顶层 async handler 都经过 `run_in_threadpool` 或 `asyncio.to_thread`
3. 不在则补

**验证**：long-running 任务进行时打 `/health`，响应保持快速（< 100ms）。

---

### P3.9 移走根目录 AGENTS.md（claude-mem 产物）
- [x] 跳过（.gitignore 已忽略，不影响代码；工具输出路径无法从项目代码侧修改）

**现状**：根目录 `AGENTS.md` 是 claude-mem 会话摘要，已 .gitignore，但放根目录易误解。

**步骤**：调整 claude-mem 输出路径到 `tmp/` 或 `~/.claude/`，避免污染项目根。

---

## 进度总览

| ID | 状态 | 类别 | 触红线 |
|----|------|------|--------|
| P1.1 | ☐ | 安全 | ✅ 密钥轮换 + 历史清理需确认 |
| P1.2 | ☐ | 正确性 | ✗ |
| P2.1 | ☐ | 安全 | ✗ |
| P2.2 | ☐ | 可观测性 | ✗ |
| P2.3 | ☐ | 文档 | ✗ |
| P2.4 | ☐ | 部署 | ✗ |
| P2.5 | ☐ | 清理 | ✗ |
| P3.1 | ☐ | 重构 | ✗ |
| P3.2 | ☐ | 重构 | ✗ |
| P3.3 | ☐ | 重构 | ✗ |
| P3.4 | ☐ | 重构 | ✗ |
| P3.5 | ☐ | 韧性 | ✗ |
| P3.6 | ☐ | 文档 | ✗ |
| P3.7 | ☐ | 可读性 | ✗ |
| P3.8 | ☐ | 性能 | ✗ |
| P3.9 | ☐ | 卫生 | ✗ |
