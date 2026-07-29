# 智云台 AI 客服系统

基于多IM平台架构的 AI 自动回复系统，内置企业微信/微信客服支持，集成 RAG 知识库 + 多 AI 模型 + 人工接管机制。

## 功能特性

- **多IM平台架构**：内置企业微信（内部消息）和微信客服（外部客户），可扩展飞书、钉钉等
- **多 AI 模型**：支持 DeepSeek、OpenAI、通义千问、Kimi 等，管理后台可动态配置主模型/备用模型
- **私聊自动回复**：客户消息 → AI 自动回复（多轮对话上下文感知）
- **群聊自动回复**：群中 @机器人 → AI 回复（上下文按用户隔离）
- **RAG 知识库**：基于 ChromaDB + BGE 向量检索，增强回答准确性
- **短追问增强检索**：≤ 8 字自动拼历史上下文，提高知识命中率
- **图片 OCR**：PaddleOCR 自动识别图片文字并纳入上下文
- **人工接管**：AI 无法回答时自动转人工，运营后台接管/释放，支持超时自动回收
- **管理后台**：12 个管理页面，统一布局，会话管理、知识库管理、渠道配置、AI 配置、系统设置

## 技术栈

| 层 | 选型 |
|----|------|
| 后端框架 | Flask (Python) |
| 数据库 | MySQL 8.0 |
| 向量数据库 | ChromaDB（嵌入部署，零额外运维） |
| Embedding | BGE-small-zh（本地 CPU） |
| AI 模型 | DeepSeek / OpenAI / 通义千问 / Kimi 等多模型动态配置 |
| OCR | PaddleOCR |
| 管理后台 | 纯 HTML + 原生 JS（无前端框架依赖） |
| 加密 | AES-256 (PBKDF2+SHA256+Fernet)，SECRET_KEY 派生 |
| 部署 | Docker + GitHub Actions + Watchtower 自动化部署 |

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
| `SECRET_KEY` | Flask 密钥（**必须配置**，空则拒绝启动） |
| `MYSQL_HOST` | MySQL 主机地址 |
| `MYSQL_PASSWORD` | 数据库密码 |
| `ADMIN_PASSWORD` | 管理后台登录密码 |
| `HF_ENDPOINT` | HuggingFace 镜像（国内服务器必填） |

> AI 模型 API Key 和企业微信配置统一通过管理后台录入，**无需**在 .env 中配置。
> 所有敏感信息在数据库中 AES 加密存储。

## 项目结构

```
├── app/
│   ├── core/              ← 多IM平台抽象层（接口 + 注册/发现）
│   ├── platforms/         ← IM平台模块
│   │   ├── wechat_work/   ← 企业微信平台（内部消息）
│   │   └── wechat_kf/     ← 微信客服平台（外部客户）
│   ├── models/            ← 数据模型（含平台配置 AES 加密存储）
│   ├── routes/            ← API 路由 + 管理后台
│   ├── services/          ← 业务逻辑层（AI对话/RAG/接管/Prompt）
│   └── utils/             ← 工具模块（csrf/幂等去重/OCR/定时任务/向量库）
├── deploy/                ← Nginx 配置模板
├── templates/admin/       ← 12个管理后台模板
├── scripts/               ← 数据库建表 + 自动迁移脚本
├── .github/workflows/     ← CI/CD 自动构建配置
├── docker-compose.yml     ← Docker 编排（含 Watchtower）
├── Dockerfile             ← 镜像构建
└── run.py                 ← 应用入口
```

## 部署

推荐使用 Docker Compose + GitHub Actions + Watchtower 自动化方案：

1. Fork 本仓库
2. 在 GitHub Secrets 中配置 Docker Hub 或阿里云 ACR 凭证
3. 在服务器安装 Docker 和 Docker Compose
4. 配置 `.env` 并启动
5. 推送代码到 main 分支即自动构建部署

详见项目完整文档。

## License

MIT
