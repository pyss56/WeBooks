# WeBooks - 企业微信记账助手

通过企业微信自建应用，在聊天窗口中快速记账、转账，管理预算，并定时推送消费汇总。

## 前置依赖

本服务使用本地 SQLite 数据库存储所有数据，无需额外部署后端服务。

## 功能

### 📝 快速记账
在企微应用中发送消息即可记账：
- `餐饮 30` — 餐饮支出30元
- `交通 15.5 地铁` — 交通支出15.5元，备注"地铁"
- `收入 工资 5000` — 工资收入5000元
- `新增支出 话费` — 快速创建新科目「话费」
- `支出 -50` — 支出退款（负值）
- 记账成功后回复 `0` 可撤销该笔交易

### 📊 消费查询
| 命令 | 说明 |
|------|------|
| `今日` / `本月` | 家庭维度的消费汇总（含预算对比） |
| `我的今日` / `我的本月` | 查看你自己的支出（含个人预算对比） |
| `他人今日` / `他人本月` | 选择其他用户查看其支出 |
| `帮助` | 查看完整使用说明 |

### 💰 预算管理
- **Web 管理页面** — 在浏览器中打开 `https://your-domain/budgets`，可视化编辑家庭/个人预算
- 支持按月切换，从历史月份复制预算
- 首页展示本月各科目预算执行进度条

### 🔄 转账功能
- `转账设置` — 进入转账配置模式，选择转出/转入账户和转账类型
- `快捷转账` — 查看已保存的转账配置
- `1 500 备注` — 执行第1条转账配置，金额500，添加备注
- `d 1` — 删除第1条转账配置
- 转账成功后回复 `0` 可撤销

### 🔀 切换账户
- `切换账户` — 从账户列表中选择，支持分别设置支出账户和收入账户

### 🔗 UUID 交易链接
- 记账成功后返回 `🔗 点击查看/修改：{url}（5分钟有效）`
- 无需登录即可在浏览器中查看、编辑或删除刚创建的交易

### ⏰ 计划任务
在 Web 管理页面（`/scheduled-tasks`）可配置定时推送任务：
- **任务类型**：无预算汇总、有预算汇总（对比预算）、自定义 SQL 查询
- **时间范围**：昨天、今天、本月、上个月、本季度、上季度、本年、去年、自定义
- **推送目标**：选择用户或按人分别推送
- **自定义 SQL**：支持 `{filter_user}` 变量，自定义标题和行格式模板
- **执行明细**：有预算汇总任务自动生成验证码 + 图表查看页面，7天有效

### 📊 汇总图表
- 有预算汇总任务推送消息仅包含总预算、总支出、剩余、占比
- 消息附带 4 位验证码和链接
- 点击链接输入验证码后可查看完整柱状图
- 支持一级科目/二级科目切换，可选是否显示预算

### ⚙️ 别名管理
- 支持为科目和账户设置别名，方便快速输入
- 在 Web 管理页面进行别名配置

### 📋 数据字典
- 任务类型、时间范围等选项从数据库 `dict_header`/`dict_detail` 表读取
- 支持在数据库直接修改字典值，无需改代码

### 🗄 日志系统
- 应用日志、API 错误日志、推送错误日志独立文件
- 按小时轮转，保留天数可通过环境变量 `LOG_RETENTION_DAYS` 配置（默认60天）

## 快速开始

### 1. 企业微信后台配置

