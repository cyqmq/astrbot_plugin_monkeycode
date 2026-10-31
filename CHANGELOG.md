# 更新日志

## [v2.0.1] - 2026-10-31

### 修复
- **后台运行中会话/最近任务不显示**：前端字段映射错误（后端 `running_tasks`/`recent_tasks` 下划线 → 前端 `runningTasks`/`recentTasks` 驼峰），`Object.assign` 无法自动映射，已改为显式字段映射

## [v2.0.0] - 2026-10-31

### 里程碑：从「设置页」升级为「管理后台」
- **概览标签**：账户详情（邮箱/用户 ID/订阅计划）、积分余额（点单位）、每日 Token 额度进度条、余额低额告警
- **会话管理**：运行中会话列表、最近任务、点击查看会话详情（状态/内容/执行轮次）
- **设置标签**：20+ 可配置项（任务默认值/轮询/日志/通知/自动切换模型/额度告警/脱敏/会话）
- **自动切换模型**：任务失败时自动切换备用模型并重启
- 前端基于 Vuetify 3，主题自动跟随 Dashboard

### 修复
- 后台账户详情/订阅数据兼容提取（嵌套结构 `user`/`data`）
- 运行中会话：显式状态查询 + 非终态兜底
- 额度告警阈值迁移为点单位（默认 100 点）

## [v1.19.2] - 2026-10-31

### 修复
- **额度告警阈值迁移**：旧配置中的原始值（如 10000）一次性迁移为新默认 **100 点**，后台不再显示错误阈值
- **运行中会话不显示**：改用显式状态查询（`pending,processing,running`）+ 兼容 `tasks/list/items` 提取 + 非终态兜底，确保后台能正确显示运行中任务

## [v1.19.1] - 2026-10-31

### 改进
- **余额单位换算**：钱包/签到/后台余额按平台规则显示为「点」（1000 原始值 = 1 点），如 605000 → **605 点**
- `low_balance_threshold` 阈值单位改为「点」，默认 100 点

## [v1.19.0] - 2026-10-31

### 新增
- **管理后台**：设置页升级为「概览 / 设置」双标签后台
  - 概览：账户详情（邮箱/用户 ID/订阅计划）、积分余额、每日 Token 额度进度条、余额低额告警
  - 运行中会话列表与最近任务，点击查看会话详情（状态/内容/执行轮次）
  - 设置：保留全部配置项
- **自动切换模型**：`auto_switch_model` + `fallback_model_ids` 配置，任务失败时自动切换备用模型并重启
- **额度告警阈值**：`low_balance_threshold` 配置，余额低于阈值在后台显示告警
- 后端新增 Web API：`GET /dashboard`（概览）、`GET /task/<id>`（会话详情）
- 前端继续使用 Vuetify 3（gzip 后约 158KB）

## [v1.18.0] - 2026-10-31

### 新增（设置页可配置项扩充）
- `notify_on_task_end`：任务完成时是否发送短通知（默认开）
- `task_summary_length`：通知中摘要截断长度（默认 200）
- `md_log_max_rounds`：任务日志导出的最大轮次数（默认 10）
- `reply_read_timeout`：`/mc 回复` 等待 agent 响应的超时（默认 60 秒）
- `max_concurrent_tasks`：最大并发任务数（默认 0 不限制，防止刷任务）
- `desensitize_enabled`：敏感信息自动脱敏开关（默认开）

以上配置均在「MonkeyCode 高级设置」视图页中管理，并已在前端表单中同步。

## [v1.17.0] - 2026-10-31

### 改进
- **输出全面友好化**：消除剩余裸 JSON 输出
  - `/mc 签到` 和自动签到通知：显示「积分」和结果消息
  - `/mc 文件`：目录显示 📁、文件显示 📄
  - `/mc Issue`：显示 `Issue #<编号> <标题>`
  - `/mc 评论`：显示 `评论 #<编号> 已创建`
- 其他查询类命令（项目/Git/技能/分支/模型/交易记录/任务列表）此前已是友好格式

## [v1.16.1] - 2026-10-31

