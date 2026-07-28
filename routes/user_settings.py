"""用户默认交易页面和 API"""
import logging
from flask import Blueprint, request, jsonify, render_template, session
from auth import login_required

logger = logging.getLogger(__name__)
bp = Blueprint('user_settings', __name__)


@bp.route('/user/settings')
@login_required
def user_settings_page():
    """用户默认交易页面"""
    from version import __app_name__, __version__
    from books.client import BookkeepingClient
    from db import get_user_default_settings, get_flat_accounts

    bk = BookkeepingClient()
    user_code = session.get('user_code', '')

    # 获取当前用户的默认设置
    defaults = get_user_default_settings(user_code)

    # 获取展平的科目列表
    expense_cats = bk.get_categories(category_type='expense')
    income_cats = bk.get_categories(category_type='income')

    def _flatten(cats, parent_name=''):
        result = []
        for c in cats:
            subs = c.get('subCategories', [])
            if subs:
                for s in subs:
                    result.append({'id': s.get('id'), 'name': s.get('name'), 'parent_name': c.get('name', '')})
            else:
                result.append({'id': c.get('id'), 'name': c.get('name'), 'parent_name': parent_name})
        return result

    expense_cats_flat = _flatten(expense_cats)
    income_cats_flat = _flatten(income_cats)

    # 获取展平的账户列表（不含隐藏）
    from db import query_accounts
    accounts = query_accounts(user_code=user_code, show_hidden=False, flat=True)

    return render_template(
        'user_settings.html',
        app_name=__app_name__,
        version=__version__,
        defaults=defaults,
        expense_categories=expense_cats_flat,
        income_categories=income_cats_flat,
        accounts=accounts,
    )


@bp.route('/api/user/settings', methods=['GET'])
@login_required
def api_get_user_settings():
    """获取用户的默认交易（管理员可指定 ?user_code=xxx）"""
    from db import get_user_default_settings
    is_admin = session.get('is_admin', False)
    current_user_code = session.get('user_code', '')
    target_user_code = request.args.get('user_code', '').strip() or current_user_code
    if not target_user_code:
        return jsonify({'success': False, 'message': '未登录'}), 401
    if not is_admin and target_user_code != current_user_code:
        return jsonify({'success': False, 'message': '无权查看'}), 403
    defaults = get_user_default_settings(target_user_code)
    return jsonify({'success': True, 'data': defaults, 'user_code': target_user_code})


@bp.route('/api/user/settings/context', methods=['GET'])
@login_required
def api_settings_context():
    """获取页面上下文（当前用户信息 + 管理员可见的用户列表）"""
    is_admin = session.get('is_admin', False)
    user_code = session.get('user_code', '')
    username = session.get('username', '')
    data = {
        'is_admin': is_admin,
        'user_code': user_code,
        'username': username,
    }
    if is_admin:
        from db import get_users
        data['users'] = get_users(status=1)
    return jsonify({'success': True, 'data': data})


@bp.route('/api/user/settings', methods=['POST'])
@login_required
def api_save_user_settings():
    """保存当前用户的默认交易（管理员可指定 user_code 保存其他用户）"""
    from db import save_user_default_settings
    is_admin = session.get('is_admin', False)
    current_user_code = session.get('user_code', '')

    data = request.get_json() or {}
    target_user_code = data.get('user_code', '').strip() or current_user_code
    if not is_admin and target_user_code != current_user_code:
        return jsonify({'success': False, 'message': '无权修改其他用户的设置'}), 403
    if not target_user_code:
        return jsonify({'success': False, 'message': '未指定用户'}), 401

    settings = {
        'default_tx_type': data.get('default_tx_type', 'expense'),
        'account_id': data.get('account_id', ''),
        'income_account_id': data.get('income_account_id', ''),
        'category_id': data.get('category_id', ''),
        'income_category_id': data.get('income_category_id', ''),
        'transfer_to_account_id': data.get('transfer_to_account_id', ''),
    }

    updated_by = session.get('username', current_user_code)
    ok = save_user_default_settings(target_user_code, settings, updated_by=updated_by)
    if ok:
        return jsonify({'success': True, 'message': '默认交易已保存'})
    return jsonify({'success': False, 'message': '保存失败'}), 500