1. 登录 [企业微信管理后台](https://work.weixin.qq.com/wework_admin/frame#apps)
2. 创建自建应用，获取 **CorpID**、**AgentID**、**Secret**
3. 配置 **可信域名**（指向部署服务器）
4. 配置 **回调URL**：`http://your-domain:5001/qywx/callback`
5. 点击 **保存** 后会进行URL验证（自动完成）

### 2. 配置

复制 `.env.sample` 并编辑配置项：

```bash
cd WeBooks
cp .env.sample .env
```

完整配置项请参考 `docker-compose.sample.yml` 文件。

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 运行

```bash
python app.py
```
服务启动在 `http://0.0.0.0:5001`

Windows 下也可直接运行 `start.cmd`（自动激活虚拟环境）。

## 菜单结构

| 一级菜单 | 子按钮 |
|---------|--------|
| 家庭 | 今日汇总、本月汇总 |
| 个人 | 我的今日、我的本月、他人今日、他人本月、快捷转账 |
| 更多 | 后台管理、转账设置、切换账户、使用帮助 |

## 管理后台页面

| 路径 | 说明 |
|------|------|
| `/` | 首页 - 本月预算执行进度 |
| `/manage` | 交易管理（查看/编辑/删除） |
| `/accounts` | 账户管理 |
| `/categories` | 科目管理 |
| `/users` | 用户管理（绑定平台账号） |
| `/budgets` | 预算管理（家庭/个人，按月切换） |
| `/scheduled-tasks` | 计划任务管理（创建/编辑/删除/执行） |
| `/aliases` | 别名管理 |
| `/message-log` | 消息日志 |
| `/reconciliation` | 对账管理 |
| `/s/t/<uuid>` | 汇总图表查看（验证码保护，7天有效） |

## Docker 部署

```bash
docker-compose -f docker-compose.sample.yml up -d
```

## 环境变量说明

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SECRET_KEY` | 随机生成 | Flask 密钥 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `LOG_RETENTION_DAYS` | `60` | 日志保留天数 |
| `WECOM_CORP_ID` | - | 企业微信 CorpID |
| `WECOM_AGENT_ID` | - | 企业微信 AgentID |
| `WECOM_CORP_SECRET` | - | 企业微信 Secret |
| `WECOM_TOKEN` | - | 企业微信 Token |
| `WECOM_ENCODING_AES_KEY` | - | 企业微信 EncodingAESKey |
| `TIMEZONE` | `Asia/Shanghai` | 时区 |
| `ADMIN_USERNAME` | `admin` | 管理后台用户名 |
| `ADMIN_PASSWORD` | - | 管理后台密码 |
| `BASE_URL` | - | 服务外部访问地址 |
| `WEB_ENTRY_CODE` | - | PC端访问入口编码（企业微信主页URL子路径） |
| `WEB_ENTRY_REDIRECT` | - | 未带入口编码时的跳转地址 |
| `WECOM_OAUTH_ENABLED` | `false` | 企业微信 OAuth 登录开关（汇总图表免验证码） |

> **OAuth 要求**：`BASE_URL` 必须为 HTTPS（443端口），域名须在企业微信管理后台配置为可信域名。
> 回调路径：`{BASE_URL}/{WEB_ENTRY_CODE}/s/cb/{uuid}`
| `/qywx/callback` | GET/POST | 企业微信回调 |
| `/api/qywx/sync_menu` | POST | 同步自定义菜单 |
| `/api/test/send` | POST | 测试发送消息 |
| `/` | GET | 首页（预算概览，需登录） |
| `/api/admin/budget-summary` | GET | 预算汇总数据（柱状图用，需登录） |
| `/admin/manage` | GET | 后台管理首页（需登录） |
| `/admin/status` | GET | API状态页面（需登录） |
| `/category/manage` | GET | 科目管理页面（需登录） |
| `/api/categories/list` | GET | 获取全部科目 |
| `/api/categories/add` | POST | 新增科目 |
| `/api/categories/modify` | POST | 修改科目 |
| `/api/categories/delete` | POST | 删除科目 |
| `/budget/manage` | GET | 预算管理页面（需登录） |
| `/api/budget/save` | POST | 保存预算 |
| `/api/budget/copy-last-month` | POST | 从上月复制预算 |
| `/transaction` | GET | 交易查询页面（需登录） |
| `/api/transactions/list` | GET | 查询交易列表 |
| `/api/transactions/modify` | POST | 修改交易 |
| `/api/transactions/delete` | POST | 删除交易 |
| `/tx/<uuid>` | GET | UUID 交易详情页（无需登录） |
| `/api/transactions/by-uuid/update` | POST | UUID 更新交易 |
| `/api/transactions/by-uuid/delete` | POST | UUID 删除交易 |
| `/reconciliation` | GET | 对账管理页面（需登录） |
| `/api/reconciliation/list` | GET | 对账列表 |
| `/api/reconciliation/create` | POST | 创建对账 |
| `/api/reconciliation/detail` | GET | 对账详情 |
| `/api/reconciliation/add-transactions` | POST | 添加交易到对账 |
| `/api/reconciliation/remove-transactions` | POST | 从对账移除交易 |
| `/api/reconciliation/confirm` | POST | 确认对账 |
| `/api/reconciliation/cancel` | POST | 取消对账 |
| `/account/manage` | GET | 账户管理页面（需登录） |
| `/api/accounts` | GET | 获取账户列表 |
| `/api/accounts/create` | POST | 新增账户 |
| `/api/accounts/modify` | POST | 修改账户 |
| `/api/accounts/delete` | POST | 删除账户 |
| `/users/manage` | GET | 用户管理页面（需登录） |
| `/api/users/list` | GET | 用户列表 |
| `/api/users/create` | POST | 新建用户 |
| `/api/users/update` | POST | 更新用户 |
| `/api/users/delete` | POST | 删除用户 |
| `/login` | GET/POST | 登录 |
| `/logout` | GET | 退出登录 |

## 架构

```text
用户 → 企业微信 → 回调 → WeBooks → SQLite
```