### 改进
- `/mc 钱包` 输出格式化：去掉空 id 和无用字段，显示「余额」和「每日 Token 余额/上限」，更清晰易读

## [v1.16.0] - 2026-10-31

### 新增
- **敏感信息脱敏**：新增 `_desensitize` 脱敏逻辑，覆盖任务日志/任务详情/用户输入/任务列表/摘要中的常见凭据：
  - GitHub PAT（`github_pat_*`、`ghp_*` 等）
  - OpenAI 风格 API Key（`sk-*`）、AWS Access Key（`AKIA*`）
  - Bearer Token、`api_key=` / `password=` 等键值对
  - PEM 私钥块
- 任务 ID / 普通内容不受影响

## [v1.15.0] - 2026-10-31

### 新增
- **命令权限控制**：新增 `admin_only_commands` 配置，默认仅主人/管理员可用的命令：
  `任务 / 回复 / 停止 / 删除 / 重启 / 换模型 / 自动批准 / 取消自动批准 / 钱包 / 签到 / 交易记录 / 任务详情 / 用户输入 / 日志 / 文件下载`
- 其他查询/协作命令（环境、任务列表、项目、Git、Issue、评论等）保持群成员可用
- 配置项可自定义，留空则所有 `/mc` 命令对群成员开放

## [v1.14.1] - 2026-10-31

### 修复
- 忽略 `webui/node_modules`，仓库从 3308 个跟踪文件减至 20 个，插件包体积从数十 MB 降到 **187KB**，修复安装卡顿

## [v1.14.0] - 2026-10-31

### 重构
- **设置视图升级为 Vuetify 前端工程**：新增 `webui/`（Vite + Vue 3 + Vuetify 3 + TypeScript），构建产物输出到 `views/settings/`
- 使用 `window.AstrBotPluginPage` bridge 与后端通信（含开发模式回退代理）
- 主题自动跟随 AstrBot Dashboard 亮暗（监听 `data-theme` + Vuetify theme 切换）
- 宿主/镜像/模型下拉框动态加载账号下最新列表

### 开发
- 前端工程开发命令：`cd webui && npm install && npm run dev`（开发）/ `npm run build`（构建）

## [v1.13.2] - 2026-10-30

### 修复
- 移除设置视图中与配置页重复的「摘要小模型人格/指令」「自动签到时间」字段（已放回配置页），视图只保留高级配置项

## [v1.13.1] - 2026-10-30

### 增强
- **视图视觉统一**：插件视图背景设为透明，透出 AstrBot Dashboard 原版背景；卡片/输入框/按钮改用 Vuetify 主题变量（`--v-theme-*`），带 fallback 兼容旧版

## [v1.13.0] - 2026-10-30

### 新增
- **动态下拉选项**：高级设置视图中的宿主/镜像/模型改为下拉框，加载时登录 MonkeyCode 自动获取账号下最新列表
- 后端新增 Web API：`GET /astrbot_plugin_monkeycode/options`（返回 hosts/images/models 列表）

### 调整
- `auto_checkin_hour`（自动签到时间）和 `summary_prompt`（摘要小模型人格）从视图移回配置页，配置页直接可改

## [v1.12.0] - 2026-10-30

### 新增
- **插件可视化视图**：新增 `views/settings/` 高级设置页面（通过 `window.AstrBotPluginView` bridge 与后端通信）
- **配置分层**：配置页只保留基础项（账号/API 地址/摘要开关/摘要提供商/签到开关），高级配置（默认档位/技能/轮询/日志/摘要人格/会话路径/签到时间）移到「MonkeyCode 高级设置」视图
- 后端新增 Web API：`GET /astrbot_plugin_monkeycode/settings`（读取高级配置）、`POST /astrbot_plugin_monkeycode/settings/save`（保存）

## [v1.11.3] - 2026-10-30

### 增强
- `default_host_id` / `default_image_id` / `default_model_id` 的配置提示更新：说明镜像/模型/宿主列表是动态的，可通过 `/mc 环境` 查询最新 ID 后手动填写（留空仍自动取第一个/平台默认）

