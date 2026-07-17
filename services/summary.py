#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汇总服务 - 生成消费汇总报告"""
import calendar
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict

import pytz

from config import get_config
from books.client import BookkeepingClient

logger = logging.getLogger(__name__)


class SummaryService:
    """消费汇总服务"""

    def __init__(self, source: str):
        self.config = get_config()
        self.client = BookkeepingClient()
        self.source = source

    # ── 时间范围工具 ──────────────────────────────

    def _get_time_range(self, period: str) -> tuple:
        """返回 (start_time, end_time)，period='today' 或 'month'"""
        tz = pytz.timezone(self.config.TIMEZONE)
        now = datetime.now(tz)
        if period == 'today':
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:  # month
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, now

    # ── 预算查询工具 ──────────────────────────────

    def _get_family_budgets(self, start_time: datetime) -> Optional[dict]:
        """获取家庭预算（科目ID → 预算金额元）"""
        try:
            from db import get_budgets, SCOPE_FAMILY
            ym = start_time.strftime('%Y-%m')
            blist = get_budgets(SCOPE_FAMILY, year_month=ym)
            return {b['category_id']: b['monthly_limit'] / 100.0 for b in blist} if blist else None
        except Exception:
            return None

    def _get_personal_budgets(self, user_code: str, start_time: datetime) -> Optional[dict]:
        """获取个人预算（科目ID → 预算金额元）"""
        if not user_code:
            return None
        try:
            from db import get_budgets, SCOPE_PERSONAL
            ym = start_time.strftime('%Y-%m')
            blist = get_budgets(SCOPE_PERSONAL, user_code, ym)
            return {b['category_id']: b['monthly_limit'] / 100.0 for b in blist} if blist else None
        except Exception:
            return None

    # ── 统一汇总入口 ──────────────────────────────

    def get_today_summary(self, from_user: str = None) -> dict:
        """家庭今日消费汇总"""
        start, end = self._get_time_range('today')
        return self._generate_summary(period_name="今日", start_time=start, end_time=end)

    def get_my_today_summary(self, from_user: str) -> dict:
        """当前用户今日消费汇总"""
        user_filter = self._get_user_filter(from_user)
        if user_filter is None:
            return {'has_data': False, 'text': '你还未记过账'}
        start, end = self._get_time_range('today')
        return self._generate_summary(
            period_name="我的今日", start_time=start, end_time=end,
            user_filter=user_filter)

    def get_my_month_summary(self, from_user: str) -> dict:
        """当前用户本月消费汇总（含个人预算对比）"""
        user_filter = self._get_user_filter(from_user)
        if user_filter is None:
            return {'has_data': False, 'text': '你还未记过账'}
        start, end = self._get_time_range('month')
        from db import get_user_code_by_sourceuser
        user_code = get_user_code_by_sourceuser(from_user, source=self.source)
        budgets = self._get_personal_budgets(user_code, start)
        return self._generate_summary(
            period_name="我的本月", start_time=start, end_time=end,
            user_filter=user_filter, budgets=budgets)

    def get_other_today_summary(self, user_name: str, user_filter: str) -> dict:
        """其他用户今日消费汇总"""
        start, end = self._get_time_range('today')
        return self._generate_summary(
            period_name=f"{user_name} 今日", start_time=start, end_time=end,
            user_filter=user_filter)

    def get_other_month_summary(self, user_name: str, user_filter: str) -> dict:
        """其他用户本月消费汇总（含个人预算对比）"""
        start, end = self._get_time_range('month')
        # 从 user_filter 提取项目用户编码查个人预算
        user_code = user_filter if user_filter else None
        budgets = self._get_personal_budgets(user_code, start)
        return self._generate_summary(
            period_name=f"{user_name} 本月", start_time=start, end_time=end,
            user_filter=user_filter, budgets=budgets)

    def get_month_summary(self, from_user: str = None) -> dict:
        """家庭本月消费汇总（含家庭预算对比）"""
        start, end = self._get_time_range('month')
        budgets = self._get_family_budgets(start)
        return self._generate_summary(
            period_name="本月", start_time=start, end_time=end, budgets=budgets)

    def get_daily_summary_for_push(self, user_filter: str = None,
                                     range_config: dict = None) -> dict:
        """
        获取每日汇总（用于定时推送）
        :param user_filter: 可选用户筛选条件
        :param range_config: 时间范围配置，None=昨天全天
        :return: {"has_data": bool, "title": str, "description": str}
        """
        start_time, end_time, period_str = self._resolve_range(range_config, 'daily')
        summary = self._generate_summary(
            period_name=period_str,
            start_time=start_time,
            end_time=end_time,
            user_filter=user_filter,
        )
        if summary['has_data']:
            title = f"📊 {period_str} 消费汇总"
            description = summary['text'].replace('\n', '<br>')
            return {'has_data': True, 'title': title, 'description': description}
        return {'has_data': False, 'title': '', 'description': ''}

    def get_monthly_summary_for_push(self, user_filter: str = None,
                                       range_config: dict = None) -> dict:
        """
        获取月度汇总（用于定时推送）
        :param user_filter: 可选用户筛选条件
        :param range_config: 时间范围配置，None=上个月
        :return: {"has_data": bool, "title": str, "description": str}
        """
        start_time, end_time, period_str = self._resolve_range(range_config, 'monthly')
        summary = self._generate_summary(
            period_name=period_str,
            start_time=start_time,
            end_time=end_time,
            user_filter=user_filter,
        )
        if summary['has_data']:
            title = f"📊 {period_str} 消费汇总"
            description = summary['text'].replace('\n', '<br>')
            return {'has_data': True, 'title': title, 'description': description}
        return {'has_data': False, 'title': '', 'description': ''}

    def get_push_summary(self, user_filter: str = None,
                          range_config: dict = None,
                          with_budget: bool = False,
                          task_name: str = None) -> dict:
        """通用推送汇总（支持可选预算对比）
        :param with_budget: True=含家庭预算对比, False=仅汇总
        :param task_name: 任务名称，用作消息标题（为空则自动生成）
        """
        start_time, end_time, period_str = self._resolve_range(range_config, 'daily')
        budgets = self._get_family_budgets(start_time) if with_budget else None
        summary = self._generate_summary(
            period_name=period_str,
            start_time=start_time,
            end_time=end_time,
            user_filter=user_filter,
            budgets=budgets,
        )
        if summary['has_data']:
            title = task_name if task_name else f"📊 {period_str} 消费汇总"
            description = summary['text'].replace('\n', '<br>')
            return {'has_data': True, 'title': title, 'description': description}
        return {'has_data': False, 'title': '', 'description': ''}

    def _resolve_range(self, range_config: dict = None, default_type: str = 'daily'):
        """
        将 range_config 解析为 (start_time, end_time, period_str)
        range_config 格式:
          {"type":"yesterday|today|last_month|custom",
           "start_value":1, "start_unit":"days|months",
           "start_hour":null, "start_minute":null,
           "end_type":"period_end|now",
           "end_hour":null, "end_minute":null}
        """
        tz = pytz.timezone(self.config.TIMEZONE)
        now = datetime.now(tz)

        if not range_config:
            range_config = {}

        rc_type = range_config.get('type') or default_type

        # 计算起始时间
        start_value = int(range_config.get('start_value', 1))
        start_unit = range_config.get('start_unit', 'days')
        start_h = range_config.get('start_hour')
        start_m = range_config.get('start_minute')

        if rc_type == 'month_offset':
            offset = int(range_config.get('value', 0))
            cur_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            start_month = cur_month
            for _ in range(offset):
                start_month = (start_month - timedelta(days=1)).replace(day=1)
            start_time = start_month
            if offset == 0:
                import calendar
                last_day = calendar.monthrange(cur_month.year, cur_month.month)[1]
                end_time = cur_month.replace(day=last_day, hour=23, minute=59, second=59)
                period_str = cur_month.strftime('%Y年%m月')
            else:
                import calendar
                last_day = calendar.monthrange(cur_month.year, cur_month.month)[1]
                end_time = cur_month.replace(day=last_day, hour=23, minute=59, second=59)
                period_str = f"{start_month.strftime('%Y年%m月')}~{cur_month.strftime('%Y年%m月')}"
        elif rc_type == 'this_month':
            import calendar
            start_time = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            last_day = calendar.monthrange(now.year, now.month)[1]
            end_time = now.replace(day=last_day, hour=23, minute=59, second=59)
            period_str = now.strftime('%Y年%m月')
        elif rc_type == 'this_quarter':
            q = (now.month - 1) // 3
            q_start_month = q * 3 + 1
            q_end_month = q_start_month + 2
            import calendar
            start_time = now.replace(month=q_start_month, day=1, hour=0, minute=0, second=0, microsecond=0)
            last_day = calendar.monthrange(now.year, q_end_month)[1]
            end_time = now.replace(month=q_end_month, day=last_day, hour=23, minute=59, second=59)
            period_str = f"{now.year}年第{q+1}季度"
        elif rc_type == 'last_quarter':
            q = (now.month - 1) // 3
            if q == 0:
                q = 3
                year = now.year - 1
            else:
                year = now.year
            q_start_month = (q - 1) * 3 + 1
            q_end_month = q_start_month + 2
            import calendar
            start_time = now.replace(year=year, month=q_start_month, day=1, hour=0, minute=0, second=0, microsecond=0)
            last_day = calendar.monthrange(year, q_end_month)[1]
            end_time = now.replace(year=year, month=q_end_month, day=last_day, hour=23, minute=59, second=59)
            period_str = f"{year}年第{q}季度"
        elif rc_type == 'this_year':
            import calendar
            start_time = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end_time = now.replace(month=12, day=31, hour=23, minute=59, second=59)
            period_str = f"{now.year}年"
        elif rc_type == 'last_year':
            import calendar
            start_time = now.replace(year=now.year-1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end_time = now.replace(year=now.year-1, month=12, day=31, hour=23, minute=59, second=59)
            period_str = f"{now.year-1}年"
        elif rc_type == 'yesterday':
            base = now - timedelta(days=1)
            if start_h is None: start_h = 0
            if start_m is None: start_m = 0
            start_time = base.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
            period_str = base.strftime('%Y-%m-%d')
        elif rc_type == 'today':
            if start_h is None: start_h = 0
            if start_m is None: start_m = 0
            start_time = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
            period_str = now.strftime('%Y-%m-%d')
        elif rc_type == 'last_month':
            first_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            last_month_end = first_this - timedelta(seconds=1)
            last_month_start = last_month_end.replace(day=1)
            if start_h is None: start_h = 0
            if start_m is None: start_m = 0
            start_time = last_month_start.replace(hour=start_h, minute=start_m)
            period_str = last_month_start.strftime('%Y年%m月')
        else:  # custom
            if start_unit == 'months':
                month = now.month - start_value
                year = now.year
                while month < 1:
                    month += 12
                    year -= 1
                from datetime import date
                start_time = now.replace(year=year, month=month, day=1,
                    hour=start_h or 0, minute=start_m or 0, second=0, microsecond=0)
            else:
                start_time = now - timedelta(days=start_value)
                start_time = start_time.replace(hour=start_h or 0, minute=start_m or 0,
                    second=0, microsecond=0)
            period_str = start_time.strftime('%Y-%m-%d %H:%M')

        # 以下类型已内置完整 end_time
        if rc_type in ('month_offset', 'this_month', 'this_quarter', 'last_quarter', 'this_year', 'last_year'):
            return start_time, end_time, period_str

        # 计算截止时间
        end_type = range_config.get('end_type', 'period_end')
        end_h = range_config.get('end_hour')
        end_m = range_config.get('end_minute')

        if end_type == 'now':
            end_time = now
            period_str += '~当前'
        elif end_type == 'time' and end_h is not None:
            # 截止到与起始同一天的指定时间
            end_time = start_time.replace(hour=end_h, minute=end_m or 0, second=59)
            period_str += f'~{end_h:02d}:{end_m or 0:02d}'
        else:  # period_end — 截止到当天/月末结束
            if rc_type in ('last_month',) or start_unit == 'months':
                # 月末
                import calendar
                last_day = calendar.monthrange(start_time.year, start_time.month)[1]
                end_time = start_time.replace(day=last_day, hour=23, minute=59, second=59)
            else:
                end_time = start_time.replace(hour=23, minute=59, second=59)
            period_str += ' 全天'

        return start_time, end_time, period_str

    def _user_filter_to_name(self, user_filter: str) -> Optional[str]:
        """从 user_filter 提取用户名称"""
        try:
            users = self.client.get_users()
            user_id = user_filter.split(':')[-1]
            for u in users:
                if str(u.get('id')) == user_id:
                    return u.get('name', '')
        except Exception:
            pass
        return None

    def _get_user_filter(self, from_user: str) -> Optional[str]:
        """根据企业微信账号查找绑定的用户编码，获取用户筛选条件"""
        try:
            from db import get_user_code_by_sourceuser
            user_code = get_user_code_by_sourceuser(from_user, source=self.source)
            if not user_code:
                logger.warning(f"[用户筛选] source_user={from_user} 未绑定项目用户")
                return None
            logger.info(f"[用户筛选] source_user={from_user} → user_code={user_code}")
            return user_code
        except Exception:
            pass
        return None

    def _generate_summary(self, period_name: str, start_time: datetime, end_time: datetime,
                          user_filter: str = None, budgets: dict = None) -> dict:
        """生成汇总文本"""
        has_budget = budgets is not None

        # 获取金额汇总（user_filter=None 时查全部，有值时查个人）
        amounts = self._get_user_amounts(start_time, end_time, user_filter)
        total_expense = float(amounts.get('total_expense_amount', 0)) if amounts else 0
        total_income = float(amounts.get('total_income_amount', 0)) if amounts else 0
        transaction_count = int(amounts.get('expense_transaction_count', 0)) if amounts else 0

        if total_expense == 0 and transaction_count == 0 and not has_budget:
            return {'has_data': False, 'text': ''}

        # 有支出时才获取统计明细
        stat_items = []
        cat_info = {}
        parent_expenses = {}
        child_expenses = {}
        if total_expense > 0 or transaction_count > 0:
            statistics = self.client.get_transactions_statistics(start_time, end_time, user_filter=user_filter)
            stat_items = statistics.get('result', {}).get('items', [])

        # 构建层级科目数据结构
        categories = self.client.get_categories()
        cat_info = {}  # id → {name, parent_id, parent_name}
        parent_to_children = defaultdict(list)  # parent_id → [child_id]
        parent_order = []  # 保持父科目顺序

        def _build_hierarchy(items, parent_id='0'):
            for item in items:
                cid = str(item.get('id'))
                cname = item.get('name', '')
                ctype = item.get('type')
                cat_info[cid] = {
                    'name': cname,
                    'parent_id': parent_id,
                    'parent_name': cat_info.get(parent_id, {}).get('name', '') if parent_id != '0' else '',
                    'type': ctype,
                }
                if parent_id != '0':
                    parent_to_children[parent_id].append(cid)
                else:
                    if ctype == 'expense':  # 只保留支出父科目的顺序
                        parent_order.append(cid)
                subs = item.get('subCategories', [])
                if subs:
                    _build_hierarchy(subs, cid)

        _build_hierarchy(categories)

        # 按父科目汇总金额（区分支出和收入）
        parent_expenses = defaultdict(float)
        child_expenses = defaultdict(lambda: defaultdict(float))
        parent_income = defaultdict(float)
        child_income = defaultdict(lambda: defaultdict(float))

        for item in stat_items:
            cat_id = str(item.get('categoryId', '0'))
            amount = abs(float(item.get('amount', 0))) / 100.0
            if amount <= 0:
                continue

            info = cat_info.get(cat_id, {})
            parent_id = info.get('parent_id', '0')
            cat_type = info.get('type', 2)

            # 跳过转账类型（type=3）
            if cat_type == 3:
                continue

            if cat_type == 'income':
                # 收入
                if parent_id == '0':
                    parent_income[cat_id] += amount
                else:
                    parent_income[parent_id] += amount
                    child_income[parent_id][cat_id] += amount
            else:
                # 支出
                if parent_id == '0':
                    parent_expenses[cat_id] += amount
                else:
                    parent_expenses[parent_id] += amount
                    child_expenses[parent_id][cat_id] += amount

        # 构建汇总文本（描述式排版，不依赖对齐）
        lines = []
        lines.append(f"📊 {period_name} 消费汇总")
        lines.append("─" * 15)

        total_budget = 0

        # 将子科目预算汇总到父科目
        parent_budgets = {}
        if has_budget:
            for cid, amt in budgets.items():
                info = cat_info.get(cid, {})
                pid = info.get('parent_id', '0')
                if pid != '0':
                    parent_budgets[pid] = parent_budgets.get(pid, 0) + amt
                else:
                    parent_budgets[cid] = parent_budgets.get(cid, 0) + amt

        if parent_expenses:
            sorted_parents = sorted(parent_expenses.items(), key=lambda x: x[1], reverse=True)
            for parent_id, parent_amount in sorted_parents:
                parent_name = cat_info.get(parent_id, {}).get('name', f"类别#{parent_id}")
                pbgt = parent_budgets.get(parent_id, 0) if has_budget else 0
                total_budget += pbgt
                if has_budget and pbgt > 0:
                    pct = (parent_amount / pbgt * 100) if pbgt > 0 else 0
                    r = pbgt - parent_amount
                    flag = '🔴' if r < 0 else '⚠️' if r < pbgt * 0.2 else ''
                    lines.append(f"📁 {parent_name}：¥{parent_amount:.2f}（预算 ¥{pbgt:.2f}，剩余 ¥{r:.2f}，已用 {pct:.0f}%）{flag}")
                elif has_budget:
                    lines.append(f"📁 {parent_name}：¥{parent_amount:.2f}（无预算）")
                else:
                    lines.append(f"📁 {parent_name}：¥{parent_amount:.2f}")
                children = child_expenses.get(parent_id, {})
                if children:
                    for child_id, child_amount in sorted(children.items(), key=lambda x: x[1], reverse=True):
                        child_name = cat_info.get(child_id, {}).get('name', f"子类#{child_id}")
                        cbgt = budgets.get(child_id, 0) if has_budget else 0
                        if has_budget and cbgt > 0:
                            child_pct = (child_amount / cbgt * 100) if cbgt > 0 else 0
                            r = cbgt - child_amount
                            flag = '🔴' if r < 0 else '⚠️' if r < cbgt * 0.2 else ''
                            lines.append(f"  {child_name}：¥{child_amount:.2f}（预算 ¥{cbgt:.2f}，剩余 ¥{r:.2f}，已用 {child_pct:.0f}%）{flag}")
                        else:
                            lines.append(f"  {child_name}：¥{child_amount:.2f}")
            lines.append("─" * 15)
        elif has_budget:
            # 无支出但有预算
            for pid in sorted(parent_budgets, key=lambda x: parent_budgets[x], reverse=True):
                amt = parent_budgets[pid]
                total_budget += amt
                pname = cat_info.get(pid, {}).get('name', f'#{pid}')
                lines.append(f"📁 {pname}：¥0.00（预算 ¥{amt:.2f}，已用 0%）")
            lines.append("─" * 15)

        lines.append(f"📝 共 {transaction_count} 笔")
        lines.append(f"💰 总支出：¥{total_expense:.2f}")
        if has_budget and total_budget > 0:
            remaining = total_budget - total_expense
            pct = (total_expense / total_budget * 100) if total_budget > 0 else 0
            flag = '🔴' if remaining < 0 else '⚠️' if remaining < total_budget * 0.2 else ''
            lines.append(f"📊 总预算：¥{total_budget:.2f}，剩余 ¥{remaining:.2f}，已用 {pct:.0f}%{flag}")
        lines.append("─" * 15)

        # 收入（单独显示）
        if parent_income:
            total_income_amount = sum(parent_income.values())
            lines.append(f"💵 收入：")
            for pid in sorted(parent_income, key=lambda x: parent_income[x], reverse=True):
                amt = parent_income[pid]
                pname = cat_info.get(pid, {}).get('name', f'#{pid}')
                lines.append(f"📁 {pname}：¥{amt:.2f}")
                children = child_income.get(pid, {})
                if children:
                    for cid in sorted(children, key=lambda x: children[x], reverse=True):
                        cname = cat_info.get(cid, {}).get('name', f'#{cid}')
                        lines.append(f"  {cname}：¥{children[cid]:.2f}")
            net = total_expense - total_income_amount
            if net > 0:
                lines.append(f"📊 净支出: ¥{net:.2f}")
            else:
                lines.append(f"📊 净收入: ¥{abs(net):.2f}")

        return {
            'has_data': True,
            'text': '\n'.join(lines),
            'total_expense': total_expense,
            'total_income': total_income,
            'transaction_count': transaction_count,
        }

    def _get_user_amounts(self, start_time: datetime, end_time: datetime, user_filter: str = None) -> dict:
        """通过统计API获取金额汇总（user_filter=None 查全部，有值查个人）"""
        statistics = self.client.get_transactions_statistics(start_time, end_time, user_filter=user_filter)
        items = statistics.get('result', {}).get('items', [])
        total_expense = 0
        for item in items:
            total_expense += float(item.get('expenseAmount', 0))
        # 获取实际交易笔数
        list_result = self.client.get_transactions_list(
            start_time, end_time, with_count=True, user_filter=user_filter)
        count = int(list_result.get('count', 0)) if list_result else 0
        return {
            'total_expense_amount': total_expense / 100.0,
            'total_income_amount': sum(float(item.get('incomeAmount', 0)) for item in items) / 100.0,
            'expense_transaction_count': count,
        }
