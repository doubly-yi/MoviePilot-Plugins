import json
import threading
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def add(plugin, phone='13800000001', cookie='private-token', enabled=True):
    response = plugin.account_api({'name': '测试账号', 'phone': phone, 'cookie': cookie, 'enabled': enabled})
    assert response['success'], response
    return response['data']['accounts'][-1]['id']


def account(plugin, aid):
    return plugin._accounts()[aid]


def test_default_config_and_no_side_effects(module):
    obj = module.BpPulseSignin()
    obj.init_plugin(None)
    assert obj.get_state() is False
    assert obj.get_service() == []
    assert obj.get_form()[1]['cron'] == '0 8 * * *'
    assert obj.data == {} and obj.messages == []


def test_manual_independent_of_schedule(plugin):
    aid = add(plugin, enabled=False)
    plugin._enabled = False
    assert plugin.check_in_api({'id': aid})['success']
    plugin._client.check_in.assert_called_once_with('private-token')
    assert account(plugin, aid)['status'] == 'success'


def test_cron_runs_selected_accounts_and_isolates_errors(plugin, module):
    first = add(plugin)
    second = add(plugin, '13800000002', 'second-token')
    third = add(plugin, '13800000003', 'third-token', False)
    plugin._client.check_in.side_effect = [module.BPError('网络失败'), {'status': 'success', 'message': '签到成功'}]
    plugin.run_service()
    assert plugin._client.check_in.call_count == 2
    assert account(plugin, first)['status'] == 'error'
    assert account(plugin, second)['status'] == 'success'
    assert account(plugin, third)['status'] == 'idle'


@pytest.mark.parametrize('cookie', ['', 'private-token'])
def test_expiry_only_notifies_no_login_or_sms(plugin, module, cookie):
    aid = add(plugin, cookie=cookie)
    plugin._notify = False  # 结果通知开关不影响过期提醒
    plugin._client.check_in.side_effect = module.AuthExpired('过期')
    plugin.run_service()
    plugin.run_service()
    plugin._client.send_code.assert_not_called()
    plugin._client.login.assert_not_called()
    assert len(plugin.messages) == 1
    assert '138****0001' in plugin.messages[0]['text']
    assert 'private-token' not in json.dumps(plugin.messages)
    assert account(plugin, aid)['status'] == 'expired'
    assert plugin._client.check_in.call_count == (1 if cookie else 0)


def test_notification_failure_retried(plugin, module):
    aid = add(plugin, cookie='')
    plugin.post_message.side_effect = [RuntimeError('通知失败'), None]
    plugin.run_service()
    assert not account(plugin, aid).get('expired_notified')
    plugin.run_service()
    assert account(plugin, aid)['expired_notified'] is True
    assert plugin.post_message.call_count == 2


def test_login_saves_token_to_only_selected_account(plugin):
    first = add(plugin)
    second = add(plugin, '13800000002', 'second-token')
    response = plugin.send_code_api({'id': second})
    assert response['success']
    plugin._client.send_code.assert_called_once_with('13800000002')
    response = plugin.login_api({'id': second, 'code': '123456'})
    assert response['success']
    plugin._client.login.assert_called_once_with('13800000002', '123456')
    assert account(plugin, second)['cookie'] == 'new-private-token'
    assert account(plugin, first)['cookie'] == 'private-token'
    serialized = json.dumps(plugin.data)
    assert '123456' not in serialized
    public = json.dumps(response)
    assert 'new-private-token' not in public and 'second-token' not in public
    assert account(plugin, second)['code_until'] == 0
    plugin._client.check_in.assert_not_called()


def test_wrong_code_preserves_old_token(plugin, module):
    aid = add(plugin)
    plugin.send_code_api({'id': aid})
    plugin._client.login.side_effect = module.BPError('验证码不正确')
    response = plugin.login_api({'id': aid, 'code': '123456'})
    assert not response['success']
    assert account(plugin, aid)['cookie'] == 'private-token'
    assert '123456' not in json.dumps(plugin.data)


def test_sms_cooldown_and_retry_on_uncertain_network(plugin, module):
    aid = add(plugin)
    plugin._client.send_code.side_effect = module.BPError('网络超时')
    assert not plugin.send_code_api({'id': aid})['success']
    assert '60' in plugin.send_code_api({'id': aid})['message']
    assert plugin._client.send_code.call_count == 1
    assert not plugin.login_api({'id': aid, 'code': '123456'})['success']


def test_login_requires_recent_sms(plugin):
    aid = add(plugin)
    assert not plugin.login_api({'id': aid, 'code': '123456'})['success']
    plugin._client.login.assert_not_called()


def test_expired_sms_and_login_rate_limit(plugin, module, monkeypatch):
    aid = add(plugin)
    plugin.send_code_api({'id': aid})
    real_now = module.time.time()
    monkeypatch.setattr(module.time, 'time', lambda: real_now + 601)
    assert not plugin.login_api({'id': aid, 'code': '123456'})['success']
    monkeypatch.setattr(module.time, 'time', lambda: real_now)
    plugin._client.login.side_effect = module.BPError('验证码错误')
    plugin.login_api({'id': aid, 'code': '123456'})
    response = plugin.login_api({'id': aid, 'code': '123456'})
    assert not response['success'] and '频繁' in response['message']
    assert plugin._client.login.call_count == 1


