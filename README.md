# StudentLog

StudentLog 是供班主任个人使用的本地学生事件档案工具。它使用浏览器作为界面，但数据保存在当前工作电脑上；需要时启动，用完即可关闭。

当前完成 Phase 1 与 Phase 2 的可离线验证版本：

- 单管理员登录，密码以 scrypt 哈希保存在 SQLite；
- 学生新增、编辑、停用、TXT/CSV 导入，以及安全的一键清空当前名单；
- 学生照片自动校正方向、居中裁切、压缩为 512×512 WebP；
- 照片卡片墙，按姓名或学号搜索；
- 手工事件记录，一条事件可关联多名学生；
- 分类、自定义标签、学生时间线与全部记录页；
- 手机、平板和桌面响应式界面；
- 前端生产资源可由 FastAPI 直接托管；
- 数据固定保存在 `data/`，不依赖 Docker。
- 浏览器录音支持开始、暂停、继续、结束和取消；
- 浏览器录音在本机临时转为 16 kHz 单声道 WAV，识别完成立即删除；
- 本地 `LocalASRProvider` 抽象，Paraformer 默认、SenseVoiceSmall 备选；
- 模型首次使用时才加载，随后缓存到应用关闭；
- 活跃学生姓名与常用场景词自动组成 Paraformer 热词；
- ASR 输出仅在“拼音完全一致且名单候选唯一”时规范为正式姓名，并提示教师核对；
- 姓名完全匹配、别名、拼音和 RapidFuzz 候选匹配；
- 置信度提示与人工学生确认；
- DeepSeek JSON 结构化和 Pydantic 校验；
- AI 草稿确认页、重新整理、字段编辑和确认保存；
- 保存原始转写与教师最终确认内容。

## 开发运行

要求 Python 3.11+ 和 Node.js（仅开发/构建时需要）。

```powershell
python -m venv .venv
.venv\Scripts\pip install -r backend\requirements.txt
cd frontend
npm install
npm run dev
```

另开终端：

```powershell
.venv\Scripts\python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8765 --reload
```

开发页面为 `http://127.0.0.1:5173`。首次账号默认是 `admin` / `change-me`，实际使用前必须在首次启动前通过 `.env` 修改。

## 本地生产方式

```powershell
cd frontend
npm run build
cd ..
.\Start StudentLog.bat
```

启动器会在 `127.0.0.1:8765` 启动应用并打开默认浏览器。此批处理入口是 Phase 1 的开发机可用版本；无需安装 Python/Node.js 的绿色 `StudentLog.exe` 在 Phase 4 交付。

## 本地语音识别

语音识别完全离线，默认使用 CPU 版 Paraformer，不再使用或配置阿里云 ASR。先安装本地语音依赖：

```powershell
.venv\Scripts\pip install -r backend\requirements-asr.txt
```

模型文件独立保存在 `models/`，不打入 EXE，也不会在录音时静默下载。默认只下载推荐模型：

```powershell
.venv\Scripts\python launcher\download_asr_models.py paraformer
# 可选的对照/回退模型
.venv\Scripts\python launcher\download_asr_models.py sensevoice
```

下载过程由 ModelScope 显示进度。也可在联网电脑下载后完整复制 `models/paraformer/` 或 `models/sensevoice/` 到离线工作电脑。系统设置页可以切换模型并查看安装、加载和热词状态。

可选开发配置：

```text
ASR_PROVIDER=paraformer
ASR_CPU_THREADS=6
ASR_ALLOW_MODEL_DOWNLOAD=false
LLM_PROVIDER=mock
```

`ASR_ALLOW_MODEL_DOWNLOAD` 正式版保持 `false`。录音仅在 `data/temp_audio/` 短暂存在，识别结束即删除，不上传、不长期保存。

## DeepSeek 配置

启用 DeepSeek：

```text
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

后端使用 `/chat/completions` 的 JSON Output，并对结果执行 Pydantic 校验。学生 ID 必须属于本地 Resolver 给出的候选，否则整次结果会被拒绝。照片、附件和原始音频不会发送给 DeepSeek。

## 名单导入格式

UTF-8 编码的 TXT 或 CSV 均可：

```text
0321 杨煜洆
0322 郭语桐
0323 王子航
```

## 数据与升级

数据库、头像、附件和备份分别位于 `data/app.db`、`data/avatars/`、`data/attachments/`、`data/backups/`。更新程序时保留整个 `data/` 目录即可。完整架构约束见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 测试

```powershell
$env:PYTHONPATH = "backend"
.venv\Scripts\python -m pytest backend\tests
cd frontend
npm run build
```

## 当前已知问题

- 尚未完成 20–50 条真实中文录音的 Paraformer/SenseVoice 对照验收；自动化测试不加载大型模型；
- 尚未用真实 DeepSeek Key 完成端到端调用，当前自动化测试使用 Mock LLM；
- 附件、完整全文检索、备份恢复和摘要属于后续阶段；
- 当前登录密码仅能在首次创建数据库前通过 `.env` 设置，设置页面在后续阶段补充；
- `Start StudentLog.bat` 仍依赖开发机 Python，最终绿色 EXE 属于调整后的 Phase 4。
