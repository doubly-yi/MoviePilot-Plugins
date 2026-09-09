"""Authenticated transport and response normalization."""
import base64
import hashlib
import json
import math
import re
import secrets
import time
from datetime import datetime
from typing import Callable, Optional

import requests
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from . import codec


def decode_text(value: str) -> str:
    """Decode fixed transport constants; this is not secret storage."""
    return base64.b64decode(value, validate=True).decode()


BASE_URL = decode_text("aHR0cHM6Ly9kaWxpbmtzdXBlcmFwcHNlcnZlci1jbi5ieWQuYXV0bw==")
EXECUTE_ENDPOINT = decode_text("L2NsdWIvc2VhL2NvbW1vblVjL2FjdGl2aXR5L3NpZ24vc2lnbklu")
HISTORY_ENDPOINT = decode_text("L2NsdWIvc2VhL2NvbW1vblVjL2FjdGl2aXR5L3NpZ24vZ2V0U2lnbkNhbGVuZGFy")
SUMMARY_ENDPOINT = decode_text("L2NsdWIvc2VhL2NSaWdodHMvaW50ZWdyYWwvdXNlci91c2Vy")
PROFILES = {
    "1": ("W", decode_text("ZHluYXN0eQ==")),
    "2": ("H", decode_text("b2NlYW4=")),
    "3": ("T", decode_text("ZGVuemE=")),
    "4": ("Y", decode_text("eWFuZ3dhbmc=")),
    "5": ("F", decode_text("ZmFuZ2NoZW5nYmFv")),
}
DEFAULTS = {
    "phone": "", "password": "", "imei_md5": "", "network_type": "wifi",
    "cn_app_inner_version": "510", "cn_app_version": "9.11.0", "device_type": "0",
    "mobile_brand": "XIAOMI", "mobile_model": "POCO F1", "soft_type": "0", "app_channel": "99",
    "target_brand": "2", "vehicle_brand": "2", "brand_flag": PROFILES["2"][1], "network_operator": "无",
    "ostype": "and", "imei": "BANGCLE01234", "mac": "00:00:00:00:00:00",
    "model": "POCO F1", "sdk": "35", "mod": "Xiaomi", "os_type": "15",
}


class TaskError(Exception):
    """A safe, user-visible error; never contains a raw response or credentials."""


