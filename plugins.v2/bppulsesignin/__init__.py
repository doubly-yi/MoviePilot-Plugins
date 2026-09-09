"""bp PULSE 多账号签到：短信登录只由用户点击触发。"""
import copy
import re
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Tuple

from apscheduler.triggers.cron import CronTrigger
from fastapi import Body, Depends

from app.core.config import settings
from app.db.user_oper import get_current_active_superuser
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import NotificationType

from .client import AuthExpired, BPClient, BPError
from .coupons import normalize_coupon, public_coupon, station_summary


class BpPulseSignin(_PluginBase):
    plugin_name = "bp PULSE 签到"
    plugin_desc = "多账号签到、短信登录、常用站点优惠券汇总与空闲枪数查询。"
    plugin_icon = "https://raw.githubusercontent.com/doubly-yi/MoviePilot-Plugins/main/icons/BpPulseSignin.ico"
    plugin_version = "1.0.1"
    plugin_author = "doubly-yi"
    author_url = "https://github.com/doubly-yi"
    plugin_config_prefix = "bppulsesignin_"
    plugin_order = 50
    auth_level = 1
    DATA_KEY = "accounts"
    SMS_INTERVAL = 60
    CODE_TTL = 600

    def init_plugin(self, config: dict = None):
        if not hasattr(self, "_lock"):
            self._lock = threading.RLock()
            self._account_locks = {}
            self._batch_lock = threading.Lock()
            self._client = BPClient()
        with self._lock:
            if hasattr(self, "_stop_event"):
                self._stop_event.set()
            self._stop_event = threading.Event()
            self._stopped = False
            config = config or {}
            self._enabled = bool(config.get("enabled", False))
            self._notify = bool(config.get("notify", True))
            self._cron = str(config.get("cron") or "0 8 * * *").strip()
            try:
                self._station = self._station_config(config.get("station"))
            except BPError:
                self._station = None
                logger.warning("bp PULSE：常用站点配置无效，请重新选择")
            self._cron_error = ""
            try:
                self._trigger(self._cron)
            except BPError as exc:
                self._cron_error = str(exc)
                logger.warning(f"bp PULSE: {exc}")
            logger.info(f"bp PULSE 初始化完成：定时签到{'开启' if self._enabled else '关闭'}，"
                        f"已配置 {len(self._accounts())} 个账号")

    @staticmethod
    def _trigger(cron):
        try:
            if len(cron.split()) != 5:
                raise ValueError()
            return CronTrigger.from_crontab(cron, timezone=settings.TZ)
        except (ValueError, TypeError):
            raise BPError("执行周期必须是有效的五段 Cron 表达式") from None

    def _settings(self):
        return {"enabled": self._enabled, "notify": self._notify, "cron": self._cron,
                "station": copy.deepcopy(self._station)}

    @staticmethod
    def _station_config(value):
        if value is None:
            return None
        if not isinstance(value, dict) or not re.fullmatch(r"[0-9]{1,64}", str(value.get("id") or "")):
            raise BPError("请从搜索结果选择常用站点")
        name = str(value.get("name") or "").strip()
        if not name or len(name) > 200:
            raise BPError("常用站点名称无效，请重新选择")
        return {"id": str(value["id"]), "name": name, "address": str(value.get("address") or "")[:500]}

    def get_state(self) -> bool:
        return self._enabled and not self._stopped

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [], self._settings()

    def get_page(self) -> List[dict]:
        return []

    @staticmethod
    def get_render_mode():
        return "vue", "dist/assets"

    @staticmethod
    def get_command():
        return []

    def stop_service(self):
        # 任务由宿主管理；已发出的 HTTP 请求受 20 秒超时限制。
        self._stopped = True
        if hasattr(self, "_stop_event"):
            self._stop_event.set()
        logger.info("bp PULSE：已停止后台任务，等待卸载或重新初始化")

    def get_service(self):
        if not self.get_state() or self._cron_error:
            return []
        return [{"id": "BpPulseSignin.CheckIn", "name": "bp PULSE 多账号签到",
                 "trigger": self._trigger(self._cron), "func": self.run_service,
                 "kwargs": {"max_instances": 1, "coalesce": True, "misfire_grace_time": 120}}]

    def get_api(self):
        routes = [("/status", self.status_api, "GET"),
                  ("/settings/validate", self.validate_settings_api, "POST"),
                  ("/account", self.account_api, "POST"),
                  ("/delete", self.delete_api, "POST"),
                  ("/send-code", self.send_code_api, "POST"),
                  ("/login", self.login_api, "POST"),
                  ("/stations/search", self.search_stations_api, "POST"),
                  ("/station/refresh", self.station_refresh_api, "POST"),
                  ("/coupons/refresh", self.coupons_refresh_api, "POST"),
                  ("/claim-prizes", self.claim_prizes_api, "POST"),
                  ("/rewards/refresh", self.rewards_refresh_api, "POST"),
                  ("/check-in", self.check_in_api, "POST")]
        return [{"path": path, "endpoint": endpoint, "methods": [method], "auth": "bear",
                 "dependencies": [Depends(get_current_active_superuser)], "summary": endpoint.__doc__,
                 "response_model": dict} for path, endpoint, method in routes]

    def _accounts(self):
        data = self.get_data(self.DATA_KEY) or {}
        return copy.deepcopy(data) if isinstance(data, dict) else {}

    @contextmanager
    def _account(self, account_id):
        if not isinstance(account_id, str) or not account_id:
            raise BPError("请选择账号")
        with self._lock:
            if account_id not in self._accounts():
                raise BPError("账号不存在，请刷新页面")
            lock = self._account_locks.setdefault(account_id, threading.Lock())
        if not lock.acquire(blocking=False):
            raise BPError("该账号正在处理，请稍后重试")
        try:
            with self._lock:
                account = self._accounts().get(account_id)
            if not account:
                raise BPError("账号不存在，请刷新页面")
            yield account
        finally:
            lock.release()

    def _store(self, account):
        with self._lock:
            accounts = self._accounts()
            if account["id"] not in accounts:
                raise BPError("账号已删除")
            account["revision"] = int(account.get("revision", 0)) + 1
            accounts[account["id"]] = account
            self.save_data(self.DATA_KEY, accounts)

    def _public(self, account):
        result = {key: account.get(key) for key in
                  ("id", "name", "phone", "enabled", "revision", "auth_status", "last_run", "status", "message")}
        result["has_token"] = bool(account.get("cookie"))
        result["auto_claim"] = account.get("auto_claim", True)
        result.update({key: account.get(key) for key in ("last_claim", "claim_status", "claim_message")})
        result["sms_wait"] = max(0, int(account.get("sms_sent_at", 0) + self.SMS_INTERVAL - time.time() + 1))
        result["code_pending"] = account.get("code_until", 0) > time.time()
        station_id = self._station["id"] if self._station else ""
        result["coupons"] = sorted([public_coupon(c, station_id, time.time()) for c in account.get("coupons", [])],
                                   key=lambda c: c.get("end") or float("inf"))
        result["coupon_updated"] = account.get("coupon_updated")
        result["coupon_error"] = account.get("coupon_error", "")
        result["rewards"] = account.get("rewards", [])
        result["reward_updated"] = account.get("reward_updated")
        result["reward_error"] = account.get("reward_error", "")
        return result

    def _reply(self, operation):
        try:
            message = operation()
            return {"success": True, "message": message or "操作成功", "data": self._status()}
        except BPError as exc:
            logger.warning(f"bp PULSE 操作未完成：{exc}")
            return {"success": False, "message": str(exc)}
        except Exception as exc:
            # 只记录异常类型，第三方异常正文可能包含凭据。
            logger.error(f"bp PULSE 操作失败：{type(exc).__name__}")
            return {"success": False, "message": "操作失败，请查看插件日志后重试"}

    def _status(self):
        with self._lock:
            return {"settings": self._settings(), "cron_error": self._cron_error,
                    "accounts": [self._public(a) for a in self._accounts().values()],
                    "station": self._station_snapshot()}

    def _station_snapshot(self):
        cached = self.get_data("station_snapshot") or {}
        return cached if self._station and cached.get("id") == self._station["id"] else None

    def _check_query_state(self):
        if self._stopped:
            raise BPError("插件已停止或重载，请在设置页重新保存配置后重试")

    def _station_query(self, operation):
        self._check_query_state()
        for aid in self._accounts():
            with self._account(aid) as account:
                if not account.get("cookie") or account.get("auth_status") == "expired":
                    continue
                try:
                    return operation(account["cookie"])
                except AuthExpired:
                    account["auth_status"] = "expired"
                    self._notify_expired(account)
                    self._store(account)
                except BPError:
                    raise
                except Exception as exc:
                    logger.warning(f"bp PULSE 站点查询失败：{type(exc).__name__}")
                    raise BPError("站点查询失败，请稍后重试") from None
        raise BPError("请先在看板登录至少一个账号，再查询站点")

    def search_stations_api(self, payload: dict = Body(...)):
        """按名称分页搜索充电站。"""
        try:
            keyword = str(payload.get("keyword") or "").strip()
            if not 2 <= len(keyword) <= 50:
                raise BPError("请输入 2～50 个字符的站点关键词")
            page = payload.get("page", 1)
            if type(page) is not int or not 1 <= page <= 100:
                raise BPError("搜索页码无效")
            data = self._station_query(lambda token: self._client.search_stations(keyword, token, page))
            if not isinstance(data.get("list"), list):
                raise BPError("站点列表格式异常")
            items = [station_summary(s) for s in data["list"] if isinstance(s, dict) and s.get("stationId")]
            return {"success": True, "data": {"items": items, "total": int(data.get("totalSize") or 0)}}
        except BPError as exc:
            return {"success": False, "message": str(exc)}
        except Exception as exc:
            logger.warning(f"bp PULSE 站点搜索失败：{type(exc).__name__}")
            return {"success": False, "message": "站点搜索失败，请稍后重试"}

    def station_refresh_api(self, payload: dict = Body(...)):
        """更新常用站点的空闲枪数，短期查询复用缓存。"""
        def refresh():
            self._check_query_state()
            with self._lock:
                station = copy.deepcopy(self._station)
                generation = self._stop_event
            if not station:
                raise BPError("请先设置常用站点")
            cached = self._station_snapshot()
            if cached and time.time() - cached.get("updated", 0) < 60 and not cached.get("error"):
                return "站点数据已是最近一分钟的结果"
            try:
                data = self._station_query(lambda token: self._client.station_details(station["id"], token))
                snapshot = station_summary(data)
                if snapshot["id"] != station["id"]:
                    raise BPError("站点详情返回不匹配，请稍后重试")
                snapshot.update(updated=time.time(), error="")
            except BPError as exc:
                snapshot = dict(cached or station, error=str(exc))
            with self._lock:
                if generation.is_set() or self._station != station:
                    raise BPError("常用站点已变更，请刷新页面")
                self.save_data("station_snapshot", snapshot)
            return "站点信息已更新"
        return self._reply(refresh)

    def coupons_refresh_api(self, payload: dict = Body(...)):
        """查询指定账号的全部未使用优惠券，不签到、不领取奖励。"""
        def refresh():
            self._check_query_state()
            generation = self._stop_event
            with self._account(payload.get("id")) as account:
                if account.get("coupon_updated") and time.time() - account["coupon_updated"] < 60 and not account.get("coupon_error"):
                    return "优惠券已是最近一分钟的结果"
                try:
                    if not account.get("cookie") or account.get("auth_status") == "expired":
                        raise AuthExpired("请手动登录后再查询优惠券")
                    data = self._client.coupons(account["cookie"])
                    coupons = [normalize_coupon(c) for c in data]
                    account.update(coupons=coupons, coupon_updated=time.time(), coupon_error="",
                                   auth_status="valid", expired_notified=False)
                except AuthExpired:
                    account.update(auth_status="expired" if account.get("cookie") else "missing",
                                   coupon_error="登录已失效，请手动登录后刷新优惠券")
                    self._notify_expired(account)
                except BPError as exc:
                    account["coupon_error"] = str(exc)
                except Exception as exc:
                    logger.warning(f"bp PULSE 优惠券查询失败：{type(exc).__name__}")
                    account["coupon_error"] = "优惠券查询失败，请稍后重试"
                if generation.is_set():
                    raise BPError("插件已重载，请重新刷新优惠券")
                self._store(account)
                logger.info(f"bp PULSE [{account['id'][:8]}]：优惠券查询{'失败' if account.get('coupon_error') else '完成'}")
            return "优惠券查询完成"
        return self._reply(refresh)

    def status_api(self):
        """获取账号登录状态和最近签到结果。"""
        return {"success": True, "data": self._status()}

    def rewards_refresh_api(self, payload: dict = Body(...)):
        """只读查询奖励任务，状态直接采用 bp 返回值，不按进度推算。"""
        def refresh():
            self._check_query_state()
            generation = self._stop_event
            with self._account(payload.get("id")) as account:
                if account.get("reward_updated") and time.time() - account["reward_updated"] < 60 and not account.get("reward_error"):
                    return "奖励任务已是最近一分钟的结果"
                try:
                    if not account.get("cookie") or account.get("auth_status") == "expired":
                        raise AuthExpired("请手动登录后再查询奖励")
                    rewards = self._client.rewards(account["cookie"])
                    account.update(rewards=rewards, reward_updated=time.time(), reward_error="",
                                   auth_status="valid", expired_notified=False)
                except AuthExpired:
                    account.update(auth_status="expired" if account.get("cookie") else "missing",
                                   reward_error="登录已失效，请手动登录后刷新奖励")
                    self._notify_expired(account)
                except BPError as exc:
                    account["reward_error"] = str(exc)
                except Exception as exc:
                    logger.warning(f"bp PULSE 奖励查询失败：{type(exc).__name__}")
                    account["reward_error"] = "奖励查询失败，请稍后重试"
                if generation.is_set():
                    raise BPError("插件已重载，请重新刷新奖励")
                self._store(account)
            return "奖励任务查询完成"
        return self._reply(refresh)

    def validate_settings_api(self, payload: dict = Body(...)):
        """校验设置；保存与重新注册定时服务由宿主标准配置流程完成。"""
        def validate():
            cron = str(payload.get("cron") or "").strip()
            self._trigger(cron)
            self._station_config(payload.get("station"))
            return "配置校验通过"
        return self._reply(validate)

    @staticmethod
    def _credentials(payload):
        name = str(payload.get("name") or "").strip()
        phone = str(payload.get("phone") or "").strip()
        if not name or len(name) > 40:
            raise BPError("账号名称为 1～40 个字符")
        if not re.fullmatch(r"1[3-9]\d{9}", phone):
            raise BPError("请输入有效的 11 位手机号")
        token = str(payload.get("cookie") or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if len(token) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise BPError("Token 格式无效")
        return name, phone, token

    def account_api(self, payload: dict = Body(...)):
        """新增或编辑账号，留空 Token 时保留已有凭据。"""
        def save():
            name, phone, token = self._credentials(payload)
            if "auto_claim" in payload and type(payload["auto_claim"]) is not bool:
                raise BPError("自动领奖开关必须为开启或关闭")
            account_id = payload.get("id")
            if not account_id:
                with self._lock:
                    accounts = self._accounts()
                    if any(a["phone"] == phone for a in accounts.values()):
                        raise BPError("该手机号已添加")
                    if len(accounts) >= 50:
                        raise BPError("最多支持 50 个账号")
                    account_id = uuid.uuid4().hex
                    accounts[account_id] = {"id": account_id, "name": name, "phone": phone,
                        "enabled": bool(payload.get("enabled", True)), "cookie": token, "revision": 1,
                        "auto_claim": payload.get("auto_claim", True),
                        "auth_status": "unknown" if token else "missing", "status": "idle", "message": "尚未签到"}
                    self.save_data(self.DATA_KEY, accounts)
            else:
                with self._account(account_id) as account, self._lock:
                    if payload.get("revision") != account.get("revision"):
                        raise BPError("账号状态已更新，请刷新后重新编辑")
                    if any(a["phone"] == phone and a["id"] != account_id for a in self._accounts().values()):
                        raise BPError("该手机号已添加")
                    changed_phone = account["phone"] != phone
                    if changed_phone or payload.get("clear_token"):
                        account["cookie"] = ""
                    if token:
                        account["cookie"] = token
                    if changed_phone or payload.get("clear_token") or token:
                        account.update(coupons=[], coupon_updated=None, coupon_error="")
                        account.update(rewards=[], reward_updated=None, reward_error="")
                        account.update(last_claim=None, claim_status=None, claim_message=None)
                        account.update(auth_status="unknown" if account["cookie"] else "missing",
                                       expired_notified=False, code_until=0, sms_sent_at=0,
                                       status="idle", message="登录信息已更新", last_run=None)
                    account.update(name=name, phone=phone, enabled=bool(payload.get("enabled", True)))
                    # 旧版前端未传此字段时保留选择；历史账号默认仍自动领奖。
                    account["auto_claim"] = payload.get("auto_claim", account.get("auto_claim", True))
                    self._store(account)
            return "账号已保存"
        return self._reply(save)

    def delete_api(self, payload: dict = Body(...)):
        """删除一个账号及其保存的登录凭据。"""
        def delete():
            with self._account(payload.get("id")) as account, self._lock:
                if payload.get("revision") != account.get("revision"):
                    raise BPError("账号状态已更新，请刷新后重试")
                accounts = self._accounts()
                del accounts[account["id"]]
                self.save_data(self.DATA_KEY, accounts)
            return "账号已删除"
        return self._reply(delete)

    def send_code_api(self, payload: dict = Body(...)):
        """仅手动发送所选账号的登录验证码。"""
        def send():
            with self._account(payload.get("id")) as account:
                now = time.time()
                if now < account.get("sms_sent_at", 0) + self.SMS_INTERVAL:
                    raise BPError("验证码发送过于频繁，请等待 60 秒后重试")
                # 请求开始即记录冷却，网络超时时也不立即重复发送。
                account.update(sms_sent_at=now, code_until=0)
                self._store(account)
                self._client.send_code(account["phone"])
                account["code_until"] = time.time() + self.CODE_TTL
                self._store(account)
            return "验证码已发送，请输入短信验证码"
        return self._reply(send)

    def login_api(self, payload: dict = Body(...)):
        """验证短信验证码并自动保存登录凭据。"""
        def login():
            code = str(payload.get("code") or "").strip()
            if not re.fullmatch(r"\d{4,8}", code):
                raise BPError("请输入 4～8 位数字验证码")
            with self._account(payload.get("id")) as account:
                if time.time() > account.get("code_until", 0):
                    raise BPError("请先发送验证码，或重新发送已超时的验证码")
                if time.time() < account.get("login_attempt_at", 0) + 3:
                    raise BPError("验证过于频繁，请稍后重试")
                account["login_attempt_at"] = time.time()
                self._store(account)
                token = self._client.login(account["phone"], code)
                account.update(cookie=token, auth_status="valid", expired_notified=False,
                               code_until=0, status="idle", message="登录成功，等待签到",
                               coupons=[], coupon_updated=None, coupon_error="",
                               rewards=[], reward_updated=None, reward_error="")
                self._store(account)
            return "登录成功，已保存登录凭据"
        return self._reply(login)

    def _notify_expired(self, account):
        if account.get("expired_notified"):
            return
        try:
            self.post_message(mtype=NotificationType.Plugin, title="bp PULSE 登录提醒",
                              text=f"账号 {account['name']}（{account['phone'][:3]}****{account['phone'][-4:]}）"
                                   "登录已过期或尚未登录，请打开插件，点击该账号的“登录”获取验证码。")
        except Exception as exc:
            logger.warning(f"bp PULSE 通知失败：{type(exc).__name__}")
            return
        account["expired_notified"] = True

    def _send_batch_notification(self, results):
        # 收集器属于本轮任务；不与手动签到或其他查询共用通知状态。
        visible = [r for r in results if self._notify or r.get("login_reminder")]
        if not visible:
            return
        sections = []
        for result in visible:
            detail = result["message"].replace("；本月累计", " · 本月累计").replace("；", "\n")
            sections.append(f"【{result['name']}】\n{detail}")
        text = "\n\n".join(sections)
        if any(r.get("login_reminder") for r in visible):
            text += "\n\n请打开插件，点击对应账号的“登录”获取验证码。"
        try:
            self.post_message(mtype=NotificationType.Plugin,
                              title="bp PULSE · 定时签到汇总" if self._notify else "bp PULSE 登录提醒",
                              text=text)
        except Exception as exc:
            logger.warning(f"bp PULSE 汇总通知失败：{type(exc).__name__}")
            return
        # 发送成功后才记录提醒；账号若已重新登录或编辑，不覆盖新状态。
        with self._lock:
            accounts = self._accounts()
            changed = False
            for result in visible:
                account = accounts.get(result.get("id"))
                if (result.get("login_reminder") and account
                        and account.get("revision") == result.get("revision")
                        and account.get("auth_status") in ("expired", "missing")):
                    account["expired_notified"] = True
                    changed = True
            if changed:
                self.save_data(self.DATA_KEY, accounts)

    def _check_in(self, account_id, manual=False, notifications=None):
        with self._account(account_id) as account:
            if self._stopped:
                raise BPError("插件已停止或重载，请在设置页重新保存配置后重试")
            if not manual and (not self.get_state() or not account.get("enabled")):
                return "账号未启用，已跳过"
            logger.info(f"bp PULSE [{account_id[:8]}]：开始{'手动' if manual else '定时'}签到，"
                        f"自动领奖{'开启' if account.get('auto_claim', True) else '关闭'}")
            account["last_run"] = datetime.now(CronTrigger(timezone=settings.TZ).timezone).isoformat(timespec="seconds")
            try:
                if not account.get("cookie") or account.get("auth_status") == "expired":
                    raise AuthExpired("请手动登录后再签到")
                result = self._client.check_in(account["cookie"], auto_claim=account.get("auto_claim", True))
                account.update(result, auth_status="valid", expired_notified=False)
                account["coupon_error"] = "签到结果已更新，请刷新优惠券"
                account["reward_error"] = "签到结果已更新，请刷新奖励状态"
            except AuthExpired:
                account.update(auth_status="expired" if account.get("cookie") else "missing",
                               status="expired", message="登录已失效，请手动登录")
                if notifications is None:
                    self._notify_expired(account)
            except BPError as exc:
                account.update(status="error", message=str(exc))
            except Exception as exc:
                logger.error(f"bp PULSE [{account_id[:8]}] 签到失败：{type(exc).__name__}")
                account.update(status="error", message="签到结果未确认，请稍后查看签到状态")
            self._store(account)
            if notifications is not None:
                expired = account["status"] == "expired"
                name = account["name"]
                if expired:
                    name += f"（{account['phone'][:3]}****{account['phone'][-4:]}）"
                notifications.append({"id": account_id, "revision": account["revision"],
                                      "name": name, "message": account["message"],
                                      "login_reminder": expired and not account.get("expired_notified")})
            elif self._notify and account["status"] != "expired":
                try:
                    self.post_message(mtype=NotificationType.Plugin, title=f"bp PULSE · {account['name']}",
                                      text=account["message"])
                except Exception as exc:
                    logger.warning(f"bp PULSE 通知失败：{type(exc).__name__}")
            logger.info(f"bp PULSE [{account['id'][:8]}]：{account['status']}")
            return account["message"]

    def check_in_api(self, payload: dict = Body(...)):
        """手动签到所选账号，与定时开关独立。"""
        return self._reply(lambda: self._check_in(payload.get("id"), manual=True))

    def claim_prizes_api(self, payload: dict = Body(...)):
        """手动领取所选账号全部已达标且尚未领取的签到奖励，不触发签到。"""
        def claim():
            self._check_query_state()
            generation = self._stop_event
            with self._account(payload.get("id")) as account:
                account["last_claim"] = datetime.now(CronTrigger(timezone=settings.TZ).timezone).isoformat(timespec="seconds")
                logger.info(f"bp PULSE [{account['id'][:8]}]：开始手动领取全部签到奖励")
                try:
                    if not account.get("cookie") or account.get("auth_status") == "expired":
                        raise AuthExpired("请手动登录后再领奖")
                    result = self._client.claim_prizes(account["cookie"])
                    account.update(claim_status=result["status"], claim_message=result["message"],
                                   auth_status="valid", expired_notified=False,
                                   coupon_error="领奖结果已更新，请刷新优惠券",
                                   reward_error="领奖结果已更新，请刷新奖励状态")
                except AuthExpired:
                    account.update(auth_status="expired" if account.get("cookie") else "missing",
                                   claim_status="expired", claim_message="登录已失效，请手动登录")
                    self._notify_expired(account)
                except BPError as exc:
                    account.update(claim_status="error", claim_message=str(exc))
                except Exception as exc:
                    logger.error(f"bp PULSE 领奖失败：{type(exc).__name__}")
                    account.update(claim_status="error", claim_message="领奖结果未确认，请先查看优惠券再重试")
                if generation.is_set():
                    raise BPError("插件已重载，领奖结果未写入记录，请先刷新优惠券确认")
                self._store(account)
                logger.info(f"bp PULSE [{account['id'][:8]}]：手动领奖 {account['claim_status']}")
                return account["claim_message"]
        return self._reply(claim)

    def run_service(self):
        stop_event = self._stop_event
        if stop_event.is_set() or not self.get_state():
            return
        if not self._batch_lock.acquire(blocking=False):
            logger.info("bp PULSE：已有批量签到正在执行，跳过本次重复运行")
            return
        try:
            notifications = []
            with self._lock:
                selected = [(a["id"], a["name"]) for a in self._accounts().values() if a.get("enabled")]
            logger.info(f"bp PULSE：定时签到，共 {len(selected)} 个账号")
            for account_id, name in selected:
                if stop_event.is_set() or not self.get_state():
                    break
                try:
                    self._check_in(account_id, notifications=notifications)
                except BPError as exc:
                    logger.warning(f"bp PULSE [{account_id[:8]}]：{exc}")
                    notifications.append({"name": name, "message": str(exc)})
                except Exception as exc:
                    logger.error(f"bp PULSE [{account_id[:8]}] 签到失败：{type(exc).__name__}")
                    notifications.append({"name": name, "message": "签到处理失败，请查看插件日志"})
            self._send_batch_notification(notifications)
        finally:
            self._batch_lock.release()
