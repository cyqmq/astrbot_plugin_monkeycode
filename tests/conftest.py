"""测试夹具：注入最小化 astrbot 假模块，使 main.py 可在无 AstrBot 环境下导入。"""
import importlib
import sys
import types


class FakeLogger:
    def info(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def debug(self, *a, **k):
        pass

    def addHandler(self, *a, **k):
        pass

    handlers = []


class FakeConfig(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)

    def save_config(self):
        pass


class FakeEvent:
    """模拟 AstrMessageEvent。"""

    def __init__(self, message_str="", origin="aiocqhttp:GroupMessage:1",
                 sender_id="u1", is_admin=False):
        self.message_str = message_str
        self.unified_msg_origin = origin
        self._sender_id = sender_id
        self._admin = is_admin

    def get_sender_id(self):
        return self._sender_id

    def is_admin(self):
        return self._admin

    def plain_result(self, text):
        return text


class FakeMessageChain:
    @staticmethod
    def message(text):
        return text


class _Filter:
    def command(self, name, **kw):
        return lambda f: f

    def llm_tool(self, name, **kw):
        return lambda f: f


def _install_fake_astrbot():
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    event = types.ModuleType("astrbot.api.event")
    star = types.ModuleType("astrbot.api.star")
    web = types.ModuleType("astrbot.api.web")

    api.logger = FakeLogger()
    api.AstrBotConfig = FakeConfig
    event.AstrMessageEvent = FakeEvent
    event.MessageChain = FakeMessageChain
    event.filter = _Filter()

    class FakeContext:
        def __init__(self):
            self.sent = []
            self.web_apis = []

        def register_web_api(self, *a, **k):
            self.web_apis.append((a, k))

        async def send_message(self, origin, chain):
            self.sent.append((origin, chain))

    class FakeStar:
        def __init__(self, context):
            self.context = context

    def register(*a, **k):
        return lambda cls: cls

    star.Context = FakeContext
    star.Star = FakeStar
    star.register = register

    web.json_response = lambda data: ("json", data)
    web.error_response = lambda message, status_code=500: ("error", message, status_code)
    web.request = types.SimpleNamespace(query={}, json=lambda default=None: {})

    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api
    sys.modules["astrbot.api.event"] = event
    sys.modules["astrbot.api.star"] = star
    sys.modules["astrbot.api.web"] = web


def load_main_module():
    _install_fake_astrbot()
    if "main" in sys.modules:
        return sys.modules["main"]
    main = importlib.import_module("main")
    sys.modules["main"] = main
    return main
