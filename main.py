"""AstrBot 插件：MonkeyCode 编程助手。

通过 MonkeyCode 云平台提交 AI 编程任务并跟踪结果。
底层复用 monkeycode-sdk（自动处理 PoW 验证码、支持自托管）。

命令：
  /mc 帮助                    查看帮助
  /mc 环境                    列出云端环境/镜像/模型
  /mc 任务 <内容>              提交编程任务（后台执行，完成后通知）
  /mc 任务列表                 最近任务
  /mc 停止 <任务ID>            停止任务

LLM 工具：use_monkeycode —— 用户说「用 MonkeyCode 帮我...」时自动调用。
"""
import asyncio
import base64
import json
import os
import re
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register
from astrbot.api.web import error_response, json_response, request

from monkeycode import MonkeyCodeClient
from monkeycode.models import RepoReq

PLUGIN_NAME = "astrbot_plugin_monkeycode"


@register(
    "astrbot_plugin_monkeycode",
    "cyqmq",
    "MonkeyCode 编程助手（基于 monkeycode-sdk）",
    "1.12.0",
)
class MonkeyCodePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._client: MonkeyCodeClient | None = None
        self._login_lock = asyncio.Lock()
        self.scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self._register_web_apis()

    def _register_web_apis(self) -> None:
        """注册插件视图（views/settings）使用的后端 API。"""
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/settings",
            self.view_get_settings,
            ["GET"],
            "获取 MonkeyCode 高级配置",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/settings/save",
            self.view_save_settings,
            ["POST"],
            "保存 MonkeyCode 高级配置",
        )

    async def view_get_settings(self):
        """返回当前高级配置值（供视图表单填充）。"""
        keys = [
            "default_repo_url",
            "default_branch",
            "default_cli_name",
            "default_host_id",
            "default_image_id",
            "default_model_id",
            "skill_ids",
            "task_timeout_seconds",
            "task_poll_interval",
            "send_md_on_end",
            "summary_prompt",
            "session_path",
            "auto_checkin_hour",
        ]
        return json_response({k: self._cfg(k, "") for k in keys})

    async def view_save_settings(self):
        """保存视图提交的高级配置。"""
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)
        keys = [
            "default_repo_url",
            "default_branch",
            "default_cli_name",
            "default_host_id",
            "default_image_id",
            "default_model_id",
            "skill_ids",
            "task_timeout_seconds",
            "task_poll_interval",
            "send_md_on_end",
            "summary_prompt",
            "session_path",
            "auto_checkin_hour",
        ]
        for k in keys:
            if k in payload:
                self.config[k] = payload[k]
        self.config.save_config()
        return json_response({"saved": True})

    async def initialize(self):
        """插件初始化：启动每日自动签到（若开启）。"""
        if self._cfg("auto_checkin_enabled", False):
            try:
                hour = int(self._cfg("auto_checkin_hour", 8) or 8)
            except (TypeError, ValueError):
                hour = 8
            self.scheduler.add_job(self._auto_checkin, "cron", hour=hour, minute=0)
            self.scheduler.start()
            logger.info(
                f"[{PLUGIN_NAME}] 每日自动签到已开启（{hour}:00），"
                f"推送目标：{self._cfg('auto_checkin_origin', '') or '未设置'}"
            )

    async def _auto_checkin(self) -> None:
        """每日自动签到并推送结果到配置的会话。"""
        origin = str(self._cfg("auto_checkin_origin", "") or "").strip()
        if not origin:
            logger.warning(f"[{PLUGIN_NAME}] 自动签到未设置推送目标，已跳过。")
            return
        try:
            client = await self._ensure_client()
            result = await asyncio.to_thread(client.checkin)
            await self._send(origin, f"✅ 每日签到完成：{self._fmt(result)[:300]}")
        except Exception as e:
            await self._send(origin, f"❌ 自动签到失败：{e}")

    # ---------- 配置 ----------

    def _cfg(self, key: str, default=None):
        try:
            return self.config.get(key, default)
        except Exception:
            return default

    # ---------- 客户端懒登录 ----------

    def _default_session_path(self) -> str:
        """返回 AstrBot 规范要求的插件数据目录下的会话文件路径。

        持久化数据（含登录会话 Cookie）应保存到
        data/plugin_data/<插件名>/，而不是系统临时目录。
        """
        try:
            from pathlib import Path

            from astrbot.core.utils.astrbot_path import get_astrbot_data_path

            plugin_name = getattr(self, "name", None) or PLUGIN_NAME
            data_dir = Path(get_astrbot_data_path()) / "plugin_data" / plugin_name
            data_dir.mkdir(parents=True, exist_ok=True)
            return str(data_dir / "session.json")
        except Exception:
            # 极低版本 AstrBot 兜底：回退到系统临时目录
            import tempfile

            return os.path.join(
                tempfile.gettempdir(),
                "astrbot_plugin_monkeycode_session.json",
            )

    async def _ensure_client(self) -> MonkeyCodeClient:
        """获取已登录的 SDK 客户端（懒登录 + 缓存 + 会话持久化）。"""
        if self._client is not None:
            return self._client
        email = str(self._cfg("email", "") or "").strip()
        password = str(self._cfg("password", "") or "")
        base_url = str(self._cfg("base_url", "https://monkeycode-ai.com") or "")
        if not email or not password:
            raise ValueError("未配置 MonkeyCode 邮箱/密码，请在插件配置中填写。")
        async with self._login_lock:
            if self._client is not None:
                return self._client
            session_path = str(self._cfg("session_path", "") or "").strip()
            if not session_path:
                session_path = self._default_session_path()
            client = MonkeyCodeClient(
                email=email,
                password=password,
                base_url=base_url,
                session_path=session_path,
            )
            if not client.is_logged_in():
                await asyncio.to_thread(client.login)
                logger.info(f"[{PLUGIN_NAME}] 登录成功（{base_url}）")
            else:
                logger.info(f"[{PLUGIN_NAME}] 使用持久化会话（{base_url}）")
            self._client = client
            return client

    async def _send(self, origin: str, text: str) -> None:
        try:
            await self.context.send_message(origin, MessageChain().message(text))
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 消息发送失败: {e}")

    async def _send_markdown(self, origin: str, filename: str, content: str) -> None:
        """把长内容写成 md 临时文件并发送到会话，避免长文本刷屏。"""
        import tempfile

        from astrbot.api.message_components import File as CompFile

        path = os.path.join(tempfile.gettempdir(), filename)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            chain = MessageChain().message(CompFile(file=path, name=filename))
            await self.context.send_message(origin, chain)
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 发送 md 文件失败: {e}")
            # 兜底：文本截断发送
            await self._send(origin, content[:3000])

    @staticmethod
    def _args(event: AstrMessageEvent, cmd: str) -> list[str]:
        """取指令参数，过滤平台附加标记（如 [MSG_ID:xxx]）。"""
        text = (event.message_str or "").strip()
        # 剥离开头的平台标记（如 [MSG_ID:123] /mc 环境）
        text = re.sub(r"^(\s*\[[A-Z_]+:[^\]]+\]\s*)+", "", text)
        text = text.lstrip("/").strip()
        if text.startswith(cmd):
            rest = text[len(cmd):]
        elif text.split() and text.split()[0].startswith(cmd):
            tokens = text.split()
            rest = tokens[0][len(cmd):] + " " + " ".join(tokens[1:])
        else:
            rest = ""
        tokens = [a for a in re.split(r"[\s,，、]+", rest) if a]
        return [a for a in tokens if not re.match(r"^\[[A-Z_]+:", a)]

    # ---------- 任务提交与后台通知 ----------

    def _repo(self) -> RepoReq:
        return RepoReq(
            repo_url=str(self._cfg("default_repo_url", "") or ""),
            branch=str(self._cfg("default_branch", "main") or "main"),
        )

    def _skill_ids(self) -> list[str] | None:
        raw = str(self._cfg("skill_ids", "") or "").strip()
        if not raw:
            return None
        return [s.strip() for s in raw.split(",") if s.strip()]

    async def _submit_and_watch(
        self, content: str, origin: str, repo_url: str = ""
    ) -> str:
        """创建任务并启动后台轮询，返回任务 ID。"""
        client = await self._ensure_client()
        repo = RepoReq(
            repo_url=repo_url or str(self._cfg("default_repo_url", "") or ""),
            branch=str(self._cfg("default_branch", "main") or "main"),
        )
        skill_ids = self._skill_ids()
        kwargs: dict[str, Any] = {
            "content": content,
            "repo": repo,
            "skill_ids": skill_ids,
        }
        cli_name = str(
            self._cfg("default_cli_name", "opencode") or "opencode"
        ).strip()
        if cli_name in ("opencode", "codex", "claude"):
            kwargs["cli_name"] = cli_name
        host_id = str(self._cfg("default_host_id", "") or "").strip()
        image_id = str(self._cfg("default_image_id", "") or "").strip()
        model_id = str(self._cfg("default_model_id", "") or "").strip()
        if host_id:
            kwargs["host_id"] = host_id
        if image_id:
            kwargs["image_id"] = image_id
        if model_id:
            kwargs["model_id"] = model_id
        try:
            task = await asyncio.to_thread(
                client.create_task,
                **kwargs,
            )
        except Exception as e:
            raise RuntimeError(f"创建任务失败：{e}") from e

        asyncio.create_task(self._watch_task(task.id, origin))
        return task.id

    async def _watch_task(self, task_id: str, origin: str) -> None:
        try:
            client = await self._ensure_client()
            timeout = int(self._cfg("task_timeout_seconds", 3600) or 3600)
            interval = int(self._cfg("task_poll_interval", 15) or 15)
            result = await asyncio.to_thread(
                client.wait_task, task_id, timeout=timeout, interval=interval
            )
            summary = await self._summarize(result)
            text = (
                f"⚡ MonkeyCode 任务完成\n"
                f"任务ID：{task_id}\n状态：{result.status}"
            )
            if result.pr_url:
                text += f"\nPR：{result.pr_url}"
            if summary:
                text += f"\n摘要：{summary[:200]}"
            if self._cfg("send_md_on_end", True):
                text += "\n完整日志已发送为 md 文件。"
            await self._send(origin, text)
            if self._cfg("send_md_on_end", True):
                md = await asyncio.to_thread(self._build_task_md, client, task_id, result)
                await self._send_markdown(origin, f"mc-{self._safe_filename(task_id)}.md", md)
        except Exception as e:
            await self._send(origin, f"❌ MonkeyCode 任务 {task_id} 失败：{e}")

    async def _summarize(self, result: Any) -> str:
        """生成简短摘要。

        - 每次摘要都是**独立调用**：小模型上下文只包含「人格指令 + 本次任务内容」，
          不保留任何多轮对话历史。
        - summary_enabled=False 或未配置小模型时，返回平台原始 summary（零 token）；
        - 开启且配置了 summary_provider_id 时，调用指定小模型生成摘要（不碰主模型）。
        """
        if not self._cfg("summary_enabled", False):
            return str(getattr(result, "summary", "") or "")
        provider_id = str(self._cfg("summary_provider_id", "") or "").strip()
        if not provider_id:
            return str(getattr(result, "summary", "") or "")
        prompt = str(self._cfg("summary_prompt", "") or "")
        # 无历史上下文，可放心喂完整任务内容；仅保留高上限防止小模型上下文溢出
        content = str(getattr(result, "content", "") or "")[:8000]
        try:
            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=(prompt + "\n\n" + content if content else prompt),
            )
            text = getattr(llm_resp, "completion_text", "") or ""
            return str(text).strip()[:500]
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 小模型摘要失败: {e}")
            return str(getattr(result, "summary", "") or "")

    @staticmethod
    def _chunk_text(data: Any) -> str:
        """把任务轮次 chunk 的 data 字段转为可读文本。

        后端 data 可能是普通文本或 base64(JSON)，这里兼容解码。
        """
        if not isinstance(data, str):
            return json.dumps(data, ensure_ascii=False)
        if data and len(data) % 4 == 0:
            try:
                decoded = base64.b64decode(data).decode("utf-8", errors="replace")
            except Exception:
                decoded = None
            if decoded is not None:
                try:
                    obj = json.loads(decoded)
                    if isinstance(obj, str):
                        return obj
                    if isinstance(obj, (dict, list)):
                        return json.dumps(obj, ensure_ascii=False)
                except Exception:
                    return decoded
                return decoded
        return data

    def _build_task_md(self, client: Any, task_id: str, result: Any) -> str:
        """把任务详情与执行轮次整理成 Markdown 文本。"""
        lines = [
            f"# MonkeyCode 任务 {task_id}",
            "",
            f"- 状态：{result.status}",
            f"- 仓库：{result.repo_url or '（未绑定）'}",
            f"- 分支：{result.branch or '-'}",
            f"- PR：{result.pr_url or '无'}",
            f"- 摘要：{result.summary or '无'}",
        ]
        if result.content:
            lines += ["", "## 任务内容", "", str(result.content)]
        try:
            rounds = client.get_task_rounds(task_id, limit=10)
            chunks = (
                rounds.get("chunks", [])
                if isinstance(rounds, dict)
                else (rounds or [])
            )
            lines += ["", "## 执行轮次", ""]
            for c in chunks:
                event = c.get("event") or c.get("kind") or "agent"
                text = self._chunk_text(c.get("data", ""))[:600]
                lines.append(f"### [{event}]")
                lines.append(text)
                lines.append("")
        except Exception:
            pass
        return "\n".join(lines)

    # ---------- 命令 ----------

    @filter.command("mc")
    async def cmd_mc(self, event: AstrMessageEvent):
        """MonkeyCode 编程助手：/mc 帮助、/mc 环境、/mc 任务 <内容> 等"""
        args = self._args(event, "mc")
        if not args:
            yield event.plain_result(self._help_text())
            return
        action = args[0]
        try:
            if action == "帮助":
                yield event.plain_result(self._help_text())
            elif action == "环境":
                yield event.plain_result(await self._format_env())
            elif action == "任务":
                content = " ".join(args[1:]).strip()
                if not content:
                    yield event.plain_result("用法：/mc 任务 <要完成的编程任务描述>")
                    return
                task_id = await self._submit_and_watch(
                    content, event.unified_msg_origin
                )
                yield event.plain_result(
                    f"✅ MonkeyCode 任务已提交：{task_id}\n完成后会在这里通知。"
                )
            elif action == "任务列表":
                yield event.plain_result(await self._format_tasks())
            elif action == "停止":
                if len(args) < 2:
                    yield event.plain_result("用法：/mc 停止 <任务ID>")
                    return
                client = await self._ensure_client()
                await asyncio.to_thread(client.stop_task, args[1])
                yield event.plain_result(f"已请求停止任务 {args[1]}。")
            elif action == "回复":
                if len(args) < 3:
                    yield event.plain_result("用法：/mc 回复 <任务ID> <要给 agent 的消息>")
                    return
                task_id = args[1]
                content = " ".join(args[2:]).strip()
                if not content:
                    yield event.plain_result("回复内容不能为空。")
                    return
                client = await self._ensure_client()
                # SDK 的 send_task_message 是原生 async（websockets），直接 await 即可
                events = await client.send_task_message(
                    task_id, content, read_timeout=60
                )
                types = [e.type for e in events]
                summary = "\n".join(f"  · {t}" for t in types[:8])
                yield event.plain_result(
                    f"✅ 已向任务 {task_id} 发送消息。\n收到事件：\n{summary}"
                )
            elif action == "钱包":
                client = await self._ensure_client()
                wallet = await asyncio.to_thread(client.get_wallet)
                yield event.plain_result(f"💰 钱包信息：\n{self._fmt(wallet)}")
            elif action == "签到":
                mode = args[1] if len(args) > 1 else ""
                if mode == "on":
                    hour = args[2] if len(args) > 2 else str(self._cfg("auto_checkin_hour", 8) or 8)
                    self.config["auto_checkin_enabled"] = True
                    self.config["auto_checkin_hour"] = int(hour)
                    self.config["auto_checkin_origin"] = event.unified_msg_origin
                    self.config.save_config()
                    if getattr(self.scheduler, "running", False):
                        self.scheduler.shutdown(wait=False)
                    self.scheduler.add_job(self._auto_checkin, "cron", hour=int(hour), minute=0)
                    self.scheduler.start()
                    yield event.plain_result(
                        f"✅ 已开启每日自动签到（{hour}:00），结果会推送到当前会话。"
                    )
                elif mode == "off":
                    self.config["auto_checkin_enabled"] = False
                    self.config.save_config()
                    if getattr(self.scheduler, "running", False):
                        self.scheduler.shutdown(wait=False)
                    yield event.plain_result("已关闭每日自动签到。")
                else:
                    client = await self._ensure_client()
                    result = await asyncio.to_thread(client.checkin)
                    yield event.plain_result(f"✅ 签到结果：\n{self._fmt(result)}")
            elif action == "项目":
                client = await self._ensure_client()
                projects = await asyncio.to_thread(client.list_projects)
                if not projects:
                    yield event.plain_result("暂无项目。")
                else:
                    lines = ["📁 项目列表："]
                    for p in projects[:10]:
                        name = p.get("name") or p.get("repo_url") or p.get("id")
                        lines.append(f"  · {name}（{p.get('id')}）")
                    yield event.plain_result("\n".join(lines))
            elif action == "Git身份":
                client = await self._ensure_client()
                ids = await asyncio.to_thread(client.list_git_identities)
                lines = ["🔑 Git 身份："]
                if not ids:
                    lines.append("  （无）")
                for it in ids[:10]:
                    lines.append(
                        f"  · {it.get('username') or it.get('email') or it.get('id')} "
                        f"[{it.get('platform')}]"
                    )
                yield event.plain_result("\n".join(lines))
            elif action == "GitBots":
                client = await self._ensure_client()
                bots = await asyncio.to_thread(client.list_git_bots)
                lines = ["🤖 Git Bots："]
                if not bots:
                    lines.append("  （无）")
                for b in bots[:10]:
                    lines.append(
                        f"  · {b.get('name') or b.get('id')} [{b.get('platform')}]"
                    )
                yield event.plain_result("\n".join(lines))
            elif action == "文件":
                if len(args) < 2:
                    yield event.plain_result("用法：/mc 文件 <VM ID> [路径]")
                    return
                vm_id = args[1]
                path = args[2] if len(args) > 2 else "/root"
                client = await self._ensure_client()
                folders = await asyncio.to_thread(client.list_folders, vm_id, path)
                text = self._fmt(folders)
                yield event.plain_result(f"📁 {path} 下的内容：\n{text[:800]}")
            elif action == "日志":
                if len(args) < 2:
                    yield event.plain_result("用法：/mc 日志 <任务ID>")
                    return
                task_id = args[1]
                client = await self._ensure_client()
                task = await asyncio.to_thread(client.get_task, task_id)
                md = await asyncio.to_thread(
                    self._build_task_md, client, task_id, task
                )
                await self._send_markdown(
                    event.unified_msg_origin, f"mc-{self._safe_filename(task_id)}.md", md
                )
                yield event.plain_result(f"✅ 已发送任务 {task_id} 的日志文件。")
            elif action == "links":
                if len(args) < 2:
                    yield event.plain_result("用法：/mc links <任务ID>")
                    return
                task_id = args[1]
                client = await self._ensure_client()
                links = await asyncio.to_thread(client.list_task_links, task_id)
                if not links:
                    yield event.plain_result("该任务轮次中没有发现预览链接。")
                else:
                    lines = ["🔗 任务预览链接："]
                    for item in links[:20]:
                        status = item["status"] or "未检测"
                        code = item["http_code"]
                        code_str = f" HTTP {code}" if code else ""
                        lines.append(
                            f"  {status}{code_str}  {item['url']}（x{item['count']}）"
                        )
                    yield event.plain_result("\n".join(lines))
            elif action == "删除":
                if len(args) < 2:
                    yield event.plain_result("用法：/mc 删除 <任务ID>")
                    return
                task_id = args[1]
                client = await self._ensure_client()
                await asyncio.to_thread(client.delete_task, task_id)
                yield event.plain_result(f"已删除任务 {task_id}。")
            elif action == "技能":
                client = await self._ensure_client()
                skills = await asyncio.to_thread(client.list_skills)
                if not skills:
                    yield event.plain_result("暂无可用技能。")
                else:
                    lines = ["🛠 可用技能："]
                    for s in skills[:20]:
                        name = s.get("name") or s.get("id") or s.get("title") or str(s)
                        lines.append(f"  · {name}")
                    yield event.plain_result("\n".join(lines))
            elif action == "分支":
                if len(args) < 3:
                    yield event.plain_result("用法：/mc 分支 <Git身份ID> <owner/repo>")
                    return
                identity_id = args[1]
                repo_full = args[2]
                client = await self._ensure_client()
                branches = await asyncio.to_thread(
                    client.list_git_branches, identity_id, repo_full
                )
                lines = ["🌿 分支列表："]
                if not branches:
                    lines.append("  （无）")
                for b in branches[:20]:
                    name = b.get("name") or b.get("branch") or str(b)
                    lines.append(f"  · {name}")
                yield event.plain_result("\n".join(lines))
            elif action == "可用模型":
                client = await self._ensure_client()
                models = await asyncio.to_thread(client.list_available_models)
                lines = ["🤖 可用模型："]
                if not models:
                    lines.append("  （无）")
                for m in (models if isinstance(models, list) else [models])[:20]:
                    name = m.get("name") or m.get("model") or m.get("id") or str(m)
                    lines.append(f"  · {name}")
                yield event.plain_result("\n".join(lines))
            elif action == "Issue":
                if len(args) < 3:
                    yield event.plain_result("用法：/mc Issue <项目ID> <标题>")
                    return
                project_id = args[1]
                title = " ".join(args[2:]).strip()
                client = await self._ensure_client()
                issue = await asyncio.to_thread(
                    client.create_project_issue, project_id, title
                )
                yield event.plain_result(f"✅ 已创建 Issue：{self._fmt(issue)[:300]}")
            elif action == "评论":
                if len(args) < 4:
                    yield event.plain_result("用法：/mc 评论 <项目ID> <IssueID> <内容>")
                    return
                project_id, issue_id = args[1], args[2]
                comment = " ".join(args[3:]).strip()
                client = await self._ensure_client()
                result = await asyncio.to_thread(
                    client.add_issue_comment, project_id, issue_id, comment
                )
                yield event.plain_result(f"✅ 已评论：{self._fmt(result)[:300]}")
            elif action == "自动批准":
                if len(args) < 2:
                    yield event.plain_result("用法：/mc 自动批准 <任务ID>（开启）或 /mc 取消自动批准 <任务ID>")
                    return
                task_id = args[1]
                client = await self._ensure_client()
                async with client.open_task_stream(task_id, mode="attach") as stream:
                    await stream.send_auto_approve(True)
                yield event.plain_result(f"已开启任务 {task_id} 的自动批准。")
            elif action == "取消自动批准":
                if len(args) < 2:
                    yield event.plain_result("用法：/mc 取消自动批准 <任务ID>")
                    return
                task_id = args[1]
                client = await self._ensure_client()
                async with client.open_task_stream(task_id, mode="attach") as stream:
                    await stream.send_auto_approve(False)
                yield event.plain_result(f"已关闭任务 {task_id} 的自动批准。")
            elif action == "任务详情":
                if len(args) < 2:
                    yield event.plain_result("用法：/mc 任务详情 <任务ID>")
                    return
                task_id = args[1]
                client = await self._ensure_client()
                task = await asyncio.to_thread(client.get_task, task_id)
                t = task.raw if hasattr(task, "raw") else task
                lines = [
                    f"📋 任务 {task_id}",
                    f"状态：{t.get('status', '')}",
                    f"内容：{str(t.get('content') or '')[:200]}",
                ]
                if t.get("model"):
                    m = t["model"]
                    lines.append(f"模型：{m.get('model') or m.get('id')}")
                if t.get("repo_url"):
                    lines.append(f"仓库：{t.get('repo_url')}")
                if t.get("pr_url"):
                    lines.append(f"PR：{t.get('pr_url')}")
                yield event.plain_result("\n".join(lines))
            elif action == "用户输入":
                if len(args) < 2:
                    yield event.plain_result("用法：/mc 用户输入 <任务ID>")
                    return
                task_id = args[1]
                client = await self._ensure_client()
                data = await asyncio.to_thread(
                    client.get_task_user_inputs, task_id, limit=20
                )
                items = data.get("items", []) if isinstance(data, dict) else (data or [])
                if not items:
                    yield event.plain_result("该任务暂无用户输入记录。")
                else:
                    lines = ["💬 用户输入："]
                    for it in items[:10]:
                        content = str(it.get("content") or "")[:120]
                        lines.append(f"  · {content}")
                    yield event.plain_result("\n".join(lines))
            elif action == "交易记录":
                client = await self._ensure_client()
                data = await asyncio.to_thread(client.get_wallet_transactions)
                tx = data.get("transactions", []) if isinstance(data, dict) else (data or [])
                if not tx:
                    yield event.plain_result("暂无交易记录。")
                else:
                    lines = ["💳 最近交易："]
                    for it in tx[:10]:
                        amount = it.get("amount", "")
                        remark = str(it.get("remark") or it.get("kind") or "")[:80]
                        lines.append(f"  · {amount} {remark}")
                    yield event.plain_result("\n".join(lines))
            elif action == "文件下载":
                if len(args) < 4:
                    yield event.plain_result("用法：/mc 文件下载 <VMID> <路径> <文件名>")
                    return
                vm_id, path, filename = args[1], args[2], args[3]
                client = await self._ensure_client()
                data = await asyncio.to_thread(
                    client.download_file, vm_id, path, filename
                )
                import tempfile

                from astrbot.api.message_components import File as CompFile

                fname = os.path.basename(filename) or "file"
                tmp = os.path.join(tempfile.gettempdir(), fname)
                with open(tmp, "wb") as f:
                    f.write(data)
                chain = MessageChain().message(CompFile(file=tmp, name=fname))
                await self.context.send_message(event.unified_msg_origin, chain)
                yield event.plain_result(f"✅ 已发送文件 {filename}。")
            elif action == "换模型":
                if len(args) < 2:
                    yield event.plain_result("用法：/mc 换模型 <任务ID> <模型ID>")
                    return
                task_id, model_id = args[1], args[2]
                client = await self._ensure_client()
                res = await client.switch_task_model(task_id, model_id, timeout=30)
                ok = res.get("success") if isinstance(res, dict) else False
                msg = (
                    res.get("message") or res.get("error")
                    if isinstance(res, dict)
                    else str(res)
                )
                yield event.plain_result(
                    f"{'✅ 已切换模型' if ok else '❌ 切换模型失败'}：{msg}"
                )
            elif action == "重启":
                if len(args) < 2:
                    yield event.plain_result("用法：/mc 重启 <任务ID>")
                    return
                task_id = args[1]
                client = await self._ensure_client()
                res = await client.restart_task(task_id, load_session=True, timeout=30)
                ok = res.get("success") if isinstance(res, dict) else False
                msg = (
                    res.get("message") or res.get("error")
                    if isinstance(res, dict)
                    else str(res)
                )
                yield event.plain_result(
                    f"{'✅ 已重启任务' if ok else '❌ 重启失败'}：{msg}"
                )
            else:
                yield event.plain_result(self._help_text())
        except Exception as e:
            yield event.plain_result(f"❌ {e}")

    async def _format_env(self) -> str:
        client = await self._ensure_client()
        hosts = await asyncio.to_thread(client.list_hosts)
        images = await asyncio.to_thread(client.list_images)
        models = await asyncio.to_thread(client.list_models)
        lines = [
            f"🏠 宿主：{len(hosts)} 个",
            f"🖼 镜像：{len(images)} 个",
            f"🤖 模型：{len(models)} 个",
        ]
        if models:
            lines.append("模型示例：")
            for m in models[:5]:
                lines.append(f"  · {m.get('name') or m.get('model') or m.get('id')}")
        return "\n".join(lines)

    async def _format_tasks(self) -> str:
        client = await self._ensure_client()
        data = await asyncio.to_thread(client.list_tasks, size=5)
        tasks = data.get("tasks") if isinstance(data, dict) else data or []
        if not tasks:
            return "暂无任务记录。"
        lines = ["📋 最近任务："]
        for t in tasks:
            status = t.get("status", "")
            title = t.get("title") or t.get("content") or t.get("id", "")
            lines.append(f"  · [{status}] {title}（{t.get('id')}）")
        return "\n".join(lines)

    @staticmethod
    def _help_text() -> str:
        return (
            "🐒 MonkeyCode 编程助手\n"
            "/mc 帮助            查看帮助\n"
            "/mc 环境            列出云端环境/镜像/模型\n"
            "/mc 任务 <内容>      提交编程任务（后台执行，完成后通知）\n"
            "/mc 回复 <任务ID> <内容>  向运行中的任务发送消息，让 agent 继续执行\n"
            "/mc 任务列表         最近任务\n"
            "/mc 停止 <任务ID>    停止任务\n"
            "/mc 钱包 / 签到       查询积分、每日签到\n"
            "/mc 项目             项目列表\n"
            "/mc Git身份           Git 身份列表\n"
            "/mc GitBots         Git Bots 列表\n"
            "/mc 文件 <VMID> [路径] 查看虚拟机目录\n"
            "/mc 日志 <任务ID>    导出任务日志为 md 文件\n"
            "/mc links <任务ID>  列出任务中的预览链接及存活状态\n"
            "/mc 删除 <任务ID>  删除任务\n"
            "/mc 技能           列出可用技能\n"
            "/mc 分支 <GitID> <owner/repo>  查看仓库分支\n"
            "/mc 可用模型        列出可用模型\n"
            "/mc Issue <项目ID> <标题>  创建 Issue\n"
            "/mc 评论 <项目ID> <IssueID> <内容>  评论 Issue\n"
            "/mc 自动批准 <任务ID> / 取消自动批准 <任务ID>\n"
            "/mc 任务详情 <任务ID>      查看任务状态/内容/模型\n"
            "/mc 用户输入 <任务ID>      查看 agent 等待的用户输入\n"
            "/mc 换模型 <任务ID> <模型ID>  切换运行中任务模型\n"
            "/mc 重启 <任务ID>          重启任务\n"
            "/mc 交易记录              积分流水\n"
            "/mc 文件下载 <VMID> <路径> <文件名>  下载任务产物文件\n"
            "/mc 签到 on [小时] / off   开启/关闭每日自动签到\n\n"
            "也可直接对我说：用 MonkeyCode 帮我 <任务描述>"
        )

    @staticmethod
    def _fmt(obj: Any) -> str:
        """把响应格式化为可读文本。"""
        if isinstance(obj, (dict, list)):
            return json.dumps(obj, ensure_ascii=False, indent=2, default=str)[:1000]
        return str(obj)

    @staticmethod
    def _safe_filename(task_id: str) -> str:
        """把任务 ID 消毒为安全文件名（只保留字母数字/连字符/下划线）。"""
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", str(task_id))[:16] or "task"
        return safe

    # ---------- LLM 工具 ----------

    @filter.llm_tool(name="use_monkeycode")
    async def tool_monkeycode(self, event: AstrMessageEvent, task_description: str):
        """提交一个 MonkeyCode AI 编程任务（读取仓库、改代码、跑命令、提 PR）。

        Args:
            task_description(string): 交给 MonkeyCode 完成的编程任务描述
        """
        try:
            task_id = await self._submit_and_watch(
                task_description, event.unified_msg_origin
            )
            yield event.plain_result(
                f"已通过 MonkeyCode 提交编程任务，任务ID：{task_id}。"
                "任务完成后会推送结果。"
            )
        except Exception as e:
            yield event.plain_result(f"MonkeyCode 任务提交失败：{e}")

    @filter.llm_tool(name="monkeycode_reply")
    async def tool_monkeycode_reply(
        self, event: AstrMessageEvent, task_id: str, content: str
    ):
        """向运行中的 MonkeyCode 任务发送一条用户消息，让 agent 继续执行。

        Args:
            task_id(string): MonkeyCode 任务 ID
            content(string): 要发送给 agent 的消息内容
        """
        try:
            client = await self._ensure_client()
            # SDK 的 send_task_message 是原生 async（websockets），直接 await 即可
            events = await client.send_task_message(task_id, content, read_timeout=60)
            types = [e.type for e in events]
            yield event.plain_result(
                f"已向任务 {task_id} 发送消息，收到事件：{', '.join(types[:5])}。"
            )
        except Exception as e:
            yield event.plain_result(f"MonkeyCode 回复失败：{e}")

    async def terminate(self):
        if getattr(self.scheduler, "running", False):
            self.scheduler.shutdown(wait=False)
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None