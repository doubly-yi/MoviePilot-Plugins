"""浏览器联调：真实插件路由 + 内存宿主 + 模拟 bp 服务，绑定本机。"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from fastapi import FastAPI, Body, Depends
from fastapi.testclient import TestClient
from host_stub import load_plugin

module = load_plugin()
plugin = module.BpPulseSignin()
plugin.init_plugin({'enabled':False,'notify':True,'cron':'0 8 * * *'})


class FakeBP:
    def send_code(self, phone):
        pass

    def login(self, phone, code):
        if code != '123456':
            raise module.BPError('验证码不正确，请重新输入')
        return 'test-token-'+phone

    def check_in(self, token):
        if token == 'expired-test-token':
            raise module.AuthExpired('登录过期')
        return {'status':'success','message':'签到成功；本月累计 8 天；礼包已领取'}


plugin._client = FakeBP()
plugin.account_api({'name':'日常充电','phone':'13800000001','cookie':'demo-token'})
plugin.account_api({'name':'家庭账号','phone':'13800000002','cookie':'expired-test-token'})
app = FastAPI()
for original in plugin.get_api():
    route = original.copy()
    route.pop('auth')
    route['path'] = '/api/v1/plugin/BpPulseSignin'+route['path']
    app.add_api_route(**route)
from app.db.user_oper import get_current_active_superuser


@app.put('/api/v1/plugin/BpPulseSignin', dependencies=[Depends(get_current_active_superuser)])
def save_host_config(config: dict = Body(...)):
    # 对应 MP 标准保存：保存配置 -> 重新初始化 -> 重新注册服务。
    plugin.update_config(config)
    plugin.stop_service()
    plugin.init_plugin(config)
    plugin.get_service()
    return {'success': True}


client = TestClient(app)


class Handler(BaseHTTPRequestHandler):
    def handle_api(self):
        length = int(self.headers.get('Content-Length', '0'))
        data = self.rfile.read(length) if length else None
        response = client.request(self.command,self.path,content=data,
                                  headers={'Content-Type':'application/json', 'X-Test-Admin':self.headers.get('X-Test-Admin','')})
        self.send_response(response.status_code)
        self.send_header('Content-Type','application/json')
        self.end_headers()
        self.wfile.write(response.content)

    do_GET = handle_api
    do_POST = handle_api
    do_PUT = handle_api

    def log_message(self, *args):
        pass


print('模拟 API: http://127.0.0.1:8791', flush=True)
ThreadingHTTPServer(('127.0.0.1',8791),Handler).serve_forever()
