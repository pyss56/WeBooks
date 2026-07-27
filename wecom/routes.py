#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""企业微信消息收发路由"""
import json
import logging
import os
import re
from datetime import datetime

from flask import Blueprint, request, jsonify

from config import get_config
from wecom.crypto import WXBizMsgCrypt, parse_xml, build_reply_xml, build_encrypted_reply_xml
from wecom.handler import WeComMessageHandler
from wecom.client import WeComClient

logger = logging.getLogger(__name__)
bp = Blueprint('wecom_routes', __name__)

config = get_config()
message_handler = WeComMessageHandler()
wecom_client = WeComClient()

# 已处理的图片 MsgId 缓存（防止 WeChat Work 超时重试导致重复入账）
_processed_image_ids = set()

MENU_BUTTONS = [
    {"name": "家庭", "sub_button": [
        {"name": "今日汇总", "type": "click", "key": "TODAY_SUMMARY"},
        {"name": "本月汇总", "type": "click", "key": "MONTH_SUMMARY"},
    ]},
    {"name": "个人", "sub_button": [
        {"name": "我的今日", "type": "click", "key": "MY_TODAY"},
        {"name": "我的本月", "type": "click", "key": "MY_MONTH"},
        {"name": "他人今日", "type": "click", "key": "OTHER_TODAY"},
        {"name": "他人本月", "type": "click", "key": "OTHER_MONTH"},
        {"name": "快捷转账", "type": "click", "key": "QUICK_TRANSFER"},
    ]},
    {"name": "更多", "sub_button": [
        {"name": "后台管理", "type": "view", "url": config.BASE_URL + "/"},
        {"name": "绑定账户", "type": "click", "key": "SWITCH_ACCOUNT"},
        {"name": "使用帮助", "type": "click", "key": "HELP"},
    ]},
]


def _clean_account_name(raw: str) -> str:
    """清理 OCR 识别的账户名：去除括号，保留数字

    如 "建设眼行信用卡(5522)" → "建设眼行信用卡5522"
    如 "建设眼行信用卡55522"  → "建设眼行信用卡55522"
    """
    return re.sub(r'[()（）]', '', raw).strip()


