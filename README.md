# 智云台 AI 客服系统

基于多IM平台的 AI 自动回复系统，使用 DeepSeek API + RAG 知识库 + 人工接管机制。

## 功能特性

- **多IM平台架构**：内置企业微信支持，可扩展飞书、钉钉等
- **私聊自动回复**：客户给客服发消息 → AI 以企业身份替同事回复
- **群聊自动回复**：客户在群中 @机器人 → AI 回复（上下文按人隔离）
- **RAG 知识库**：向量检索增强回答准确性
- **图片 OCR**：自动识别图片中的文字并回复
- **人工接管**：AI 无法回答时自动转人工，运营后台接管/释放
- **管理后台**：对话列表、知识库管理、平台配置

## 技术栈

| 层 | 选型 |
|----|------|
| 后端框架 | Flask (Python) |
| 数据库 | MySQL 8.0 |
| 向量数据库 | ChromaDB |
| Embedding | BGE-small-zh |
| AI 模型 | DeepSeek API |
| OCR | PaddleOCR |
| 管理后台 | HTML + htmx |

## 快速开始

```bash
# 1. 复制环境变量模板
cp .env.example .env
# 编辑 .env 填写配置（见下方说明）

# 2. 使用 Docker Compose 启动
docker compose up -d

# 3. 访问管理后台
# http://localhost/admin
```

### 环境变量说明

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `WX_CORP_ID` | 企业微信 CorpID |
| `WX_AGENT_SECRET` | 企业微信应用 Secret |
| `WX_TOKEN` | 回调验证 Token |
| `WX_ENCODING_AES_KEY` | 回调加解密密钥 |
| `MYSQL_PASSWORD` | 数据库密码 |

完整配置项详见 `.env.example`。

## 项目结构

```
├── app/
│   ├── core/              ← 多IM平台抽象层
│   ├── platforms/         ← IM平台模块（wechat_work/）
│   ├── models/            ← 数据模型
│   ├── routes/            ← API 路由
│   ├── services/          ← 业务逻辑层
│   └── utils/             ← 工具模块
├── deploy/                ← 部署配置
├── templates/             ← 管理后台模板
├── .github/workflows/     ← CI/CD 配置
├── docker-compose.yml     ← Docker 编排
├── Dockerfile             ← 镜像构建
└── run.py                 ← 应用入口
```

## 部署

详见 [部署操作手册](./deploy/deploy.sh) 和项目文档。

## License

MIT
