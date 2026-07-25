#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交易服务 - 解析用户消息并创建交易"""
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from books.client import BookkeepingClient
from config import get_config

logger = logging.getLogger(__name__)


def parse_time_from_text(text: str):
    """
    从文本中解析自然语言时间表达式，返回 (cleaned_text, datetime_or_None)
    从文本中移除时间关键词，剩余文本继续用于记账解析。

    支持的格式：
    - 昨天 / 昨日                    → 昨天当前时刻
    - 前天 / 前日                    → 前天当前时刻
    - X月Y号 / X月Y日                → 今年X月Y日当前时刻
    - Y号 / Y日（本月的Y日）          → 本月Y日当前时刻
    - HH:MM / HH：MM                → 今天指定时刻
    - (早上/上午/中午/下午/晚上)X点     → 今天指定时刻（含时段调整）
    - X点Y分 / X点半                 → 今天指定时刻
    - X分钟前                        → 相对时间
    - 上述日期＋时间组合               → 组合后的时刻
    """
    now = datetime.now()
    rest = text.strip()

    year, month, day = now.year, now.month, now.day
    hour, minute = now.hour, now.minute
    has_date = False
    has_time = False

    # === 1. 日期解析 ===

    # 昨天/前天
    m = re.search(r'昨天|昨日', rest)
    if m:
        d = now - timedelta(days=1)
        year, month, day = d.year, d.month, d.day
        has_date = True
        rest = rest[:m.start()] + rest[m.end():]

    m = re.search(r'前天|前日', rest)
    if m:
        d = now - timedelta(days=2)
        year, month, day = d.year, d.month, d.day
        has_date = True
        rest = rest[:m.start()] + rest[m.end():]

    # "X月Y号/日" 或 "X月Y"
    m = re.search(r'(\d{1,2})\s*月\s*(\d{1,2})\s*(?:[号日])?', rest)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
        has_date = True
        rest = rest[:m.start()] + rest[m.end():]
        # 年份默认今年（用户在当月说"12月25号"通常指今年12月）

    # 单独的 "Y号/日"（非紧跟月）
    m = re.search(r'(?<!\d)(\d{1,2})\s*[号日](?!\s*月)', rest)
    if m and not has_date:
        d = int(m.group(1))
        if 1 <= d <= 31:
            day = d
            has_date = True
            rest = rest[:m.start()] + rest[m.end():]

    # === 2. 时间解析 ===

    # HH:MM 格式（24小时制）
    m = re.search(r'(\d{1,2})[:：](\d{2})', rest)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        has_time = True
        rest = rest[:m.start()] + rest[m.end():]

    # 中文时间：X点半 / X点Y分 / (早上/下午)X点
    if not has_time:
        m = re.search(
            r'(早上|上午|中午|下午|晚上)?\s*(\d{1,2})\s*点'
            r'(?:\s*(\d{1,2})\s*分?)?\s*(半)?',
            rest
        )
        if m:
            tod = m.group(1) or ''
            hour = int(m.group(2))
            minute = int(m.group(3)) if m.group(3) else (30 if m.group(4) == '半' else 0)
            has_time = True
            rest = rest[:m.start()] + rest[m.end():]

            # 根据时段修饰词调整小时
            if tod in ('下午',) and hour < 12:
                hour += 12
            elif tod in ('晚上',) and hour < 12:
                hour += 12
            elif tod in ('早上', '上午') and hour >= 12:
                hour -= 12
            elif tod == '中午' and hour > 12:
                hour = 12

    # 无"点"的时段词：下午3 / 晚上8
    if not has_time:
        m = re.search(r'(早上|上午|中午|下午|晚上)\s*(\d{1,2})(?!\s*[点：:\d])', rest)
        if m:
            tod = m.group(1)
            hour = int(m.group(2))
            minute = 0
            has_time = True
            rest = rest[:m.start()] + rest[m.end():]

            if tod in ('下午',) and hour < 12:
                hour += 12
            elif tod in ('晚上',) and hour < 12:
                hour += 12

    # X分钟前
    if not has_time and not has_date:
        m = re.search(r'(\d+)\s*分钟前', rest)
        if m:
            mins = int(m.group(1))
            rest = rest[:m.start()] + rest[m.end():]
            return rest.strip(), now - timedelta(minutes=mins)

    # === 3. 构建最终时间 ===
    if has_time or has_date:
        try:
            pt = now.replace(year=year, month=month, day=day,
                             hour=hour, minute=minute, second=0, microsecond=0)
            return rest.strip(), pt
        except (ValueError, OverflowError):
            pass

    return rest.strip(), None


