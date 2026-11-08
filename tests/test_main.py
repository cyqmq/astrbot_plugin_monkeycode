"""main.py 纯逻辑单元测试（不依赖真实 AstrBot，SDK 需已安装）。"""
import json

import pytest

from tests.conftest import FakeConfig, FakeEvent, load_main_module

main = load_main_module()
Plugin = main.MonkeyCodePlugin


@pytest.fixture
def plugin():
    p = Plugin.__new__(Plugin)
    p.config = FakeConfig()
    p._use_settings = {}
    return p


# ---------- _args ----------
def test_args_basic(plugin):
    ev = FakeEvent("/mc 任务 修复登录接口")
    assert plugin._args(ev, "mc") == ["任务", "修复登录接口"]


def test_args_no_slash(plugin):
    ev = FakeEvent("mc 环境")
    assert plugin._args(ev, "mc") == ["环境"]


def test_args_strip_platform_meta(plugin):
    ev = FakeEvent("[MSG_ID:123] /mc 任务 修复")
    assert plugin._args(ev, "mc") == ["任务", "修复"]


def test_args_empty(plugin):
    assert plugin._args(FakeEvent("/mc"), "mc") == []


# ---------- _desensitize ----------
def test_desensitize_github_pat(plugin):
    text = plugin._desensitize("token is github_pat_ABCDEFGHIJKLMNOPQRST123456")
    assert "github_pat_***" in text and "ABCDEFGHIJKLMNOPQRST" not in text


def test_desensitize_sk_key(plugin):
    text = plugin._desensitize("key=sk-abcdefghijklmnop")
    assert "sk-***" in text


def test_desensitize_key_value(plugin):
    text = plugin._desensitize("password=secret123")
    assert "password=***" in text


def test_desensitize_disabled(plugin):
    plugin.config["desensitize_enabled"] = False
    text = plugin._desensitize("github_pat_ABCDEFGHIJKLMNOPQRST123456")
    assert "github_pat_ABCDEFGHIJKLMNOPQRST" in text


def test_desensitize_empty(plugin):
    assert plugin._desensitize("") == ""


# ---------- 使用白名单 ----------
def test_can_use_no_whitelist_any_user(plugin):
    assert plugin._can_use_command(FakeEvent(sender_id="u1"))


def test_can_use_whitelisted(plugin):
    plugin.config["command_whitelist"] = "10001,10002"
    assert plugin._can_use_command(FakeEvent(sender_id="10001"))


def test_can_use_denied(plugin):
    plugin.config["command_whitelist"] = "10001"
    assert not plugin._can_use_command(FakeEvent(sender_id="9999"))


def test_can_use_admin_override(plugin):
    plugin.config["command_whitelist"] = "10001"
    assert plugin._can_use_command(FakeEvent(sender_id="9999", is_admin=True))


def test_can_use_session_disabled(plugin):
    plugin._use_settings["aiocqhttp:GroupMessage:1"] = {"enabled": False}
    assert not plugin._can_use_command(FakeEvent())


def test_can_use_session_enabled_override(plugin):
    plugin._use_settings["aiocqhttp:GroupMessage:1"] = {"enabled": False}
    # 即便全局白名单放行，会话禁用仍生效
    assert not plugin._can_use_command(FakeEvent(sender_id="10001"))


# ---------- 控制权限 ----------
def test_can_control_empty_whitelist(plugin):
    assert plugin._can_control_use(FakeEvent(sender_id="u1"))


def test_can_control_whitelisted(plugin):
    plugin.config["command_control_whitelist"] = "10001"
    assert plugin._can_control_use(FakeEvent(sender_id="10001"))


def test_can_control_denied(plugin):
    plugin.config["command_control_whitelist"] = "10001"
    assert not plugin._can_control_use(FakeEvent(sender_id="9999"))


# ---------- 会话级启用/禁用持久化 ----------
def test_set_session_use_persist(monkeypatch, tmp_path, plugin):
    monkeypatch.setattr(plugin, "_use_settings_path", lambda: str(tmp_path / "u.json"))
    plugin._set_session_use("aiocqhttp:GroupMessage:1", False)
    assert plugin._use_settings["aiocqhttp:GroupMessage:1"]["enabled"] is False
    data = json.loads((tmp_path / "u.json").read_text())
    assert data["aiocqhttp:GroupMessage:1"]["enabled"] is False


def test_session_use_enabled_default(plugin):
    assert plugin._session_use_enabled("aiocqhttp:GroupMessage:9")
