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
import re
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register

from monkeycode import MonkeyCodeClient
from monkeycode.models import RepoReq

PLUGIN_NAME = "astrbot_plugin_monkeycode"


@register(
    "astrbot_plugin_monkeycode",
    "cyqmq",
    "MonkeyCode 编程助手（基于 monkeycode-sdk）",
    "1.0.0",
)
class MonkeyCodePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._client: MonkeyCodeClient | None = None
        self._login_lock = asyncio.Lock()

    # ---------- 配置 ----------

    def _cfg(self, key: str, default=None):
        try:
            return self.config.get(key, default)
        except Exception:
            return default

    # ---------- 客户端懒登录 ----------

    async def _ensure_client(self) -> MonkeyCodeClient:
        """获取已登录的 SDK 客户端（懒登录 + 缓存）。"""
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
            client = MonkeyCodeClient(email=email, password=password, base_url=base_url)
            await asyncio.to_thread(client.login)
            self._client = client
            logger.info(f"[{PLUGIN_NAME}] 登录成功（{base_url}）")
            return client

    async def _send(self, origin: str, text: str) -> None:
        try:
            await self.context.send_message(origin, MessageChain().message(text))
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 消息发送失败: {e}")

    @staticmethod
    def _args(event: AstrMessageEvent, cmd: str) -> list[str]:
        """取指令参数，过滤平台附加标记（如 [MSG_ID:xxx]）。"""
        text = (event.message_str or "").strip().lstrip("/").strip()
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
        try:
            task = await asyncio.to_thread(
                client.create_task,
                content=content,
                repo=repo,
                skill_ids=skill_ids,
            )
        except Exception as e:
            raise RuntimeError(f"创建任务失败：{e}") from e

        asyncio.create_task(self._watch_task(task.id, origin))
        return task.id

    async def _watch_task(self, task_id: str, origin: str) -> None:
        try:
            client = await self._ensure_client()
            result = await asyncio.to_thread(
                client.wait_task, task_id, timeout=3600, interval=15
            )
            text = (
                f"⚡ MonkeyCode 任务完成\n"
                f"任务ID：{task_id}\n状态：{result.status}"
            )
            if result.repo_url:
                text += f"\n仓库：{result.repo_url}"
            if result.branch:
                text += f"\n分支：{result.branch}"
            if result.pr_url:
                text += f"\nPR：{result.pr_url}"
            if result.summary:
                text += f"\n摘要：{result.summary}"
            await self._send(origin, text)
        except Exception as e:
            await self._send(origin, f"❌ MonkeyCode 任务 {task_id} 失败：{e}")

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
                events = await client.send_task_message(
                    task_id, content, read_timeout=60
                )
                types = [e.type for e in events]
                summary = "\n".join(f"  · {t}" for t in types[:8])
                yield event.plain_result(
                    f"✅ 已向任务 {task_id} 发送消息。\n收到事件：\n{summary}"
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
            "/mc 停止 <任务ID>    停止任务\n\n"
            "也可直接对我说：用 MonkeyCode 帮我 <任务描述>"
        )

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
            events = await client.send_task_message(task_id, content, read_timeout=60)
            types = [e.type for e in events]
            yield event.plain_result(
                f"已向任务 {task_id} 发送消息，收到事件：{', '.join(types[:5])}。"
            )
        except Exception as e:
            yield event.plain_result(f"MonkeyCode 回复失败：{e}")

    async def terminate(self):
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None