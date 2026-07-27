#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""企业微信消息处理器"""
import logging
import os
import requests
from typing import Optional

from wecom.client import WeComClient
from services.message_handler import MessageHandler

logger = logging.getLogger(__name__)


class WeComMessageHandler(MessageHandler):
    """企业微信消息处理"""

    def __init__(self):
        super().__init__(source='wecom')
        self.wecom_client = WeComClient()

    def handle_text_message(self, content: str, from_user: str,
                            message_log_id: int = None) -> str:
        """重写：根据基类标记的回复模式分流，卡片与文本分离。"""
        msg = super().handle_text_message(content, from_user, message_log_id)
        key = self._key(from_user)
        mode = self._reply_mode.pop(key, 'text')
        data = self._reply_data.pop(key, {})

        if mode in ('card', 'composite'):
            card_content = data.get('card_content') or msg
            card_title = data.get('card_title', '✅ 记账成功')
            self._send_booking_card(card_content, card_title, from_user)
            if mode == 'composite':
                # composite 模式：卡片已发，返回的是纯别名确认提示
                return msg
            # card 模式：不发文本
            return ''
        return msg

    def _send_booking_card(self, booking_msg: str, title: str, from_user: str):
        """发送记账成功卡片（含完整记账信息 + 编辑链接按钮）。"""
        last = self._last_transaction.get(self._key(from_user))
        if last and last.get('uuid'):
            from config import get_config
            cfg = get_config()
            view_url = f"{cfg.BASE_URL}/tx/{last['uuid']}" if cfg.BASE_URL else ''
            brief = booking_msg.replace('✅ 记账成功！\n', '').replace('✅ 记账成功！', '')
            self.wecom_client.send_text_card(
                title=title,
                description=brief.replace('\n', '<br>'),
                url=view_url,
                btntxt="查看详情",
                to_user=from_user,
            )

    # ── 平台特有命令 ──────────────────────────────

    def handle_extra_command(self, content: str, from_user: str,
                             user_code: str = None) -> Optional[str]:
        if content in ('更新菜单',):
            return self._handle_sync_menu(from_user)
        return None

    def _get_platform_help_suffix(self) -> str:
        ocr_hint = ""
        try:
            from services.ocr import is_ocr_available
            if is_ocr_available():
                ocr_hint = "📷 截图记账：\n• 发送「消费截图/支付截图」- 自动识别金额入账\n\n"
        except Exception:
            pass
        return (
            f"{ocr_hint}"
            "🔄 更新菜单：\n"
            "• 「更新菜单」- 同步最新菜单配置到企业微信\n\n"
        )

    # ── 菜单同步 ──────────────────────────────────

    def _handle_sync_menu(self, from_user: str) -> str:
        """处理更新菜单请求"""
        try:
            port = int(os.getenv('PORT', 5001))
            url = f"http://localhost:{port}/api/qywx/sync_menu"
            resp = requests.post(url, timeout=10)
            result = resp.json()
            if result.get('success'):
                logger.info(f"用户 {from_user} 触发菜单更新成功")
                return '✅ 菜单更新成功'
            else:
                logger.warning(f"用户 {from_user} 触发菜单更新失败: {result.get('message')}")
                return f'❌ 菜单更新失败: {result.get("message")}'
        except Exception as e:
            logger.error(f"用户 {from_user} 触发菜单更新异常: {e}")
            return f'❌ 菜单更新异常: {str(e)}'
