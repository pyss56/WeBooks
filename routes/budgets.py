"""预算管理 API 和页面"""
import logging
import pytz
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, session
from auth import login_required

logger = logging.getLogger(__name__)
bp = Blueprint('budgets', __name__)


@bp.route('/api/budgets', methods=['GET'])
def api_get_budgets():
    from_user = request.args.get('user_code', '')
    scope = request.args.get('scope', 'personal')
    if not from_user:
        return jsonify({'success': False, 'message': '缺少 user_code 参数'}), 400
    try:
        from services.budget import BudgetService
        from db import get_budgets, SCOPE_PERSONAL, SCOPE_FAMILY
        bs = BudgetService()
        user_filter = None
        if scope == 'personal':
            user_filter = f"0:{from_user}"
        result = bs.get_budget_status(scope, from_user, user_filter=user_filter)
        user_code = from_user if scope == SCOPE_PERSONAL else None
        budgets = get_budgets(scope, user_code)
        data = [{'category_id': b['category_id'], 'category_name': b['category_name'], 'monthly_limit': b['monthly_limit'] / 100.0} for b in budgets]
        return jsonify({'success': True, 'data': data, 'status_text': result['text']})
    except Exception as e:
        logger.error(f"获取预算列表异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/budgets/set', methods=['POST'])
def api_set_budget():
    data = request.get_json() or {}
    scope = data.get('scope', 'personal')
    from_user = data.get('user_code', '')
    category_name = data.get('category_name', '')
    amount = data.get('amount', 0)
    if not from_user or not category_name:
        return jsonify({'success': False, 'message': '缺少参数'}), 400
    try:
        from services.budget import BudgetService
        bs = BudgetService()
        result = bs.set_budget(scope, from_user, category_name, float(amount))
        return jsonify(result)
    except Exception as e:
        logger.error(f"设置预算异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/budgets/delete', methods=['POST'])
def api_delete_budget():
    data = request.get_json() or {}
    scope = data.get('scope', 'personal')
    from_user = data.get('user_code', '')
    category_name = data.get('category_name', '')
    if not from_user or not category_name:
        return jsonify({'success': False, 'message': '缺少参数'}), 400
    try:
        from services.budget import BudgetService
        bs = BudgetService()
        result = bs.delete_budget(scope, from_user, category_name)
        return jsonify(result)
    except Exception as e:
        logger.error(f"删除预算异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/budgets/transfer', methods=['POST'])
def api_transfer_budget():
    data = request.get_json() or {}
    scope = data.get('scope', 'personal')
    from_user = data.get('user_code', '')
    from_name = data.get('from_category', '')
    to_name = data.get('to_category', '')
    if not from_user or not from_name or not to_name:
        return jsonify({'success': False, 'message': '缺少参数'}), 400
    try:
        from services.budget import BudgetService
        bs = BudgetService()
        result = bs.transfer_budget(scope, from_user, from_name, to_name)
        return jsonify(result)
    except Exception as e:
        logger.error(f"转移预算异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/admin/budget-summary')
@login_required
def api_admin_budget_summary():
    try:
        from services.budget import BudgetService
        from db import get_budgets, SCOPE_PERSONAL, SCOPE_FAMILY
        from books.client import BookkeepingClient
        bs = BudgetService()
        bk = BookkeepingClient()
        stat_amount = bs._get_current_month_stat()
        budgets_map = {b['category_id']: b for b in get_budgets(SCOPE_FAMILY, None)}
        all_cats = bk.get_categories(category_type=None)
        all_cats.sort(key=lambda c: c.get('displayOrder', 0) or 0)
        for cat in all_cats:
            subs = cat.get('subCategories', [])
            if subs:
                subs.sort(key=lambda s: s.get('displayOrder', 0) or 0)
        cat_map = bs._build_flat_category_map()
        def _get_stat(cid):
            total = stat_amount.get(cid, 0) or 0
            for cid2, info in cat_map.items():
                if info.get('parent_id') == cid:
                    total += stat_amount.get(cid2, 0) or 0
            return round(total, 2)
        def _build_item(cid, name, level):
            b = budgets_map.get(cid)
            budget_amount = b['monthly_limit'] / 100.0 if b else 0
            spent = _get_stat(cid)
            remaining = round(budget_amount - spent, 2)
            pct = round((spent / budget_amount * 100), 1) if budget_amount > 0 else 0
            return {'category_id': cid, 'category_name': name, 'level': level, 'budget': budget_amount, 'spent': spent, 'remaining': remaining, 'percentage': pct, 'over_budget': spent > budget_amount}
        tree = []
        for cat in all_cats:
            if cat.get('type') != 'expense':
                continue
            cid = str(cat['id'])
            cname = cat.get('name', '')
            subs = cat.get('subCategories', [])
            children = []
            for sub in subs:
                scid = str(sub['id'])
                scname = sub.get('name', '')
                children.append(_build_item(scid, scname, 2))
            parent_item = _build_item(cid, cname, 1)
            if children:
                parent_item['children'] = children
                total_budget = sum(c['budget'] for c in children)
                total_spent = sum(c['spent'] for c in children)
                parent_item['budget'] = total_budget
                parent_item['spent'] = total_spent
                parent_item['remaining'] = round(total_budget - total_spent, 2)
                parent_item['percentage'] = round((total_spent / total_budget * 100), 1) if total_budget > 0 else 0
                parent_item['over_budget'] = total_spent > total_budget
            if parent_item['budget'] > 0 or parent_item['spent'] > 0:
                tree.append(parent_item)
        return jsonify({'success': True, 'tree': tree})
    except Exception as e:
        logger.error(f"获取预算汇总异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/budgets')
@login_required
def budgets_page():
    from config import get_config
    config = get_config()
    from datetime import datetime
    now = datetime.now()
    cur_ym = request.args.get('ym', now.strftime('%Y-%m'))
    if not (len(cur_ym) == 7 and cur_ym[4] == '-'):
        cur_ym = now.strftime('%Y-%m')
    try:
        from books.client import BookkeepingClient
        from db import SCOPE_PERSONAL, SCOPE_FAMILY, get_budgets
        from version import __version__
        bk = BookkeepingClient()
        categories = bk.get_categories(category_type='expense')
        categories.sort(key=lambda c: c.get('displayOrder', 0) or 0)
        for cat in categories:
            subs = cat.get('subCategories', [])
            if subs:
                subs.sort(key=lambda s: s.get('displayOrder', 0) or 0)
        tree_cats = []
        leaf_only = []
        for item in categories:
            parent_id = str(item.get('id'))
            parent_name = item.get('name', '')
            subs = item.get('subCategories', [])
            children = []
            for sub in subs:
                cid = str(sub.get('id'))
                cname = sub.get('name', '')
                children.append({'id': cid, 'name': cname, 'parent': parent_name})
                leaf_only.append({'id': cid, 'name': cname, 'parent': parent_name})
            if not children:
                leaf_only.append({'id': parent_id, 'name': parent_name, 'parent': ''})
            tree_cats.append({'id': parent_id, 'name': parent_name, 'children': children})
        all_users = bk.get_users()
        users_list = [u for u in all_users if u.get('status', 1) == 1]
        users = [{'name': t['name'], 'code': t.get('code', t['name']), 'id': str(t['id'])} for t in users_list]
        user_budgets = {}
        for u in users:
            blist = get_budgets(SCOPE_PERSONAL, u['code'], cur_ym)
            user_budgets[u['code']] = {b['category_id']: b['monthly_limit'] / 100.0 for b in blist}
        family_list = get_budgets(SCOPE_FAMILY, year_month=cur_ym)
        family_budgets = {b['category_id']: b['monthly_limit'] / 100.0 for b in family_list}
        tz = pytz.timezone(config.TIMEZONE)
        now_tz = datetime.now(tz)
        # 根据选中的月份计算统计时间范围
        ym_parts = cur_ym.split('-')
        ym_year, ym_month = int(ym_parts[0]), int(ym_parts[1])
        import calendar
        month_last_day = calendar.monthrange(ym_year, ym_month)[1]
        month_start = now_tz.replace(year=ym_year, month=ym_month, day=1, hour=0, minute=0, second=0, microsecond=0)
        month_end = now_tz.replace(year=ym_year, month=ym_month, day=month_last_day, hour=23, minute=59, second=59)
        # 如果选中的是当前月，截止时间用当前时间
        if cur_ym == now_tz.strftime('%Y-%m'):
            month_end = now_tz
        def _get_stat(user_filter=None):
            from db import get_transactions_statistics
            result = get_transactions_statistics(month_start.strftime('%Y-%m-%d %H:%M:%S'), month_end.strftime('%Y-%m-%d %H:%M:%S'), user_filter=user_filter)
            items = result.get('result', {}).get('items', [])
            name_to_id = {c['name']: c['id'] for c in leaf_only}
            stat = {}
            for item in items:
                cname = item.get('categoryName', '')
                cid = name_to_id.get(cname, '0')
                # 直接用 expenseAmount，不混入收入
                amount = float(item.get('expenseAmount', 0)) / 100.0
                if amount <= 0:
                    continue
                stat[cid] = stat.get(cid, 0) + amount
            return stat
        family_actual = _get_stat()
        user_actual = {}
        for u in users:
            user_actual[u['code']] = _get_stat(f"0:{u['id']}")
        has_current = bool(family_list) or any(user_budgets.values())
        return render_template('budgets.html', tree=tree_cats, leaves=leaf_only, users=users, user_budgets=user_budgets, family_budgets=family_budgets, family_actual=family_actual, user_actual=user_actual, cur_ym=cur_ym, has_current=has_current, version=__version__)
    except Exception as e:
        logger.error(f"加载预算管理页面异常: {e}")
        return f"加载失败: {e}", 500


@bp.route('/api/budget/save', methods=['POST'])
@login_required
def api_budget_save():
    data = request.get_json() or {}
    budgets_data = data.get('budgets', {})
    year_month = data.get('year_month', '')
    if not budgets_data:
        return jsonify({'success': False, 'message': '没有需要保存的数据'}), 400
    try:
        from books.client import BookkeepingClient
        from db import set_budget as db_set_budget, delete_budget as db_delete_budget
        from db import SCOPE_FAMILY, SCOPE_PERSONAL
        bk = BookkeepingClient()
        categories = bk.get_categories(category_type=None)
        name_map = {}
        def _walk(items):
            for item in items:
                cid = str(item.get('id'))
                name_map[cid] = item.get('name', '')
                subs = item.get('subCategories', [])
                if subs:
                    _walk(subs)
        _walk(categories)
        total_saved = 0
        ym = year_month or None
        for scope_key, cat_budgets in budgets_data.items():
            scope = SCOPE_FAMILY if scope_key == 'family' else SCOPE_PERSONAL
            user_code = None if scope_key == 'family' else scope_key
            for cid, amount in cat_budgets.items():
                amount = float(amount)
                cat_name = name_map.get(cid, '')
                if amount > 0:
                    db_set_budget(scope, user_code, cid, cat_name, amount, ym, updated_by=session.get('username', 'admin'))
                    total_saved += 1
                else:
                    db_delete_budget(scope, cid, user_code, ym)
        return jsonify({'success': True, 'message': f'已保存 {total_saved} 条预算记录', 'saved': total_saved})
    except Exception as e:
        logger.error(f"保存预算异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/budget/copy-last-month', methods=['POST'])
@login_required
def api_budget_copy_last_month():
    data = request.get_json() or {}
    year_month = data.get('year_month', '')
    if not year_month or len(year_month) != 7:
        return jsonify({'success': False, 'message': '月份格式错误'}), 400
    try:
        from db import get_budgets, set_budget as db_set_budget
        from db import SCOPE_FAMILY, SCOPE_PERSONAL
        from datetime import datetime
        y, m = int(year_month[:4]), int(year_month[5:7])
        if m == 1:
            last_ym = f'{y-1:04d}-12'
        else:
            last_ym = f'{y:04d}-{m-1:02d}'
        family_existing = get_budgets(SCOPE_FAMILY, year_month=year_month)
        if family_existing:
            return jsonify({'success': False, 'message': '本月已有预算数据，不能复制'}), 400
        copied = 0
        for b in get_budgets(SCOPE_FAMILY, year_month=last_ym):
            db_set_budget(SCOPE_FAMILY, None, b['category_id'], b['category_name'], b['monthly_limit'] / 100.0, year_month, updated_by=session.get('username', 'admin'))
            copied += 1
        user_codes = set()
        for b in get_budgets(SCOPE_PERSONAL, year_month=last_ym):
            user_codes.add(b['user_code'])
        for uc in user_codes:
            for b in get_budgets(SCOPE_PERSONAL, uc, last_ym):
                db_set_budget(SCOPE_PERSONAL, uc, b['category_id'], b['category_name'], b['monthly_limit'] / 100.0, year_month, updated_by=session.get('username', 'admin'))
                copied += 1
        return jsonify({'success': True, 'message': f'已从 {last_ym} 复制 {copied} 条预算'})
    except Exception as e:
        logger.error(f"复制预算异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
