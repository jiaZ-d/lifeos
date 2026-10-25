# LifeOS

> 个人生活与目标管理系统 · 记录生活 · 未来推演 · 目标落地 · 每日待办

LifeOS 是一个**本地运行**的个人成长管理系统:用六个维度记录生活,以 PIN 加密保护隐私,把目标逐级拆解为每天可执行的待办,并结合 AI(智谱 GLM)推演未来、生成周期报告。

**核心闭环**:记录 → 现状画像 → 目标 → 子目标 → 月度进度规划 → 周任务 → 每日待办 → 看板回顾 → 更准的推演。

**数据主权**:所有数据存储在本机 SQLite 文件,私密记录 AES-256-GCM 加密保存,不上传任何第三方服务器。

## 功能特性

| 模块 | 说明 |
|---|---|
| 📝 六分类记录 | 工作 / 生活作息 / 饮食 / 学习 / 锻炼 / 社交,各带专属字段;中文全文搜索;每日小结自动生成 |
| 📚 个人知识库 | 领域 → 笔记本 → 笔记三级组织;新建笔记不弹窗直达编辑;Markdown 即时渲染编辑(vditor,编辑时图片就地显示),粘贴 / 拖拽 / 上传嵌入图片,按用户隔离访问 |
| 🔒 隐私加密 | 私密记录标题/内容/标签全部 AES-256-GCM 加密,列表仅显示 🔒 占位;PIN 连续错误防暴力锁定;管理员可配置恢复口令协助找回 |
| 🎯 目标树 | 目标 → 子目标 → 月度进度规划 → 周任务,支持 AI 生成拆解草稿,上层进度由下层实时汇总 |
| ✅ 今日待办 | 每天 02:00 自动生成(未开机则首次打开补生成);不限时待办;未完成自动顺延,3 次进入欠账区 |
| 📋 看板 | 目标/子目标/月度规划/周任务四维度切换,三列状态,上层状态由下层自动推导 |
| 🕐 时间轴 | 日/周/月/年四粒度浏览,当前时期居中;AI 周报/月报/年报可人工编辑 |
| 🔮 未来推演 | 基于 personal 现状 + 社会/行业趋势 + 健康基线推演未来 N 年,生成建议目标并一键落地为任务树 |
| 📊 统计 | GitHub 风格年度热力图、近 30 天完成趋势、拖延统计 |
| 🤖 LLM 集成 | 默认智谱 GLM(OpenAI 兼容端点可切换);无 API Key 时自动降级为内置模板 |
| 👥 多用户 | 数据按用户完全隔离;首个注册用户自动成为管理员(用户管理 / LLM 配置 / PIN 恢复) |

## 技术栈

- **后端**:Python 3.12 · FastAPI · SQLAlchemy 2 (async) · SQLite (aiosqlite) · Alembic · Argon2 · PyJWT
- **前端**:React 18 · Vite 5 · ECharts · react-router-dom(构建产物由后端随服务分发)
- **AI**:智谱 GLM(OpenAI 兼容),可选任意兼容端点

## 目录结构

```
lifeos/
├── apps/
│   ├── server/          # FastAPI 后端
│   │   ├── app/         # 源码:api/ · services/ · models · auth · tests/
│   │   ├── migrations/  # Alembic 数据库迁移
│   │   └── scripts/     # 调试 / 维护脚本
│   └── web/             # React (Vite) 前端
├── config/              # 配置:server.json(端口) · llm_config.json(不入库) · example 模板
├── data/                # 运行时数据(不入库):SQLite · JWT 密钥 · 附件 · 备份
├── *.bat                # 启动 / 重启 / 停止脚本(读取 config/server.json)
├── README.md
└── LICENSE              # Apache-2.0
```

## 快速开始

### 1. 启动后端

```powershell
cd apps/server
uv venv --python 3.12 .venv                        # 或: python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"    # uv 用户: -m uv pip install -e ".[dev]"

.venv\Scripts\python -m app.main                  # 监听地址/端口读 config/server.json
```

浏览器打开 `http://127.0.0.1:8000`,点击"注册新用户"——**第一个注册的用户自动成为管理员**(密码 ≥6 位)。

### 2. 构建前端(修改前端代码后)

```powershell
cd apps/web
npm install
npx vite build      # 开发模式:npx vite(localhost:5173,已配 CORS)
```

### 3. 运行测试

```powershell
cd apps/server
$env:PYTHONPATH = "$PWD"
.venv\Scripts\python -m pytest          # 51 项(默认跳过 llm_real 标记的真实 API 用例)
```

## 配置(根目录 `config/`)

| 文件 | 说明 |
|---|---|
| `config/server.json` | 服务监听地址与端口(`host` / `port`),`python -m app.main` 与启动脚本均读取此文件 |
| `config/llm_config.json` | LLM 运行时配置:`base_url` / `model` / `api_key` / `thinking`(思考强度:默认/关闭/低/中/高) |
| `config/llm_config.example.json` | 上述文件的模板,Key 以 `xxx` 占位 |

**模型 Key 配置步骤**:

1. 复制模板:`copy config\llm_config.example.json config\llm_config.json`(也可以直接在应用「⚙️ 设置 → 🤖 LLM 配置」页填写,仅管理员,保存即写入该文件);
2. 把 `api_key` 的 `xxx` 替换为真实 Key——默认端点是[智谱开放平台](https://open.bigmodel.cn/) `https://open.bigmodel.cn/api/paas/v4`,Key 在其控制台创建;模型名必须是平台上架的(如 `glm-5.3-flash`);
3. `base_url` 兼容任意 OpenAI 风格端点,可自行切换其他服务商;
4. 不配置 Key 也能用:所有 AI 功能自动降级为内置模板输出,其余功能不受影响;
5. 可选「🧠 思考强度」:默认(跟随服务商)/ 关闭(响应最快)/ 低 / 中 / 高(更强推理),在设置页选择,对智谱 GLM 混合推理模型生效。

## 定时任务

| 时间 | 任务 | 错过处理 |
|---|---|---|
| 每天 01:00 | 生成前一日每日小结 | 相关页面首次打开时补跑 |
| 每天 02:00 | 从目标任务自动生成今日待办 | 当天首次打开"今日"页时补跑 |
| 每天 21:30 | 生成今日小结 | 同上 |
| 每日 | 未完成待办自动顺延(3 次转欠账) | 打开"今日"页时惰性执行 |

## 安全设计

- **本地存储**:数据库、JWT 密钥(首启随机生成,持久化于 `data/secret.key`)、LLM 配置均在本机 `data/` 目录,已被 `.gitignore` 排除
- **隐私加密**:私密记录 DEK/KEK 分层加密;搜索索引不含私密内容;PIN 与管理员恢复口令均经 Argon2/防暴力锁定保护
- **两级 AI 授权**:分类级"AI 可用"开关(社交类默认不参与)+ 单条记录开关,同时允许才进入 AI 上下文;私密记录永不进入

## License

本项目基于 [Apache License 2.0](LICENSE) 开源。
