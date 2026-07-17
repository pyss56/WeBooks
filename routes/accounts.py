"""账户管理 API 和页面"""
import json
import logging
import os
from flask import Blueprint, request, jsonify, render_template, session
from auth import login_required
from db import invalidate_account_cache

logger = logging.getLogger(__name__)
bp = Blueprint('accounts', __name__)

# 加载账户图标映射
_ACCOUNT_ICONS_LIST = []
_acc_icons_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'account_icons.json')
try:
    with open(_acc_icons_path, 'r', encoding='utf-8') as f:
        _ACCOUNT_ICONS_LIST = json.load(f)
    logger.info(f"已加载 {len(_ACCOUNT_ICONS_LIST)} 个账户图标")
except Exception as e:
    logger.warning(f"加载账户图标文件失败: {e}")


@bp.route('/api/accounts', methods=['GET'])
def api_accounts():
    """获取账户列表"""
    try:
        from books.client import BookkeepingClient
        bk = BookkeepingClient()
        accounts = bk.get_accounts()
        return jsonify({'success': True, 'data': accounts})
    except Exception as e:
        logger.error(f"获取账户列表异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/accounts/add', methods=['POST'])
@login_required
def api_accounts_add():
    """创建账户"""
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    category = data.get('category', 5)
    icon = data.get('icon', '1')
    color = data.get('color', 'ff6b22')
    currency = data.get('currency', 'CNY')
    comment = data.get('comment', '')
    parent_id = data.get('parent_id', '0')
    if not name:
        return jsonify({'success': False, 'message': '请输入账户名称'}), 400
    if parent_id and parent_id != '0':
        from db import get_connection
        conn = get_connection()
        try:
            cur = conn.execute("SELECT COUNT(*) as cnt FROM \"transaction\" WHERE (account_id=? OR to_account_id=?) AND deleted_at IS NULL", (parent_id, parent_id))
            if cur.fetchone()['cnt'] > 0:
                return jsonify({'success': False, 'message': '父账户已有交易记录，无法添加子账户'}), 400
            # 子账户继承父账户的科目
            cur = conn.execute("SELECT category FROM accounts WHERE id=? AND deleted_at IS NULL", (parent_id,))
            row = cur.fetchone()
            if row:
                category = row['category']
        finally:
            conn.close()
    # 币种强制为 CNY
    currency = 'CNY'
    try:
        from books.client import BookkeepingClient
        bk = BookkeepingClient()
        sub_accounts = data.get('sub_accounts')
        created_by = session.get('username', 'admin')
        account = bk.create_account(name, category, icon=icon, color=color, currency=currency, comment=comment, sub_accounts=sub_accounts, parent_id=parent_id, created_by=created_by)
        if account:
            invalidate_account_cache()
            return jsonify({'success': True, 'account': account})
        else:
            return jsonify({'success': False, 'message': '创建账户失败'}), 500
    except Exception as e:
        logger.error(f"创建账户异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/accounts/modify', methods=['POST'])
@login_required
def api_accounts_modify():
    """修改账户"""
    data = request.get_json() or {}
    account_id = data.get('id', '')
    name = data.get('name', '').strip()
    icon = data.get('icon')
    color = data.get('color')
    comment = data.get('comment')
    hidden = data.get('hidden')
    category = data.get('category')
    if not account_id:
        return jsonify({'success': False, 'message': '缺少账户ID'}), 400
    # 子账户禁止修改科目
    if category is not None:
        from db import get_connection
        conn = get_connection()
        try:
            cur = conn.execute("SELECT parent_id FROM accounts WHERE id=? AND deleted_at IS NULL", (account_id,))
            row = cur.fetchone()
            if row and row['parent_id'] and row['parent_id'] != '0':
                return jsonify({'success': False, 'message': '子账户的科目继承自父账户，不允许修改'}), 400
        finally:
            conn.close()
    # 币种不允许修改
    if data.get('currency') is not None:
        return jsonify({'success': False, 'message': '币种不允许修改'}), 400
    try:
        from books.client import BookkeepingClient
        bk = BookkeepingClient()
        kwargs = {}
        if name:
            kwargs['name'] = name
        if icon is not None:
            kwargs['icon'] = icon
        if color is not None:
            kwargs['color'] = color
        if comment is not None:
            kwargs['comment'] = comment
        if hidden is not None:
            kwargs['hidden'] = hidden
        if category is not None:
            kwargs['category'] = category
        updated_by = session.get('username', 'admin')
        account = bk.modify_account(account_id, updated_by=updated_by, **kwargs)
        if account:
            invalidate_account_cache()
            return jsonify({'success': True, 'account': account})
        else:
            return jsonify({'success': False, 'message': '未检测到变更'}), 200
    except Exception as e:
        logger.error(f"修改账户异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/accounts/delete', methods=['POST'])
@login_required
def api_accounts_delete():
    """删除账户"""
    data = request.get_json() or {}
    account_id = data.get('id', '')
    if not account_id:
        return jsonify({'success': False, 'message': '缺少账户ID'}), 400
    try:
        from books.client import BookkeepingClient
        bk = BookkeepingClient()
        ok = bk.delete_account(account_id)
        if ok:
            invalidate_account_cache()
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': '删除账户失败'}), 500
    except Exception as e:
        logger.error(f"删除账户异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/accounts')
@login_required
def accounts_page():
    """账户设置页面"""
    from version import __app_name__, __version__
    return render_template('accounts.html',
        app_name=__app_name__,
        version=__version__,
    )


@bp.route('/api/user-account', methods=['GET'])
@login_required
def api_get_user_accounts():
    """获取所有账户绑定"""
    try:
        from db import get_user_accounts
        account_id = request.args.get('account_id', '')
        bindings = get_user_accounts(account_id) if account_id else get_user_accounts()
        return jsonify({'success': True, 'bindings': bindings})
    except Exception as e:
        logger.error(f"获取账户绑定异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/user-account/save', methods=['POST'])
@login_required
def api_save_user_accounts():
    """保存账户的用户绑定"""
    data = request.get_json() or {}
    account_id = data.get('account_id', '')
    bindings = data.get('bindings', [])
    confirmed = data.get('confirmed', False)
    if not account_id:
        return jsonify({'success': False, 'message': '缺少账户ID'}), 400
    try:
        from db import set_user_accounts, get_user_accounts, get_connection
        # 找出被解绑的用户（之前有但现在没有的）
        existing = get_user_accounts(account_id)
        existing_codes = {b['user_code'] for b in existing}
        new_codes = {b['user_code'] for b in bindings}
        unbound_codes = existing_codes - new_codes

        # 检查哪些用户的默认账户会受影响
        # 1) 被解绑的用户
        # 2) 之前无绑定（全员可用）→ 现在有绑定：所有将该账户设为默认的用户
        check_codes = set(unbound_codes)
        if not existing_codes and new_codes:
            # 从无绑定变为有绑定，视为移除了其他所有用户的权限
            conn = get_connection()
            try:
                cur = conn.execute("SELECT user_code FROM user_default_account WHERE account_id=? OR income_account_id=?", (account_id, account_id))
                for row in cur.fetchall():
                    if row['user_code'] not in new_codes:
                        check_codes.add(row['user_code'])
            finally:
                conn.close()

        conflicts = []
        if check_codes:
            conn = get_connection()
            try:
                placeholders = ','.join('?' for _ in check_codes)
                cur = conn.execute(f"""
                    SELECT user_code, account_id, income_account_id
                    FROM user_default_account
                    WHERE user_code IN ({placeholders})
                      AND (account_id=? OR income_account_id=?)
                """, list(check_codes) + [account_id, account_id])
                for row in cur.fetchall():
                    directions = []
                    if str(row['account_id']) == account_id:
                        directions.append('支出')
                    if str(row['income_account_id']) == account_id:
                        directions.append('收入')
                    conflicts.append({
                        'user_code': row['user_code'],
                        'directions': directions,
                    })
            finally:
                conn.close()

        # 如果有冲突且未确认，返回确认提示
        if conflicts and not confirmed:
            return jsonify({
                'success': False,
                'needs_confirm': True,
                'conflicts': conflicts,
                'message': f'有 {len(conflicts)} 个用户将该账户设为默认账户，解绑后将清空其默认账户设置',
            })

        updated_by = session.get('username', 'admin')
        ok = set_user_accounts(account_id, bindings, updated_by=updated_by)

        # 如果已确认，清空 user_default_account 中的引用
        if ok and conflicts and confirmed:
            conn = get_connection()
            try:
                for c in conflicts:
                    user_code = c['user_code']
                    updates = []
                    if '支出' in c['directions']:
                        updates.append("account_id=''")
                    if '收入' in c['directions']:
                        updates.append("income_account_id=NULL")
                    if updates:
                        sql = f"UPDATE user_default_account SET {', '.join(updates)}, updated_at=datetime('now','localtime') WHERE user_code=?"
                        conn.execute(sql, (user_code,))
                conn.commit()
            finally:
                conn.close()

        if ok:
            invalidate_account_cache()
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': '保存失败'}), 500
    except Exception as e:
        logger.error(f"保存账户绑定异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/icons/account')
@login_required
def api_account_icons():
    """获取账户图标列表"""
    global _ACCOUNT_ICONS_LIST
    try:
        from books.client import BookkeepingClient
        bk = BookkeepingClient()
        accounts = bk.get_accounts()
        used_ids = set()
        def _walk(items):
            for item in items:
                cid = str(item.get('icon', ''))
                if cid:
                    used_ids.add(cid)
                subs = item.get('subAccounts', [])
                if subs:
                    _walk(subs)
        _walk(accounts)
        icon_map = {i['id']: i for i in _ACCOUNT_ICONS_LIST}
        result = []
        seen = set()
        for cid in sorted(used_ids, key=lambda x: int(x) if x.isdigit() else 0):
            if cid in icon_map and cid not in seen:
                result.append(icon_map[cid])
                seen.add(cid)
        for icon in _ACCOUNT_ICONS_LIST:
            if icon['id'] not in seen:
                result.append(icon)
                seen.add(icon['id'])
        return jsonify({'success': True, 'icons': result})
    except Exception:
        return jsonify({'success': True, 'icons': _ACCOUNT_ICONS_LIST})