class Stopped(TaskError):
    pass


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def md5_hex(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest().upper()


def pwd_login_key(password: str) -> str:
    return md5_hex(md5_hex(password))


def sha1_mixed(value: str) -> str:
    mixed = "".join(f"{b:02X}" if i % 2 == 0 else f"{b:02x}"
                    for i, b in enumerate(hashlib.sha1(value.encode()).digest()))
    return "".join(c for i, c in enumerate(mixed) if not (c == "0" and i % 2 == 0))


def sign_string(fields: dict, password: str) -> str:
    return "&".join(f"{k}={fields[k]}" for k in sorted(fields)) + "&password=" + password


def aes_encrypt(plain: str, key_hex: str) -> str:
    padder = padding.PKCS7(128).padder()
    data = padder.update(plain.encode()) + padder.finalize()
    cipher = Cipher(algorithms.AES(bytes.fromhex(key_hex)), modes.CBC(bytes(16))).encryptor()
    return (cipher.update(data) + cipher.finalize()).hex().upper()


def aes_decrypt(cipher_hex: str, key_hex: str) -> str:
    cipher = Cipher(algorithms.AES(bytes.fromhex(key_hex)), modes.CBC(bytes(16))).decryptor()
    data = cipher.update(bytes.fromhex(cipher_hex)) + cipher.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return (unpadder.update(data) + unpadder.finalize()).decode()


def number(value):
    try:
        result = float(value)
        return (int(result) if result.is_integer() else result) if math.isfinite(result) else 0
    except (ValueError, TypeError):
        return 0


def parse_calendar(data) -> Optional[dict]:
    if not isinstance(data, dict):
        return None
    today = str(data.get("today") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", today):
        raise ValueError("Invalid calendar date")
    datetime.strptime(today, "%Y-%m-%d")
    if not isinstance(data.get("calendar"), list):
        raise ValueError("Invalid calendar payload")
    records = {}
    for month in data["calendar"]:
        if not isinstance(month, list):
            raise ValueError("Invalid calendar month")
        for raw in month:
            if not isinstance(raw, dict):
                raise ValueError("Invalid calendar day")
            date = str(raw.get("sign_date") or "")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                raise ValueError("Invalid calendar day date")
            datetime.strptime(date, "%Y-%m-%d")
            day = {"sign_date": date, "is_sign": raw.get("is_sign") in (True, 1, "1", "true"),
                   "integral": number(raw.get("integral")), "reward_type": str(raw.get("reward_type") or ""),
                   "continuation": number(raw.get("continuation"))}
            if date in records and records[date] != day:
                raise ValueError("Conflicting calendar records")
            records[date] = day
    # The default endpoint returns three months. Never request an expanded range for the board.
    month_keys = sorted({date[:7] for date in records})[-3:]
    days = sorted((d for d in records.values() if d["sign_date"][:7] in month_keys), key=lambda d: d["sign_date"])
    months = []
    for key in month_keys:
        items = [d for d in days if d["sign_date"].startswith(key)]
        completed = [d for d in items if d["is_sign"]]
        months.append({"month": key, "days": items, "signed_days": len(completed),
                       "integral": sum(d["integral"] for d in completed)})
    signed = [d for d in days if d["is_sign"] and d["sign_date"].startswith(today[:7])]
    future = sorted((d for d in days if d.get("sign_date") and d["sign_date"] >= today
                     and str(d.get("reward_type")) == "7" and not d.get("is_sign")), key=lambda d: d["sign_date"])
    next_reward = None
    if today and future:
        target = future[0]["sign_date"]
        next_reward = {"date": target, "daysLeft": (datetime.strptime(target, "%Y-%m-%d") - datetime.strptime(today, "%Y-%m-%d")).days}
    return {"today": today, "duration": number(data.get("durationDays")),
            "monthSignDays": len(signed), "monthIntegral": sum(number(d.get("integral")) for d in signed),
            "rewardCards": number(data.get("rewardCardNum")), "tips": str(data.get("tips") or "")[:500],
            "nextReward": next_reward, "months": months,
            "todayIntegral": number(data.get("todayIntegral")),
            "todaySigned": records[today]["is_sign"] if today in records else None,
            "todayEarned": records[today]["integral"] if today in records and records[today]["is_sign"] else 0}


def validate_config(config: dict) -> dict:
    result = {k: str(config.get(k, v) if config.get(k, v) is not None else "") for k, v in DEFAULTS.items()}
    for k in result:
        if k != "password":
            result[k] = result[k].strip()
    if not re.fullmatch(r"1\d{10}", result["phone"]):
        raise TaskError("请填写 11 位手机号")
    if not result["password"]:
        raise TaskError("请填写登录密码")
    brand = result["target_brand"]
    if brand not in PROFILES:
        raise TaskError("请选择有效的品牌")
    # Retain target_brand as the saved field for compatibility with old configs.
    # Legacy vehicle_brand/brand_flag values can never override the selection.
    result["vehicle_brand"] = brand
    result["brand_flag"] = PROFILES[brand][1]
    if result["imei_md5"] and not re.fullmatch(r"[a-fA-F0-9]{32}", result["imei_md5"]):
        raise TaskError("设备标识必须是 32 位十六进制字符，或留空自动生成")
    for k in DEFAULTS:
        if k not in ("phone", "password", "imei_md5"):
            if not result[k] or len(result[k]) > 100 or any(ord(c) < 32 for c in result[k]):
                raise TaskError("请检查高级参数，字段不能为空或包含换行")
    return result


class TaskClient:
    def __init__(self, config: dict, stopped: Callable[[], bool] = lambda: False,
                 log: Callable[[str], None] = lambda message: None):
        self.config = validate_config(config)
        self.stopped = stopped
        self.log = log
        self.http = requests.Session()
        self.imei_md5 = self.config["imei_md5"] or md5_hex(decode_text("YnlkLXFsLQ==") + self.config["phone"])

    def close(self):
        self.http.close()

    def _check_stop(self):
        if self.stopped():
            raise Stopped("插件已停止")

    def encode_outer(self, payload: dict, now_ms: int) -> str:
        payload = dict(payload)
        for name in ("ostype", "imei", "mac", "model", "sdk"):
            payload[name] = self.config[name]
        payload["serviceTime"] = str(now_ms)
        payload["mod"] = self.config["mod"]
        payload["checkcode"] = hashlib.sha256(dumps(payload).encode()).hexdigest()
        return codec.encrypt_envelope(dumps(payload))

    def post_secure(self, endpoint: str, payload: dict) -> dict:
        self._check_stop()
        self.log("发送服务请求")
        headers = {"accept-encoding": "identity", "content-type": "application/json; charset=UTF-8",
                   "user-agent": "okhttp/4.12.0", "version": self.config["cn_app_inner_version"],
                   "platform": "ANDROID", "BrandFlag": self.config["brand_flag"]}
        body = dumps({"request": self.encode_outer(payload, int(time.time() * 1000))})
        try:
            with self.http.post(BASE_URL + endpoint, headers=headers, data=body.encode(),
                                timeout=(10, 30), allow_redirects=False, stream=True) as response:
                if response.status_code != 200:
                    raise TaskError(f"接口 HTTP {response.status_code}")
                content = bytearray()
                for chunk in response.iter_content(65536):
                    self._check_stop()
                    content.extend(chunk)
                    if len(content) > 2 * 1024 * 1024:
                        raise TaskError("接口返回数据过大")
                self._check_stop()
                envelope = json.loads(content)
                result = json.loads(codec.decrypt_envelope(envelope["response"].strip()))
                if not isinstance(result, dict):
                    raise ValueError()
                return result
        except requests.RequestException:
            raise TaskError("网络请求失败或超时，请检查连接；本次不会自动重试") from None
        except (ValueError, TypeError, KeyError, AttributeError):
            raise TaskError("接口响应格式或解密异常") from None

    def login_request(self, now_ms: int, random_value: str) -> dict:
        c = self.config
        ts = str(now_ms)
        inner = {"appInnerVersion": c["cn_app_inner_version"], "appVersion": c["cn_app_version"],
                 "bluetoothMac": "", "city": "", "configVersion": "10000", "deviceType": c["device_type"],
                 "devicename": c["mobile_brand"] + c["mobile_model"], "imeiMD5": self.imei_md5,
                 "isAuto": "0", "latitude": "", "longitude": "", "mobileBrand": c["mobile_brand"],
                 "mobileModel": c["mobile_model"], "networkOperator": c["network_operator"],
                 "networkType": c["network_type"], "osType": "Android", "osVersion": c["os_type"],
                 "random": random_value, "softType": c["soft_type"], "timeStamp": ts}
        fields = {**inner, "appChannel": c["app_channel"], "identifier": c["phone"], "loginType": 0,
                  "reqTimestamp": ts, "targetBrand": c["target_brand"]}
        return {"appChannel": c["app_channel"], "encryData": aes_encrypt(dumps(inner), pwd_login_key(c["password"])),
                "identifier": c["phone"], "imeiMD5": self.imei_md5, "isAuto": "0", "loginType": 0,
                "reqTimestamp": ts, "sign": sha1_mixed(sign_string(fields, md5_hex(c["password"]))),
                "targetBrand": c["target_brand"]}

    def login(self) -> dict:
        response = self.post_secure("/app/auth/login", self.login_request(int(time.time() * 1000), secrets.token_hex(16).upper()))
        if str(response.get("code")) != "0":
            raise TaskError("登录失败，请检查账号、密码及品牌参数（服务端拒绝登录）")
        try:
            inner = json.loads(aes_decrypt(response["respondData"], pwd_login_key(self.config["password"])))
            token = inner["token"]
            relation = token.get("superBindRelationDtoMap") or {}
            super_id = str(token.get("superId") or "")
            user_id = str((relation.get(self.config["target_brand"]) or {}).get("userId") or super_id)
            result = {"userId": user_id, "superId": super_id, "signToken": str(token.get("signToken") or ""),
                      "encryToken": str(token.get("encryToken") or token.get("encryptToken") or ""), "bindMap": relation}
            if not all(result[k] for k in ("userId", "signToken", "encryToken")):
                raise ValueError()
            return result
        except (ValueError, KeyError, TypeError, AttributeError):
            raise TaskError("登录响应缺少凭据或无法解密") from None

    def token_outer(self, now_ms: int, session: dict, inner: dict):
        c = self.config
        key = md5_hex(session["encryToken"])
        fields = {**inner, "appChannel": c["app_channel"], "identifier": session["superId"] or session["userId"],
                  "identifierType": 0 if inner.get("vin") else 2, "imeiMD5": self.imei_md5,
                  "reqTimestamp": str(now_ms), "targetBrand": c["target_brand"], "vehicleBrand": c["vehicle_brand"]}
        if inner.get("vin"):
            fields["objective"] = inner["vin"]
        outer = {"appChannel": c["app_channel"], "encryData": aes_encrypt(dumps(inner), key),
                 "identifier": fields["identifier"], "identifierType": fields["identifierType"],
                 "imeiMD5": self.imei_md5, "objective": inner.get("vin") or None, "outModelTypes": None,
                 "reqTimestamp": str(now_ms), "sign": sha1_mixed(sign_string(fields, md5_hex(session["signToken"]))),
                 "softType": None, "targetBrand": c["target_brand"], "vehicleBrand": c["vehicle_brand"], "version": None}
        return outer, key

    def common_uc(self, endpoint: str, session: dict, extra: Optional[dict] = None):
        inner = {"random": secrets.token_hex(16).upper(), "timeStamp": str(int(time.time() * 1000)),
                 "version": self.config["cn_app_inner_version"], "uid": session["userId"], "brand_uid": session["userId"],
                 "super_uid": session["superId"] or "", "phone_no": self.config["phone"],
                 "brand": self.config["target_brand"], "belong_brand": self.config["target_brand"], **(extra or {})}
        outer, key = self.token_outer(int(time.time() * 1000), session, inner)
        response = self.post_secure(endpoint, outer)
        if str(response.get("code")) not in ("0", "200"):
            code = str(response.get("code", ""))
            safe_code = code if re.fullmatch(r"-?\d{1,10}", code) else "未知"
            raise TaskError(f"业务接口拒绝请求（代码 {safe_code}），登录凭据可能已失效；本次未重新登录")
        try:
            data = json.loads(aes_decrypt(response["respondData"], key))
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (KeyError, ValueError, TypeError):
            raise TaskError("业务响应缺失或无法解密") from None

    def balance(self, session: dict):
        # Query the current account summary; do not reuse legacy snapshots.
        r = self.common_uc(SUMMARY_ENDPOINT, session)
        if r.get("ret") != 200 or not isinstance(r.get("data"), dict):
            raise TaskError("积分余额查询失败")
        data = r["data"]
        if str(data.get("super_uid") or "") != str(session.get("superId") or session["userId"]):
            raise TaskError("积分余额账号不匹配")
        result = {"source": "api", "fetched_at": time.time()}
        for field in ("available_integral_sum", "gain_integral_sum", "expend_integral_sum",
                      "going_expired_integral_sum", "having_expired_integral_sum",
                      "freezing_integral_sum", "locking_integral_sum"):
            value = data.get(field)
            # Missing or malformed data must never appear as a zero balance.
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                raise TaskError("积分余额格式异常")
            try:
                parsed = float(value)
                if not math.isfinite(parsed) or parsed < 0:
                    raise ValueError()
            except ValueError:
                raise TaskError("积分余额格式异常") from None
            result[field] = int(parsed) if parsed.is_integer() else parsed
        return result

    def run(self, session: dict) -> dict:
        # Session acquisition belongs to the plugin. Never log in on query failure.
        self._check_stop()
        self.log("使用当前登录凭据开始签到")
        r = self.common_uc(EXECUTE_ENDPOINT, session)
        if r.get("ret") != 200 or not isinstance(r.get("data"), dict):
            raise TaskError("签到失败，服务端未返回成功结果")
        data = r["data"]
        duplicate = data.get("duplicate") is True
        result = {"ok": True, "stage": "already" if duplicate else "signed", "duration_days": number(data.get("durationDays")),
                  "integral": number(data.get("integral")), "duplicate": duplicate, "calendar": None, "balance": None, "warnings": []}
        for name, operation in (("calendar", lambda: self._calendar(session)), ("balance", lambda: self.balance(session))):
            self._check_stop()
            try:
                result[name] = operation()
            except Stopped:
                raise
            except (TaskError, ValueError, TypeError, AttributeError):
                warning = "签到日历查询失败" if name == "calendar" else "积分余额查询失败"
                result["warnings"].append(warning)
                self.log(warning + "，签到结果已保留")
        return result

    def _calendar(self, session):
        r = self.common_uc(HISTORY_ENDPOINT, session)
        if r.get("ret") != 200:
            raise TaskError("签到日历查询失败")
        result = parse_calendar(r.get("data"))
        if result is None:
            raise TaskError("签到日历格式错误")
        return result


def notification(result: dict):
    duplicate = result.get("duplicate") is True
    title = "Dicar 今日已签到" if duplicate else "Dicar 签到成功"
    lines = [f"{'今日已签到' if duplicate else '签到成功'}（连续{result.get('duration_days') or 0}天，+{result.get('integral') or 0}积分）"]
    calendar = result.get("calendar")
    if calendar:
        lines.append(f"本月已签到{calendar['monthSignDays']}天 | 连续{calendar['duration']}天 | 本月+{calendar['monthIntegral']}积分 | 补签卡{calendar['rewardCards']}张")
        if calendar.get("nextReward"):
            reward = calendar["nextReward"]
            lines.append(f"下次奖励：{reward['date']}（还需{reward['daysLeft']}天）")
        if calendar.get("tips"):
            lines.append(calendar["tips"])
    balance = result.get("balance")
    if balance and balance.get("source") == "api":
        lines.append(f"积分余额：{balance['available_integral_sum']}")
    lines.extend(result.get("warnings", []))
    return title, "\n".join(lines)
