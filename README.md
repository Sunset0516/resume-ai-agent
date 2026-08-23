# 个人简历 AI Agent

一个基于 Python + FastAPI 的智能简历问答网站。访客打开网页即可与 AI 助手对话，AI 会基于你的简历内容回答关于你的技能、经历、项目等问题。

## 核心功能

- **AI 智能问答**：接入 DeepSeek/OpenAI API，支持 SSE 流式输出，打字机效果
- **持久记忆**：双层记忆架构（会话级 + 长期记忆），AI 回答可跨会话引用关键信息
- **简历文档上传**：上传 PDF/Word/TXT 简历，AI 自动解析提取结构化信息并入库
- **管理后台**：可视化编辑简历各模块（基本信息/教育/实习/项目/技能）和长期记忆
- **可上线部署**：FastAPI + SQLite，单文件数据库零部署成本

## 技术栈

| 层 | 技术 |
|---|---|
| 后端框架 | FastAPI + Uvicorn |
| 数据库 | SQLAlchemy + SQLite |
| LLM 接口 | DeepSeek / OpenAI 兼容接口（同步 + SSE 流式） |
| 文档解析 | PyPDF2（PDF）、python-docx（Word） |
| 前端 | Jinja2 模板 + 原生 HTML/CSS/JS |
| 配置管理 | python-dotenv + pydantic-settings |

## 快速开始

```bash
# 1. 克隆项目
git clone https://github.com/你的用户名/resume-ai-agent.git
cd resume-ai-agent

# 2. 创建虚拟环境并安装依赖
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate
pip install -r requirements.txt

# 3. 配置 API Key
# 复制 .env.example 为 .env，填入你的 LLM API Key
cp .env.example .env
# 编辑 .env 填入 LLM_API_KEY

# 4. 启动服务
python run.py --port 8000

# 5. 打开浏览器
# 前台：http://127.0.0.1:8000/
# 后台：http://127.0.0.1:8000/admin
```

## 项目结构

```
resume-ai-agent/
├── app/
│   ├── main.py                # FastAPI 入口
│   ├── config.py             # 配置读取
│   ├── database.py           # 数据库引擎
│   ├── models.py             # ORM 模型（8张表）
│   ├── schemas.py            # Pydantic 校验模型
│   ├── api/
│   │   ├── chat.py           # 聊天接口（非流式 + SSE）
│   │   ├── resume.py         # 简历 CRUD + 文档上传解析
│   │   └── memory.py         # 长期记忆管理
│   ├── services/
│   │   ├── llm_service.py    # LLM API 封装
│   │   ├── memory_service.py # 记忆检索
│   │   ├── resume_crud.py    # 简历数据操作
│   │   ├── agent_service.py  # Agent 核心（串联简历+记忆+LLM）
│   │   └── doc_parser.py     # 文档解析（PDF/DOCX/TXT → 结构化）
│   └── templates/
│       ├── index.html         # 前台聊天页
│       └── admin.html         # 管理后台
├── static/                    # 前端 CSS/JS
├── data/                      # SQLite 数据库 + 示例数据
├── .env.example              # 环境变量模板
├── requirements.txt
└── run.py                    # 启动脚本
```

## API 概览

| 方法 | 路径 | 功能 |
|---|---|---|
| POST | `/api/chat` | AI 对话（支持流式 SSE） |
| POST | `/api/resume` | 创建简历 |
| GET | `/api/resume` | 获取简历 |
| POST | `/api/resume/upload` | 上传简历文档，AI 自动解析 |
| GET | `/api/resume/export/text` | 导出简历纯文本 |
| POST | `/api/memory` | 添加长期记忆 |
| GET | `/api/memory` | 查询记忆列表 |
| GET | `/health` | 健康检查 |
| GET | `/docs` | Swagger API 文档 |

## 环境变量说明

```env
LLM_PROVIDER=openai           # openai / dashscope
LLM_API_KEY=sk-xxx            # 你的 API Key
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
LLM_TEMPERATURE=0.7
LLM_TIMEOUT=60
```

## 部署到服务器

```bash
# 安装依赖
pip install -r requirements.txt

# 配置 .env 后启动
python run.py --port 8000 --host 0.0.0.0

# 生产环境建议用 gunicorn + nginx
gunicorn app.main:app -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

## License

MIT
