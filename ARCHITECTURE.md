# StudentLog 正式架构要求

StudentLog 是一个面向单教师、以 PC 浏览器为界面的本地数据工具。正式运行与开发统一采用 Docker，但不因此引入云端数据或多用户架构。

## 运行模型

正式版通过 `docker compose` 启动 Docker Hub 镜像。FastAPI 在容器内托管 React 静态页面、API、SQLite 与本地文件访问；浏览器通过 `127.0.0.1:8765` 使用。应用主体与语音识别可离线工作，只有 DeepSeek 整理和阶段性摘要需要网络。

## 本地 ASR

语音识别采用 `LocalASRProvider` 统一接口，Paraformer 为默认方案，SenseVoiceSmall 为备选和对照方案。浏览器录音由后端在本机转为 16 kHz 单声道 WAV，模型在第一次转写时懒加载并缓存到进程结束。Paraformer 热词由活跃学生姓名和少量场景词生成，学生名单变化后自动失效重建；本地姓名解析器仍负责最终关联确认。

模型固定放在宿主机 `models/paraformer/` 和 `models/sensevoice/`，通过 `./models:/app/models` 绑定挂载，与镜像和 `data/` 分离。正式版禁止录音时静默联网下载。原始录音只在 `data/temp_audio/` 暂存并在请求结束后删除。

生产镜像使用多阶段构建：Node.js 只存在于前端构建阶段，运行阶段只有 Python、FastAPI、静态资源和本地 ASR 依赖。停止 PWA、PyInstaller、Windows 批处理启动器和绿色便携版开发。

## 持久数据

所有长期数据固定保存在程序目录旁的 `data/`：

- `data/app.db`：SQLite 数据库；
- `data/avatars/`：处理后的学生照片；
- `data/attachments/`：事件附件；
- `data/backups/`：本机备份。

镜像与数据逻辑分离。升级镜像不得覆盖宿主机的 `./data` 和 `./models`。

## 明确排除

不引入云服务器、PostgreSQL、Redis、云数据库、多用户、远程访问或实时同步。Docker 是唯一生产交付方式，并始终使用 `./data` 与 `./models` 本地绑定目录；备份与恢复不以云同步替代。

## Phase 4：PC 体验与 Docker 正式发布

1. 完成事实型阶段性摘要，不保存学生画像或评分；
2. 完成浏览器草稿保护、明确错误提示与失败重试；
3. 以 PC Chrome / Edge 为主要体验目标，不做 PWA 和手机端专项优化；
4. Docker 镜像加入健康检查与优雅停止；
5. 提供独立的 Docker 开发编排和 Docker Hub 自动发布；
6. 验证容器重建与镜像升级不覆盖 `./data`、`./models`。