def parse_account_from_text(text: str):
    """
    从文本中解析 @账户名，返回 (cleaned_text, account_name_or_None)
    支持格式：任意位置带 @账户名
    例如：
    - "餐饮 30 @现金"       → ("餐饮 30", "现金")
    - "餐饮 30 午餐 @信用卡"  → ("餐饮 30 午餐", "信用卡")
    - "@零钱 餐饮 30"        → ("餐饮 30", "零钱")
    """
    m = re.search(r'@(\S+)', text)
    if m:
        account_name = m.group(1).strip()
        cleaned = text[:m.start()] + text[m.end():]
        return cleaned.strip(), account_name
    return text.strip(), None


def parse_transaction_notice_text(text: str) -> dict:
    """解析微信/银行类交易结果通知文本，提取金额、时间、类型和商家信息。
    
    正则规则从 ts_parse_rule 表加载，用户可通过 Web UI 配置。
    """
    cleaned = (text or '').strip()
    if not cleaned:
        return {'success': False, 'message': '空内容'}

    result = {'success': False, 'message': '未识别到交易通知'}

    # 从数据库加载匹配的解析规则
    from db import load_notice_parse_templates
    rules = load_notice_parse_templates(cleaned)

    # 按优先级应用所有匹配规则
    for rule in rules:
        field_type = rule.get('field_type', '')
        pattern = rule.get('regex_pattern', '')
        if not pattern:
            continue
        match = re.search(pattern, cleaned)
        if not match:
            continue

        if field_type == 'time' and not result.get('transaction_time'):
            try:
                g = match.groups()
                if len(g) >= 4:
                    now = datetime.now()
                    month = int(g[0])
                    day = int(g[1])
                    hour = int(g[2])
                    minute = int(g[3])
                    dt = now.replace(year=now.year, month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
                    result['transaction_time'] = dt
            except (ValueError, IndexError):
                pass

        elif field_type == 'amount' and 'amount' not in result:
            try:
                result['amount'] = float(match.group(1))
            except (ValueError, IndexError):
                pass

        elif field_type == 'merchant' and 'merchant' not in result:
            try:
                merchant = match.group(1).strip() if match.lastindex else ''
                if merchant:
                    result['merchant'] = merchant
                    if re.search(r'退款|退货|退回', merchant):
                        result['type'] = 'income'
                    elif result.get('type') != 'income':
                        result['type'] = 'expense'
            except IndexError:
                pass

        elif field_type == 'account' and 'account_hint' not in result:
            try:
                parts = [g for g in match.groups() if g]
                if parts:
                    result['account_hint'] = ''.join(parts)
            except IndexError:
                pass

        elif field_type == 'direction' and 'type' not in result:
            kw = match.group(1).lower() if match.lastindex else match.group(0).lower()
            if kw in ('退款', '退货', '退回', '收入', '到账'):
                result['type'] = 'income'
            elif kw in ('消费', '支出', '付款'):
                result['type'] = 'expense'

    # 建设银行兼容：有金额+消费关键词但没有商家，从原文提取
    if result.get('amount') is not None and 'merchant' not in result and re.search(r'消费', cleaned):
        result['merchant'] = cleaned.split('在', 1)[-1].split('消费', 1)[0].strip() if '在' in cleaned else cleaned.strip()
        if 'type' not in result:
            result['type'] = 'expense'

    # 清理 merchant 中的省略号
    if result.get('merchant'):
        result['merchant'] = result['merchant'].rstrip('…').rstrip('...').strip()

    # 可用额度（辅助字段）
    available_match = re.search(r'可用额度[:：]\s*([+-]?\d+(?:\.\d{1,2})?)\s*元?', cleaned)
    if available_match:
        result['available_amount'] = float(available_match.group(1))

    if result.get('amount') is not None and result.get('merchant'):
        result['success'] = True
        result['message'] = '已识别交易通知内容'

    return result


class TransactionService:
    """交易服务"""

    def __init__(self, source: str):
        self.client = BookkeepingClient()
        self.source = source

    def _create_transaction_with_known_category(self, category_id, amount: float, from_user: str,
                                                user_code: str, transaction_time: Optional[datetime],
                                                account_name: Optional[str], raw_message: Optional[str],
                                                message_log_id: Optional[int], comment: str,
                                                transaction_type: int) -> dict:
        """根据已知科目直接创建交易。"""
        from db import get_flat_accounts
        direction = 'income' if transaction_type == 2 else 'expense'
        account = None
        if account_name:
            flat_accounts = get_flat_accounts(user_code)
            _an_lower = account_name.lower()
            for a in flat_accounts:
                _name = a['name']
                _nl = _name.lower()
                if _nl == _an_lower or _an_lower in _nl or _nl in _an_lower:
                    account = a
                    break
        if not account:
            account = self.client.get_default_account(from_user=from_user, direction=direction, source=self.source)
        if not account:
            flat_accounts = get_flat_accounts(user_code)
            account = flat_accounts[0] if flat_accounts else None
        if not account:
            return {'success': False, 'message': '未找到可用账户，请先配置账户'}

        if transaction_time is None:
            transaction_time = datetime.now()

        result = self.client.create_transaction(
            category_id=category_id,
            amount=amount,
            account_id=account['id'],
            comment=comment or '',
            transaction_time=transaction_time,
            transaction_type=transaction_type,
            created_by=from_user,
            user_code=user_code,
            source=self.source,
            source_user=from_user,
            raw_message=raw_message,
            message_log_id=message_log_id,
        )

        if result.get('success'):
            tx_uuid = result.get('result', {}).get('uuid', '')
            tx_code = result.get('result', {}).get('verify_code', '')
            link = f'\n📊 编辑验证码：{tx_code}' if tx_uuid and tx_code else ''
            time_str = transaction_time.strftime('%Y-%m-%d %H:%M:%S')
            return {
                'success': True,
                'id': result.get('result', {}).get('id', ''),
                'uuid': tx_uuid,
                'verify_code': tx_code,
                'category_id': category_id,
                'amount': amount,
                'transaction_type': transaction_type,
                'message': f"✅ 记账成功！\n📂 科目ID:{category_id}: ¥{amount:.2f}\n"
                           f"💳 {account['name']}\n🕐 {time_str}\n"
                           f"{'📝 ' + comment if comment else ''}{link}",
            }
        return {'success': False, 'message': f'记账失败: {result.get("errorMessage", "未知错误")}'}

    def parse_and_create(self, text: str, from_user: str,
                         transaction_time: Optional[datetime] = None,
                         account_name: Optional[str] = None,
                         raw_message: Optional[str] = None,
                         message_log_id: Optional[int] = None,
                         notice_template: Optional[dict] = None) -> dict:
        """
        解析用户文本并创建交易
        支持的格式:
        - "类别 金额"             例如: 餐饮 30（支出）
        - "类别 金额 备注"        例如: 餐饮 30 午餐（支出）
        - "类别金额"             例如: 餐饮30（支出）
        - "支出 类别 金额"        例如: 支出 餐饮 30
        - "收入 类别 金额"        例如: 收入 工资 5000
        - "收入 类别 金额 备注"   例如: 收入 兼职 200 外快

        :param text: 用户输入文本
        :param from_user: 用户ID（用于记录）
        :return: {"success": bool, "message": str}
        """
        logger.info(f"[交易解析] parse_and_create 被调用: text='{text}', from_user='{from_user}'")
        text = text.strip()

        # 检查企业微信用户是否已绑定
        from db import get_user_code_by_sourceuser
        user_code = get_user_code_by_sourceuser(from_user, source=self.source)
        if not user_code:
            return {'success': False, 'message': f'⚠️ 未绑定账户（微信账号: {from_user}），请先联系管理员绑定微信账号'}

        if notice_template:
            category_name = notice_template.get('category_name') or ''
            merchant_name = notice_template.get('merchant_name') or ''
            merchant_category_name = notice_template.get('merchant_category_name') or ''
            resolved_category_name = category_name or merchant_category_name or ''
            if resolved_category_name:
                from db import get_connection
                conn = get_connection()
                try:
                    row = conn.execute("SELECT id FROM categories WHERE name=? AND (type=2 OR type=1)", (resolved_category_name,)).fetchone()
                    category_id = row['id'] if row else None
                finally:
                    conn.close()
                if category_id:
                    return self._create_transaction_with_known_category(
                        category_id=category_id,
                        amount=float(notice_template.get('amount', 0) or 0),
                        from_user=from_user,
                        user_code=user_code,
                        transaction_time=transaction_time,
                        account_name=notice_template.get('account_name'),
                        raw_message=raw_message,
                        message_log_id=message_log_id,
                        comment=notice_template.get('comment') or '',
                        transaction_type=2 if notice_template.get('direction') == 'income' else 3,
                    )

        # 检查是否是新增科目命令（提前处理，不需金额）
        add_match = re.match(r'^(新增(?:收入|支出)?)\s*(.+)$', text)
        if add_match:
            prefix = add_match.group(1)
            new_name = add_match.group(2).strip()
            if not new_name:
                return {'success': False, 'message': '请指定要创建的科目名称'}
            # 根据前缀判断类型
            cat_type = 2  # 默认支出
            type_label = '支出'
            if prefix == '新增收入':
                cat_type = 1
                type_label = '收入'
            new_cat = self.client.create_category(new_name, cat_type, created_by=from_user)
            if new_cat:
                return {'success': True, 'message': f'✅ 已创建{type_label}科目「{new_name}」\n请重新发送记账命令，例如：{new_name} 30'}
            return {'success': False, 'message': f'创建{type_label}科目失败，可能名称已存在'}

        # 尝试匹配 "类别 金额 备注" 或 "类别 金额"
        # 支持整数、小数和负数金额（如 -8.8 表示退款）
        pattern = r'^(.+?)\s+(-?\d+(?:\.\d{1,2})?)(?:\s+(.*))?$'
        match = re.match(pattern, text)

        if not match:
            # 尝试匹配 "类别金额" 无空格格式
            pattern2 = r'^(.+?)(-?\d+(?:\.\d{1,2})?)$'
            match = re.match(pattern2, text)

        if not match:
            return {
                'success': False,
                'message': '格式不正确，请发送：类别 金额 备注\n例如：餐饮 30 午餐',
            }

        category_name = match.group(1).strip()
        amount_str = match.group(2)
        comment = match.group(3).strip() if len(match.groups()) > 2 and match.group(3) else ''

        # 判断收入/支出类型
        transaction_type = 3  # 默认支出
        type_label = '支出'
        if category_name.startswith('收入'):
            transaction_type = 2
            type_label = '收入'
            category_name = category_name[2:].strip()
        elif category_name.startswith('支出'):
            category_name = category_name[2:].strip()
        elif category_name.startswith('消费'):
            category_name = category_name[2:].strip()

        if not category_name:
            return {
                'success': False,
                'message': f'请指定{type_label}类别，例如：{"收入 工资 5000" if transaction_type == 2 else "餐饮 30"}',
            }

        # 解析金额
        try:
            amount = float(amount_str)
            if amount == 0:
                return {
                    'success': False,
                    'message': '金额不能为0',
                }
        except ValueError:
            return {
                'success': False,
                'message': f'金额格式不正确: {amount_str}',
            }

        # 查找类别
        category_type = 'income' if transaction_type == 2 else 'expense'
        resolved_category_name = category_name
        resolved_category_id = None
        category = self.client.find_category_by_name(category_name, category_type=category_type)
        if not category:
            # 检查别名表（用 ID 查找，防名称变更）
            from db import resolve_alias
            alias_id, alias_name = resolve_alias(category_name, 'category')
            if alias_id:
                resolved_category_name = alias_name or category_name
                resolved_category_id = alias_id
                category = self.client.find_category_by_id(alias_id, category_type)
                if category:
                    logger.info(f"别名解析: 「{category_name}」→ ID={alias_id} ({category.get('name')})")
        if not category:
            available_list, available_text = self._get_category_tree_text(category_type)
            logger.info(f"[交易解析] 科目未找到: '{category_name}', type={category_type}, 可用列表={available_list[:5]}..., 即将返回 needs_resolve")
            return {
                'success': False,
                'needs_resolve': True,
                'resolve_type': 'category',
                'original_input': category_name,
                'available': available_list[:30],
                'available_text': available_text,
                'pending_data': {
                    'text': text, 'from_user': from_user,
                    'category_name': category_name, 'amount_str': amount_str,
                    'comment': comment, 'transaction_type': transaction_type,
                    'type_label': type_label, 'user_code': user_code,
                    'transaction_time': transaction_time,
                    'account_name': account_name,
                    'raw_message': raw_message,
                    'message_log_id': message_log_id,
                },
                'message': f'未找到{type_label}类别「{category_name}」\n'
                           f'可用{type_label}类别：\n{available_text}\n'
                           f'请回复序号选择（0取消）',
            }

        # 安全检查：查到的科目是顶级/主科目时拒绝交易（不允许自动创建子科目）
        if not resolved_category_id and (category.get('parentId') == '0' or not category.get('parentId')):
            logger.warning(f"查到的科目是顶级科目，拒绝交易: {category.get('name')} (id={category.get('id')})")
            available_list, available_text = self._get_category_tree_text(category_type)
            return {
                'success': False,
                'needs_resolve': True,
                'resolve_type': 'category',
                'original_input': category_name,
                'available': available_list[:30],
                'available_text': available_text,
                'pending_data': {
                    'text': text, 'from_user': from_user,
                    'category_name': category_name, 'amount_str': amount_str,
                    'comment': comment, 'transaction_type': transaction_type,
                    'type_label': type_label, 'user_code': user_code,
                    'transaction_time': transaction_time,
                    'account_name': account_name,
                    'raw_message': raw_message,
                    'message_log_id': message_log_id,
                },
                'message': f'「{category_name}」是顶级科目，无法直接使用。\n'
                           f'请从以下{type_label}类别中选择：\n{available_text}\n'
                           f'回复序号选择（0取消）',
            }

        # 根据发送用户和交易类型获取账户
        # 如果消息中指定了 @账户名，优先使用指定账户
        direction = 'income' if transaction_type == 2 else 'expense'
        account = None

        if account_name:
            # 在可用账户中查找匹配（使用统一过滤，排除他人绑定账户）
            from db import get_flat_accounts
            flat_accounts = get_flat_accounts(user_code)
            _an_lower = account_name.lower()
            _match_score = -1
            for a in flat_accounts:
                _name = a['name']
                _nl = _name.lower()
                # 精确匹配
                if _nl == _an_lower:
                    account = a
                    _match_score = 100
                    break
                # 用户输入包含在账户名中（如 "信用" → "信用卡"）
                if _an_lower in _nl and len(_an_lower) > _match_score:
                    account = a
                    _match_score = len(_an_lower)
                # 账户名包含在用户输入中（如 "信用卡" → "信用"）
                if _nl in _an_lower and len(_nl) > _match_score:
                    account = a
                    _match_score = len(_nl)
            if not account:
                # 检查别名表（用 ID 查找，防账户重命名）
                from db import resolve_alias
                alias_id, alias_name = resolve_alias(account_name, 'account')
                if alias_id:
                    for a in flat_accounts:
                        if str(a.get('id')) == str(alias_id):
                            account = a
                            logger.info(f"别名解析: 账户「{account_name}」→ ID={alias_id} ({a.get('name')})")
                            break
                    if not account:
                        logger.warning(f"别名指向的账户 ID={alias_id} 不存在，尝试按名称匹配")
                        if alias_name:
                            for a in flat_accounts:
                                if a['name'] == alias_name:
                                    account = a
                                    break
            if not account:
                # 没找到匹配，返回可选账户列表给 handler
                acct_names = [a['name'] for a in flat_accounts]
                available_text = '\n'.join(f'{i+1}. {name}' for i, name in enumerate(acct_names))
                return {
                    'success': False,
                    'needs_resolve': True,
                    'resolve_type': 'account',
                    'original_input': account_name,
                    'available': acct_names,
                    'available_text': available_text,
                    'pending_data': {
                        'text': text, 'from_user': from_user,
                        'category_name': category_name, 'amount_str': amount_str,
                        'comment': comment, 'transaction_type': transaction_type,
                        'type_label': type_label, 'user_code': user_code,
                        'transaction_time': transaction_time,
                        'account_name': account_name,
                        'resolved_category_name': resolved_category_name,
                        'category_id': category['id'],
                        'raw_message': raw_message,
                        'message_log_id': message_log_id,
                    },
                    'message': f'未找到账户「{account_name}」\n'
                               f'可用账户：\n{available_text}\n'
                               f'请回复序号选择（0取消）',
                }
            if not account:
                # 没找到匹配的账户名，用默认逻辑
                logger.warning(f"未找到指定账户「{account_name}」，使用默认账户")

        if not account:
            account = self.client.get_default_account(from_user=from_user, direction=direction, source=self.source)
        if not account:
            from db import get_flat_accounts
            flat_accounts = get_flat_accounts(user_code)
            if flat_accounts:
                account = flat_accounts[0]
            else:
                return {
                    'success': False,
                    'message': '未找到可用账户，请先配置账户',
                }

        # 备注：source/source_user 字段已记录来源，备注中不再重复标记
        full_comment = comment or ''

        # 创建交易
        if transaction_time is None:
            transaction_time = datetime.now()
        type_label = '收入' if transaction_type == 2 else '支出'
        logger.debug(f"[保存交易] 准备创建: category_id={category['id']}, amount={amount}, "
                     f"account_id={account['id']}, tx_type={transaction_type}, "
                     f"user_code={user_code}, from_user={from_user}")
        result = self.client.create_transaction(
            category_id=category['id'],
            amount=amount,
            account_id=account['id'],
            comment=full_comment,
            transaction_time=transaction_time,
            transaction_type=transaction_type,
            created_by=from_user,
            user_code=user_code,
            source=self.source,
            source_user=from_user,
            raw_message=raw_message,
            message_log_id=message_log_id,
        )
        logger.debug(f"[保存交易] create_transaction 返回: success={result.get('success')}, "
                     f"id={result.get('result', {}).get('id', '')}, "
                     f"uuid={result.get('result', {}).get('uuid', '')}")

        if result.get('success'):
            # 记录账单
            tx_id = result.get('result', {}).get('id', '')
            tx_uuid = result.get('result', {}).get('uuid', '')

            icon = '💵' if transaction_type == 2 else '💳'
            time_str = transaction_time.strftime('%Y-%m-%d %H:%M:%S')
            acct_display = f" {icon} {account['name']}"
            link = ''
            tx_code = ''
            if tx_uuid:
                # 使用数据库保存的验证码（与 add_transaction 一致）
                tx_code = result.get('result', {}).get('verify_code', '')
            if tx_uuid and tx_code:
                    from config import get_config
                    _c = get_config()
                    link = f'\n📊 编辑验证码：{tx_code}'
            return {
                'success': True,
                'id': result.get('result', {}).get('id', ''),
                'uuid': tx_uuid,
                'verify_code': tx_code,
                'category_id': category['id'],
                'amount': amount,
                'transaction_type': transaction_type,
                'resolved_category_name': resolved_category_name if resolved_category_name != category_name else None,
                'resolved_id': resolved_category_id or category.get('id'),
                'message': f"✅ 记账成功！\n"
                           f"📂 {category['name']}: ¥{amount:.2f}\n"
                           f"{acct_display}\n"
                           f"🕐 {time_str}\n"
                           f"{'📝 ' + comment if comment else ''}"
                           f"{link}",
            }
        else:
            logger.error(f"创建交易失败: {result}")
            return {
                'success': False,
                'message': f'记账失败: {result.get("errorMessage", "未知错误")}',
            }

    def _get_available_category_names(self, category_type: str = 'expense') -> str:
        """获取可用的类别名称列表（区分一级/二级科目）"""
        categories = self.client.get_categories(category_type=category_type)

        lines = []

        def _format_cat(item, depth=0):
            name = item.get('name', '')
            subs = item.get('subCategories', [])
            if depth == 0:
                # 一级科目
                if subs:
                    lines.append(f"📂 {name}（一级科目，不能直接使用）")
                    for sub in subs:
                        _format_cat(sub, depth=1)
                else:
                    lines.append(f"   • {name}")
            else:
                # 二级科目
                lines.append(f"   └ {name}")

        for item in categories:
            _format_cat(item)

        return '\n'.join(lines[:30]) if lines else '（暂无类别）'

    def _get_available_category_list(self, category_type: str = 'expense') -> list:
        """获取可选的子科目名称列表（仅二级/叶子科目，用于序号选择）"""
        categories = self.client.get_categories(category_type=category_type)
        result = []
        for item in categories:
            subs = item.get('subCategories', [])
            if subs:
                for sub in subs:
                    result.append(sub.get('name', ''))
            else:
                result.append(item.get('name', ''))
        return result

    def _get_category_tree_text(self, category_type: str = 'expense') -> tuple:
        """返回 (序号列表, 层级显示文本)，一级科目作为分组标题不给序号。"""
        categories = self.client.get_categories(category_type=category_type)
        available = []   # 可选序号列表
        lines = []       # 显示文本
        for item in categories:
            name = item.get('name', '')
            subs = item.get('subCategories', [])
            if subs:
                lines.append(f'\n📂 {name}')
                for sub in subs:
                    idx = len(available) + 1
                    available.append(sub.get('name', ''))
                    lines.append(f'  {idx}. {sub["name"]}')
            else:
                idx = len(available) + 1
                available.append(name)
                lines.append(f'  {idx}. {name}')
        return available, '\n'.join(lines).lstrip('\n')

    def create_from_resolved(self, pending_data: dict, resolved_value: str,
                              resolve_type: str = 'category') -> dict:
        """
        根据已修正的科目/账户名创建交易（交互选择后的回调）
        """
        from_user = pending_data['from_user']
        transaction_time = pending_data.get('transaction_time')

        from db import get_user_code_by_sourceuser
        user_code = get_user_code_by_sourceuser(from_user, source=self.source)
        if not user_code:
            return {'success': False, 'message': f'⚠️ 未绑定账户（微信账号: {from_user}）'}

        if resolve_type == 'category':
            return self._finish_create_with_category(
                pending_data, resolved_value, from_user, user_code, transaction_time
            )
        elif resolve_type == 'account':
            return self._finish_create_with_account(
                pending_data, resolved_value, from_user, user_code, transaction_time
            )
        return {'success': False, 'message': '未知的修正类型'}

    def _finish_create_with_category(self, pending, resolved_name, from_user, user_code, transaction_time):
        """选择科目后的创建"""
        category_type = 'income' if pending['transaction_type'] == 2 else 'expense'
        # 优先用 pending 中已有的 category_id（别名解析或之前已确定）
        category = None
        if pending.get('category_id'):
            category = self.client.find_category_by_id(pending['category_id'], category_type)
        if not category:
            category = self.client.find_category_by_name(resolved_name, category_type=category_type)
        if not category:
            return {'success': False, 'message': f'科目「{resolved_name}」不存在'}

        amount = float(pending['amount_str'])
        comment = pending.get('comment', '')
        direction = 'income' if pending['transaction_type'] == 2 else 'expense'

        account = None
        account_needs_resolve = False
        if pending.get('account_name'):
            account = self._find_account(pending['account_name'], user_code)
            if not account:
                # 用户用 @ 指定了账户但没找到，进入账户选择
                account_needs_resolve = True
        if not account and not account_needs_resolve:
            account = self.client.get_default_account(from_user=from_user, direction=direction, source=self.source)
        if not account and not account_needs_resolve:
            from db import get_flat_accounts
            flat = get_flat_accounts(user_code)
            account = flat[0] if flat else None

        if account_needs_resolve:
            # 科目已解决，但账户需要选择（使用统一过滤，排除他人绑定账户）
            from db import get_flat_accounts
            flat_accounts = get_flat_accounts(user_code)
            acct_names = [a['name'] for a in flat_accounts]
            available_text = '\n'.join(f'{i+1}. {name}' for i, name in enumerate(acct_names))
            # 把已解决的科目信息带到账户选择阶段
            new_pending = dict(pending)
            new_pending['category_id'] = category['id']
            new_pending['category_name'] = category['name']
            new_pending['resolved_category_name'] = resolved_name
            return {
                'success': False,
                'needs_resolve': True,
                'resolve_type': 'account',
                'original_input': pending['account_name'],
                'available': acct_names,
                'available_text': available_text,
                'pending_data': new_pending,
                'message': f'✅ 科目已选择：「{resolved_name}」\n'
                           f'未找到账户「{pending["account_name"]}」\n'
                           f'可用账户：\n{available_text}\n'
                           f'请回复序号选择（0取消）',
            }

        if not account:
            return {'success': False, 'message': '未找到可用账户'}

        if transaction_time is None:
            transaction_time = datetime.now()

        logger.debug(f"[_finish_create_with_category] 创建交易: category_id={category['id']}, "
                     f"account_id={account['id']}, amount={amount}, user_code={user_code}")
        result = self.client.create_transaction(
            category_id=category['id'], amount=amount, account_id=account['id'],
            comment=comment or '', transaction_time=transaction_time,
            transaction_type=pending['transaction_type'],
            created_by=from_user, user_code=user_code, source=self.source, source_user=from_user,
            raw_message=pending.get('raw_message'),
            message_log_id=pending.get('message_log_id'),
        )
        logger.debug(f"[_finish_create_with_category] 结果: success={result.get('success')}, "
                     f"id={result.get('result', {}).get('id', '')}")

        if result.get('success'):
            tx_uuid = result.get('result', {}).get('uuid', '')
            icon = '💵' if pending['transaction_type'] == 2 else '💳'
            time_str = transaction_time.strftime('%Y-%m-%d %H:%M:%S')
            link = ''
            vcode = result.get('result', {}).get('verify_code', '')
            if tx_uuid and vcode:
                link = f'\n📊 编辑验证码：{vcode}'
            return {
                'success': True, 'id': result.get('result', {}).get('id', ''),
                'uuid': tx_uuid, 'verify_code': vcode, 'resolved_category_name': resolved_name,
                'resolved_id': category.get('id'),
                'message': f"✅ 记账成功！\n📂 {category['name']}: ¥{amount:.2f}\n"
                           f"{icon} {account['name']}\n🕐 {time_str}\n"
                           f"{'📝 ' + comment if comment else ''}{link}",
            }
        return {'success': False, 'message': f'记账失败: {result.get("errorMessage", "未知错误")}'}

    def _finish_create_with_account(self, pending, resolved_name, from_user, user_code, transaction_time):
        """选择账户后的创建"""
        account = self._find_account(resolved_name, user_code)
        if not account:
            return {'success': False, 'message': f'账户「{resolved_name}」不存在'}

        amount = float(pending['amount_str'])
        comment = pending.get('comment', '')
        if transaction_time is None:
            transaction_time = datetime.now()

        logger.debug(f"[_finish_create_with_account] 创建交易: category_id={pending['category_id']}, "
                     f"account_id={account['id']}, amount={amount}")
        result = self.client.create_transaction(
            category_id=pending['category_id'], amount=amount, account_id=account['id'],
            comment=comment or '', transaction_time=transaction_time,
            transaction_type=pending['transaction_type'],
            created_by=from_user, user_code=user_code, source=self.source, source_user=from_user,
            raw_message=pending.get('raw_message'),
            message_log_id=pending.get('message_log_id'),
        )

        if result.get('success'):
            tx_uuid = result.get('result', {}).get('uuid', '')
            icon = '💵' if pending['transaction_type'] == 2 else '💳'
            time_str = transaction_time.strftime('%Y-%m-%d %H:%M:%S')
            link = ''
            vcode = result.get('result', {}).get('verify_code', '')
            if tx_uuid and vcode:
                link = f'\n📊 编辑验证码：{vcode}'
            # 获取实际科目名称（已由科目选择阶段确定）
            from db import get_connection
            _conn = get_connection()
            try:
                _cur = _conn.execute("SELECT name FROM categories WHERE id=?", (pending['category_id'],))
                _r = _cur.fetchone()
                _cat_name = _r['name'] if _r else pending.get('category_name', '')
            finally:
                _conn.close()
            return {
                'success': True, 'id': result.get('result', {}).get('id', ''),
                'uuid': tx_uuid, 'resolved_account_name': resolved_name,
                'resolved_id': account.get('id'),
                'message': f"✅ 记账成功！\n📂 {_cat_name}: ¥{amount:.2f}\n"
                           f" {icon} {account['name']}\n🕐 {time_str}\n"
                           f"{'📝 ' + comment if comment else ''}{link}",
            }
        return {'success': False, 'message': f'记账失败: {result.get("errorMessage", "未知错误")}'}

    def _find_account(self, name: str, user_code: str = None) -> Optional[dict]:
        """在可用账户（含子账户）中按名称查找"""
        from db import get_flat_accounts
        for a in get_flat_accounts(user_code):
            if a.get('name') == name:
                return a
        return None
