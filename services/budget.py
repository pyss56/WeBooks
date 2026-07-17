#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预算服务 - 通过 ledger 科目 ID 关联的预算管理"""
import logging
from datetime import datetime
from typing import Optional

import pytz

from config import get_config
from books.client import BookkeepingClient
from db import (
    SCOPE_PERSONAL, SCOPE_FAMILY,
    get_budgets, get_budget,
    set_budget as db_set_budget,
    delete_budget as db_delete_budget,
    refresh_budget_category_name,
)

logger = logging.getLogger(__name__)


class BudgetService:
    """预算服务"""

    def __init__(self):
        self.config = get_config()
        self.client = BookkeepingClient()

    # ── 工具方法 ──────────────────────────────────

    def _build_flat_category_map(self) -> dict:
        """构建 category_id → {name, parent_id} 的扁平映射。"""
        categories = self.client.get_categories(category_type=None)
        id_map = {}

        def _walk(items, parent_id='0'):
            for item in items:
                cid = str(item.get('id'))
                cname = item.get('name', '')
                id_map[cid] = {
                    'id': cid,
                    'name': cname,
                    'parent_id': parent_id,
                    'type': item.get('type'),
                }
                subs = item.get('subCategories', [])
                if subs:
                    _walk(subs, cid)

        _walk(categories)
        return id_map

    def _lookup_category_by_name(self, category_name: str,
                                  category_type: str = 'expense') -> Optional[dict]:
        """通过 ledger 查找科目，返回 {id, name, parent_id} 或 None"""
        cat = self.client.find_category_by_name(category_name, category_type=category_type)
        if cat:
            return {
                'id': str(cat.get('id')),
                'name': cat.get('name', category_name),
                'parent_id': str(cat.get('parentId', '0')),
            }
        return None

    def _get_current_month_stat(self, user_filter: str = None) -> dict:
        """获取本月各科目实际支出（元），返回 category_id → amount（仅支出科目）"""
        import logging
        logger = logging.getLogger(__name__)
        tz = pytz.timezone(self.config.TIMEZONE)
        now = datetime.now(tz)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        logger.info(f"[预算] 统计时间范围: {month_start} ~ {now}")

        statistics = self.client.get_transactions_statistics(
            month_start, now, user_filter=user_filter)
        stat_items = statistics.get('result', {}).get('items', [])
        logger.info(f"[预算] get_transactions_statistics 返回 {len(stat_items)} 条")

        # 构建类型映射
        id_map = self._build_flat_category_map()
        logger.info(f"[预算] category_id_map 共 {len(id_map)} 个科目")

        result = {}
        for item in stat_items:
            cid = str(item.get('categoryId', '0'))
            # 直接用 expenseAmount，不混入收入
            amount = float(item.get('expenseAmount', 0)) / 100.0
            cname = item.get('categoryName', '')
            logger.info(f"[预算]   item: cid={cid}, name={cname}, expenseAmount_元={amount}")
            if amount <= 0:
                logger.info(f"[预算]   -> 跳过 (amount<=0)")
                continue
            # 只统计支出科目（type=2）
            cat = id_map.get(cid)
            if cat:
                logger.info(f"[预算]   cat_map: type={cat.get('type')}, name={cat.get('name')}")
                if cat.get('type') != 'expense':
                    logger.info(f"[预算]   -> 跳过 (非支出科目 type={cat.get('type')})")
                    continue
            else:
                logger.info(f"[预算]   cid={cid} 未在 id_map 中找到")
            result[cid] = result.get(cid, 0) + amount
            logger.info(f"[预算]   -> result[{cid}] = {result[cid]}")
        logger.info(f"[预算] 最终 result: {result}")
        return result

    # ── 核心功能（双 scope） ──────────────────────

    def _scope_label(self, scope: str) -> str:
        return '家庭' if scope == SCOPE_FAMILY else '个人'

    def set_budget(self, scope: str, from_user: str, category_name: str,
                   amount: float) -> dict:
        """设置科目预算。"""
        cat = self._lookup_category_by_name(category_name, category_type='expense')
        if not cat:
            return {
                'success': False,
                'message': f'未找到支出科目「{category_name}」\n'
                           f'请先添加该科目',
            }

        user_code = from_user if scope == SCOPE_PERSONAL else None
        ok = db_set_budget(scope, user_code, cat['id'], cat['name'], amount, updated_by=from_user)
        if ok:
            label = self._scope_label(scope)
            return {
                'success': True,
                'message': f'✅ 已设置{label}预算「{cat["name"]}」：¥{amount:.0f}',
            }
        return {'success': False, 'message': '预算保存失败，请稍后重试'}

    def delete_budget(self, scope: str, from_user: str,
                       category_name: str) -> dict:
        """删除科目预算。"""
        cat = self._lookup_category_by_name(category_name, category_type='expense')
        user_code = from_user if scope == SCOPE_PERSONAL else None

        if cat:
            ok = db_delete_budget(scope, cat['id'], user_code)
        else:
            budgets = get_budgets(scope, user_code)
            matched = [b for b in budgets if b['category_name'] == category_name]
            if not matched:
                label = self._scope_label(scope)
                return {
                    'success': False,
                    'message': f'未找到{label}预算「{category_name}」',
                }
            ok = db_delete_budget(scope, matched[0]['category_id'], user_code)

        if ok:
            return {'success': True, 'message': f'✅ 已删除「{category_name}」的预算'}
        return {'success': False, 'message': '删除失败，请稍后重试'}

    def transfer_budget(self, scope: str, from_user: str, from_name: str,
                        to_name: str) -> dict:
        """将预算从一个科目转移到另一个科目。"""
        to_cat = self._lookup_category_by_name(to_name, category_type='expense')
        if not to_cat:
            return {
                'success': False,
                'message': f'未找到目标支出科目「{to_name}」\n'
                           f'请先添加该科目',
            }

        user_code = from_user if scope == SCOPE_PERSONAL else None

        from_cat = self._lookup_category_by_name(from_name, category_type='expense')
        budget_record = None
        if from_cat:
            budget_record = get_budget(scope, from_cat['id'], user_code)
        else:
            budgets = get_budgets(scope, user_code)
            matched = [b for b in budgets if b['category_name'] == from_name]
            if matched:
                budget_record = matched[0]

        if not budget_record:
            label = self._scope_label(scope)
            return {
                'success': False,
                'message': f'未找到{label}预算「{from_name}」的设置',
            }

        amount = budget_record['monthly_limit'] / 100.0  # 分→元

        existing = get_budget(scope, to_cat['id'], user_code)
        new_amount = amount + existing['monthly_limit'] / 100.0 if existing else amount

        db_delete_budget(scope, budget_record['category_id'], user_code)
        db_set_budget(scope, user_code, to_cat['id'], to_cat['name'], new_amount, updated_by=from_user)

        label = self._scope_label(scope)
        from_label = budget_record['category_name']
        if existing:
            return {
                'success': True,
                'message': (f'✅ 已转移{label}预算\n'
                           f'「{from_label}」¥{amount:.0f} → 「{to_cat["name"]}」\n'
                           f'目标科目当前总预算：¥{new_amount:.0f}'),
            }
        return {
            'success': True,
            'message': (f'✅ 已转移{label}预算\n'
                       f'「{from_label}」¥{amount:.0f} → 「{to_cat["name"]}」'),
        }

    def get_budget_status(self, scope: str, from_user: str,
                          user_filter: str = None,
                          year_month: str = None) -> dict:
        """获取预算执行情况。
        :param year_month: 'YYYY-MM'，None 则默认当月
        """
        if year_month is None:
            from datetime import datetime
            year_month = datetime.now().strftime('%Y-%m')

        user_code = from_user if scope == SCOPE_PERSONAL else None
        budgets = get_budgets(scope, user_code, year_month)

        label = self._scope_label(scope)
        id_map = self._build_flat_category_map()
        stat_amount = self._get_current_month_stat(user_filter=user_filter)

        # 找出有支出但没预算的科目
        spent_cats = set(stat_amount.keys())
        budgeted_cats = {b['category_id'] for b in budgets}
        unbudgeted_spent = sorted(cid for cid in spent_cats if cid not in budgeted_cats and stat_amount.get(cid, 0) > 0)

        if not budgets and not unbudgeted_spent:
            if scope == SCOPE_PERSONAL:
                return {'has_data': False,
                        'text': '你还没有设置个人预算\n发送「预算 科目名 金额」设置'}
            return {'has_data': False,
                    'text': '还没有设置家庭预算\n发送「家庭预算 科目名 金额」设置'}

        lines = [f'📊 {label}预算执行情况', '科目  预算  已花  剩余  占比', '─' * 13]

        total_budget = 0
        total_spent = 0

        for b in sorted(budgets, key=lambda x: x['monthly_limit'], reverse=True):
            cid = b['category_id']
            budget_amount = b['monthly_limit'] / 100.0
            name_snapshot = b['category_name']
            current_info = id_map.get(cid)
            if current_info:
                display_name = current_info['name']
                if display_name != name_snapshot:
                    refresh_budget_category_name(scope, cid, display_name, user_code)
            else:
                display_name = f'⚠{name_snapshot}'
            spent = stat_amount.get(cid, 0) or 0
            total_budget += budget_amount
            total_spent += spent

            remaining = budget_amount - spent
            pct = (spent / budget_amount * 100) if budget_amount > 0 else 0
            flag = '🔴' if pct >= 100 else '⚠️' if pct >= 80 else '⚡' if pct >= 50 else ''
            lines.append(f'{display_name}  {budget_amount:.0f}  {spent:.0f}  {remaining:.0f}  {pct:.0f}%{flag}')

        for cid in unbudgeted_spent:
            info = id_map.get(cid)
            display_name = info['name'] if info else f'?{cid}'
            spent = stat_amount.get(cid, 0) or 0
            total_spent += spent
            lines.append(f'{display_name}  0  {spent:.0f}  -{spent:.0f}  100%')

        lines.append('─' * 13)
        if total_budget > 0:
            remaining = total_budget - total_spent
            pct = total_spent / total_budget * 100
            flag = '🔴' if pct >= 100 else '⚠️' if pct >= 80 else '⚡' if pct >= 50 else ''
            lines.append(f'合计  {total_budget:.0f}  {total_spent:.0f}  {remaining:.0f}  {pct:.0f}%{flag}')
        else:
            lines.append(f'合计  0  {total_spent:.0f}  -{total_spent:.0f}  100%')

        return {'has_data': True, 'text': '\n'.join(lines)}

        return {'has_data': True, 'text': '\n'.join(lines)}

    def get_budget_alert(self, scope: str, user_code: str,
                          category_id: str) -> Optional[str]:
        """记账后检查该科目预算是否超支，返回提醒文本或 None"""
        uc = user_code if scope == SCOPE_PERSONAL else None
        budget = get_budget(scope, category_id, uc)
        if not budget:
            return None

        user_filter = None
        if scope == SCOPE_PERSONAL and uc:
            user_filter = f"0:{uc}"

        stat_amount = self._get_current_month_stat(user_filter=user_filter)

        id_map = self._build_flat_category_map()
        category_ids = {category_id}
        for cid, info in id_map.items():
            if info['parent_id'] == category_id:
                category_ids.add(cid)

        total_spent = sum(stat_amount.get(cid, 0) for cid in category_ids)

        budget_amount = budget['monthly_limit'] / 100.0
        pct = (total_spent / budget_amount * 100) if budget_amount > 0 else 0

        label = self._scope_label(scope)
        if pct >= 100:
            overspent = total_spent - budget_amount
            return (
                f'⚠️ 预算提醒：「{budget["category_name"]}」已超支 ¥{overspent:.0f}\n'
                f'本月已花费 ¥{total_spent:.0f} / ¥{budget_amount:.0f}'
            )
        elif pct >= 80:
            remaining = budget_amount - total_spent
            return (
                f'⚡ 预算提醒：「{budget["category_name"]}」已使用 {pct:.0f}%\n'
                f'剩余预算：¥{remaining:.0f}'
            )

        return None

    # ── 辅助方法 ──────────────────────────────────

    @staticmethod
    def _progress_bar(pct: float, length: int = 10) -> str:
        """生成进度条 ██████░░░░"""
        filled = min(int(pct / 100 * length), length)
        return '█' * filled + '░' * (length - filled)

    @staticmethod
    def _budget_flag(pct: float) -> str:
        """根据使用率返回状态标记"""
        if pct >= 100:
            return '🔴'
        elif pct >= 80:
            return '⚠️'
        elif pct >= 50:
            return '⚡'
        return ''
