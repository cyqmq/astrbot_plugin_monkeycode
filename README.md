# astrbot_plugin_monkeycode

AstrBot 插件：通过 **MonkeyCode 云平台** 提交 AI 编程任务并跟踪结果。
底层复用 [monkeycode-sdk](https://github.com/cyqmq/monkeycode-sdk)，自动处理 PoW 验证码、支持自托管。

## 安装

1. 将本目录放到 AstrBot 的 `data/plugins/astrbot_plugin_monkeycode/`。
2. 在 AstrBot 管理面板「插件」页刷新/重载插件（首次会通过 pip 安装依赖 `monkeycode-sdk`，已发布到 PyPI）。
3. 在「插件配置」中填写基础配置：

| 配置项 | 说明 |
|---|---|
| `email` | MonkeyCode 账号邮箱 |
| `password` | MonkeyCode 账号密码 |
| `base_url` | API 地址（云平台默认 `https://monkeycode-ai.com`；自托管填自己域名） |
| `summary_enabled` | 启用 LLM 生成任务摘要（默认关闭，用平台原始摘要，零 token） |
| `summary_provider_id` | 摘要专用小模型提供商（配置界面下拉选择） |
| `summary_prompt` | 摘要小模型人格/指令（默认中文简洁摘要） |
| `auto_checkin_enabled` | 开启每日自动签到（默认关闭） |
| `auto_checkin_hour` | 每日自动签到时间（小时 0-23，默认 8） |
| `admin_only_commands` | 仅主人/管理员可用的命令（逗号分隔，默认覆盖消耗积分/任务运维/账户相关命令） |

> 高级配置（默认仓库/分支/CLI/宿主/镜像/模型/技能、轮询参数、日志开关、
> 会话持久化路径、自动切换模型、额度告警）请在插件详情页打开 **「MonkeyCode 后台」** 中配置。
> 后台「概览」标签显示账户详情、积分/Token 额度、余额告警、运行中会话与最近任务，
> 点击会话可查看执行轮次详情；「设置」标签管理全部可配置项。

> 摘要说明：默认**不调用任何模型**，直接使用 MonkeyCode 平台返回的原始摘要。
> 开启 `summary_enabled` 并填写 `summary_provider_id` 后，才会调用你指定的小模型生成摘要。
> 每次摘要都是**独立调用**，小模型上下文只包含「人格指令 + 本次完整任务内容」，
> 不保留多轮对话历史，也不会使用 AstrBot 主模型。

> 安全说明：任务日志/详情/摘要/用户输入中的常见敏感凭据（GitHub PAT、`sk-*` API Key、
> Bearer Token、`api_key=`/`password=` 键值对、PEM 私钥）会自动脱敏为 `***`，避免泄露。

### 依赖安装排障（pip 找不到 monkeycode-sdk）

`monkeycode-sdk` 已发布到 PyPI（官方源）。如果你的 pip 使用**国内镜像源**（如阿里源），
镜像可能滞后数小时，导致报错：

```
ERROR: Could not find a version that satisfies the requirement monkeycode-sdk>=1.7.1
```

解决办法（任选其一）：

1. 使用已同步的镜像源安装（清华源已同步）：
   ```bash
   pip install -i https://pypi.tuna.tsinghua.edu.cn/simple monkeycode-sdk
   ```
2. 使用官方源安装：
   ```bash
   pip install -i https://pypi.org/simple monkeycode-sdk
   ```
3. 等待当前镜像源同步（阿里源通常数小时内完成）后重装。

在 AstrBot 中手动安装依赖：

```bash
cd <AstrBot 安装目录>
source .venv/bin/activate  # 如使用虚拟环境
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple monkeycode-sdk
```

## 命令

```
/mc 帮助              查看帮助
/mc 环境              列出云端环境/镜像/模型
/mc 任务 <内容>        提交编程任务（后台执行，完成后通知）
/mc 回复 <任务ID> <内容>  向运行中的任务发送消息，让 agent 继续执行
/mc 任务列表           最近任务
/mc 停止 <任务ID>      停止任务
/mc 钱包 / 签到        查询积分、每日签到
/mc 项目              项目列表
/mc Git身份            Git 身份列表
/mc GitBots          Git Bots 列表
/mc 文件 <VMID> [路径]  查看虚拟机目录
/mc 日志 <任务ID>       导出任务日志为 md 文件
/mc links <任务ID>     列出任务中的预览链接及存活状态
/mc 删除 <任务ID>       删除任务
/mc 技能              列出可用技能
/mc 分支 <GitID> <owner/repo>  查看仓库分支
/mc 可用模型              列出可用模型
/mc Issue <项目ID> <标题>   创建 Issue
/mc 评论 <项目ID> <IssueID> <内容>  评论 Issue
/mc 自动批准 <任务ID>      开启/关闭任务自动批准
/mc 签到 on [小时] / off  开启/关闭每日自动签到（结果推送当前会话）
```

任务完成后，机器人会发送**简短文本通知 + 完整日志 md 文件**，避免长文本刷屏和浪费上下文。

示例：
```
/mc 任务 修复登录接口的异常处理并补测试
/mc 回复 <任务ID> 记得加上日志
/mc 回复 <任务ID> 测试跑通了再告诉我
```

## 自然语言（LLM 工具）

对机器人说：

```
用 MonkeyCode 帮我修一下这个仓库的 bug
```

LLM 会调用 `use_monkeycode` 工具，自动提交任务并在完成后推送结果。

## 说明

- 登录由 `monkeycode-sdk` 自动完成，包括 PoW 验证码（SHA-256 前缀碰撞，本地求解）。
- 创建任务可能返回 `code=10205 主机不在线`：这是 MonkeyCode 云平台环境问题，
  请到控制台确认云端环境已真正启动。
- OhMyAgent API Key 不是 REST 会话凭证，本插件使用账号密码登录（Cookie 会话）。

## 版本

见 [CHANGELOG.md](CHANGELOG.md)。