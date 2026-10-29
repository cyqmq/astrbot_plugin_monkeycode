# astrbot_plugin_monkeycode

AstrBot 插件：通过 **MonkeyCode 云平台** 提交 AI 编程任务并跟踪结果。
底层复用 [monkeycode-sdk](https://github.com/cyqmq/monkeycode-sdk)，自动处理 PoW 验证码、支持自托管。

## 安装

1. 将本目录放到 AstrBot 的 `data/plugins/astrbot_plugin_monkeycode/`。
2. 在 AstrBot 管理面板「插件」页刷新/重载插件（首次会安装依赖 `monkeycode-sdk`，需要能访问 GitHub）。
3. 在「插件配置」中填写：

| 配置项 | 说明 |
|---|---|
| `email` | MonkeyCode 账号邮箱 |
| `password` | MonkeyCode 账号密码 |
| `base_url` | API 地址（云平台默认 `https://monkeycode-ai.com`；自托管填自己域名） |
| `default_repo_url` | 默认 GitHub 仓库 URL（**可留空：不绑定仓库也能创建任务**） |
| `default_branch` | 默认分支（`main`） |
| `skill_ids` | 默认技能列表（逗号分隔，可选） |

## 命令

```
/mc 帮助              查看帮助
/mc 环境              列出云端环境/镜像/模型
/mc 任务 <内容>        提交编程任务（后台执行，完成后通知）
/mc 任务列表           最近任务
/mc 停止 <任务ID>      停止任务
```

示例：
```
/mc 任务 修复登录接口的异常处理并补测试
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