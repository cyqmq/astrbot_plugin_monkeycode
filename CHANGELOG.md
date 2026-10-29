# 更新日志

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