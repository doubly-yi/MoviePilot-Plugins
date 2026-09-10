"""MoviePilot V2 scheduled task adapter."""
import copy
import hashlib
import json
import os
import threading
import time
from datetime import datetime

import pytz
from apscheduler.triggers.cron import CronTrigger
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import NotificationType

from .transport import PROFILES, TaskClient, TaskError, DEFAULTS, Stopped, decode_text, notification, validate_config
from .panel import render_calendar

PREVIOUS_ID = decode_text("QnlkU2lnbmlu")


class Dicar(_PluginBase):
    plugin_name = "Dicar"
    plugin_desc = "签到插件，支持定时签到、积分余额查询和签到日历。"
    plugin_icon = "signin.png"
    plugin_version = "1.0.1"
    plugin_author = "doubly-yi"
    author_url = "https://github.com/doubly-yi"
    plugin_config_prefix = "dicar_"
    plugin_order = 26
    auth_level = 1

    def __init__(self):
        super().__init__()
        self._lock = threading.RLock()
        self._run_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._config = self.defaults()
        self._error = ""

    @staticmethod
    def defaults():
        fields = {k: v for k, v in DEFAULTS.items() if k not in ("vehicle_brand", "brand_flag")}
        return {**fields, "enabled": False, "notify": True, "onlyonce": False,
                "cron": "30 3 * * *", "debug": False, "relogin": False}

    @staticmethod
    def _trigger(cron):
        try:
            return CronTrigger.from_crontab(str(cron).strip(), timezone=settings.TZ)
        except (ValueError, TypeError):
            raise TaskError("执行周期须为有效的五段 Cron 表达式") from None

    def _load_password(self):
        """Keep plaintext only in memory; bind the encrypted password to its account."""
        password = self._config.get("password", "")
        phone = str(self._config.get("phone") or "").strip()
        if not phone and not password:
            return ""
        if not isinstance(password, str):
            raise TaskError("密码格式无效，请重新填写")
        saved = self.get_data("password_secret")
        if not password and not saved:
            return ""
        account = hashlib.sha256(phone.encode()).hexdigest()
        if not password and (not isinstance(saved, dict) or saved.get("account") != account):
            raise TaskError("账号已改变，请填写对应密码")
        try:
            path = self.get_data_path() / "password.key"
            if password and not path.exists():
                try:
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    pass
                else:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(Fernet.generate_key())
                        stream.flush()
                        os.fsync(stream.fileno())
            cipher = Fernet(path.read_bytes())
            if password:
                self.save_data("password_secret", {"version": 1, "account": account,
                               "ciphertext": cipher.encrypt(password.encode()).decode()})
                return password
            return cipher.decrypt(saved["ciphertext"].encode()).decode()
        except (OSError, ValueError, TypeError, KeyError, AttributeError, InvalidToken):
            raise TaskError("无法读取或保存加密密码，请检查插件数据目录或重新填写密码") from None

    def _import_previous(self):
        """Copy existing state once through host APIs; never activate a second job."""
        if self.get_config() is not None:
            return None
        previous = self.get_config(plugin_id=PREVIOUS_ID)
        if not isinstance(previous, dict) or not previous.get("phone"):
            return None
        try:
            saved = {key: self.get_data(key, plugin_id=PREVIOUS_ID) for key in (
                "password_secret", "login_session", "last_result", "calendar_snapshot", "balance_snapshot")}
            if saved["password_secret"]:
                key_data = (self.get_data_path(plugin_id=PREVIOUS_ID) / "password.key").read_bytes()
                Fernet(key_data)  # Reject a missing/corrupt key before copying state.
                path = self.get_data_path() / "password.key"
                if path.exists():
                    if path.read_bytes() != key_data:
                        raise TaskError("本地凭据密钥已存在，无法自动导入旧配置")
                else:
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(key_data)
                        stream.flush()
                        os.fsync(stream.fileno())
            for key, value in saved.items():
                if value is not None:
                    self.save_data(key, value)
            config = {k: v for k, v in previous.items() if k in self.defaults()}
            config.update(enabled=False, onlyonce=False, relogin=False)
            # New configuration is persisted by init_plugin after secret migration.
            return config
        except (OSError, ValueError, TypeError, InvalidToken):
            raise TaskError("旧配置导入失败，请检查数据目录和凭据密钥") from None

    def init_plugin(self, config=None):
        with self._lock:
            self._stop.set()
            self._stop = threading.Event()
            self._config = self.defaults()
            self._calendar_attempt = 0
            self._calendar_error = ""
            self._error = ""
            imported = False
            if config is None:
                try:
                    config = self._import_previous()
                    imported = config is not None
                except TaskError as exc:
                    self._error = str(exc)
                    logger.warning(f"Dicar：{self._error}")
                    return
            if isinstance(config, dict):
                self._config.update({k: v for k, v in config.items() if k in self._config})
            for key in ("enabled", "notify", "onlyonce", "debug", "relogin"):
                self._config[key] = self._config[key] is True
            relogin = self._config["relogin"]
            once = self._config["onlyonce"] or relogin
            self._config["onlyonce"] = False
            self._config["relogin"] = False
            # Consume actions and remove submitted plaintext before doing other work.
            if once or self._config.get("password"):
                stored_config = copy.deepcopy(self._config)
                stored_config["password"] = ""
                self.update_config(stored_config)
            self._error = ""
            try:
                self._config["password"] = self._load_password()
                if imported:
                    stored_config = copy.deepcopy(self._config)
                    stored_config["password"] = ""
                    self.update_config(stored_config)
                self._trigger(self._config["cron"])
                if self._config["enabled"] or once:
                    validate_config(self._config)
            except TaskError as exc:
                self._config["password"] = ""
                self._error = str(exc)
                logger.warning(f"Dicar：{self._error}")
                return
            if once:
                generation = self._stop
                cfg = copy.deepcopy(self._config)
                cfg["relogin"] = relogin
                self._thread = threading.Thread(target=self._run_once, args=(generation, cfg),
                                                name="Dicar-once", daemon=True)
                self._thread.start()
        logger.info("Dicar配置已加载")

    def _run_once(self, generation, config):
        if not generation.wait(3):
            self._execute(generation, config)

    def get_state(self):
        return bool(self._config["enabled"] and not self._error and not self._stop.is_set())

    def get_service(self):
        if not self.get_state():
            return []
        return [{"id": "Dicar_daily", "name": "Dicar", "trigger": self._trigger(self._config["cron"]),
                 "func": self.run_service, "kwargs": {"max_instances": 1, "coalesce": True}}]

    def run_service(self):
        with self._lock:
            if not self.get_state() or self._stop.is_set():
                return
            generation, cfg = self._stop, copy.deepcopy(self._config)
        self._execute(generation, cfg)

    def _execute(self, generation, config):
        if generation.is_set():
            return
        if not self._run_lock.acquire(blocking=False):
            logger.info("Dicar已有任务执行中，本次跳过")
            return
        try:
            self._perform(generation, config)
        finally:
            self._run_lock.release()

    def _perform(self, generation, config):
        client = None
        source = ""
        fingerprint = ""
        try:
            if generation.is_set():
                return
            client = TaskClient(config, stopped=generation.is_set,
                               log=(lambda message: logger.info("Dicar：" + message)) if config["debug"] else lambda message: None)
            fingerprint = self._fingerprint(client.config)
            session, source = self._session(client, generation, force=config.get("relogin") is True)
            result = client.run(session)
            title, text = notification(result)
        except Stopped:
            return
        except TaskError as exc:
            result = {"ok": False, "error": str(exc)}
            title, text = "Dicar 签到失败", str(exc)
        except Exception as exc:
            logger.warning(f"Dicar异常：{type(exc).__name__}")
            result = {"ok": False, "error": "签到异常，请查看插件日志；本次不会自动重试"}
            title, text = "Dicar 签到失败", result["error"]
        finally:
            if client:
                client.close()
        with self._lock:
            if generation.is_set():
                return
            result["session_source"] = source
            result["fingerprint"] = fingerprint
            if result.get("calendar") is not None:
                self._save_calendar(result["calendar"], fingerprint)
            self._save_balance(result.get("balance"), fingerprint,
                               "积分余额查询失败" if not result.get("balance") else "")
            if not result.get("ok") and source == "cached":
                result["error"] += "。本次使用已保存 Token，未自动重新登录；如确认失效，请手动重新登录一次"
                text = result["error"]
            result["updated_at"] = datetime.now(pytz.timezone(settings.TZ)).strftime("%Y-%m-%d %H:%M:%S")
            self.save_data("last_result", result)
            logger.info(title + "：" + text)
            if config["notify"]:
                try:
                    self.post_message(mtype=NotificationType.Plugin, title=title, text=text)
                except Exception as exc:
                    logger.warning(f"Dicar通知发送失败：{type(exc).__name__}")

    @staticmethod
    def _fingerprint(config):
        fields = {k: v for k, v in config.items() if k not in ("baseline_integral", "baseline_date")}
        return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def _session(self, client, generation, force=False, allow_login=True):
        """Persist before execution so failures never cause another automatic login."""
        fingerprint = self._fingerprint(client.config)
        with self._lock:
            if generation.is_set():
                raise Stopped("插件已停止")
            saved = self.get_data("login_session")
        if saved is not None and not force:
            if not isinstance(saved, dict) or saved.get("fingerprint") != fingerprint:
                raise TaskError("账号或设备参数已改变，请勾选“重新登录一次”并保存")
            session = saved.get("session")
            if not isinstance(session, dict) or not all(isinstance(session.get(k), str) and session[k]
                    for k in ("userId", "signToken", "encryToken")) or not isinstance(session.get("superId"), str):
                raise TaskError("保存的登录凭据不完整，请手动重新登录一次")
            cookies = saved.get("cookies", {})
            if isinstance(cookies, dict):
                client.http.cookies.update(cookies)
            logger.info("Dicar：复用已保存 Token，不调用登录接口")
            return session, "cached"
        if not allow_login:
            raise TaskError("尚无保存的登录凭据，请先在设置中签到一次")
        logger.info("Dicar：" + ("按手动操作重新登录" if force else "尚无保存的 Token，首次登录"))
        session = client.login()
        saved = {"version": 1, "fingerprint": fingerprint,
                 "session": {k: session.get(k, "") for k in ("userId", "superId", "signToken", "encryToken")},
                 "cookies": client.http.cookies.get_dict(), "saved_at": time.time()}
        with self._lock:
            if generation.is_set():
                raise Stopped("插件已重载，本次不保存旧登录凭据")
            self.save_data("login_session", saved)
        logger.info("Dicar：Token 已保存，后续签到将复用")
        return saved["session"], "login"

    def stop_service(self):
        with self._lock:
            self._stop.set()

    def get_api(self):
        return []

    def _save_calendar(self, calendar, fingerprint):
        self.save_data("calendar_snapshot", {"calendar": calendar, "fingerprint": fingerprint,
                       "fetched_at": time.time(), "updated_at": datetime.now(pytz.timezone(settings.TZ)).strftime("%Y-%m-%d %H:%M:%S")})
        self._calendar_attempt = time.time()
        self._calendar_error = ""

    def _save_balance(self, balance, fingerprint, error=""):
        # Keep the last successful value on failure, explicitly marked as cached.
        snapshot = self.get_data("balance_snapshot") or {}
        if snapshot.get("fingerprint") != fingerprint:
            snapshot = {}
        if balance is not None and balance.get("source") == "api":
            snapshot = {"balance": balance, "fingerprint": fingerprint}
        snapshot["error"] = error
        self.save_data("balance_snapshot", snapshot)

    def _refresh_calendar(self):
        """Query calendar and balance with the saved session; never log in or execute tasks."""
        with self._lock:
            generation, cfg = self._stop, copy.deepcopy(self._config)
            if generation.is_set():
                return "插件已停止，请保存设置后重新打开"
            if time.time() - getattr(self, "_calendar_attempt", 0) < 60:
                return self._calendar_error
        if not self._run_lock.acquire(blocking=False):
            return "正在签到，请稍后重新打开看板"
        client = None
        try:
            client = TaskClient(cfg, stopped=generation.is_set)
            fingerprint = self._fingerprint(client.config)
            snapshot = self.get_data("calendar_snapshot") or {}
            balance_snapshot = self.get_data("balance_snapshot") or {}
            if (snapshot.get("fingerprint") == fingerprint and time.time() - snapshot.get("fetched_at", 0) < 60
                    and balance_snapshot.get("fingerprint") == fingerprint
                    and not balance_snapshot.get("error")
                    and time.time() - balance_snapshot.get("balance", {}).get("fetched_at", 0) < 60):
                return ""
            session, _ = self._session(client, generation, allow_login=False)
            calendar, balance, errors = None, None, []
            for label, query in (("签到日历", client._calendar), ("积分余额", client.balance)):
                try:
                    value = query(session)
                    if label == "签到日历":
                        calendar = value
                    else:
                        balance = value
                except Stopped:
                    raise
                except (TaskError, ValueError, TypeError, AttributeError) as exc:
                    errors.append(str(exc) if isinstance(exc, TaskError) else label + "格式异常")
            with self._lock:
                if generation.is_set():
                    return "配置已更新，请重新打开看板"
                if calendar is not None:
                    self._save_calendar(calendar, fingerprint)
                self._save_balance(balance, fingerprint, "积分余额查询失败" if balance is None else "")
                self._calendar_attempt = time.time()
                self._calendar_error = "；".join(errors)
            return self._calendar_error
        except (TaskError, ValueError, TypeError, AttributeError) as exc:
            message = str(exc) if isinstance(exc, TaskError) else "看板数据格式异常"
        except Exception as exc:
            logger.warning(f"签到日历查询异常：{type(exc).__name__}")
            message = "签到日历查询失败，请稍后重新打开"
        finally:
            if client:
                client.close()
            self._run_lock.release()
        with self._lock:
            if not generation.is_set():
                self._calendar_attempt = time.time()
                self._calendar_error = message
        return message

    def get_page(self):
        error = self._refresh_calendar()
        snapshot = self.get_data("calendar_snapshot")
        result = self.get_data("last_result") or {}
        try:
            fingerprint = self._fingerprint(validate_config(self._config))
        except TaskError:
            fingerprint = ""
        if not isinstance(snapshot, dict) or snapshot.get("fingerprint") != fingerprint:
            snapshot = None
        if result.get("fingerprint") != fingerprint:
            result = {}
        # Ignore legacy estimated balances and isolate account-specific snapshots.
        result.pop("balance", None)
        balance_snapshot = self.get_data("balance_snapshot") or {}
        if balance_snapshot.get("fingerprint") == fingerprint:
            result["balance"] = balance_snapshot.get("balance")
            result["balance_error"] = balance_snapshot.get("error") or error
        return render_calendar(snapshot, result, error=error)

    def get_form(self):
        def field(model, label, component="VTextField", cols=6, **props):
            return {"component": "VCol", "props": {"cols": 12, "md": cols}, "content": [
                {"component": component, "props": {"model": model, "label": label, **props}}]}

        def row(*fields):
            return {"component": "VRow", "content": list(fields)}

        profiles = [{"title": name, "value": value} for value, (name, _) in PROFILES.items()]
        advanced = [
            ("cn_app_inner_version", "App 内部版本"), ("cn_app_version", "App 版本"),
            ("device_type", "设备类型"), ("soft_type", "软件类型"), ("app_channel", "App 渠道"),
            ("mobile_brand", "设备厂商"), ("mobile_model", "手机型号"), ("network_type", "网络类型"),
            ("network_operator", "网络运营商"), ("ostype", "系统标识"), ("os_type", "系统版本"),
            ("imei", "IMEI 参数"), ("mac", "MAC 参数"), ("model", "外层设备型号"),
            ("sdk", "SDK 版本"), ("mod", "外层设备厂商"),
        ]
        return [{"component": "VForm", "content": [
            row(field("enabled", "启用定时签到", "VSwitch", 3), field("notify", "发送通知", "VSwitch", 3),
                field("onlyonce", "立即运行一次", "VSwitch", 3), field("relogin", "重新登录一次", "VSwitch", 3)),
            row(field("cron", "执行周期（Cron）", cols=12, hint="五段表达式，按 MoviePilot 时区执行；默认每天 03:30", persistentHint=True)),
            row(field("phone", "手机号", autocomplete="off"), field("password", "密码", type="password", autocomplete="new-password",
                hint="留空保留已保存密码", persistentHint=True)),
            row(field("target_brand", "品牌", "VSelect", cols=12, items=profiles)),
            {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "class": "my-3"},
             "text": "自动复用 Token，失效后需手动重新登录。与手机 App 不能同时在线，重新登录会使另一端掉线。"},
            {"component": "VExpansionPanels", "content": [{"component": "VExpansionPanel", "content": [
                {"component": "VExpansionPanelTitle", "text": "高级请求参数"},
                {"component": "VExpansionPanelText", "content": [row(
                    field("imei_md5", "设备标识（IMEI MD5）", hint="留空时按手机号生成稳定标识", persistentHint=True),
                    field("debug", "详细日志", "VSwitch"))] + [row(*(field(k, label) for k, label in advanced[i:i + 2])) for i in range(0, len(advanced), 2)]},
            ]}]},
        ]}], self.defaults()
