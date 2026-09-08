from unittest.mock import Mock
import pytest
from host_stub import load_plugin


@pytest.fixture(scope="session")
def module():
    return load_plugin()


@pytest.fixture
def plugin(module):
    obj = module.BpPulseSignin()
    obj.init_plugin({"enabled": True, "notify": True, "cron": "0 8 * * *"})
    obj._client = Mock()
    obj._client.check_in.return_value = {"status": "success", "message": "签到成功；本月累计 3 天；礼包已领取"}
    obj._client.login.return_value = "new-private-token"
    return obj
