# StudentLog

StudentLog 是供班主任个人使用的本地学生事件档案工具。它使用浏览器作为界面，但数据保存在当前工作电脑上；需要时启动，用完即可关闭。

当前完成 Phase 1：

- 单管理员登录，密码以 scrypt 哈希保存在 SQLite；
- 学生新增、编辑、停用、TXT/CSV 导入；
- 学生照片自动校正方向、居中裁切、压缩为 512×512 WebP；
- 照片卡片墙，按姓名或学号搜索；
- 手工事件记录，一条事件可关联多名学生；
- 分类、自定义标签、学生时间线与全部记录页；
- 手机、平板和桌面响应式界面；
- 前端生产资源可由 FastAPI 直接托管；
- 数据固定保存在 `data/`，不依赖 Docker。

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

- Phase 1 暂不包含语音、ASR、AI 整理、附件、全文检索、备份恢复和摘要；
- 当前登录密码仅能在首次创建数据库前通过 `.env` 设置，设置页面在后续阶段补充；
- `Start StudentLog.bat` 仍依赖开发机 Python，最终绿色 EXE 属于调整后的 Phase 4。