## [v1.11.2] - 2026-10-30

### 增强
- `default_cli_name` 使用 `string + options` 渲染为静态单选下拉框（AstrBot WebUI 支持）

## [v1.11.1] - 2026-10-30

### 修复
- `default_cli_name` 配置类型由不支持的 `select` 改为 `string`（AstrBot 支持类型不含 select），hint 注明可选值 opencode/codex/claude，代码侧已有合法性校验

## [v1.11.0] - 2026-10-30

### 新增
- **默认 CLI 可选**：新增配置 `default_cli_name`（opencode/codex/claude 下拉选择），创建任务时传给 SDK
- **新命令**：
  - `/mc 任务详情 <任务ID>`：查看任务状态/内容/模型/仓库/PR
  - `/mc 用户输入 <任务ID>`：查看 agent 等待的用户输入
  - `/mc 交易记录`：查看最近积分流水
  - `/mc 文件下载 <VMID> <路径> <文件名>`：下载任务产物文件
  - `/mc 换模型 <任务ID> <模型ID>`：切换运行中任务模型（WebSocket 控制通道）
  - `/mc 重启 <任务ID>`：重启任务（WebSocket 控制通道）

## [v1.10.6] - 2026-10-30

### 修复
- **/mc 日志「执行轮次」为空**：适配 SDK `get_task_rounds` 返回的 `chunks` 结构，并兼容 `data` 的 base64(JSON) 解码展示
- **前置平台标记导致命令失效**：`[MSG_ID:xxx] /mc 环境` 等前置标记现在会被正确剥离再解析

> 提示：升级插件后如仍使用旧 SDK，请执行 `pip install -U monkeycode-sdk` 确保拉取最新版。

## [v1.10.5] - 2026-10-30

### 修复
- **数据持久化合规**：登录会话文件默认保存到 `data/plugin_data/astrbot_plugin_monkeycode/session.json`（AstrBot 规范目录），不再写入系统临时目录；仅当用户显式配置 `session_path` 时才使用自定义路径

## [v1.10.4] - 2026-10-30

### 新增
- 默认任务档位配置：`default_host_id` / `default_image_id` / `default_model_id`（留空自动取默认/第一个）
- 任务轮询参数：`task_timeout_seconds`（默认 3600）/ `task_poll_interval`（默认 15）
- `send_md_on_end`：控制任务完成时是否发送完整日志 md 文件

## [v1.10.3] - 2026-10-30

### 新增
- `summary_provider_id` 配置项改用 `_special: "select_provider"`：AstrBot WebUI 渲染为 LLM 提供商下拉框，直接选择即可，无需手动复制 provider_id

## [v1.10.2] - 2026-10-30

### 修复
- 修正 `email` 配置项提示文案，去掉不必要的「不是学号」说明

## [v1.10.1] - 2026-10-30

### 变更
- SDK 依赖从 GitHub 仓库切换为 PyPI：`monkeycode-sdk>=1.7.1`，安装更稳定（`pip install monkeycode-sdk`）
- README 补充「依赖安装排障」：国内镜像源未同步时使用清华源/官方源安装

## [v1.10.0] - 2026-10-29

### 新增
- **登录会话持久化**：新增 `session_path` 配置项（留空自动使用系统临时目录）
- **免重复登录**：插件重启后复用持久化会话，不再每次重新登录
- **自动重登**：登录态过期时 SDK 自动重新登录并重试请求，任务不再因会话失效失败

## [v1.9.1] - 2026-10-25

### 修复
- 同步 `@register` 装饰器版本号与 `metadata.yaml` 一致（v1.9.0）

## [v1.9.0] - 2026-10-25

### 新增
- **每日自动签到**：`/mc 签到 on [小时]` 开启定点自动签到，结果推送到当前会话；`/mc 签到 off` 关闭
- 配置项：`auto_checkin_enabled` / `auto_checkin_hour` / `auto_checkin_origin`
- 自动签到由插件层实现（APScheduler 定时任务），SDK 仅保留 `checkin()` 基础调用

## [v1.8.0] - 2026-10-25

