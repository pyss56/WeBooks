#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""企业微信API客户端"""
import json
import logging
import time
from typing import Optional

import requests

from config import get_config

logger = logging.getLogger(__name__)


class WeComClient:
    """企业微信API客户端"""

    def __init__(self):
        self.config = get_config()
        self._access_token = None
        self._token_expires_at = 0
        # 优先使用代理地址，用于规避IP白名单限制
        self.api_base_url = (self.config.WECOM_AGENT_URL.rstrip('/')
                             if self.config.WECOM_AGENT_URL
                             else self.config.WECOM_API_BASE_URL.rstrip('/'))

    def _get_access_token(self) -> str:
        """获取企业微信access_token（带缓存）"""
        now = time.time()
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        url = f"{self.api_base_url}/cgi-bin/gettoken"
        params = {
            'corpid': self.config.WECOM_CORP_ID,
            'corpsecret': self.config.WECOM_CORP_SECRET,
        }

        resp = requests.get(url, params=params, timeout=10)
        result = resp.json()

        if result.get('errcode') != 0:
            raise Exception(f"获取access_token失败: {result.get('errmsg')}")

        self._access_token = result['access_token']
        # 提前5分钟过期，确保token有效
        self._token_expires_at = now + result.get('expires_in', 7200) - 300
        return self._access_token

    def _log_send_message(self, msg_type: str, input_data: dict, result: dict, to_user: str):
        """记录发送消息日志"""
        try:
            from db import add_message_log
            import json as _json
            add_message_log(
                msg_type='send',
                input_json=_json.dumps(input_data, ensure_ascii=False, default=str),
                output_json=_json.dumps(result, ensure_ascii=False, default=str) if result else None,
                source_user=to_user,
                source='wecom',
                result='success' if result and result.get('errcode') == 0 else 'failed',
                created_by=to_user
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"记录发送消息日志失败: {e}")

    def send_text_message(self, content: str, to_user: str = None) -> dict:
        """发送文本消息"""
        if to_user is None:
            to_user = self.config.WECOM_TO_USER

        access_token = self._get_access_token()
        url = f"{self.api_base_url}/cgi-bin/message/send?access_token={access_token}"

        data = {
            "touser": to_user,
            "msgtype": "text",
            "agentid": self.config.WECOM_AGENT_ID,
            "text": {
                "content": content
            },
            "safe": 0,
            "enable_duplicate_check": 0,
        }

        resp = requests.post(url, json=data, timeout=10)
        result = resp.json()
        self._log_send_message('text', data, result, to_user)
        return result

    def send_text_card(self, title: str, description: str, url: str,
                       btntxt: str = "查看详情", to_user: str = None) -> dict:
        """发送文本卡片消息（description 自动截断到 512 字节）"""
        if to_user is None:
            to_user = self.config.WECOM_TO_USER

        # 企业微信限制 description 最长 512 字节，截断时避免拆分多字节字符
        desc_bytes = description.encode('utf-8')
        if len(desc_bytes) > 512:
            desc_bytes = desc_bytes[:512]
            # 回退到上一个完整的字符边界
            while desc_bytes and (desc_bytes[-1] & 0xC0) == 0x80:
                desc_bytes = desc_bytes[:-1]
            if desc_bytes and desc_bytes[-1] & 0x80:
                desc_bytes = desc_bytes[:-1]
            description = desc_bytes.decode('utf-8', errors='ignore')

        access_token = self._get_access_token()
        api_url = f"{self.api_base_url}/cgi-bin/message/send?access_token={access_token}"

        data = {
            "touser": to_user,
            "msgtype": "textcard",
            "agentid": self.config.WECOM_AGENT_ID,
            "textcard": {
                "title": title,
                "description": description,
                "url": url,
            },
            "safe": 0,
            "enable_duplicate_check": 0,
        }
        if btntxt:
            data["textcard"]["btntxt"] = btntxt

        resp = requests.post(api_url, json=data, timeout=10)
        result = resp.json()
        self._log_send_message('textcard', data, result, to_user)
        return result

    def send_markdown_message(self, content: str, to_user: str = None) -> dict:
        """发送Markdown消息"""
        if to_user is None:
            to_user = self.config.WECOM_TO_USER

        access_token = self._get_access_token()
        url = f"{self.api_base_url}/cgi-bin/message/send?access_token={access_token}"

        data = {
            "touser": to_user,
            "msgtype": "markdown",
            "agentid": self.config.WECOM_AGENT_ID,
            "markdown": {
                "content": content
            },
            "safe": 0,
            "enable_duplicate_check": 0,
        }

        resp = requests.post(url, json=data, timeout=10)
        result = resp.json()
        self._log_send_message('markdown', data, result, to_user)
        return result

    def create_menu(self, menu_buttons: list) -> dict:
        """创建自定义菜单"""
        access_token = self._get_access_token()
        url = f"{self.api_base_url}/cgi-bin/menu/create?access_token={access_token}&agentid={self.config.WECOM_AGENT_ID}"

        data = {
            "button": menu_buttons
        }

        resp = requests.post(url, json=data, timeout=10)
        return resp.json()

    def get_menu(self) -> dict:
        """获取自定义菜单"""
        access_token = self._get_access_token()
        url = f"{self.api_base_url}/cgi-bin/menu/get?access_token={access_token}&agentid={self.config.WECOM_AGENT_ID}"

        resp = requests.get(url, timeout=10)
        return resp.json()

    def get_user_info(self, user_id: str) -> Optional[dict]:
        """获取用户信息"""
        access_token = self._get_access_token()
        url = f"{self.api_base_url}/cgi-bin/user/get?access_token={access_token}&userid={user_id}"

        resp = requests.get(url, timeout=10)
        result = resp.json()

        if result.get('errcode') != 0:
            return None
        return result

    def get_userid_by_oauth_code(self, code: str) -> Optional[str]:
        """通过 OAuth code 获取企业微信用户 UserID"""
        access_token = self._get_access_token()
        url = f"{self.api_base_url}/cgi-bin/user/getuserinfo?access_token={access_token}&code={code}"
        resp = requests.get(url, timeout=10)
        result = resp.json()
        if result.get('errcode') != 0:
            logger.error(f"OAuth 获取用户失败: {result}")
            return None
        return result.get('UserId')

    def get_media(self, media_id: str, save_path: str) -> bool:
        """下载企业微信媒体文件（如图片）到本地

        企业微信临时素材有效期3天，可通过此接口下载。
        :param media_id: 素材ID（从图片消息的 MediaId 字段获取）
        :param save_path: 保存路径
        :return: 是否下载成功
        """
        access_token = self._get_access_token()
        url = f"{self.api_base_url}/cgi-bin/media/get?access_token={access_token}&media_id={media_id}"
        try:
            resp = requests.get(url, timeout=30)
            content_type = resp.headers.get('Content-Type', '')
            if 'image' in content_type or 'application/octet-stream' in content_type:
                with open(save_path, 'wb') as f:
                    f.write(resp.content)
                logger.info(f"企业微信图片下载成功: media_id={media_id[:16]}... size={len(resp.content)}")
                return True
            else:
                # 企业微信返回了非图片响应（可能是错误信息或重定向等）
                logger.warning(f"企业微信图片下载失败: media_id={media_id[:16]}... "
                               f"Content-Type={content_type} size={len(resp.content)}")
                # 如果是JSON错误，记录下来
                try:
                    err = resp.json()
                    logger.error(f"企业微信图片下载JSON错误: {err}")
                except Exception:
                    # 非JSON响应，记录前200字节
                    logger.error(f"企业微信图片下载响应(非JSON): {resp.content[:200]}")
                return False
        except Exception as e:
            logger.error(f"企业微信图片下载异常: media_id={media_id[:16]}... error={e}")
            return False