def _handle_image_message(msg_data: dict, from_user: str, message_log_id: int = None) -> str:
    """处理企业微信图片消息 - OCR识别消费截图并自动记账"""
    import uuid as _uuid
    import requests as _req
    from services.ocr import ocr_image, parse_screenshot, is_ocr_available, UPLOAD_DIR

    media_id = msg_data.get('MediaId', '')
    pic_url = msg_data.get('PicUrl', '')
    msg_id = msg_data.get('MsgId', '')

    if not media_id and not pic_url:
        return '❌ 未获取到图片信息，请重新发送截图'

    # 消息去重：同一 MsgId 只处理一次
    if msg_id:
        if msg_id in _processed_image_ids:
            logger.info(f"图片消息去重跳过: MsgId={msg_id}")
            return ''
        _processed_image_ids.add(msg_id)
        if len(_processed_image_ids) > 1000:
            _processed_image_ids.clear()

    if not is_ocr_available():
        logger.warning(f"用户 {from_user} 发送了截图，但OCR引擎不可用")
        return (
            '📷 已收到您的截图，但 OCR 识别功能暂未安装\n'
            '请联系管理员安装 ddddocr：pip install ddddocr\n\n'
            '您也可以尝试手动输入记账命令，格式：类别 金额 备注'
        )

    # 下载图片 — 优先使用 PicUrl（CDN直链，无需API代理）
    ext = 'jpg'
    saved_name = f"wecom_{_uuid.uuid4().hex}.{ext}"
    saved_path = os.path.join(UPLOAD_DIR, saved_name)

    download_ok = False
    if pic_url:
        logger.info(f"从 PicUrl 下载图片: {pic_url[:64]}... 保存到 {saved_path}")
        try:
            resp = _req.get(pic_url, timeout=30)
            if resp.status_code == 200 and len(resp.content) > 0:
                with open(saved_path, 'wb') as f:
                    f.write(resp.content)
                logger.info(f"PicUrl 图片下载成功: size={len(resp.content)}")
                download_ok = True
            else:
                logger.warning(f"PicUrl 下载失败: status={resp.status_code}")
        except Exception as e:
            logger.warning(f"PicUrl 下载异常，尝试 MediaId 下载: {e}")

    if not download_ok and media_id:
        logger.info(f"从 MediaId 下载图片: media_id={media_id[:16]}...")
        download_ok = wecom_client.get_media(media_id, saved_path)
    if not download_ok:
        return '❌ 图片下载失败，请重新发送截图'

    try:
        # OCR 识别
        logger.info(f"开始 OCR 识别: {saved_path}")
        texts = ocr_image(saved_path)
        if not texts:
            return (
                '📷 未能识别到文字\n'
                '请确保截图清晰，或手动发送：\n'
                '类别 金额 备注\n'
                '如：餐饮 30 午餐'
            )

        # 解析截图
        parsed = parse_screenshot(texts)
        bill_type = parsed.get('bill_type', 'expense')
        amount = parsed.get('amount')
        transaction_time = parsed.get('transaction_time')
        merchant = parsed.get('merchant', '')
        account_name = parsed.get('account_name', '')

        logger.info(f"OCR 解析结果: type={bill_type}, amount={amount}, "
                     f"time={transaction_time}, merchant={merchant}, account={account_name}")

        # ── 消息1：识别结果 ──
        type_label = '支出' if bill_type == 'expense' else '收入'
        lines = []

        if amount:
            lines.append(f'✅ 💵 金额：¥{amount:.2f}')
        else:
            lines.append('❌ ❌ 💵 金额：未识别')
        if merchant:
            lines.append(f'✅ 🏪 商户：{merchant}')
        else:
            lines.append('❌ ❌ 🏪 商户：未识别')
        if account_name:
            lines.append(f'✅ 🏦 账户：{account_name}')
        else:
            lines.append('❌ ❌ 🏦 账户：未识别')
        if transaction_time:
            lines.append(f'✅ 🕐 时间：{transaction_time}')
        else:
            lines.append('❌ ❌ 🕐 时间：未识别')

        cmd = merchant or ('其他支出' if bill_type == 'expense' else '其他收入')
        cmd += f' {amount:.2f}' if amount else ' 金额'
        if account_name:
            # 清理账户名：OCR 可能漏掉括号，将尾部数字还原为 (卡号)
            acct_clean = _clean_account_name(account_name)
            cmd += f' @{acct_clean}'
        lines += ['', f'📝 {cmd}', '', f'（商户→科目、账户→别名自动匹配）']

        # 先发送识别结果消息
        wecom_client.send_text_message('\n'.join(lines), from_user)

        if not amount:
            return ''

        # ── 消息2：自动入账 ──
        # 构造标准记账文本，走 handle_text_message 复用完整入账逻辑
        try:
            cat_name = merchant or ('其他支出' if bill_type == 'expense' else '其他收入')
            cmd_text = f"{cat_name} {amount:.2f}"
            if account_name:
                # 清理账户名：OCR 可能漏掉括号，将尾部数字还原为 (卡号)
                acct_clean = _clean_account_name(account_name)
                cmd_text += f' @{acct_clean}'

            result_msg = message_handler.handle_text_message(
                cmd_text, from_user, message_log_id=message_log_id
            )

            if result_msg:
                wecom_client.send_text_message(result_msg, from_user)

            # 记账成功 → 将图片移至持久目录，以交易 UUID 命名
            last_tx = message_handler._last_transaction.get(
                message_handler._key(from_user))
            tx_uuid = last_tx.get('uuid') if last_tx else None
            if tx_uuid and os.path.exists(saved_path):
                from services.ocr import IMAGES_DIR
                dest = os.path.join(IMAGES_DIR, f'ts_{tx_uuid}.jpg')
                os.rename(saved_path, dest)
                logger.info(f"OCR 图片已持久化: {dest}")
        except Exception as txn_e:
            logger.error(f"OCR 自动入账异常: {txn_e}")
            wecom_client.send_text_message(
                '⚠️ 自动入账异常，请直接发送上面命令手动记账', from_user)

        return ''

    except Exception as ocr_e:
        logger.error(f"OCR 识别异常: {ocr_e}", exc_info=True)
        wecom_client.send_text_message(
            '📷 OCR 识别异常，请重新发送清晰的截图', from_user)
        return ''


