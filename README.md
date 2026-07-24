# WeBooks - 企业微信记账助手

WeBooks 是一套面向企业微信自建应用的轻量记账与财务管理系统。用户可以在企业微信聊天窗口中快速记账、转账、查询预算，并通过 Web 管理后台完成账户、科目、预算、角色和菜单配置。

## 项目特点

- 企业微信自建应用集成：支持消息记账、转账、帮助说明、汇总推送
- 本地 SQLite 存储：无需额外部署数据库服务
- Web 管理后台：账户、科目、预算、对账、角色、菜单、计划任务一体化管理
- PWA 支持：可安装为桌面应用，支持独立窗口运行
- 自定义图标：浏览器标签页和安装后的应用图标可使用项目 logo
- 权限系统：角色、菜单、按钮级权限可灵活配置

## 快速开始

### 1. 环境要求

- Python 3.10+
- pip
- 可选：Docker / Docker Compose

### 2. 配置企业微信

1. 登录企业微信管理后台，创建自建应用
2. 获取 CorpID、AgentID、Secret
3. 配置可信域名与回调地址
4. 回调地址建议为：
   - http://your-domain:5001/qywx/callback

### 3. 配置环境变量

复制示例文件后修改配置：

```bash
cp .env.sample .env
```

常用配置项包括：

- WECOM_CORP_ID：企业微信 CorpID
- WECOM_AGENT_ID：应用 AgentID
- WECOM_CORP_SECRET：应用 Secret
- WECOM_TOKEN / WECOM_ENCODING_AES_KEY：回调消息验签配置
- WECOM_AGENT_URL：企业微信代理地址，用于规避 IP 白名单限制
- BASE_URL：外部访问地址，用于生成消息中的链接
- ADMIN_USERNAME / ADMIN_PASSWORD：管理后台登录账号
- WECOM_OAUTH_ENABLED：是否启用 OAuth 登录（默认关闭）

### 4. 安装依赖

```bash
pip install -r requirements.txt
```

### 5. 启动服务

```bash
python app.py
```

默认服务监听：
- http://0.0.0.0:5001

Windows 环境下也可直接运行：

```bash
start.cmd
```

### 6. Docker 部署

```bash
docker-compose -f docker-compose.sample.yml up -d
```

## 核心功能

### 📝 快速记账

可在企业微信应用中直接发送消息完成记账，例如：

- 餐饮 30
- 交通 15.5 地铁
- 收入 工资 5000
- 新增支出 话费
- 支出 -50

记账成功后可回复 0 撤销最近一笔交易。

### 📊 消费查询

- 今日 / 本月：查看家庭维度汇总
- 我的今日 / 我的本月：查看当前用户自己的支出
- 他人今日 / 他人本月：切换查看其他用户数据
- 帮助：查看完整命令说明

### 💰 预算管理

- 支持家庭预算与个人预算
- 可在 Web 页面中编辑预算、按月切换、复制历史预算
- 首页会展示预算执行进度

### 🔄 转账功能

- 支持保存转账配置
- 可按配置执行转账
- 支持删除转账配置

### ⏰ 计划任务

在 Web 管理页面的 /scheduled-tasks 中可配置定时推送任务，包括：

- 无预算汇总
- 有预算汇总
- 自定义 SQL 查询

可指定时间范围、推送目标、执行明细与验证码链接。

### 🔐 权限与菜单管理

- 角色管理：/roles
- 菜单管理：/menu
- 用户管理：/user
- 按钮级权限：所有写操作 API 默认受权限控制

### 📱 PWA 与图标

- 浏览器可将应用安装到桌面，像原生 App 一样使用
- 侧边栏底部提供安装入口
- 页面使用项目图标作为浏览器标签页和安装图标
- 图标文件位于 static/logo.png 与 static/favicon.ico

## 数据库与初始化

项目使用本地 SQLite 数据库，数据库文件位于 data/data.db。

首次启动时会自动创建数据库表，并初始化：

- 默认角色（admin / user）
- 默认菜单结构
- 默认菜单与角色绑定

菜单初始化逻辑会在数据库首次建表/空表时补齐默认数据，避免每次启动都重复重建。

## 管理后台页面

| 路径 | 说明 |
|------|------|
| / | 首页 |
| /user | 用户管理 |
| /roles | 角色管理 |
| /menu | 菜单管理 |
| /manage | 交易管理 |
| /accounts | 账户管理 |
| /categories | 科目管理 |
| /budgets | 预算管理 |
| /scheduled-tasks | 计划任务 |
| /aliases | 别名管理 |
| /message-log | 消息日志 |
| /reconciliation | 对账管理 |
| /add-transaction | 页面记账 |
| /transaction | 交易查询 |

## 目录说明

- app.py：Flask 主程序
- db.py：数据库初始化与数据操作
- routes/：页面与接口路由
- services/：业务逻辑
- templates/：前端模板
- static/：静态资源与 PWA 相关文件
- wecom/：企业微信集成模块
