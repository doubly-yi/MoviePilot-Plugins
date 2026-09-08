"""隔离宿主替身；不加载用户 MP 配置、数据库或外部账号。"""
import copy
import importlib.util
import logging
import sys
import types
from pathlib import Path
from unittest.mock import Mock

from fastapi import Header, HTTPException


def load_plugin():
    for name in ('app', 'app.core', 'app.db', 'app.schemas', 'app.plugins'):
        module = types.ModuleType(name)
        module.__path__ = []
        sys.modules[name] = module

    class PluginBase:
        def __init__(self):
            self.data = {}
            self.config = {}
            self.messages = []
            self.post_message = Mock(side_effect=lambda **kw: self.messages.append(kw))

        def get_data(self, key):
            return copy.deepcopy(self.data.get(key))

        def save_data(self, key, value):
            self.data[key] = copy.deepcopy(value)

        def update_config(self, value):
            self.config = copy.deepcopy(value)
            return True

    sys.modules['app.plugins']._PluginBase = PluginBase

    def admin(x_test_admin: str = Header(default='')):
        if x_test_admin != 'yes':
            raise HTTPException(403, '管理员权限不足')

    Scheduler = Mock()
    modules = {
        'app.core.config': {'settings': types.SimpleNamespace(TZ='Asia/Shanghai')},
        'app.db.user_oper': {'get_current_active_superuser': admin},
        'app.log': {'logger': logging.getLogger('bp-tests')},
        'app.schemas.types': {'NotificationType': types.SimpleNamespace(Plugin='插件')},
        'app.scheduler': {'Scheduler': Scheduler},
    }
    for name, attrs in modules.items():
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        sys.modules[name] = module
    path = Path(__file__).resolve().parents[3] / 'plugins.v2/bppulsesignin'
    name = 'app.plugins.bppulsesignin'
    spec = importlib.util.spec_from_file_location(name, path / '__init__.py', submodule_search_locations=[str(path)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
