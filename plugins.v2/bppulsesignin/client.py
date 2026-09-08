"""bp PULSE 请求协议，移植自用户提供的 bp_pulse.py；无自动登录。"""
import hashlib
import json
import time
import urllib.error
import urllib.request

BASE = "https://emsp-api.bppulse.net.cn/v1/"
APP_ID = "WP6qSwV1FaSRQkZNZdJPIvwEgCspcd0G"
SECRET = "20f43b14a64251a689595b44a437f85f366a0b97"


class BPError(RuntimeError):
    """可安全展示给用户的业务错误。"""


class AuthExpired(BPError):
    pass


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def payload(data):
    timestamp = str(int(time.time()))
    raw = SECRET + "appId" + APP_ID + "data" + dumps(data) + "timestamp" + timestamp + SECRET
    return {"appId": APP_ID, "data": data,
            "sign": hashlib.sha1(raw.encode()).hexdigest().upper(), "timestamp": timestamp}


class BPClient:
    def search_stations(self, keyword, token, page=1):
        return self.request("standard/poi/map/relatedStationPageList",
                            {"stationName": keyword, "locLongitude": 0, "locLatitude": 0,
                             "pageNum": page, "pageSize": 10}, token)

    def station_details(self, station_id, token):
        return self.request("standard/poi/v1/es/station/details",
                            {"stationId": station_id, "longitude": 0, "latitude": 0}, token)

    def coupons(self, token):
        coupons, seen = [], set()
        for page in range(1, 101):
            data = self.request("standard/activity/api/coupon/list",
                                {"couponReceiveType": 0, "pageNum": page, "pageSize": 10}, token)
            items = data.get("list")
            if not isinstance(items, list) or any(not isinstance(c, dict) for c in items):
                raise BPError("优惠券列表格式异常，请稍后刷新")
            try:
                total = int(data["totalSize"])
            except (KeyError, TypeError, ValueError):
                raise BPError("优惠券分页信息异常，请稍后刷新") from None
            if total < 0 or total > 1000:
                raise BPError("优惠券数量超出查询范围，未更新缓存")
            for item in items:
                key = str(item.get("couponId") or "")
                if not key or key in seen:
                    raise BPError("优惠券分页发生变化，请重新刷新")
                seen.add(key)
                coupons.append(item)
            if len(coupons) >= total:
                return coupons
            if not items:
                break
        raise BPError("优惠券列表未获取完整，请重新刷新")

    def request(self, path, data, token=""):
        headers = {"Content-Type": "application/json; charset=UTF-8", "X-CLIENT-ID": "0",
                   "X-EMP-ID": "1", "VERSION": "2.0.4"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(BASE + path, dumps(payload(data)).encode(), headers, method="POST")
        try:
            # 凭据请求不跟随重定向，避免把 Authorization 带到其它目标。
            opener = urllib.request.build_opener(NoRedirect())
            with opener.open(request, timeout=20) as response:
                result = json.loads(response.read(2 * 1024 * 1024).decode())
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and token:
                raise AuthExpired("登录已过期，请手动登录") from None
            raise BPError(f"bp 服务返回 HTTP {exc.code}，请稍后重试") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise BPError("无法连接 bp 服务，请检查网络后重试") from None
        except (ValueError, UnicodeError):
            raise BPError("bp 服务返回了无效数据") from None
        if not isinstance(result, dict):
            raise BPError("bp 服务响应格式异常")
        if token and result.get("code") in (20, 21, "20", "21"):
            raise AuthExpired("登录已过期，请手动登录")
        if result.get("code") not in (0, "0"):
            # 不直接展示上游 msg，避免回显手机号、验证码或 Token。
            raise BPError("bp 未接受本次请求，请检查验证码或稍后重试")
        data = result.get("data")
        if data is not None and not isinstance(data, dict):
            raise BPError("bp 服务数据格式异常")
        return data or {}

    def send_code(self, phone):
        self.request("standard/ucenter/account/validCode", {"mobile": phone, "sendType": "1"})

    def login(self, phone, code):
        data = self.request("standard/ucenter/account/login",
                            {"loginName": phone, "password": code, "loginType": "3"})
        token = data.get("token")
        if not isinstance(token, str) or not token.strip():
            raise BPError("登录响应缺少凭据，请重新登录")
        return token.strip()

    def check_in(self, token):
        data = self.request("standard/activity/api/signInActivity/signInAndGetInfo",
                            {"authSignInFlag": True}, token)
        signed = data.get("signInFlag") is True
        lines = ["签到成功" if signed else "签到请求已处理（可能今日已签到）"]
        count = data.get("totalSignInCount")
        if isinstance(count, (int, float)):
            lines.append(f"本月累计 {count} 天")
        try:
            prize = self.request("standard/activity/api/signInActivity/receiveAllSignInPrize", {}, token)
            lines.append("礼包已领取" if prize.get("receiveFlag") else "暂无可领取礼包")
        except AuthExpired:
            raise
        except BPError:
            lines.append("礼包领取失败，下次签到时重试")
            return {"status": "warning", "message": "；".join(lines)}
        return {"status": "success" if signed else "processed", "message": "；".join(lines)}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
