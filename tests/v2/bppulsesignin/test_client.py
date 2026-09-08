import hashlib
import io
import json
import urllib.error
from unittest.mock import Mock
import pytest


def client_module(module):
    import sys
    return sys.modules['app.plugins.bppulsesignin.client']


def test_signature_matches_script(module, monkeypatch):
    client = client_module(module)
    monkeypatch.setattr(client.time, 'time', lambda: 1720000000)
    data = {'mobile':'13800000001','sendType':'1'}
    result = client.payload(data)
    raw = client.SECRET+'appId'+client.APP_ID+'data'+json.dumps(data,ensure_ascii=False,separators=(',',':'))+'timestamp1720000000'+client.SECRET
    assert result['sign'] == hashlib.sha1(raw.encode()).hexdigest().upper()


@pytest.mark.parametrize('result,error', [({'code':20},'AuthExpired'), ({'code':'21'},'AuthExpired'), ({'code':1,'msg':'secret-token'},'BPError'), ([], 'BPError'), ({'code':0,'data':[]}, 'BPError')])
def test_response_errors(module, monkeypatch, result, error):
    client = client_module(module)
    response = io.BytesIO(json.dumps(result).encode())
    monkeypatch.setattr(client.urllib.request, 'build_opener', lambda *_: Mock(open=Mock(return_value=response)))
    with pytest.raises(getattr(client,error)) as caught:
        client.BPClient().request('test',{},'secret-token')
    assert 'secret-token' not in str(caught.value)


@pytest.mark.parametrize('status,expected', [(401,'AuthExpired'),(403,'BPError'),(500,'BPError')])
def test_http_failures_do_not_leak_response(module, monkeypatch, status, expected):
    client = client_module(module)
    err = urllib.error.HTTPError('url',status,'secret',{},io.BytesIO(b'private-token'))
    monkeypatch.setattr(client.urllib.request, 'build_opener', lambda *_: Mock(open=Mock(side_effect=err)))
    with pytest.raises(getattr(client,expected)) as caught:
        client.BPClient().request('test',{},'private-token')
    assert 'private-token' not in str(caught.value)


def test_request_headers_body_and_timeout(module, monkeypatch):
    client = client_module(module)
    opener = Mock(open=Mock(return_value=io.BytesIO(b'{"code":0,"data":{}}')))
    monkeypatch.setattr(client.urllib.request,'build_opener',lambda *_:opener)
    client.BPClient().request('sign',{'authSignInFlag':True},'my-token')
    req = opener.open.call_args.args[0]
    assert req.full_url == client.BASE+'sign'
    assert req.get_header('Authorization') == 'Bearer my-token'
    assert req.get_method() == 'POST'
    assert json.loads(req.data)['data'] == {'authSignInFlag':True}
    assert opener.open.call_args.kwargs['timeout'] == 20


def test_prize_failure_keeps_partial_result(module):
    client = client_module(module)
    obj = client.BPClient()
    obj.request = Mock(side_effect=[{'signInFlag':True,'totalSignInCount':3}, client.BPError('bad')])
    result = obj.check_in('token')
    assert result['status'] == 'warning'
    assert '签到成功' in result['message'] and '礼包领取失败' in result['message']


def test_prize_auth_expiry_is_propagated(module):
    client = client_module(module)
    obj = client.BPClient()
    obj.request = Mock(side_effect=[{'signInFlag':True}, client.AuthExpired('expired')])
    with pytest.raises(client.AuthExpired):
        obj.check_in('token')


def test_login_without_token_fails(module):
    client = client_module(module)
    obj = client.BPClient()
    obj.request = Mock(return_value={})
    with pytest.raises(client.BPError):
        obj.login('13800000001','123456')
