#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""消息处理器基类 - 多平台消息处理（企业微信、钉钉等）"""
import logging
import re
from typing import Optional

from services.transaction import TransactionService, parse_time_from_text, parse_account_from_text
from services.summary import SummaryService
from services.budget import BudgetService

logger = logging.getLogger(__name__)


class MessageHandler:
    """消息处理器基类，封装平台无关的业务逻辑"""

    def __init__(self, source: str):
        self.source = source
        self.transaction_service = TransactionService(source)
        self.summary_service = SummaryService(source)
        self.budget_service = BudgetService()
        self._pending_selectors = {}
        self._pending_other_selectors = {}
        self._last_transaction = {}
        self._transfer_leaves_cache = {}
        self._pending_resolve = {}
        self._pending_actions = {}  # {key: {reply_code: {'type': str, 'data': dict, 'label': str}}}
        self._pending_selection_state = {}
        self._reply_mode = {}  # {key: 'card'|'composite'|'text'}, 平台覆写按此分流
        self._reply_data = {}  # {key: {'card_title': str, 'card_content': str}}, 卡片富文本内容

    def _key(self, from_user):
        return f"{self.source}:{from_user}"

    @property
    def bk_client(self):
        return self.transaction_service.client

    # ── 平台扩展钩子 ──────────────────────────────

    def handle_extra_command(self, content: str, from_user: str,
                             user_code: str = None) -> Optional[str]:
        """子类重写此方法处理平台特有命令，返回 None 表示未处理"""
        return None

    def handle_extra_event(self, event: str, event_key: str, from_user: str,
                           user_code: str = None) -> Optional[str]:
        """子类重写此方法处理平台特有事件，返回 None 表示未处理"""
        return None

    # ── 文本消息处理 ──────────────────────────────

    def handle_text_message(self, content: str, from_user: str,
                            message_log_id: int = None) -> str:
        content = content.strip()

        # 检查绑定
        user_code, err = self.bk_client.require_user_bound(from_user, source=self.source)
        if err:
            return err

        # 平台特有命令
        extra = self.handle_extra_command(content, from_user, user_code)
        if extra is not None:
            return extra

        # 通用命令
        if content in ('今日汇总', '今天汇总', '今日'):
            return self._handle_today_summary(from_user)
        elif content in ('本月汇总', '月汇总', '本月', '月度汇总'):
            return self._handle_month_summary(from_user)
        elif content in ('帮助', '帮助信息', '功能', '菜单', '指令'):
            return self._get_help_text()
        elif content in ('统计', '本月统计'):
            return self._handle_month_summary(from_user)
        elif content in ('我的今日', '我的'):
            return self._get_user_summary('today', '我的', from_user=from_user)
        elif content in ('我的本月', '我的月度'):
            return self._get_user_summary('month', '我的', from_user=from_user)
        elif content in ('他人今日', '他人'):
            return self._list_users_for_selection('today', from_user)
        elif content in ('他人本月', '他人月度'):
            return self._list_users_for_selection('month', from_user)
        elif content in ('绑定账户', '切换账户', '换账户', '更换账户', '切换账号', '切换'):
            self._pending_selectors[self._key(from_user)] = {'step': 'account', 'user_code': user_code}
            return self._list_accounts_for_selection(from_user, user_code)
        elif content in ('快捷转账', '转账'):
            return self._handle_quick_transfer(from_user, user_code)

        # 待处理操作选择模式（撤销/保存映射等）—— 只有 content 精确匹配已注册的 action key 才拦截
        if self._key(from_user) in self._pending_actions:
            actions = self._pending_actions.get(self._key(from_user))
            if actions and content in actions:
                return self._handle_action_input(content, from_user)

        # 通用选择模式（科目/账户/其他候选项）
        if self._key(from_user) in self._pending_selection_state:
            return self._handle_selection_input(content, from_user)

        # 科目/账户解析选择模式
        if self._key(from_user) in self._pending_resolve:
            if not re.match(r'^\d{1,3}$', content):
                self._pending_resolve.pop(self._key(from_user), None)
            else:
                return self._handle_resolve_selection(content, from_user)

        # 账户选择模式
        if self._key(from_user) in self._pending_selectors:
            state = self._pending_selectors[self._key(from_user)]
            if content == '0':
                self._pending_selectors.pop(self._key(from_user), None)
                self._transfer_leaves_cache.pop(self._key(from_user), None)
                self._transfer_leaves_cache.pop(self._key(from_user) + '_user_code', None)
                return '已取消操作'
            if isinstance(state, dict) and state.get('step') == 'account':
                uc = state.get('user_code')
                result = self._handle_account_selection(content, from_user, uc)
                if result:
                    if not state.get('_refreshed'):
                        self._pending_selectors.pop(self._key(from_user), None)
                    else:
                        state.pop('_refreshed', None)
                    return result
                return '请输入"支出序号 收入序号"（如 1 2，0=取消）'

        # 他人查询模式
        if self._key(from_user) in self._pending_other_selectors:
            if content == '0':
                self._pending_other_selectors.pop(self._key(from_user), None)
                return '已取消查询'
            result = self._handle_other_user_selection(content, from_user)
            if result:
                self._pending_other_selectors.pop(self._key(from_user), None)
                return result
            return '请输入有效序号（0=取消）'

        # 快捷转账模式
        if self._key(from_user) in self._transfer_leaves_cache:
            if content == '0':
                self._transfer_leaves_cache.pop(self._key(from_user), None)
                self._transfer_leaves_cache.pop(self._key(from_user) + '_user_code', None)
                self._pending_selectors.pop(self._key(from_user), None)
                self._pending_other_selectors.pop(self._key(from_user), None)
                return '已取消转账'
            transfer_result = self._do_quick_transfer(content, from_user, user_code)
            if transfer_result:
                return transfer_result
            return '请按格式回复：转出账户序号 转入账户序号 金额 备注（如 1 2 50 信用卡还款，0=取消）'


        # 解析记账命令
        parsed_content, parsed_time = parse_time_from_text(content)
        if parsed_time:
            logger.debug(f"⏰ 解析到交易时间: {parsed_time} (原文: {content})")
        parsed_content, parsed_account = parse_account_from_text(parsed_content)
        if parsed_account:
            logger.debug(f"🏦 解析到指定账户: {parsed_account} (原文: {content})")

        # 优先识别交易结果通知类文本，生成辅助记账建议
        from services.transaction import parse_transaction_notice_text
        from db import resolve_alias, get_flat_accounts
        notice_result = parse_transaction_notice_text(content)
        notice_account_name = None  # 从通知中识别到的账户
        _notice_account_hint = ''  # 通知中的账户提示文本，供后续别名保存
        if notice_result.get('success'):
            logger.debug(f"🧾 识别到交易结果通知: {content}")
            parsed_content = f"{notice_result['merchant']} {notice_result['amount']}"
            if notice_result.get('transaction_time'):
                parsed_time = notice_result['transaction_time']
            if notice_result.get('type') == 'income':
                parsed_content = f"收入 {parsed_content}"
            else:
                parsed_content = f"支出 {parsed_content}"
            # 用 alias 尝试匹配通知中的账户信息
            account_hint = notice_result.get('account_hint', '')
            if account_hint and not parsed_account:
                _acct_alias_id, _acct_alias_name = resolve_alias(account_hint, 'account')
                if _acct_alias_name:
                    notice_account_name = _acct_alias_name
            _notice_account_hint = account_hint if not parsed_account else ''

        # 判断是否应提示选择账户：有 account_hint 且未命中 alias
        _show_account_prompt = bool(_notice_account_hint and not notice_account_name)

        # 嵌入别名匹配信息到 raw_message
        import json as _json
        _enriched_raw = content
        if notice_result.get('success'):
            _nm = {}
            if notice_result.get('merchant'):
                _nm['merchant'] = notice_result['merchant']
            if _notice_account_hint:
                _nm['account_hint'] = _notice_account_hint
            if notice_account_name:
                _nm['account_name'] = notice_account_name
            if _nm:
                _enriched_raw = content + ' __NOTICE_MATCH__' + _json.dumps(_nm, ensure_ascii=False)

        result = self.transaction_service.parse_and_create(
            parsed_content, from_user,
            transaction_time=parsed_time,
            account_name=parsed_account or notice_account_name,
            raw_message=_enriched_raw,
            message_log_id=message_log_id)

        if result.get('needs_resolve') and result.get('resolve_type') == 'category':
            available_text = result.get('available_text', '')
            if available_text:
                original_input = result.get('original_input', '') or ''
                result['message'] = (
                    f'未找到「{original_input}」对应的记账科目，请从以下选择：\n'
                    f'{available_text}\n'
                    '回复序号选择（0取消）'
                )

        if result.get('needs_resolve'):
            pending = result.get('pending_data', {})
            # 注入通知中识别到的账户信息，供后续别名保存使用
            if _notice_account_hint and not pending.get('account_hint'):
                pending['account_hint'] = _notice_account_hint
            if notice_account_name and not pending.get('account_name'):
                pending['account_name'] = notice_account_name
            if _show_account_prompt and not pending.get('account_name'):
                pending['account_name'] = _notice_account_hint
            choice_state = {
                'available': result.get('available', []),
                'resolve_type': result.get('resolve_type', 'category'),
                'pending_data': pending,
                'original_input': result.get('original_input', ''),
                'prompt': result.get('message', '请选择'),
            }
            self._start_selection_state(from_user, choice_state)
            logger.debug(f"[handler] needs_resolve 触发, message={result['message'][:100]}")
            return choice_state['prompt']

        msg = result['message']

        if result.get('success') and 'category_id' in result:
            self._reply_mode[self._key(from_user)] = 'card'
            for scope in ('personal', 'family'):
                alert = self.budget_service.get_budget_alert(
                    scope, user_code, result['category_id'])
                if alert:
                    msg += '\n\n' + alert
            if 'id' in result:
                tx_type = 'income' if result.get('transaction_type') == 2 else 'expense'
                self._last_transaction[self._key(from_user)] = {
                    'id': result['id'],
                    'uuid': result.get('uuid', ''),
                    'type': tx_type,
                }
                self._pending_actions[self._key(from_user)] = {
                    '9': {
                        'type': 'undo',
                        'data': {'tx_id': result['id'], 'tx_type': tx_type, 'from_user': from_user},
                        'label': '撤销此笔记账',
                    },
                }
                msg += '\n\n回复9可撤销'
            self._reply_data[self._key(from_user)] = {
                'card_title': '✅ 记账成功',
                'card_content': msg,
            }
        elif not result.get('success') and '未绑定' not in msg:
            msg = self._get_accounting_help()
        return msg

    # ── 事件消息处理 ──────────────────────────────

    def handle_event(self, event: str, event_key: str, from_user: str) -> str:
        if event != 'click':
            logger.info(f"非click事件: event={event}, event_key={event_key}, from_user={from_user}")
            return self._get_help_text()

        user_code, err = self.bk_client.require_user_bound(from_user, source=self.source)
        if err:
            return err

        # 平台特有事件
        extra = self.handle_extra_event(event, event_key, from_user, user_code)
        if extra is not None:
            return extra

        if event_key == 'SWITCH_ACCOUNT':
            self._pending_selectors[self._key(from_user)] = {'step': 'account', 'user_code': user_code}
            return self._list_accounts_for_selection(from_user, user_code)
        elif event_key == 'QUICK_EXPENSE':
            expense_example = self._get_example_category_names(2, '饮料')
            income_example = self._get_example_category_names(1, '工资')
            return f'📝 快速记账：\n发送"类别 金额 备注"\n支出：{expense_example} 30\n收入：收入 {income_example} 5000'
        elif event_key == 'TODAY_SUMMARY':
            return self._handle_today_summary(from_user)
        elif event_key == 'MONTH_SUMMARY':
            return self._handle_month_summary(from_user)
        elif event_key == 'MY_TODAY':
            return self._get_user_summary('today', '我的', from_user=from_user)
        elif event_key == 'MY_MONTH':
            return self._get_user_summary('month', '我的', from_user=from_user)
        elif event_key == 'OTHER_TODAY':
            return self._list_users_for_selection('today', from_user)
        elif event_key == 'OTHER_MONTH':
            return self._list_users_for_selection('month', from_user)
        elif event_key == 'HELP':
            return self._get_help_text()
        elif event_key == 'QUICK_TRANSFER':
            return self._handle_quick_transfer(from_user, user_code)
        else:
            logger.warning(f"未知事件: event={event}, event_key={event_key}, from_user={from_user}")
            return self._get_help_text()

    # ── 科目/账户解析选择 ──────────────────────────

    def _start_selection_state(self, from_user: str, state: dict) -> str:
        """启动一个通用序号选择流。"""
        self._pending_selection_state[self._key(from_user)] = state
        return state.get('prompt', '请选择')

    def _handle_selection_input(self, content: str, from_user: str) -> str:
        """统一处理通用序号选择输入。"""
        state = self._pending_selection_state.get(self._key(from_user))
        if not state:
            return ''

        if content == '0':
            self._pending_selection_state.pop(self._key(from_user), None)
            return '已取消操作'
        if not re.match(r'^\d{1,3}$', content):
            return '请输入有效序号（0=取消）'

        try:
            idx = int(content) - 1
        except ValueError:
            return '请输入有效序号（0=取消）'

        available = state.get('available', [])
        if idx < 0 or idx >= len(available):
            return f'序号无效，请输入 1-{len(available)}（0=取消）'

        selected = available[idx]
        self._pending_selection_state.pop(self._key(from_user), None)
        # callback_data 优先：通知账户选择等自定义回调场景
        if state.get('callback_data'):
            return self._finish_account_selection_for_notice(selected, state)
        if state.get('resolve_type'):
            return self._resolve_selection_result(
                from_user,
                selected,
                state.get('resolve_type', 'category'),
                state.get('pending_data', {}),
                state,
            )
        return state.get('callback', lambda *_: '请选择')(selected, state)

    def _handle_resolve_selection(self, content: str, from_user: str) -> str:
        return self._handle_selection_input(content, from_user)

    def _resolve_selection_result(self, from_user: str, selected: str, resolve_type: str,
                                  pending_data: dict, state: dict) -> str:
        """通用选择结果处理：复用给科目/账户等选择场景。"""
        result = self.transaction_service.create_from_resolved(pending_data, selected, resolve_type)
        if result.get('success'):
            key = self._key(from_user)
            original_input = state.get('original_input', '')
            resolved_id = result.get('resolved_id', '')
            tx_id = result.get('id', '')
            notice_account_hint = pending_data.get('account_hint', '')
            notice_account_name = pending_data.get('account_name', '')

            # 自动保存科目/账户别名
            from db import add_input_alias
            alias_parts = []
            if original_input and resolved_id:
                ok = add_input_alias(
                    original_input, resolve_type, resolved_id,
                    target_name=selected, created_by=from_user)
                if ok:
                    alias_parts.append(f'科目「{original_input}」→「{selected}」')

            if resolve_type == 'category' and notice_account_hint and notice_account_name:
                from db import get_flat_accounts, get_user_code_by_sourceuser
                uc = get_user_code_by_sourceuser(from_user, source=self.source)
                for a in (get_flat_accounts(uc) if uc else []):
                    if a['name'] == notice_account_name:
                        ok2 = add_input_alias(
                            notice_account_hint, 'account', a['id'],
                            target_name=notice_account_name, created_by=from_user)
                        if ok2:
                            alias_parts.append(f'账户「{notice_account_hint}」→「{notice_account_name}」')
                        break

            # 构建最终消息
            msg = result['message']
            if alias_parts:
                msg += '\n\n✅ 已自动保存映射：' + '、'.join(alias_parts)
            # 检查是否提示账户匹配
            _account_keywords_enabled = bool(not notice_account_name and notice_account_hint)
            if _account_keywords_enabled:
                msg += f'\n💳 未匹配到账户，回复2选择账户并保存「{notice_account_hint}」识别规则'
            msg += '\n\n回复9撤销'

            # 卡片内容 = 完整消息（含别名和撤销）
            self._reply_mode[key] = 'card'
            self._reply_data[key] = {
                'card_title': '✅ 记账成功',
                'card_content': msg,
            }

            # 注册后续操作
            actions = {'9': {'type': 'undo', 'data': {'tx_id': tx_id, 'from_user': from_user}, 'label': '撤销'}}
            if _account_keywords_enabled:
                actions['2'] = {
                    'type': 'select_account',
                    'data': {
                        'from_user': from_user, 'account_hint': notice_account_hint,
                        'pending_data': pending_data, 'resolved_category': selected,
                        'resolved_category_id': resolved_id,
                    },
                    'label': '选择账户',
                }
            self._pending_actions[key] = actions
            self._pending_resolve.pop(key, None)
            return msg
        elif result.get('needs_resolve'):
            if result.get('resolve_type') == 'account':
                # 账户未匹配 → 走账户选择流程
                key = self._key(from_user)
                pending = pending_data
                if result.get('pending_data'):
                    pending = result['pending_data']
                account_hint = pending.get('account_name', '') or pending.get('account_hint', '') or result.get('original_input', '')
                select_data = {
                    'from_user': from_user,
                    'account_hint': account_hint,
                    'pending_data': pending,
                    'resolved_category': selected,
                    'resolved_category_id': result.get('resolved_id', '') or pending.get('category_id', ''),
                }
                return self._start_account_selection_for_notice(select_data, from_user)
            self._pending_resolve[self._key(from_user)] = result
            return result['message']
        else:
            self._pending_resolve.pop(self._key(from_user), None)
            return result.get('message', '创建失败')

    def _handle_action_input(self, content: str, from_user: str) -> str:
        """通用的待处理操作选择——不同回复数值对应不同业务类型。"""
        actions = self._pending_actions.get(self._key(from_user))
        if not actions:
            self._pending_actions.pop(self._key(from_user), None)
            return ''

        action = actions.get(content)
        if not action:
            # content 不在已注册的 action key 中，静默清理，不走任何业务
            self._pending_actions.pop(self._key(from_user), None)
            return ''

        self._pending_actions.pop(self._key(from_user), None)

        if action['type'] in ('undo', 'undo_booking'):
            return self._execute_undo_booking(action['data'])
        elif action['type'] == 'save_alias':
            return self._execute_save_alias(action['data'])
        elif action['type'] == 'select_account':
            return self._start_account_selection_for_notice(action['data'], from_user)
        return action.get('label', '已处理')

    def _execute_undo_booking(self, data: dict) -> str:
        """撤销交易。"""
        tx_id = data.get('tx_id', '')
        from_user = data.get('from_user', '')
        if not tx_id:
            return '撤销失败：没有可撤销的交易'
        ok = self.bk_client.delete_transaction(tx_id, updated_by=from_user)
        if ok.get('success'):
            return '✅ 已撤销此笔记账'
        return f'撤销失败: {ok.get("errorMessage", "未知错误")}'

    def _execute_save_alias(self, data: dict) -> str:
        """保存输入别名映射（科目 + 账户，如果有）。"""
        from db import add_input_alias
        parts = []
        ok = add_input_alias(
            data['original_input'], data['target_type'],
            data.get('resolved_id', ''),
            target_name=data['resolved_to'],
            created_by=data.get('from_user', ''))
        if ok:
            parts.append(f'「{data["original_input"]}」→「{data["resolved_to"]}」（科目）')
        # 如果有账户信息，一并保存
        acct_name = data.get('account_name', '')
        if acct_name:
            from db import get_user_code_by_sourceuser, get_flat_accounts
            user_code = get_user_code_by_sourceuser(data.get('from_user', ''), source=self.source)
            flat = get_flat_accounts(user_code) if user_code else []
            acct_id = ''
            for a in flat:
                if a['name'] == acct_name:
                    acct_id = a['id']
                    break
            ok_acct = add_input_alias(
                data['original_input'], 'account',
                acct_id, target_name=acct_name,
                created_by=data.get('from_user', ''))
            if ok_acct:
                parts.append(f'「{data["original_input"]}」→「{acct_name}」（账户）')
        if parts:
            return f'✅ 已保存映射：{"、".join(parts)}\n下次将自动识别'
        return '保存失败'

    # ── 通知账户选择 ──────────────────────────────

    def _start_account_selection_for_notice(self, data: dict, from_user: str) -> str:
        """启动通知账户选择流程 —— 展示可选账户列表让用户选择。"""
        flat = self._get_flat_accounts(from_user)
        if not flat:
            return '暂无可用账户'
        data['_flat'] = flat
        state = {
            'available': [a['name'] for a in flat],
            'callback_data': data,
        }
        self._start_selection_state(from_user, state)
        lines = [f"📋 选择此通知对应的账户（回复序号，0=取消）："]
        for i, a in enumerate(flat, 1):
            lines.append(f"{i}. {a.get('_display_name', a['name'])}")
        return '\n'.join(lines)

    def _finish_account_selection_for_notice(self, selected_name: str, state: dict) -> str:
        """账户选定后：保存别名映射 + 创建交易。"""
        data = state.get('callback_data', {})
        account_hint = data.get('account_hint', '')
        flat = data.get('_flat', [])
        pending_data = data.get('pending_data', {})
        resolved_category = data.get('resolved_category', '')
        resolved_category_id = data.get('resolved_category_id', '')

        selected_account = next((a for a in flat if a['name'] == selected_name), None)
        if not selected_account:
            return '账户未找到'

        from_user = data.get('from_user', '')
        parts = []

        from db import add_input_alias, get_user_code_by_sourceuser

        # ① 保存账户别名
        if account_hint:
            alias_ok = add_input_alias(
                account_hint, 'account',
                selected_account['id'],
                target_name=selected_name,
                created_by=from_user)
            if alias_ok:
                parts.append(f'账户「{account_hint}」→「{selected_name}」')

        # ② 保存科目别名
        original_input = pending_data.get('category_name', '')
        if original_input and resolved_category_id:
            ok_cat = add_input_alias(
                original_input, 'category',
                resolved_category_id, target_name=resolved_category,
                created_by=from_user)
            if ok_cat:
                parts.append(f'科目「{original_input}」→「{resolved_category}」')

        # ③ 创建交易
        user_code = get_user_code_by_sourceuser(from_user, source=self.source) or ''
        if user_code and resolved_category_id:
            from datetime import datetime
            amount = float(pending_data.get('amount_str', 0) or 0)
            tx_type = pending_data.get('transaction_type', 3)
            ttime = pending_data.get('transaction_time') or datetime.now()
            tx_result = self.bk_client.create_transaction(
                category_id=resolved_category_id,
                amount=amount,
                account_id=selected_account['id'],
                comment=pending_data.get('comment', '') or '',
                transaction_time=ttime,
                transaction_type=tx_type,
                created_by=from_user,
                user_code=user_code,
                source=self.source,
                source_user=from_user,
                raw_message=pending_data.get('raw_message'),
                message_log_id=pending_data.get('message_log_id'),
            )
            if tx_result.get('success'):
                tx_uuid = tx_result.get('result', {}).get('uuid', '')
                tx_id = tx_result.get('result', {}).get('id', '')
                vcode = tx_result.get('result', {}).get('verify_code', '')
                parts.append(f'交易已创建 ¥{amount:.2f}')
                # 存储撤销能力
                self._last_transaction[self._key(from_user)] = {
                    'id': tx_id, 'uuid': tx_uuid, 'type': 'expense' if tx_type != 2 else 'income',
                }
                self._pending_actions[self._key(from_user)] = {
                    '9': {
                        'type': 'undo',
                        'data': {'tx_id': tx_id, 'from_user': from_user},
                        'label': '撤销此笔记账',
                    },
                }
                # 发送卡片（含验证码）
                time_str = ttime.strftime('%Y-%m-%d %H:%M:%S') if hasattr(ttime, 'strftime') else str(ttime)
                vcode_link = f'\n📊 编辑验证码：{vcode}' if tx_uuid and vcode else ''
                self._reply_mode[self._key(from_user)] = 'card'
                self._reply_data[self._key(from_user)] = {
                    'card_title': '✅ 记账成功',
                    'card_content': f'✅ 记账成功！\n📂 {resolved_category}: ¥{amount:.2f}\n💳 {selected_name}\n🕐 {time_str}{vcode_link}\n\n回复9可撤销',
                }
            else:
                parts.append(f'交易创建失败: {tx_result.get("errorMessage", "未知错误")}')

        msg = f'✅ 已配置：{"、".join(parts)}\n下次收到同类通知将自动识别'
        if any('交易已创建' in p for p in parts):
            msg += '\n\n回复9可撤销'
        return msg

    # ── 汇总查询 ──────────────────────────────────

    def _handle_today_summary(self, from_user: str) -> str:
        summary = self.summary_service.get_today_summary(from_user)
        if summary['has_data']:
            return summary['text']
        return self._get_no_data_text('今天')

    def _handle_month_summary(self, from_user: str) -> str:
        summary = self.summary_service.get_month_summary(from_user)
        if summary['has_data']:
            return summary['text']
        return self._get_no_data_text('本月')

    def _get_user_summary(self, period: str, display_name: str, from_user: str = None,
                          user_filter: str = None) -> str:
        period_label = '今日' if period == 'today' else '本月'
        if user_filter:
            if period == 'today':
                summary = self.summary_service.get_other_today_summary(display_name, user_filter)
            else:
                summary = self.summary_service.get_other_month_summary(display_name, user_filter)
            no_data = f'📭 {display_name} {period_label}暂无支出记录'
        else:
            logger.info(f"[我的{period_label}] from_user={from_user}")
            if period == 'today':
                summary = self.summary_service.get_my_today_summary(from_user)
            else:
                summary = self.summary_service.get_my_month_summary(from_user)
            logger.info(f"[我的{period_label}] has_data={summary.get('has_data')}, text_len={len(summary.get('text', ''))}")
            no_data = f'📭 你{period_label}还没有支出记录'
        if summary.get('has_data'):
            return summary['text']
        return no_data

    def _list_users_for_selection(self, period: str, from_user: str) -> str:
        try:
            users = self.bk_client.get_users()
            visible_users = [u for u in users if u.get('name') != from_user and u.get('status', 1) == 1]
            if not visible_users:
                return '暂无其他用户记录'

            self._pending_other_selectors[self._key(from_user)] = {'period': period}
            period_label = '今日' if period == 'today' else '本月'
            lines = [f"📋 选择要查看{period_label}支出的用户（回复序号，0=取消）："]
            for i, user in enumerate(visible_users, 1):
                lines.append(f"{i}. {user.get('name')}")
            return '\n'.join(lines)
        except Exception as e:
            logger.error(f"列出用户异常: {e}")
            return '获取用户列表失败'

    def _handle_other_user_selection(self, content: str, from_user: str) -> Optional[str]:
        match = re.match(r'^(?:账户\s*)?(\d+)$', content)
        if not match:
            return None
        try:
            users = [u for u in self.bk_client.get_users() if u.get('name') != from_user and u.get('status', 1) == 1]
            idx = int(match.group(1)) - 1
            if idx < 0 or idx >= len(users):
                return f'序号无效，请输入 1-{len(users)}（0=取消）'
            selected_user = users[idx]
            user_name = selected_user.get('name', '')
            user_code = selected_user.get('code', selected_user.get('name', ''))
            user_filter = f"0:{user_code}"
            info = self._pending_other_selectors.get(self._key(from_user), {})
            period = info.get('period', 'today')
            return self._get_user_summary(period, user_name, user_filter=user_filter)
        except Exception as e:
            logger.error(f"处理他人查询异常: {e}")
            return '查询失败，请稍后重试'

    # ── 账户选择 ──────────────────────────────────

    def _list_accounts_for_selection(self, from_user: str = None, user_code: str = None) -> str:
        try:
            flat_accounts = self._get_flat_accounts(from_user)
            if not flat_accounts:
                return '暂无可用账户，请先配置账户'

            expense_name = None
            income_name = None
            if user_code:
                from db import get_user_account
                expense_id = get_user_account(user_code, 'expense')
                income_id = get_user_account(user_code, 'income')
                for acc in flat_accounts:
                    aid = str(acc.get('id', ''))
                    if not expense_name and expense_id and aid == str(expense_id):
                        expense_name = acc.get('name', '')
                    if not income_name and income_id and aid == str(income_id):
                        income_name = acc.get('name', '')
            else:
                expense_id = income_id = None

            lines = ["📋 切换默认账户"]
            lines.append("─" * 20)
            lines.append(f"📤 当前支出账户：{expense_name or '未设置'}")
            lines.append(f"📥 当前收入账户：{income_name or '未设置'}")
            lines.append("─" * 20)
            lines.append("回复：支出序号 收入序号（如 1 2，同一账户用 1 1，0=取消）")

            for idx, acc in enumerate(flat_accounts, 1):
                aid = str(acc.get('id', ''))
                display = acc.get('_display_name', acc.get('name', f'账户#{aid}'))
                marks = []
                if expense_id and aid == str(expense_id):
                    marks.append('支出')
                if income_id and aid == str(income_id):
                    marks.append('收入')
                mark = f' ← {"+".join(marks)}' if marks else ''
                lines.append(f"{idx}. {display}{mark}")

            from db import _account_cache_version
            self._pending_selectors[self._key(from_user)] = {
                'step': 'account',
                'user_code': user_code,
                'flat_accounts': flat_accounts,
                'cache_version': _account_cache_version,
            }
            return '\n'.join(lines)
        except Exception as e:
            logger.error(f"获取账户列表异常: {e}")
            return '获取账户列表失败，请稍后重试'

    def _handle_account_selection(self, content: str, from_user: str, user_code: str = None) -> Optional[str]:
        match = re.match(r'^\s*(\d+)\s+(\d+)\s*$', content)
        if not match:
            return None

        state = self._pending_selectors.get(self._key(from_user), {})
        accounts = state.get('flat_accounts')

        from db import _account_cache_version
        if not accounts or state.get('cache_version', -1) != _account_cache_version:
            fresh = self._get_flat_accounts(from_user)
            if not fresh:
                return '暂无可用账户'
            state['flat_accounts'] = fresh
            state['cache_version'] = _account_cache_version
            accounts = fresh
            state['_refreshed'] = True
            notice = '⚠️ 账户或绑定已变更，列表已更新，请重新选择'
            return notice + '\n\n' + self._list_accounts_for_selection(from_user, user_code)

        exp_idx = int(match.group(1)) - 1
        inc_idx = int(match.group(2)) - 1

        if exp_idx < 0 or exp_idx >= len(accounts):
            return f'支出序号无效，请输入 1-{len(accounts)}'
        if inc_idx < 0 or inc_idx >= len(accounts):
            return f'收入序号无效，请输入 1-{len(accounts)}'

        exp_acct = accounts[exp_idx]
        inc_acct = accounts[inc_idx]

        from books.client import BookkeepingClient
        ok1 = BookkeepingClient.save_user_account(user_code, exp_acct['id'], 'expense', updated_by=user_code)
        ok2 = BookkeepingClient.save_user_account(user_code, inc_acct['id'], 'income', updated_by=user_code)

        if ok1 and ok2:
            self._pending_selectors.pop(self._key(from_user), None)
            return (f'✅ 已完成默认账户设置\n'
                    f'📤 支出：{exp_acct["name"]}\n'
                    f'📥 收入：{inc_acct["name"]}')
        return '保存失败，请稍后重试'

    def _get_flat_accounts(self, from_user: str = None) -> list:
        try:
            from db import get_flat_accounts, get_user_code_by_sourceuser
            user_code = get_user_code_by_sourceuser(from_user, source=self.source) if from_user else None
            return get_flat_accounts(user_code)
        except Exception:
            return []

    # ── 帮助信息 ──────────────────────────────────

    def _get_help_text(self) -> str:
        expense_text = self._get_categories_text(category_type='expense', label='支出')
        income_text = self._get_categories_text(category_type='income', label='收入')
        expense_example = self._get_example_category_names('expense', '饮料')
        income_example = self._get_example_category_names('income', '工资')
        extra = self._get_platform_help_suffix()
        return (
            "📖 使用帮助\n"
            "─────────────\n"
            "💰 支出记账：\n"
            "发送：类别 金额 备注\n"
            f"例如：{expense_example} 30\n\n"
            "💵 收入记账：\n"
            "发送：收入 类别 金额 备注\n"
            f"例如：收入 {income_example} 5000\n\n"
            "↩️ 撤销功能：\n"
            "记账/转账成功后，回复0可撤销该笔\n\n"
            "📊 查询汇总：\n"
            "• 「今日」- 今日全部消费汇总（含家庭预算对比）\n"
            "• 「本月」- 本月全部消费汇总（含家庭预算对比）\n"
            "• 「我的今日」- 查看你自己的支出\n"
            "• 「我的本月」- 查看你本月的支出（含个人预算对比）\n"
            "• 「他人今日」- 查看其他人的今日支出\n"
            "• 「他人本月」- 查看其他人的本月支出\n\n"
            "🔄 转账功能：\n"
            "• 「转账」- 回复「转出账户序号 转入账户序号 金额 备注」执行转账\n\n"
            "🔀 绑定账户：\n"
            "• 「绑定账户」- 选择账户后可分别设为支出/收入账户\n\n"
            "📂 科目管理：\n"
            "• 通过 Web 页面管理交易科目：科目管理菜单\n\n"
            "💰 预算管理：\n"
            "• 通过 Web 页面管理预算：预算管理菜单\n\n"
            f"{extra}"
            "─────────────\n"
            f"{expense_text}\n\n{income_text}"
        )

    def _get_platform_help_suffix(self) -> str:
        """子类可重写添加平台特有帮助内容"""
        return ''

    def _get_categories_text(self, category_type: str = 'expense', label: str = '支出') -> str:
        try:
            categories = self.bk_client.get_categories(category_type=category_type)
            if not categories:
                return f"📂 暂无{label}科目"
            lines = [f"📂 可用{label}科目："]
            for cat in categories:
                name = cat.get('name', '')
                subs = cat.get('subCategories', [])
                if subs:
                    sub_names = [s.get('name', '') for s in subs]
                    lines.append(f"📂 {name}[一级]")
                    lines.append(f"   └ {'、'.join(sub_names[:6])}[二级]")
                else:
                    lines.append(f"• {name}")
            return '\n'.join(lines)
        except Exception as e:
            logger.warning(f"获取科目列表失败: {e}")
            return ""

    def _get_example_category_names(self, category_type: str = 'expense', fallback: str = '餐饮') -> str:
        try:
            categories = self.bk_client.get_categories(category_type=category_type)
            for cat in categories:
                subs = cat.get('subCategories', [])
                if subs:
                    return subs[0].get('name', fallback)
                return cat.get('name', fallback)
        except Exception:
            pass
        return fallback

    def _get_no_data_text(self, period: str) -> str:
        return f"📭 {period}暂无支出记录"

    def _get_accounting_help(self) -> str:
        return self._get_help_text()

    # ── 快捷转账 ──────────────────────────────────

    def _get_excluded_account_ids(self, from_user: str, accounts: list) -> set:
        excluded = set()
        if not from_user:
            logger.debug("[排除] from_user 为空，不排除任何账户")
            return excluded
        from db import get_user_code_by_sourceuser, get_excluded_account_ids as _shared_excluded
        user_code = get_user_code_by_sourceuser(from_user, source=self.source) or from_user
        excluded = _shared_excluded(user_code)
        logger.debug(f"[排除] from_user={from_user} user_code={user_code} 排除集合={excluded}")
        return excluded

    def _get_all_leaf_accounts(self, from_user: str = None) -> list:
        try:
            from db import get_flat_accounts, get_user_code_by_sourceuser
            user_code = get_user_code_by_sourceuser(from_user, source=self.source) if from_user else None
            return get_flat_accounts(user_code)
        except Exception:
            return []

    def _handle_quick_transfer(self, from_user: str, user_code: str = None) -> str:
        leaves = self._get_all_leaf_accounts(from_user)
        if len(leaves) < 2:
            return '需要至少 2 个可用账户才能转账'

        from db import _account_cache_version
        self._transfer_leaves_cache[self._key(from_user)] = {
            'leaves': leaves,
            'cache_version': _account_cache_version,
        }
        if user_code:
            self._transfer_leaves_cache[self._key(from_user) + '_user_code'] = user_code

        lines = ["📋 快捷转账"]
        lines.append("─" * 15)
        for i, acc in enumerate(leaves, 1):
            lines.append(f"{i}. {acc.get('_display_name', acc['name'])}")
        lines.append("─" * 15)
        lines.append("回复：转出账户序号 转入账户序号 金额 备注")
        lines.append("例如：1 2 50 信用卡还款")
        lines.append("回复0取消")
        return '\n'.join(lines)

    def _do_quick_transfer(self, content: str, from_user: str, user_code: str = None) -> Optional[str]:
        m = re.match(r'^(\d+)\s+(\d+)\s+(\d+(?:\.\d{1,2})?)(?:\s+(.*))?$', content)
        if not m:
            return None

        from_idx = int(m.group(1)) - 1
        to_idx = int(m.group(2)) - 1
        amount = float(m.group(3))
        comment = m.group(4).strip() if m.group(4) else ''

        cache = self._transfer_leaves_cache.get(self._key(from_user), {})
        leaves = cache.get('leaves') if isinstance(cache, dict) else cache

        from db import _account_cache_version
        if not leaves or (isinstance(cache, dict) and cache.get('cache_version', -1) != _account_cache_version):
            notice = '⚠️ 账户或绑定已变更，列表已更新，请重新选择'
            return notice + '\n\n' + self._handle_quick_transfer(from_user, user_code)

        if from_idx < 0 or from_idx >= len(leaves):
            return f'转出账户序号无效（1-{len(leaves)}），请重新发送「转账」'
        if to_idx < 0 or to_idx >= len(leaves):
            return f'转入账户序号无效（1-{len(leaves)}），请重新发送「转账」'
        if from_idx == to_idx:
            return '转出和转入不能是同一个账户，请重新发送「转账」'
        if amount <= 0:
            return '金额必须大于0'

        from_acc = leaves[from_idx]
        to_acc = leaves[to_idx]

        from_cur = from_acc.get('currency', 'CNY')
        to_cur = to_acc.get('currency', 'CNY')
        if from_cur != to_cur:
            return f'❌ 币种不一致：{from_acc["name"]}({from_cur}) → {to_acc["name"]}({to_cur})，请重新发送「转账」'

        full_comment = comment or ''
        if not user_code:
            user_code = self._transfer_leaves_cache.get(self._key(from_user) + '_user_code', from_user)
        result = self.bk_client.create_transfer(
            from_acc['id'], to_acc['id'],
            amount, full_comment,
            created_by=from_user, user_code=user_code,
            source=self.source, source_user=from_user)
        if result.get('success'):
            tx_id = result.get('result', {}).get('id', '')
            tx_uuid = result.get('result', {}).get('uuid', '')
            if tx_id:
                self._last_transaction[self._key(from_user)] = {
                    'id': tx_id,
                    'uuid': tx_uuid,
                    'type': 'transfer',
                }
                self._pending_actions[self._key(from_user)] = {
                    '9': {
                        'type': 'undo',
                        'data': {'tx_id': tx_id, 'tx_type': 'transfer', 'from_user': from_user},
                        'label': '撤销此笔转账',
                    },
                }
            from config import get_config
            _base = get_config().BASE_URL
            link = f'\n🔗 点击查看/修改：{_base}/tx/{tx_uuid}（5分钟有效）' if tx_uuid and _base else ''
            msg = (f"✅ 转账成功\n"
                   f"📤 {from_acc['name']} → {to_acc['name']}\n"
                   f"💰 ¥{amount:.2f}\n"
                   f"{'📝 ' + comment if comment else ''}"
                   f"{link}")
            if tx_id:
                msg += '\n\n回复9可撤销'
            self._transfer_leaves_cache.pop(self._key(from_user), None)
            return msg
        return f"转账失败: {result.get('errorMessage', '未知错误')}"
