from typing import Tuple, List, Dict, Any, Optional

from apscheduler.triggers.cron import CronTrigger
from qbittorrentapi import TorrentDictionary

from app.helper.downloader import DownloaderHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import ServiceInfo


class BtManager(_PluginBase):
    # 插件名称
    plugin_name = "BT种子管理"
    # 插件描述
    plugin_desc = "管理下载器中的BT种子"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/doubly-yi/MoviePilot-Plugins/main/icons/BT_Manager.png"
    # 插件版本
    plugin_version = "0.0.2"
    # 插件作者
    plugin_author = "Doubly"
    # 作者主页
    author_url = "https://github.com/doubly-yi"
    # 插件配置项ID前缀
    plugin_config_prefix = "btmanager_"
    # 加载顺序
    plugin_order = 24
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _tag_name = None
    _downloaders = None
    _downloader_helper = None
    _start_right_now = False
    # 分享率限制
    _ratio_limit = None
    # 上传速度限制
    _up_speed_limit = None
    # 执行周期
    _cron = "0 0 * * 0"

    def init_plugin(self, config: dict = None):
        logger.info(f"初始化插件 {self.plugin_name}")

        self._downloader_helper = DownloaderHelper()

        if config:
            self._enabled = config.get("enabled", False)
            self._tag_name = config.get("tag_name", "BT")
            self._downloaders = config.get("downloaders", None)
            self._start_right_now = config.get("start_right_now", False)
            try:
                ratio_limit = config.get("ratio_limit", 0)
                self._ratio_limit = float(ratio_limit if ratio_limit else 0)
            except ValueError:
                self._ratio_limit = 0
            try:
                up_speed_limit = config.get("up_speed_limit", 0)
                self._up_speed_limit = float(up_speed_limit if up_speed_limit else 0)
            except ValueError:
                self._up_speed_limit = 0
            self._cron = config.get("cron", "0 0 * * 0")

            if self._start_right_now:
                logger.info("立即运行一次")
                self.run_service()
                self._start_right_now = False

            config = {
                "enabled": self._enabled,
                "tag_name": self._tag_name,
                "downloaders": self._downloaders,
                "start_right_now": self._start_right_now,
                "ratio_limit": self._ratio_limit,
                "up_speed_limit": self._up_speed_limit,
                "cron": self._cron
            }
            # 打印配置信息
            logger.info(f"更新配置：{config}")
            self.update_config(config)

        logger.info(f"插件 {self.plugin_name} 初始化完成")

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """

        # 目前只支持qb，tr没有测试过
        downloader_options = [{"title": config.name, "value": config.name} for config in
                              self._downloader_helper.get_configs().values() if config.type == 'qbittorrent']

        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'start_right_now',
                                            'label': '立即运行一次'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VCronField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '0 0 0 ? *'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'downloaders',
                                            'label': '下载器',
                                            'items': downloader_options,
                                            'multiple': True,
                                            'chips': True,
                                            'clearable': True,
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'tag_name',
                                            'label': '标签名称'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'ratio_limit',
                                            'label': '分享率限制'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'up_speed_limit',
                                            'label': '上传速度限制（KB/S）（-1不限速）'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal'
                                        },
                                        'content': [
                                            {
                                                'component': 'div',
                                                'content': [
                                                    {
                                                        'component': 'span',
                                                        'text': '自动识别下载器中的BT中，根据设定对BT种子进行限制。（目前仅支持QB）'
                                                    },
                                                    {
                                                        'component': 'br'
                                                    },
                                                    {
                                                        'component': 'span',
                                                        'text': '标签名称：设置后会自动将BT种子添加标签'
                                                    },
                                                    {
                                                        'component': 'br'
                                                    },
                                                    {
                                                        'component': 'span',
                                                        'text': '分享率限制：设置后分享率高于设置的BT种子会被暂停'
                                                    },
                                                    {
                                                        'component': 'br'
                                                    },
                                                    {
                                                        'component': 'span',
                                                        'text': '上传速度限制：设置后会将BT种子上传速度限制到设置的速度（-1不限速）'
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "tag_name": 'BT',
            "downloaders": None,
            "start_right_now": False,
            "ratio_limit": 0,
            "up_speed_limit": 0,
            "cron": "0 0 * * 0"
        }

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_page(self) -> List[dict]:
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        if self.get_state():
            logger.info(f"插件 {self.plugin_name} 已启用，注册服务")
            return [{
                "id": "BtManager",
                "name": "BT种子管理",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.run_service,
                "kwargs": {}
            }]
        return []

    def stop_service(self):
        pass

    def get_state(self) -> bool:
        return self._enabled

    def get_downloader_service(self, name: str) -> Optional[ServiceInfo]:
        """
        获取指定名称的下载器服务信息
        :param name: 下载器名称
        :return: 下载器服务信息
        :rtype: ServiceInfo
        """

        if not name:
            return None

        return self._downloader_helper.get_service(name)

    def get_torrents(self, service: ServiceInfo) -> List[TorrentDictionary]:
        """
        获取指定下载器中的所有种子信息
        :param service: 下载器服务信息
        :return: 种子信息列表
        :rtype: Tuple[List[TorrentDictionary]
        """
        if not service:
            return []
        torrents, error = service.instance.get_torrents()
        return torrents

    def run_service(self):
        """
        运行插件服务
        """
        if not self._enabled:
            logger.info("插件未启用，跳过运行")
            return
        if not self._tag_name:
            logger.info("未设置标签名称，跳过运行")
            return
        if not self._downloaders:
            logger.info("未设置下载器，跳过运行")
            return
        for downloader in self._downloaders:
            service = self.get_downloader_service(downloader)
            if not service:
                logger.warning(f"未找到下载器 {downloader} 的服务信息")
                continue
            torrents = self.get_torrents(service)
            if not torrents:
                logger.info(f"下载器 {downloader} 中没有种子")
                continue
            # 打印第一个种子的信息
            first_torrent = torrents[0]
            print(first_torrent)
            for torrent in torrents:
                # 打印所有的种子信息
                if self.is_bt_torrent(torrent, service.type):
                    logger.info(f"种子 {self.get_torrent_name(torrent, service.type)} 是BT种子")

                    # 如果设置了标签，则添加标签
                    if self._tag_name:
                        logger.info(f"给种子 {self.get_torrent_name(torrent, service.type)} 添加标签 {self._tag_name}")
                        self.add_tag(service, torrent, self._tag_name)

                    # 如果设置了上传限速，则设置上传限速
                    if self._up_speed_limit:
                        logger.info(
                            f"设置种子 {self.get_torrent_name(torrent, service.type)} 的上传限速为 {self._up_speed_limit} KB/S")
                        self.set_upload_limit(service, torrent, self._up_speed_limit)

                    # 如果设置了分享率限制，则暂停做种
                    if self._ratio_limit and self._ratio_limit > 0:
                        # 获取当前的分享率
                        ratio = self.get_torrent_ratio(torrent, service.type)
                        if ratio >= self._ratio_limit:
                            logger.info(
                                f"种子 {self.get_torrent_name(torrent, service.type)} 的分享率达到限制，暂停做种")
                            self.pause_torrent(service, torrent)

    def get_torrent_ratio(self, torrent: TorrentDictionary, dl_type: str) -> float:
        """
        获取种子的分享率
        """
        if dl_type == "qbittorrent":
            return float(torrent.get("ratio"))
        else:
            logger.warning("不支持的下载器类型")
            return -1

    def get_trackers_count(self, torrent: TorrentDictionary, dl_type: str) -> int:
        """
        获取种子的tracker信息
        """
        if dl_type == "qbittorrent":
            return torrent.get("trackers_count")
        elif dl_type == "transmission":
            trackers = torrent.trackers
            for tracker in trackers:
                logger.info(f"tracker: {tracker}")
            return len(torrent.trackers)
        else:
            logger.warning("不支持的下载器类型")
            return -1

    def get_torrent_name(self, torrent: TorrentDictionary, dl_type: str) -> str:
        """
        获取种子名称
        """
        if dl_type == "qbittorrent":
            return torrent.get("name")
        elif dl_type == 'transmission':
            return torrent.name
        else:
            logger.warning("不支持的下载器类型")
            return ""

    def is_bt_torrent(self, torrent: TorrentDictionary, dl_type: str) -> bool:
        """
        判断种子是否是BT种子
        """
        trackers_count = self.get_trackers_count(torrent, dl_type)
        return trackers_count == 0

    def get_torrent_tags(self, torrent: TorrentDictionary, dl_type: str) -> List[str]:
        """
        获取种子的标签信息
        """
        if dl_type == "qbittorrent":
            tags = torrent.get("tags")
            return tags.replace(" ", "").split(",")
        else:
            logger.warning("不支持的下载器类型")
            return []

    def get_torrent_hash(self, torrent: TorrentDictionary, dl_type: str) -> str:
        """
        获取种子的hash信息
        """
        if dl_type == "qbittorrent":
            return torrent.get("hash")
        else:
            logger.warning("不支持的下载器类型")
            return ""

    def add_tag(self, service: ServiceInfo, torrent: TorrentDictionary, tag: str):
        """
        添加标签
        """
        dl_type = service.type
        if dl_type == "qbittorrent":
            tags = self.get_torrent_tags(torrent, dl_type)
            if tag not in tags:
                service.instance.set_torrents_tag(self.get_torrent_hash(torrent, dl_type), tag)
        else:
            logger.warning("不支持的下载器类型")
            return

    def set_upload_limit(self, service: ServiceInfo, torrent: TorrentDictionary, limit: float):
        """
        设置上传速度限速，单位是KB/S
        """
        limit = int(limit * 1024)
        dl_type = service.type
        if dl_type == "qbittorrent":
            qbc = service.instance.qbc
            if not qbc:
                logger.warning("未找到qBittorrent客户端实例")
                return
            qbc.torrents_set_upload_limit(limit=limit, torrent_hashes=self.get_torrent_hash(torrent, dl_type))
        else:
            logger.warning("不支持的下载器类型")
            return

    def pause_torrent(self, service: ServiceInfo, torrent: TorrentDictionary):
        """
        暂停做种
        """
        dl_type = service.type
        if dl_type == "qbittorrent":
            service.instance.stop_torrents(self.get_torrent_hash(torrent, dl_type))
        else:
            logger.warning("不支持的下载器类型")
