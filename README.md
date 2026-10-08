# StudentLog

StudentLog 是供班主任个人使用的学生事件档案工具。产品以 PC 浏览器为主要界面，正式运行统一采用 Docker，数据和本地 ASR 模型仍保存在部署电脑的 `./data` 与 `./models`。

当前已完成 Phase 1–4 的主要功能：

- 单管理员登录，密码以 scrypt 哈希保存在 SQLite；
- 学生新增、编辑、停用、TXT/CSV 导入，以及安全的一键清空当前名单；
- 学生照片自动校正方向、居中裁切、压缩为 512×512 WebP；
- 照片卡片墙，按姓名或学号搜索；
- 手工事件记录，一条事件可关联多名学生；
- 分类、自定义标签、学生时间线与全部记录页；
- 面向 PC Chrome / Edge 的桌面布局；
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
- 学生档案支持 7 天、30 天、本学期和自定义日期的事实型阶段性摘要；
- 文字与 AI 整理草稿自动保存在当前浏览器，意外刷新后可以恢复；
- 网络、DeepSeek 和本地服务故障均显示明确错误，并保留可重试入口；
- Docker 镜像提供健康检查、优雅停止和独立的 Docker 开发编排。

## Docker 正式运行

Docker 是唯一正式运行方式。镜像内的 FastAPI 直接托管构建后的 React 页面：

```powershell
docker compose pull
docker compose up -d
```

Compose 直接使用 Docker Hub 的 `docker.io/frayscc/studentlog:latest`。浏览器打开 `http://127.0.0.1:8765`。当前目录的 `./data` 映射到容器 `/app/data`，`./models` 映射到 `/app/models`；删除或升级容器不会覆盖这两个目录。全新数据库第一次打开时由用户创建管理员账号，不提供默认密码。正式使用前请复制 `.env.example` 为 `.env`，并为 `APP_SECRET` 设置长随机字符串。

## Docker 开发

后端热重载与 Vite 开发服务器均在容器内运行，开发电脑只需要 Docker：

```powershell
docker compose -f docker-compose.dev.yml up --build
```

开发页面为 `http://127.0.0.1:5173`，API 为 `http://127.0.0.1:8765`。生产 `docker-compose.yml` 始终只拉取 Docker Hub 镜像，不包含 `build`。

## 本地语音识别

语音识别完全离线，默认使用 CPU 版 Paraformer。镜像已经包含 ASR 运行依赖，模型单独下载到宿主机的 `./models`：

```powershell
docker compose run --rm studentlog python scripts/download_asr_models.py paraformer
# 可选回退模型
docker compose run --rm studentlog python scripts/download_asr_models.py sensevoice
```

下载过程由 ModelScope 显示进度。模型不会在点击录音后静默下载。也可以从其他电脑完整复制 `models/paraformer/` 或 `models/sensevoice/`。

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
docker compose -f docker-compose.dev.yml run --rm studentlog pytest backend/tests
docker compose -f docker-compose.dev.yml run --rm frontend npm run build
```

## 当前已知问题

- 尚未完成 20–50 条真实中文录音的 Paraformer/SenseVoice 对照验收；自动化测试不加载大型模型；
- 尚未用真实 DeepSeek Key 完成端到端调用，当前自动化测试使用 Mock LLM；
- 全新数据库会在首次打开时要求创建本地管理员账号；已有数据库继续使用原账号，不会被升级覆盖；
- 不再计划 PWA、手机端专项适配、Windows 启动器或绿色 EXE；后续发布与升级均以 Docker 镜像为准。
