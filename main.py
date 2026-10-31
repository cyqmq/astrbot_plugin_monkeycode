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
from monkeycode.models import RepoReq, group_models

PLUGIN_NAME = "astrbot_plugin_monkeycode"


def _b64decode(s: str) -> str:
    """尝试 base64 解码为 UTF-8 文本；失败则原样返回。

    多行日志中的 base64 可能包含换行符，先去掉空白再解码。
    """
    raw = re.sub(r"\s+", "", s)
    raw = raw.replace("-", "+").replace("_", "/")
    pad = "=" * ((4 - len(raw) % 4) % 4)
    try:
        return base64.b64decode(raw + pad).decode("utf-8", errors="replace")
    except Exception:
        return s


_SENSITIVE_RE = re.compile(
    r"api[_-]?key|apikey|access[_-]?key|secret|password|passwd|token"
    r"|authorization|cookie|env|credential|\bkey\b",
    re.IGNORECASE,
)


def _redact_sensitive(value: Any) -> Any:
    """递归脱敏：密钥类字段（api_key/token/secret/password/env 等）值替换为 ***。

    字符串值如果是 JSON 文本（如 config_files.content），会先解析再递归脱敏。
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            kl = str(k).lower()
            if _SENSITIVE_RE.search(kl) and v not in (None, ""):
                if kl == "envs" and isinstance(v, dict):
                    out[k] = {"***": "***"}
                else:
                    out[k] = "***"
            else:
                out[k] = _redact_sensitive(v)
        return out
    if isinstance(value, list):
        return [_redact_sensitive(v) for v in value]
    if isinstance(value, str):
        stripped = value.lstrip()
        if stripped and stripped[0] in ("{", "["):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, (dict, list)):
                    return json.dumps(_redact_sensitive(parsed), ensure_ascii=False)
            except (json.JSONDecodeError, ValueError):
                pass
        return value
    return value


try:
    from monkeycode.stream import format_round_text as _sdk_format_round_text
except ImportError:
    _sdk_format_round_text = None


@register(
    "astrbot_plugin_monkeycode",
    "cyqmq",
    "MonkeyCode 编程助手（基于 monkeycode-sdk）",
    "2.0.8",
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
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/options",
            self.view_get_options,
            ["GET"],
            "获取宿主/镜像/模型选项",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/dashboard",
            self.view_dashboard,
            ["GET"],
            "获取账户/额度/运行中任务概览",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/task/<task_id>",
            self.view_task_detail,
            ["GET"],
            "获取任务详情与会话轮次",
        )

    async def view_get_options(self):
        """返回当前账号可用的宿主/镜像/模型列表（供视图下拉框）。"""
        try:
            client = await self._ensure_client()
            hosts = await asyncio.to_thread(client.list_hosts)
            images = await asyncio.to_thread(client.list_images)
            models = await asyncio.to_thread(client.list_models)
            return json_response(
                {
                    "hosts": [self._normalize_host(h) for h in (hosts or [])],
                    "images": images or [],
                    "models": self._tag_model_groups(models or []),
                }
            )
        except Exception as e:
            return error_response(f"获取选项失败：{e}", status_code=500)

    @staticmethod
    def _tag_model_groups(models: list[dict]) -> list[dict]:
        """按页面分类给模型标注 _group（我的/基础/专业/旗舰/其他）。"""
        groups = group_models(models)
        names = {
            "private": "我的模型",
            "basic": "基础模型",
            "pro": "专业模型",
            "ultra": "旗舰模型",
            "other": "其他",
        }
        for key, label in names.items():
            for m in groups.get(key, []):
                m["_group"] = label
        return models

    @staticmethod
    def _normalize_host(h: dict) -> dict:
        """把平台宿主字段统一为后台下拉所需结构（状态/核心/内存/说明/自建公共）。"""
        memory = h.get("memory") or h.get("memory_size") or h.get("mem") or ""
        is_public = bool(
            h.get("is_public")
            or h.get("is_shared")
            or h.get("public")
            or str(h.get("type") or "").lower() == "public"
        )
        return {
            "id": str(h.get("id") or h.get("host_id") or ""),
            "name": str(h.get("name") or h.get("hostname") or ""),
            "status": str(h.get("status") or ""),
            "cpu": str(h.get("cpu") or h.get("cpu_core") or h.get("cores") or ""),
            "memory": memory,
            "remark": str(
                h.get("remark") or h.get("description") or h.get("note") or ""
            ),
            "is_public": is_public,
        }

    async def view_dashboard(self):
        """返回后台概览：账户详情、额度、运行中任务。"""
        try:
            client = await self._ensure_client()
            whoami = await asyncio.to_thread(client.whoami)
            wallet = await asyncio.to_thread(client.get_wallet)
            subscription = await asyncio.to_thread(client.get_subscription)
            user = self._extract_user(whoami)
            sub = subscription
            if isinstance(subscription, dict):
                sub = (
                    subscription.get("subscription")
                    or subscription.get("data")
                    or subscription
                )

            # 显式查询运行中任务（平台状态含 pending/processing/running）
            running_data = await asyncio.to_thread(
                client.list_tasks, size=20, status="pending,processing,running"
            )
            running = self._extract_task_list(running_data)

            # 最近任务
            recent_data = await asyncio.to_thread(client.list_tasks, size=10)
            recent = self._extract_task_list(recent_data)

            # 兜底：若 running 为空但 recent 存在非终态任务，补入展示
            if not running:
                terminal = {
                    "completed",
                    "success",
                    "error",
                    "failed",
                    "terminated",
                    "stopped",
                    "canceled",
                }
                running = [
                    t
                    for t in recent
                    if str(t.get("status") or "").lower() not in terminal
                ]

            return json_response(
                {
                    "user": user,
                    "wallet": wallet,
                    "subscription": sub,
                    "running_tasks": running,
                    "recent_tasks": (recent or [])[:10],
                }
            )
        except Exception as e:
            return error_response(f"获取概览失败：{e}", status_code=500)

    @staticmethod
    def _extract_user(data: Any) -> dict[str, Any]:
        """从 whoami 返回结构中兼容提取用户信息。"""
        if isinstance(data, dict):
            return data.get("user") or data.get("data") or data
        return data or {}

    @staticmethod
    def _extract_task_list(data: Any) -> list[dict[str, Any]]:
        """从 list_tasks 返回结构中兼容提取任务列表。"""
        if isinstance(data, dict):
            return (
                data.get("tasks")
                or data.get("list")
                or data.get("items")
                or []
            )
        return data or []

    async def view_task_detail(self, task_id: str):
        """返回任务详情与会话轮次（后台会话详情）。"""
        try:
            client = await self._ensure_client()
            task = await asyncio.to_thread(client.get_task, task_id)
            rounds = await asyncio.to_thread(
                client.get_task_rounds, task_id, limit=20
            )
            raw = task.raw if hasattr(task, "raw") else task
            return json_response({"task": raw, "rounds": rounds})
        except Exception as e:
            return error_response(f"获取任务详情失败：{e}", status_code=500)

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
            "session_path",
            "notify_on_task_end",
            "task_summary_length",
            "md_log_max_rounds",
            "reply_read_timeout",
            "max_concurrent_tasks",
            "desensitize_enabled",
            "auto_switch_model",
            "fallback_model_ids",
            "low_balance_threshold",
        ]
        # 阈值单位迁移：旧版本存的是原始值（1000 原始=1 点），
        # 若配置值 >= 1000，视为旧原始值，一次性迁移为新默认 100 点。
        threshold = int(self._cfg("low_balance_threshold", 100) or 100)
        if threshold >= 1000:
            threshold = 100
            self.config["low_balance_threshold"] = threshold
            self.config.save_config()
        data = {k: self._cfg(k, "") for k in keys}
        data["low_balance_threshold"] = threshold
        return json_response(data)

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
            "session_path",
            "notify_on_task_end",
            "task_summary_length",
            "md_log_max_rounds",
            "reply_read_timeout",
            "max_concurrent_tasks",
            "desensitize_enabled",
            "auto_switch_model",
            "fallback_model_ids",
            "low_balance_threshold",
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
            await self._send(origin, f"✅ 每日签到完成：{self._format_checkin(result)}")
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

    # ---------- 权限控制 ----------

    def _admin_only_actions(self) -> set[str]:
        """返回仅主人/管理员可用的命令集合。"""
        raw = str(self._cfg("admin_only_commands", "") or "").strip()
        if not raw:
            return set()
        return {s.strip() for s in raw.split(",") if s.strip()}

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
        max_tasks = int(self._cfg("max_concurrent_tasks", 0) or 0)
        if max_tasks > 0:
            data = await asyncio.to_thread(
                client.list_tasks, status="pending,processing"
            )
            running = data.get("tasks") if isinstance(data, dict) else (data or [])
            if len(running or []) >= max_tasks:
                raise RuntimeError(
                    f"并发任务数已达上限（{max_tasks}），请稍后再试。"
                )
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
            await self._maybe_auto_switch(client, task_id, result)
            summary = await self._summarize(result)
            if self._cfg("notify_on_task_end", True):
                summary_len = int(self._cfg("task_summary_length", 200) or 200)
                text = (
                    f"⚡ MonkeyCode 任务完成\n"
                    f"任务ID：{task_id}\n状态：{result.status}"
                )
                if result.pr_url:
                    text += f"\nPR：{result.pr_url}"
                if summary:
                    text += f"\n摘要：{summary[:summary_len]}"
                if self._cfg("send_md_on_end", True):
                    text += "\n完整日志已发送为 md 文件。"
                await self._send(origin, text)
            if self._cfg("send_md_on_end", True):
                md = await asyncio.to_thread(self._build_task_md, client, task_id, result)
                await self._send_markdown(origin, f"mc-{self._safe_filename(task_id)}.md", md)
        except Exception as e:
            await self._send(origin, f"❌ MonkeyCode 任务 {task_id} 失败：{e}")

    async def _maybe_auto_switch(
        self, client: Any, task_id: str, result: Any
    ) -> None:
        """任务失败且开启自动切换时，用备用模型切换并重启任务。"""
        status = getattr(result, "status", "")
        if status not in ("error", "failed", "task-error"):
            return
        if not self._cfg("auto_switch_model", False):
            return
        fallback = [
            m.strip()
            for m in str(self._cfg("fallback_model_ids", "") or "").split(",")
            if m.strip()
        ]
        if not fallback:
            return
        model_id = fallback[0]
        try:
            await client.switch_task_model(
                task_id, model_id, load_session=True, timeout=30
            )
            await client.restart_task(task_id, load_session=True, timeout=30)
            logger.info(
                f"[{PLUGIN_NAME}] 任务 {task_id} 失败，已自动切换模型 {model_id} 并重启"
            )
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 自动切换模型失败: {e}")

    async def _summarize(self, result: Any) -> str:
        """生成简短摘要。

        - 每次摘要都是**独立调用**：小模型上下文只包含「人格指令 + 本次任务内容」，
          不保留任何多轮对话历史。
        - summary_enabled=False 或未配置小模型时，返回平台原始 summary（零 token）；
        - 开启且配置了 summary_provider_id 时，调用指定小模型生成摘要（不碰主模型）。
        """
        if not self._cfg("summary_enabled", False):
            return self._desensitize(str(getattr(result, "summary", "") or ""))
        provider_id = str(self._cfg("summary_provider_id", "") or "").strip()
        if not provider_id:
            return self._desensitize(str(getattr(result, "summary", "") or ""))
        prompt = str(self._cfg("summary_prompt", "") or "")
        # 无历史上下文，可放心喂完整任务内容；仅保留高上限防止小模型上下文溢出
        content = self._desensitize(
            str(getattr(result, "content", "") or "")[:8000]
        )
        try:
            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=(prompt + "\n\n" + content if content else prompt),
            )
            text = getattr(llm_resp, "completion_text", "") or ""
            return self._desensitize(str(text).strip()[:500])
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 小模型摘要失败: {e}")
            return str(getattr(result, "summary", "") or "")

    @staticmethod
    def _desensitize(self, text: str) -> str:
        """对文本中的敏感凭据做脱敏（API Key / PAT / token / 私钥等）。"""
        if not self._cfg("desensitize_enabled", True):
            return text
        if not text:
            return text
        patterns = [
            # GitHub fine-grained PAT
            (r"github_pat_[A-Za-z0-9_]{16,}", "github_pat_***"),
            # GitHub classic tokens
            (r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{16,}", r"\1_***"),
            # OpenAI 风格 API Key
            (r"\bsk-[A-Za-z0-9_-]{12,}", "sk-***"),
            # AWS Access Key
            (r"\bAKIA[0-9A-Z]{16}\b", "AKIA***"),
            # Bearer token
            (r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{16,}", r"\1***"),
            # 通用键值对凭据
            (
                r"(?i)((?:api[_-]?key|apikey|access[_-]?token|auth[_-]?token|"
                r"secret|password|passwd|client[_-]?secret)\s*[=:]\s*)"
                r"[^\s,;\"'<>]+",
                r"\1***",
            ),
            # 私钥块
            (
                r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?"
                r"-----END [A-Z ]*PRIVATE KEY-----",
                "-----BEGIN PRIVATE KEY-----***-----END PRIVATE KEY-----",
            ),
        ]
        for pattern, repl in patterns:
            text = re.sub(pattern, repl, text, flags=re.DOTALL | re.IGNORECASE)
        return text

    @staticmethod
    def _chunk_text(data: Any) -> str:
        """把任务轮次 chunk 的 data 字段转为可读文本。

        兼容协议：
        - data 可能是普通文本或 base64(JSON)
        - user-input 的 content 是第二层 base64，需再解一次
        - task-running 等事件含 OpenCode ACP 载荷（sessionUpdate），
          按 available_commands_update / agent_message / tool_call 分类精简
        """
        if _sdk_format_round_text is not None:
            return _sdk_format_round_text(data)
        if isinstance(data, dict):
            obj = data
        elif not isinstance(data, str):
            return json.dumps(data, ensure_ascii=False)
        else:
            decoded = _b64decode(data)
            try:
                parsed = json.loads(decoded)
            except (json.JSONDecodeError, ValueError):
                return decoded if decoded != data else data
            if not isinstance(parsed, dict):
                return decoded if decoded != data else data
            obj = parsed

        # user-input：content 是第二层 base64（用户原始文本）
        content = obj.get("content")
        if isinstance(content, str):
            inner = _b64decode(content)
            if inner != content:
                return inner

        # OpenCode ACP 事件：按 sessionUpdate 分类
        update = obj.get("update") if isinstance(obj.get("update"), dict) else {}
        session_update = (
            obj.get("sessionUpdate") or update.get("sessionUpdate") or ""
        )
        if session_update:
            if session_update == "available_commands_update":
                cmds = update.get("availableCommands") or []
                names = [
                    c.get("name")
                    for c in cmds
                    if isinstance(c, dict) and c.get("name")
                ][:10]
                return (
                    "、".join(names)
                    if names
                    else f"共 {len(cmds)} 项"
                )
            if session_update in ("agent_message", "agent_message_chunk"):
                msg = update.get("message") or update.get("content")
                if isinstance(msg, dict):
                    msg = msg.get("text") or msg
                return str(msg) if msg is not None else ""
            if session_update == "agent_thought_chunk":
                thought = update.get("thought") or update.get("content")
                if isinstance(thought, dict):
                    thought = thought.get("text") or thought
                return str(thought)[:300] if thought else "（思考中）"
            if session_update == "usage_update":
                usage = update.get("usage") or {}
                if isinstance(usage, dict):
                    total = (
                        usage.get("totalTokens")
                        or usage.get("total_tokens")
                        or usage.get("total")
                        or ""
                    )
                    if total:
                        return f"用量：{total}"
                return "用量更新"
            if session_update in ("tool_call", "tool_call_update"):
                title = update.get("title") or update.get("kind") or ""
                status = update.get("status") or ""
                extra = " ".join(str(x) for x in (title, status) if x)
                return extra or json.dumps(
                    _redact_sensitive(update), ensure_ascii=False
                )[:300]
            if session_update in ("call", "call-response"):
                title = update.get("title") or update.get("kind") or ""
                status = update.get("status") or ""
                extra = " ".join(str(x) for x in (title, status) if x)
                if extra:
                    return extra
                return json.dumps(
                    _redact_sensitive(update), ensure_ascii=False
                )[:300]
            return (
                f"{session_update} "
                f"{json.dumps(_redact_sensitive(update or obj), ensure_ascii=False)[:300]}"
            )

        # 其他事件：优先取 content/message/text 字段
        for key in ("content", "message", "text"):
            v = obj.get(key)
            if isinstance(v, str) and v:
                return v
        return json.dumps(_redact_sensitive(obj), ensure_ascii=False)[:300]

    def _build_task_md(self, client: Any, task_id: str, result: Any) -> str:
        """把任务详情与执行轮次整理成 Markdown 文本。"""
        lines = [
            f"# MonkeyCode 任务 {task_id}",
            "",
            f"- 状态：{result.status}",
            f"- 仓库：{result.repo_url or '（未绑定）'}",
            f"- 分支：{result.branch or '-'}",
            f"- PR：{result.pr_url or '无'}",
            f"- 摘要：{self._desensitize(str(result.summary or '')) or '无'}",
        ]
        if result.content:
            lines += ["", "## 任务内容", "", self._desensitize(str(result.content))]
        try:
            rounds = client.get_task_rounds(
                task_id, limit=int(self._cfg("md_log_max_rounds", 10) or 10)
            )
            chunks = (
                rounds.get("chunks", [])
                if isinstance(rounds, dict)
                else (rounds or [])
            )
            lines += ["", "## 执行轮次", ""]
            for c in chunks:
                event = c.get("event") or c.get("kind") or "agent"
                text = self._desensitize(self._chunk_text(c.get("data", "")))[:600]
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
        admin_only = self._admin_only_actions()
        if action in admin_only and not event.is_admin():
            yield event.plain_result("该功能仅主人/管理员可用。")
            return
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
                    task_id,
                    content,
                    read_timeout=int(self._cfg("reply_read_timeout", 60) or 60),
                )
                types = [e.type for e in events]
                summary = "\n".join(f"  · {t}" for t in types[:8])
                yield event.plain_result(
                    f"✅ 已向任务 {task_id} 发送消息。\n收到事件：\n{summary}"
                )
            elif action == "钱包":
                client = await self._ensure_client()
                wallet = await asyncio.to_thread(client.get_wallet)
                yield event.plain_result(self._format_wallet(wallet))
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
                    yield event.plain_result(f"✅ 签到结果：{self._format_checkin(result)}")
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
                text = self._format_folders(folders)
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
                yield event.plain_result(f"✅ 已创建 Issue：{self._format_issue(issue)}")
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
                yield event.plain_result(f"✅ 已评论：{self._format_comment(result)}")
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
                    f"内容：{self._desensitize(str(t.get('content') or ''))[:200]}",
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
                        content = self._desensitize(str(it.get("content") or ""))[:120]
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
            lines.append(
                f"  · [{status}] {self._desensitize(str(title))}（{t.get('id')}）"
            )
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
    def _to_points(value: Any) -> str:
        """把平台原始数值换算为「点」（1000 原始值 = 1 点）。"""
        try:
            points = int(value) / 1000
            return f"{points:g} 点"
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _format_wallet(wallet: Any) -> str:
        """把钱包信息格式化为可读文本（去掉空 id / 无用字段）。"""
        if not isinstance(wallet, dict):
            return str(wallet)
        balance = wallet.get("balance")
        daily_balance = wallet.get("daily_token_balance")
        daily_limit = wallet.get("daily_token_limit")
        lines = ["💰 钱包信息"]
        if balance is not None:
            lines.append(f"· 余额：{MonkeyCodePlugin._to_points(balance)}")
        if daily_balance is not None:
            if daily_limit is not None:
                lines.append(f"· 每日 Token：{daily_balance} / {daily_limit}")
            else:
                lines.append(f"· 每日 Token 余额：{daily_balance}")
        return "\n".join(lines)

    @staticmethod
    def _format_checkin(result: Any) -> str:
        """把签到结果格式化为可读文本。"""
        if isinstance(result, dict):
            parts = []
            for k in ("amount", "points", "balance", "integral"):
                v = result.get(k)
                if v is not None:
                    parts.append(f"积分：{MonkeyCodePlugin._to_points(v)}")
            msg = result.get("message") or result.get("msg")
            if msg:
                parts.append(str(msg))
            if parts:
                return "；".join(parts)
        return str(result)

    @staticmethod
    def _format_folders(folders: Any) -> str:
        """把目录/文件列表格式化为可读文本。"""
        items = folders if isinstance(folders, list) else (folders or [])
        if not items:
            return "（空）"
        lines = []
        for it in items[:50]:
            if not isinstance(it, dict):
                lines.append(str(it))
                continue
            name = (
                it.get("name")
                or it.get("filename")
                or it.get("path")
                or it.get("id")
            )
            is_dir = it.get("is_dir") or it.get("type") in (
                "dir",
                "directory",
                "folder",
            )
            prefix = "📁 " if is_dir else "📄 "
            lines.append(f"{prefix}{name}")
        return "\n".join(lines)

    @staticmethod
    def _format_issue(issue: Any) -> str:
        """把 Issue 创建结果格式化为可读文本。"""
        if isinstance(issue, dict):
            iid = issue.get("id") or issue.get("number") or issue.get("issue_id")
            title = issue.get("title")
            parts = []
            if iid:
                parts.append(f"Issue #{iid}")
            if title:
                parts.append(str(title))
            if parts:
                return " ".join(parts)
        return str(issue)

    @staticmethod
    def _format_comment(result: Any) -> str:
        """把评论结果格式化为可读文本。"""
        if isinstance(result, dict):
            cid = result.get("id") or result.get("comment_id")
            if cid:
                return f"评论 #{cid} 已创建"
            msg = result.get("message") or result.get("msg")
            if msg:
                return str(msg)
            if result.get("success") is False:
                return "评论失败"
            return "已评论"
        return str(result)

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
            events = await client.send_task_message(
                    task_id,
                    content,
                    read_timeout=int(self._cfg("reply_read_timeout", 60) or 60),
                )
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