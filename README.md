# StudentLog

StudentLog 是供班主任个人使用的本地学生事件档案工具。它使用浏览器作为界面，但数据保存在当前工作电脑上；需要时启动，用完即可关闭。

当前完成 Phase 1、Phase 2 与 Phase 3：

- 单管理员登录，密码以 scrypt 哈希保存在 SQLite；
- 学生新增、编辑、停用、TXT/CSV 导入，以及安全的一键清空当前名单；
- 学生照片自动校正方向、居中裁切、压缩为 512×512 WebP；
- 照片卡片墙，按姓名或学号搜索；
- 手工事件记录，一条事件可关联多名学生；
- 分类、自定义标签、学生时间线与全部记录页；
- 手机、平板和桌面响应式界面；
- 前端生产资源可由 FastAPI 直接托管；
- 数据固定保存在 `data/`；可本机运行，也可通过 Docker Hub 镜像启动；
- 浏览器录音支持开始、暂停、继续、结束和取消；
- 浏览器录音在本机临时转为 16 kHz 单声道 WAV，识别完成立即删除；
- 本地 `LocalASRProvider` 抽象，Paraformer 默认、SenseVoiceSmall 备选；
- 模型首次使用时才加载，随后缓存到应用关闭；
- 活跃学生姓名与常用场景词自动组成 Paraformer 热词；
- ASR 输出优先按唯一同音姓名规范；对姓氏相同的近音姓名，仅在最佳候选明显领先时修正，并提示教师核对；
- 姓名完全匹配、别名、拼音和 RapidFuzz 候选匹配；
- 置信度提示与人工学生确认；
- DeepSeek JSON 结构化和 Pydantic 校验；
- AI 草稿确认页、重新整理、字段编辑和确认保存；
- 保存原始转写与教师最终确认内容。
- 全文搜索覆盖学生姓名、学号、原始转写、事件字段和标签；
- 支持按学生、分类、标签与时间范围组合筛选；
- 事件支持图片附件，自动校正方向、压缩并生成 WebP；
- 支持 JSON、CSV 数据导出；
- 支持包含 SQLite、头像、附件和必要配置的完整 ZIP 备份与恢复；
- 恢复前自动生成当前数据的安全备份，并校验 ZIP 路径与 SQLite 完整性。

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

开发页面为 `http://127.0.0.1:5173`。全新数据库首次打开时会进入初始化页面，由用户自行创建本地管理员账号。

## 本地生产方式

```powershell
cd frontend
npm run build
cd ..
.\Start StudentLog.bat
```

启动器会在 `127.0.0.1:8765` 启动应用并打开默认浏览器。此批处理入口是 Phase 1 的开发机可用版本；无需安装 Python/Node.js 的绿色 `StudentLog.exe` 在 Phase 4 交付。

## Docker 运行方式

Docker 部署是可选的服务器/开发环境运行方式，不改变默认的本地便携版数据结构。镜像内的 FastAPI 会直接托管 `frontend/dist`：

```powershell
docker compose pull
docker compose up -d
```

Compose 直接使用 Docker Hub 的 `docker.io/frayscc/studentlog:latest`，不在部署电脑上构建镜像。浏览器打开 `http://127.0.0.1:8765`。当前目录的 `./data` 映射到容器 `/app/data`，`./models` 映射到 `/app/models`；删除或升级容器不会覆盖这两个目录。全新数据库第一次打开时会显示初始化页面，由用户自行创建管理员用户名和密码，不再提供默认密码。建议在 `.env` 中为 `APP_SECRET` 设置一个长随机字符串。

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

完整备份与结构化导出位于“系统设置 → 数据导出与备份”。恢复 ZIP 会替换当前数据库、头像和附件；执行前应用会自动将当前状态备份到 `data/backups/`，恢复完成后需要使用备份中的管理员账号重新登录。

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
- 阶段性 AI 摘要、PWA、草稿保护与 Windows 绿色 EXE 属于 Phase 4；
- 全新数据库会在首次打开时要求创建本地管理员账号；已有数据库继续使用原账号，不会被升级覆盖；
- `Start StudentLog.bat` 仍依赖开发机 Python，最终绿色 EXE 属于调整后的 Phase 4。