def _process_message(msg_data: dict) -> str:
    """处理企业微信消息"""
    msg_type = msg_data.get('MsgType', '')
    from_user = msg_data.get('FromUserName', '')

    import json as _json
    _input_str = _json.dumps(msg_data, ensure_ascii=False, default=str)

    reply_content = ''

    # 先解析项目用户编码（用于日志）
    created_by_user = from_user
    if msg_type in ('text', 'event'):
        from db import require_user_bound
        resolved_code, _ = require_user_bound(from_user, source='wecom')
        if resolved_code:
            created_by_user = resolved_code

    # 记录消息日志，获取日志ID以便关联到交易
    message_log_id = None
    try:
        from db import add_message_log
        message_log_id = add_message_log(
            msg_type='receive',
            input_json=_input_str,
            output_json=None,
            source_user=from_user,
            source='wecom',
            result='processing',
            created_by=created_by_user
        )
    except Exception as _e:
        logger.error(f"记录消息日志失败: {_e}")

    if msg_type == 'text':
        content = msg_data.get('Content', '')
        try:
            reply_content = message_handler.handle_text_message(
                content, from_user, message_log_id=message_log_id)
        except Exception as _e:
            logger.error(f"[回调] ❌ 处理文本消息异常: {_e}", exc_info=True)
            reply_content = f'抱歉，处理消息时出现错误: {_e}'
    elif msg_type == 'image':
        try:
            reply_content = _handle_image_message(msg_data, from_user, message_log_id)
        except Exception as _e:
            logger.error(f"[回调] ❌ 处理图片消息异常: {_e}", exc_info=True)
            reply_content = f'抱歉，处理图片消息时出现错误: {_e}'
    elif msg_type == 'event':
        event = msg_data.get('Event', '')
        event_key = msg_data.get('EventKey', '')
        logger.info(f"事件详情: Event={event}, EventKey={event_key}, from={from_user}")
        try:
            reply_content = message_handler.handle_event(event, event_key, from_user)
        except Exception as _e:
            logger.error(f"[回调] ❌ 处理事件异常: {_e}", exc_info=True)
            reply_content = ''
    elif msg_type == 'voice':
        reply_content = "抱歉，暂不支持语音输入，请发送文字消息\n格式：类别 金额 备注"
    else:
        reply_content = ''

    # 更新消息日志的回复内容和结果
    if message_log_id and message_log_id > 0:
        try:
            from db import get_connection
            conn = get_connection()
            try:
                conn.execute(
                    "UPDATE message_log SET output_json=?, result=? WHERE id=?",
                    (reply_content if reply_content else None,
                     'success' if reply_content else 'no_reply',
                     message_log_id)
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as _e:
            logger.error(f"更新消息日志失败: {_e}")

    return reply_content


@bp.route('/qywx/callback', methods=['GET', 'POST'])
def qywx_callback():
    """企业微信回调入口"""
    import time as _time
    _t0 = _time.time()
    _ip = request.remote_addr or 'unknown'
    logger.debug(f"[回调] 收到请求 method={request.method} ip={_ip} args={dict(request.args)}")

    if not config.WECOM_TOKEN or not config.WECOM_ENCODING_AES_KEY:
        logger.warning("[回调] 企业微信未配置")
        return "企业微信未配置", 500

    try:
        crypt = WXBizMsgCrypt(
            config.WECOM_TOKEN,
            config.WECOM_ENCODING_AES_KEY,
            config.WECOM_CORP_ID,
        )
        logger.debug("[回调] WXBizMsgCrypt 初始化成功")
    except Exception as e:
        logger.error(f"[回调] 初始化加解密模块失败: {e}")
        return "配置错误", 500

    msg_signature = request.args.get('msg_signature', '')
    timestamp = request.args.get('timestamp', '')
    nonce = request.args.get('nonce', '')

    # URL验证（GET请求）
    if request.method == 'GET':
        echostr = request.args.get('echostr', '')
        logger.debug(f"[回调] URL验证 echostr长度={len(echostr)}")
        try:
            decrypted_echostr = crypt.verify_url(msg_signature, timestamp, nonce, echostr)
            logger.info(f"[回调] URL验证成功 耗时={_time.time()-_t0:.3f}s")
            return decrypted_echostr
        except Exception as e:
            logger.error(f"[回调] URL验证失败: {e}")
            return "验证失败", 403

    # 接收消息（POST请求）
    try:
        raw_data = request.get_data(as_text=True)
        logger.debug(f"[回调] 原始加密XML长度={len(raw_data)}")
        parsed = parse_xml(raw_data)
        encrypted = parsed.get('Encrypt', '')
        logger.debug(f"[回调] 密文长度={len(encrypted)}")

        # 验证签名
        calc_signature = crypt.get_signature(timestamp, nonce, encrypted)
        if calc_signature != msg_signature:
            logger.warning(f"[回调] 消息签名验证失败 calc={calc_signature} expect={msg_signature}")
            return "签名验证失败", 403
        logger.debug(f"[回调] 签名验证通过")

        # 解密消息
        decrypted_xml = crypt.decrypt(encrypted)
        msg_data = parse_xml(decrypted_xml)
        logger.debug(f"🔓 解密后XML:\n{decrypted_xml}")

        logger.debug(f"📩 收到消息: type={msg_data.get('MsgType')} "
                     f"event={msg_data.get('Event','')} from={msg_data.get('FromUserName')}")

        logger.debug(f"--- MSG DATA START ---")
        for k, v in msg_data.items():
            logger.debug(f"  [{k}] = {v}")
        logger.debug(f"--- MSG DATA END ---")

        # 处理消息
        reply_content = _process_message(msg_data)
        logger.debug(f"[回调] 处理结果: reply_len={len(reply_content) if reply_content else 0}")

        # 构建回复
        if reply_content:
            to_user = msg_data.get('FromUserName', '')
            from_user = msg_data.get('ToUserName', '')
            reply_xml = build_reply_xml(to_user, from_user, reply_content,
                                        nonce, timestamp)
            logger.debug(f"🔒 加密前XML:\n{reply_xml}")

            # 加密回复
            encrypted_reply = crypt.encrypt(reply_xml)
            reply_signature = crypt.get_signature(timestamp, nonce, encrypted_reply)
            encrypted_reply_xml = build_encrypted_reply_xml(
                encrypted_reply, reply_signature, timestamp, nonce
            )
            logger.debug(f"[回调] ✅ 处理完成 耗时={_time.time()-_t0:.3f}s 回复长度={len(reply_content)}")
            return encrypted_reply_xml, 200, {'Content-Type': 'application/xml'}
        else:
            logger.debug(f"[回调] ✅ 处理完成 耗时={_time.time()-_t0:.3f}s 无回复")
            return '', 200

    except Exception as e:
        logger.error(f"[回调] ❌ 处理异常: {e}", exc_info=True)
        return '', 200


@bp.route('/api/qywx/sync_menu', methods=['POST'])
def api_sync_menu():
    """同步企业微信自定义菜单"""
    try:
        result = wecom_client.create_menu(MENU_BUTTONS)
        if result.get('errcode') == 0:
            return jsonify({'success': True, 'message': '菜单同步成功'})
        else:
            return jsonify({'success': False, 'message': f'菜单同步失败: {result.get("errmsg")}'})
    except Exception as e:
        logger.error(f"同步菜单异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/test/send', methods=['POST'])
def api_test_send():
    """测试发送消息"""
    data = request.get_json() or {}
    content = data.get('content', '测试消息：WeBooks 已正常运行 🎉')
    to_user = data.get('to_user', config.WECOM_TO_USER)
    try:
        result = wecom_client.send_text_message(content, to_user)
        if result.get('errcode') == 0:
            return jsonify({'success': True, 'message': '消息发送成功'})
        else:
            return jsonify({'success': False, 'message': f'发送失败: {result.get("errmsg")}'})
    except Exception as e:
        logger.error(f"测试发送异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


def sync_menu_on_startup():
    """启动时推送菜单到企业微信"""
    if not config.WECOM_CORP_ID or not config.WECOM_CORP_SECRET:
        logger.warning("企业微信未配置，跳过菜单同步")
        return

    try:
        result = wecom_client.create_menu(MENU_BUTTONS)
        if result.get('errcode') == 0:
            logger.info("企业微信菜单同步成功")
        else:
            logger.warning(f"企业微信菜单同步失败: {result.get('errmsg')}")
    except Exception as e:
        logger.warning(f"企业微信菜单同步异常: {e}")


def init_wecom(app):
    """初始化企业微信模块：注册路由、配置校验、菜单同步"""
    app.register_blueprint(bp)
    try:
        from wecom.client import WeComClient
        WeComClient()._get_access_token()
        logger.info("✅ 企业微信配置验证成功")
    except Exception as e:
        logger.error(f"❌ 企业微信配置验证失败: {e}")
        logger.warning("服务将继续启动，但企业微信消息功能可能不可用")
    sync_menu_on_startup()
