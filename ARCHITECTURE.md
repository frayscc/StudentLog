# StudentLog 正式架构要求

StudentLog 是一个“具有 Web UI 的本地桌面工具”，不是需要持续在线的服务器服务。

## 运行模型

正式版面向 Windows 单教师、单电脑使用：双击启动器后，程序只监听 `127.0.0.1`，启动 FastAPI、托管已构建的 React 静态页面，并自动打开默认浏览器。关闭启动器即停止服务。应用主体与语音识别均可离线使用；只有 DeepSeek 整理和阶段性摘要需要网络。

## 本地 ASR

语音识别采用 `LocalASRProvider` 统一接口，Paraformer 为默认方案，SenseVoiceSmall 为备选和对照方案。浏览器录音由后端在本机转为 16 kHz 单声道 WAV，模型在第一次转写时懒加载并缓存到进程结束。Paraformer 热词由活跃学生姓名和少量场景词生成，学生名单变化后自动失效重建；本地姓名解析器仍负责最终关联确认。

模型固定放在 `models/paraformer/` 和 `models/sensevoice/`，与程序和 `data/` 分离，不打入 EXE。正式版禁止运行时静默联网下载。原始录音只在 `data/temp_audio/` 暂存并在请求结束后删除。

Node.js、npm 与 Vite 仅用于开发和构建。正式发布采用绿色便携目录，并在 Phase 4 使用 PyInstaller 打包 Python 运行时与启动器。用户无需安装 Python、Node.js 或 Docker。

## 持久数据

所有长期数据固定保存在程序目录旁的 `data/`：

- `data/app.db`：SQLite 数据库；
- `data/avatars/`：处理后的学生照片；
- `data/attachments/`：事件附件；
- `data/backups/`：本机备份。

程序文件与 `data/` 逻辑分离。升级不得覆盖该目录，也不得把数据写入临时目录、PyInstaller 解压目录或 AppData 临时目录。

## 明确排除

不引入 Docker、云服务器、NAS 部署、PostgreSQL、Redis、云数据库、多用户、远程访问或实时同步。备份与恢复是本地数据安全的核心能力，不以云同步替代。

## Phase 4：本地发布与体验优化

1. 完成前后端生产构建，FastAPI 托管 React 静态页面；
2. 制作 Windows 本地启动器，自动启动 localhost 服务并打开浏览器；
3. 使用 PyInstaller 打包绿色便携版，不依赖 Python、Node.js 或 Docker；
4. 验证关闭、重启后数据完整；
5. 验证升级不会覆盖 `data/`；
6. 完成完整备份与全新环境恢复测试。