def test_public_status_never_contains_credentials(plugin):
    aid = add(plugin)
    plugin.send_code_api({'id': aid})
    response = plugin.status_api()
    assert 'private-token' not in json.dumps(response)
    assert 'cookie' not in response['data']['accounts'][0]
    assert response['data']['accounts'][0]['has_token']
    assert 'cookie' not in json.dumps(plugin.get_form())


def test_edit_preserves_cookie_and_clears_on_phone_change(plugin):
    aid = add(plugin)
    public = plugin.status_api()['data']['accounts'][0]
    payload = {**public, 'name': '改名', 'cookie': ''}
    assert plugin.account_api(payload)['success']
    assert account(plugin, aid)['cookie'] == 'private-token'
    payload.update(phone='13900000001', revision=account(plugin, aid)['revision'])
    assert plugin.account_api(payload)['success']
    assert account(plugin, aid)['cookie'] == ''
    assert account(plugin, aid)['code_until'] == 0


def test_stale_edit_does_not_overwrite_login(plugin):
    aid = add(plugin)
    stale = plugin.status_api()['data']['accounts'][0]
    plugin.send_code_api({'id': aid})
    plugin.login_api({'id': aid, 'code': '123456'})
    assert not plugin.account_api({**stale, 'cookie': 'stale-token'})['success']
    assert account(plugin, aid)['cookie'] == 'new-private-token'


def test_delete_removes_credentials(plugin):
    aid = add(plugin)
    assert plugin.delete_api({'id': aid, 'revision': 1})['success']
    assert not plugin._accounts()
    assert not plugin.check_in_api({'id': aid})['success']


@pytest.mark.parametrize('patch', [{'phone':'123'}, {'name':''}, {'cookie':'bad\ntoken'}, {'cookie':'x'*8193}])
def test_invalid_account_input(plugin, patch):
    response = plugin.account_api({'name':'测试', 'phone':'13800000001', **patch})
    assert not response['success']
    assert not plugin._accounts()


def test_duplicate_phone_and_bearer_prefix(plugin):
    aid = add(plugin, cookie='Bearer clean-token')
    assert account(plugin, aid)['cookie'] == 'clean-token'
    assert not plugin.account_api({'name':'重复','phone':'13800000001'})['success']


@pytest.mark.parametrize('cron', ['', '* * * *', '0 8 * * * *', 'bad bad bad bad bad', '0 99 * * *'])
def test_invalid_cron_does_not_replace_settings(plugin, cron):
    response = plugin.validate_settings_api({'enabled': True, 'cron': cron})
    assert not response['success']
    assert plugin._cron == '0 8 * * *'


def test_validation_has_no_side_effects_and_host_config_applies(plugin):
    assert plugin.validate_settings_api({'enabled':True,'cron':'30 9 * * *','notify':False})['success']
    assert plugin._cron == '0 8 * * *'
    assert plugin.config == {}
    config = {'enabled':True,'cron':'30 9 * * *','notify':False}
    plugin.update_config(config)
    plugin.stop_service()
    plugin.init_plugin(config)
    job = plugin.get_service()[0]
    assert str(job['trigger'].timezone) == 'Asia/Shanghai'
    assert job['kwargs']['max_instances'] == 1
    assert plugin._notify is False


def test_reload_retains_accounts_and_locks(plugin):
    aid = add(plugin)
    with plugin._account(aid):
        lock = plugin._lock
        plugin.init_plugin({'enabled':True})
        assert plugin._lock is lock
        assert not plugin.check_in_api({'id':aid})['success']
    assert account(plugin, aid)['cookie'] == 'private-token'
    plugin.stop_service()
    assert not plugin.check_in_api({'id':aid})['success']
    assert plugin.get_service() == []


def test_account_operations_can_run_independently(plugin):
    first = add(plugin)
    second = add(plugin, '13800000002', 'second-token')
    entered, release = threading.Event(), threading.Event()
    def check(token):
        if token == 'private-token':
            entered.set()
            assert release.wait(3)
        return {'status':'success','message':'完成'}
    plugin._client.check_in.side_effect = check
    worker = threading.Thread(target=lambda: plugin.check_in_api({'id':first}))
    worker.start()
    assert entered.wait(3)
    try:
        assert not plugin.send_code_api({'id':first})['success']
        assert plugin.check_in_api({'id':second})['success']
    finally:
        release.set()
        worker.join(3)
    assert account(plugin, second)['status'] == 'success'


def test_authenticated_fastapi_routes(plugin):
    app = FastAPI()
    for original in plugin.get_api():
        route = original.copy()
        route.pop('auth')
        route['path'] = '/api/v1/plugin/BpPulseSignin' + route['path']
        app.add_api_route(**route)
    with TestClient(app) as client:
        base = '/api/v1/plugin/BpPulseSignin'
        assert client.get(base+'/status').status_code == 403
        headers = {'X-Test-Admin':'yes'}
        created = client.post(base+'/account', headers=headers, json={'name':'测试','phone':'13800000001'}).json()
        aid = created['data']['accounts'][0]['id']
        assert client.post(base+'/send-code', headers=headers, json={'id':aid}).json()['success']
        assert client.post(base+'/login', headers=headers, json={'id':aid,'code':'123456'}).json()['success']
        assert client.post(base+'/check-in', headers=headers, json={'id':aid}).json()['success']
        assert len(app.openapi()['paths']) == 7
