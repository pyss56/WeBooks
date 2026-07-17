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
        self._pending_alias = {}

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

        # 别名确认模式
        if self._key(from_user) in self._pending_alias:
            return self._handle_alias_confirm(content, from_user)

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

        # 撤销命令
        if content == '0' and self._key(from_user) in self._last_transaction:
            last = self._last_transaction.pop(self._key(from_user))
            tx_id = last['id']
            ok = self.bk_client.delete_transaction(tx_id, updated_by=from_user)
            if ok.get('success'):
                from db import get_dict
                type_label = get_dict('tx_type', last.get('type', ''), last.get('type', '交易'))
                return f'✅ 已撤销上一笔{type_label}'
            return f'撤销失败: {ok.get("errorMessage", "未知错误")}'

        # 解析记账命令
        parsed_content, parsed_time = parse_time_from_text(content)
        if parsed_time:
            logger.info(f"⏰ 解析到交易时间: {parsed_time} (原文: {content})")
        parsed_content, parsed_account = parse_account_from_text(parsed_content)
        if parsed_account:
            logger.info(f"🏦 解析到指定账户: {parsed_account} (原文: {content})")
        result = self.transaction_service.parse_and_create(
            parsed_content, from_user,
            transaction_time=parsed_time,
            account_name=parsed_account,
            raw_message=content,
            message_log_id=message_log_id)

        if result.get('needs_resolve'):
            self._pending_resolve[self._key(from_user)] = result
            logger.info(f"[handler] needs_resolve 触发, message={result['message'][:100]}")
            return result['message']

        msg = result['message']

        if result.get('success') and 'category_id' in result:
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
                msg += '\n\n回复0可撤销'
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

    def _handle_resolve_selection(self, content: str, from_user: str) -> str:
        state = self._pending_resolve.get(self._key(from_user))
        if not state:
            return ''

        if content == '0':
            self._pending_resolve.pop(self._key(from_user), None)
            return '已取消操作'

        try:
            idx = int(content) - 1
        except ValueError:
            return '请输入有效序号（0=取消）'

        available = state.get('available', [])
        if idx < 0 or idx >= len(available):
            return f'序号无效，请输入 1-{len(available)}（0=取消）'

        selected = available[idx]
        resolve_type = state.get('resolve_type', 'category')
        pending_data = state.get('pending_data', {})

        result = self.transaction_service.create_from_resolved(pending_data, selected, resolve_type)
        if result.get('success'):
            original_input = state.get('original_input', '')
            resolved_id = result.get('resolved_id', '')
            self._pending_alias[self._key(from_user)] = {
                'original_input': original_input,
                'resolved_to': selected,
                'resolved_id': resolved_id,
                'target_type': resolve_type,
            }
            self._pending_resolve.pop(self._key(from_user), None)
            msg = result['message']
            msg += f'\n\n是否以后将「{original_input}」识别为「{selected}」？\n回复1确认，0取消'
            return msg
        elif result.get('needs_resolve'):
            self._pending_resolve[self._key(from_user)] = result
            return result['message']
        else:
            self._pending_resolve.pop(self._key(from_user), None)
            return result.get('message', '创建失败')

    def _handle_alias_confirm(self, content: str, from_user: str) -> str:
        state = self._pending_alias.get(self._key(from_user))
        if not state:
            self._pending_alias.pop(self._key(from_user), None)
            return ''

        if content == '1':
            from db import add_input_alias
            ok = add_input_alias(
                state['original_input'], state['target_type'],
                state.get('resolved_id', ''),
                target_name=state['resolved_to'],
                created_by=from_user)
            self._pending_alias.pop(self._key(from_user), None)
            if ok:
                return f'✅ 已保存映射：「{state["original_input"]}」→「{state["resolved_to"]}」\n下次将自动识别'
            return '保存失败'
        elif content == '0':
            self._pending_alias.pop(self._key(from_user), None)
            return '已取消，下次仍会询问'
        else:
            return '请回复1确认，0取消'

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
            from config import get_config
            _base = get_config().BASE_URL
            link = f'\n🔗 点击查看/修改：{_base}/tx/{tx_uuid}（5分钟有效）' if tx_uuid and _base else ''
            msg = (f"✅ 转账成功\n"
                   f"📤 {from_acc['name']} → {to_acc['name']}\n"
                   f"💰 ¥{amount:.2f}\n"
                   f"{'📝 ' + comment if comment else ''}"
                   f"{link}")
            if tx_id:
                msg += '\n\n回复0可撤销'
            self._transfer_leaves_cache.pop(self._key(from_user), None)
            return msg
        return f"转账失败: {result.get('errorMessage', '未知错误')}"