### 新增（可选功能按需接入）
- `/mc 可用模型`：列出可用模型
- `/mc Issue <项目ID> <标题>`：创建 Issue
- `/mc 评论 <项目ID> <IssueID> <内容>`：评论 Issue
- `/mc 自动批准 <任务ID>` / `/mc 取消自动批准 <任务ID>`：任务自动批准开关（WebSocket）
- 基于 SDK v1.0.0

## [v1.7.0] - 2026-10-25

### 新增
- `/mc 删除 <任务ID>`：删除任务
- `/mc 技能`：列出可用技能（配合 skill_ids）
- `/mc 分支 <GitID> <owner/repo>`：查看仓库分支
- 基于 SDK v0.1.10（附件上传、任务删除、插件/技能列表、钱包流水、Git 分支）

### 修复（审查反馈）
- `_send_markdown` 文件名使用 `_safe_filename` 消毒任务 ID，防止非常规 ID 导致路径问题
- 确认 `send_task_message` 为 SDK 原生异步（websockets），直接 `await` 正确

## [v1.6.0] - 2026-10-25

### 新增
- `/mc links <任务ID>`：列出任务中的预览链接及存活状态（基于 SDK v0.1.9）

### 修复（AstrBot 审查反馈）
- 同步 `@register` 装饰器版本号与 `metadata.yaml` 一致（v1.6.0）
- 移除 `requirements.txt` 中未使用的 `apscheduler` 依赖

## [v1.5.1] - 2026-10-25

### 变更
- 小模型摘要改为**每次独立调用**：上下文只包含「人格指令 + 本次完整任务内容」，不保留多轮对话历史
- 去掉任务内容 2000 字符截断（改为 8000 高上限防溢出），可喂更完整内容
- 更新配置提示与 README 说明

## [v1.5.0] - 2026-10-25

### 新增
- **小模型摘要**：可配置 `summary_enabled` / `summary_provider_id` / `summary_prompt`
  - 默认关闭：使用 MonkeyCode 平台原始摘要，**零 token 消耗**
  - 开启后仅调用指定的小模型生成摘要，不碰 AstrBot 主模型
- 新增 `_summarize`：根据配置生成简短摘要，失败自动回退平台摘要

## [v1.4.0] - 2026-10-25

### 新增
- `/mc 日志 <任务ID>`：导出任务日志为 md 文件发送
- 任务完成通知改为**简短文本 + 完整 md 文件**，避免长文本刷屏与上下文浪费
- 新增 `_send_markdown` / `_build_task_md`：长内容转文件发送

## [v1.3.0] - 2026-10-25

### 新增
- `/mc 文件 <VMID> [路径]`：查看虚拟机目录内容（基于 SDK v0.1.8 文件管理）

## [v1.2.0] - 2026-10-25

### 新增
- `/mc 钱包`、`/mc 签到`：查询积分余额、每日签到
- `/mc 项目`：项目列表
- `/mc Git身份`、`/mc GitBots`：Git 身份与 Git Bots 列表
- 基于 SDK v0.1.7 新增能力

## [v1.1.0] - 2026-10-25

### 新增
- `/mc 回复 <任务ID> <内容>`：向运行中的 MonkeyCode 任务发送消息，让 agent 继续执行（基于 SDK WebSocket 会话交互）
- LLM 工具 `monkeycode_reply`：自然语言「继续让 agent 做某事」时自动调用

## [v1.0.1] - 2026-10-25

### 变更
- 明确支持**不绑定 Git 仓库**创建任务：`default_repo_url` 可留空，任务也能正常运行

## [v1.0.0] - 2026-10-25

### 新增
- AstrBot 插件首版：通过 MonkeyCode 云平台提交 AI 编程任务
- 命令：`/mc 帮助 / 环境 / 任务 / 任务列表 / 停止`
- LLM 工具 `use_monkeycode`：自然语言「用 MonkeyCode 帮我...」自动触发
- 底层复用 monkeycode-sdk（自动 PoW 验证码、自托管支持）
- 后台任务轮询：任务完成后主动推送结果到会话