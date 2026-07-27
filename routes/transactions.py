"""交易查询、修改、删除 API"""
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, session, render_template
from auth import login_required

logger = logging.getLogger(__name__)
bp = Blueprint('transactions', __name__)


@bp.route('/api/transactions/list', methods=['GET'])
@login_required
def api_transactions_list():
    """查询交易列表"""
    try:
        from db import get_transactions, count_transactions, get_connection
        limit = int(request.args.get('limit', 500))
        offset = int(request.args.get('offset', 0))
        bill_type = request.args.get('bill_type') or None
        created_by = request.args.get('created_by') or request.args.get('source_user') or None
        account_filter = request.args.get('account_filter') or None
        reconciliation_flag = request.args.get('reconciliation_flag') or None
        transaction_time_from = request.args.get('transaction_time_from') or request.args.get('bill_time_from') or None
        transaction_time_to = request.args.get('transaction_time_to') or request.args.get('bill_time_to') or None
        reconciliation_no = request.args.get('reconciliation_no') or None
        exclude_transfer = request.args.get('exclude_transfer') == '1'

        txs = get_transactions(
            limit=limit, offset=offset,
            bill_type=bill_type, created_by=created_by,
            account_filter=account_filter,
            reconciliation_flag=reconciliation_flag,
            transaction_time_from=transaction_time_from, transaction_time_to=transaction_time_to,
            reconciliation_no=reconciliation_no,
            exclude_transfer=exclude_transfer,
        )
        total = count_transactions(
            bill_type=bill_type, created_by=created_by,
            account_filter=account_filter,
            reconciliation_flag=reconciliation_flag,
            transaction_time_from=transaction_time_from, transaction_time_to=transaction_time_to,
            reconciliation_no=reconciliation_no
        )
        total_income = 0
        total_expense = 0
        conn = get_connection()
        try:
            sql = 'SELECT COALESCE(SUM(CASE WHEN bill_type=\'income\' THEN ABS(amount) ELSE 0 END),0) as ti, COALESCE(SUM(CASE WHEN bill_type=\'expense\' THEN ABS(amount) ELSE 0 END),0) as te FROM "transaction" WHERE deleted_at IS NULL'
            params = []
            if bill_type:
                sql += ' AND bill_type=?'
                params.append(bill_type)
            if created_by:
                sql += ' AND created_by=?'
                params.append(created_by)
            if account_filter:
                sql += ' AND category_name LIKE ?'
                params.append(f'%{account_filter}%')
            if reconciliation_flag:
                sql += ' AND reconciliation_flag=?'
                params.append(reconciliation_flag)
            if transaction_time_from:
                sql += ' AND transaction_time>=?'
                params.append(transaction_time_from)
            if transaction_time_to:
                sql += ' AND transaction_time<=?'
                params.append(transaction_time_to)
            if reconciliation_no:
                sql += ' AND reconciliation_no=?'
                params.append(reconciliation_no)
            cur = conn.execute(sql, params)
            r = cur.fetchone()
            if r:
                total_income = int(r['ti'])
                total_expense = int(r['te'])
        finally:
            conn.close()
        return jsonify({'success': True, 'data': txs, 'total': total, 'total_income': total_income, 'total_expense': total_expense})
    except Exception as e:
        logger.error(f"查询交易列表异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/transactions/users', methods=['GET'])
@login_required
def api_transactions_users():
    """获取交易中的创建人列表"""
    try:
        from db import get_distinct_users
        users = get_distinct_users()
        return jsonify({'success': True, 'data': users})
    except Exception as e:
        logger.error(f"获取创建人列表异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/bills/accounts', methods=['GET'])
@login_required
def api_bills_accounts():
    """获取交易中的科目列表"""
    from db import get_connection
    try:
        conn = get_connection()
        cursor = conn.execute(
            "SELECT DISTINCT category_name FROM \"transaction\" WHERE category_name IS NOT NULL ORDER BY category_name"
        )
        accounts = [r['category_name'] for r in cursor.fetchall()]
        conn.close()
        return jsonify({'success': True, 'data': accounts})
    except Exception as e:
        logger.error(f"获取科目列表异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/categories/leaf-names', methods=['GET'])
@login_required
def api_categories_leaf_names():
    """获取科目叶子名称列表（区分类型）"""
    try:
        from books.client import BookkeepingClient
        bk = BookkeepingClient()
        bill_type = request.args.get('bill_type', 'expense')
        cat_type = 'expense' if bill_type == 'expense' else 'income'
        categories = bk.get_categories(category_type=cat_type)
        leaf_names = []
        for cat in categories:
            subs = cat.get('subCategories', [])
            if subs:
                for sub in subs:
                    leaf_names.append(sub.get('name', ''))
            else:
                leaf_names.append(cat.get('name', ''))
        return jsonify({'success': True, 'data': leaf_names})
    except Exception as e:
        logger.error(f"获取科目叶子名称列表异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/transactions/modify', methods=['POST'])
@login_required
def api_transactions_modify():
    """修改交易信息"""
    data = request.get_json() or {}
    tx_id = data.get('id', 0)
    if not tx_id:
        return jsonify({'success': False, 'message': '缺少交易ID'}), 400
    try:
        from db import get_connection, modify_transaction
        conn = get_connection()
        try:
            cursor = conn.execute("SELECT * FROM \"transaction\" WHERE id = ?", (tx_id,))
            tx = cursor.fetchone()
        finally:
            conn.close()
        if not tx:
            return jsonify({'success': False, 'message': '交易不存在'}), 404
        tx = dict(tx)
        new_type = data.get('bill_type')
        if new_type and new_type != tx['bill_type']:
            return jsonify({'success': False, 'message': '收支类型不允许修改'})
        kwargs = {}
        if 'category_name' in data:
            kwargs['category_name'] = data['category_name']
        if 'amount' in data:
            kwargs['amount'] = data['amount']
        if 'comment' in data:
            kwargs['comment'] = data['comment']
        if 'created_by' in data:
            kwargs['created_by'] = data['created_by']
        if 'transaction_time' in data:
            kwargs['transaction_time'] = data['transaction_time']
        if 'account_id' in data:
            kwargs['account_id'] = data['account_id']
        updated_by = session.get('username', 'admin')
        modify_transaction(tx_id, updated_by=updated_by, **kwargs)
        return jsonify({'success': True, 'message': '交易已更新'})
    except Exception as e:
        logger.error(f"修改交易异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/transactions/delete', methods=['POST'])
@login_required
def api_transactions_delete():
    """删除交易"""
    data = request.get_json() or {}
    tx_id = data.get('id', 0)
    if not tx_id:
        return jsonify({'success': False, 'message': '缺少交易ID'}), 400
    try:
        from db import get_connection, soft_delete_transaction
        conn = get_connection()
        try:
            cursor = conn.execute("SELECT * FROM \"transaction\" WHERE id = ?", (tx_id,))
            tx = cursor.fetchone()
        finally:
            conn.close()
        if not tx:
            return jsonify({'success': False, 'message': '交易不存在'}), 404
        tx = dict(tx)
        if tx.get('reconciliation_flag') == '1':
            return jsonify({'success': False, 'message': '已对账的交易不能删除，请先从对账中移除'})
        updated_by = session.get('username', 'admin')
        soft_delete_transaction(tx_id, updated_by=updated_by)
        return jsonify({'success': True, 'message': '交易已删除'})
    except Exception as e:
        logger.error(f"删除交易异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/transactions/by-uuid', methods=['GET'])
def api_transactions_by_uuid():
    """通过 UUID 获取交易详情（需验证码，有有效期）"""
    tx_uuid = request.args.get('uuid', '')
    code = request.args.get('code', '')
    if not tx_uuid:
        return jsonify({'success': False, 'message': '缺少 uuid'}), 400
    from db import get_connection
    _conn = get_connection()
    _row = _conn.execute("SELECT verify_code FROM \"transaction\" WHERE uuid=?", (tx_uuid,)).fetchone()
    expected = _row['verify_code'] if _row else ''
    _conn.close()
    if not code or code != expected:
        return jsonify({'success': False, 'message': '验证码错误'}), 403
    try:
        from db import get_transaction_by_uuid
        from datetime import datetime, timedelta
        from db import get_dict
        expire_min = int(get_dict('sys_config', 'tx_expire_minutes', '5'))
        tx = get_transaction_by_uuid(tx_uuid)
        if not tx:
            return jsonify({'success': False, 'message': '交易不存在'}), 404
        try:
            created = datetime.strptime(tx['created_at'], '%Y-%m-%d %H:%M:%S')
        except (ValueError, KeyError):
            created = datetime.now()
        if datetime.now() - created > timedelta(minutes=expire_min):
            return jsonify({'success': False, 'message': f'链接已过期（创建超过{expire_min}分钟）'}), 410
        return jsonify({'success': True, 'data': tx})
    except Exception as e:
        logger.error(f"查询交易异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/tx/<tx_uuid>')
def transaction_edit_page_by_uuid(tx_uuid):
    """通过 UUID 打开交易详情页面（无需登录，需验证码）"""
    from version import __app_name__, __version__
    return render_template('tx_detail.html', app_name=__app_name__, version=__version__,
                           tx_uuid=tx_uuid)


@bp.route('/api/transactions/by-uuid/update', methods=['POST'])
def api_transactions_by_uuid_update():
    """通过 UUID 修改交易（无需登录，5分钟有效期）"""
    data = request.get_json() or {}
    tx_uuid = data.get('uuid', '')
    if not tx_uuid:
        return jsonify({'success': False, 'message': '缺少 uuid'}), 400
    try:
        from db import get_transaction_by_uuid, modify_transaction
        from datetime import datetime, timedelta
        tx = get_transaction_by_uuid(tx_uuid)
        if not tx:
            return jsonify({'success': False, 'message': '交易不存在或已过期'}), 404
        # 检查5分钟有效期
        try:
            created = datetime.strptime(tx['created_at'], '%Y-%m-%d %H:%M:%S')
        except (ValueError, KeyError):
            created = datetime.now()
        if datetime.now() - created > timedelta(minutes=5):
            return jsonify({'success': False, 'message': '链接已过期（创建超过5分钟）'}), 410

        kwargs = {}
        if 'category_name' in data:
            kwargs['category_name'] = data['category_name']
        if 'amount' in data:
            val = float(data['amount'])
            kwargs['amount'] = val
        if 'comment' in data:
            kwargs['comment'] = data['comment']
        if 'transaction_time' in data:
            kwargs['transaction_time'] = data['transaction_time']
        if 'account_id' in data:
            kwargs['account_id'] = str(data['account_id'])
        if 'account_name' in data:
            kwargs['account_name'] = data['account_name']
        if 'to_account_id' in data:
            kwargs['to_account_id'] = str(data['to_account_id'])
        if 'to_account_name' in data:
            kwargs['to_account_name'] = data['to_account_name']

        ok = modify_transaction(tx['id'], updated_by='uuid_link', **kwargs)
        if ok:
            result = {'success': True, 'message': '交易已更新'}
            # 如果交易来自通知解析，检测是否有可优化的 alias
            result = _check_alias_suggestion(tx, kwargs, result)
            return jsonify(result)
        return jsonify({'success': False, 'message': '更新失败'}), 500
    except Exception as e:
        logger.error(f"UUID更新交易异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/transactions/by-uuid/delete', methods=['POST'])
def api_transactions_by_uuid_delete():
    """通过 UUID 删除交易（无需登录，5分钟有效期）"""
    data = request.get_json() or {}
    tx_uuid = data.get('uuid', '')
    if not tx_uuid:
        return jsonify({'success': False, 'message': '缺少 uuid'}), 400
    try:
        from db import get_transaction_by_uuid, soft_delete_transaction
        from datetime import datetime, timedelta
        tx = get_transaction_by_uuid(tx_uuid)
        if not tx:
            return jsonify({'success': False, 'message': '交易不存在或已过期'}), 404
        try:
            created = datetime.strptime(tx['created_at'], '%Y-%m-%d %H:%M:%S')
        except (ValueError, KeyError):
            created = datetime.now()
        if datetime.now() - created > timedelta(minutes=5):
            return jsonify({'success': False, 'message': '链接已过期（创建超过5分钟）'}), 410
        if tx.get('reconciliation_flag') == '1':
            return jsonify({'success': False, 'message': '已对账的交易不能删除'})

        ok = soft_delete_transaction(tx['id'], updated_by='uuid_link')
        if ok:
            return jsonify({'success': True, 'message': '交易已删除'})
        return jsonify({'success': False, 'message': '删除失败'}), 500
    except Exception as e:
        logger.error(f"UUID删除交易异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


def _check_alias_suggestion(tx: dict, kwargs: dict, result: dict) -> dict:
    """如果交易来自通知解析且用户修改了科目/账户，提示可更新 alias 映射。"""
    raw_msg = (tx.get('raw_message') or '').strip()
    if not raw_msg:
        return result
    try:
        from services.transaction import parse_transaction_notice_text
        notice = parse_transaction_notice_text(raw_msg)
    except Exception:
        return result
    if not notice.get('success'):
        return result

    suggestions = []
    merchant = notice.get('merchant', '')
    # 科目变了
    new_cat = kwargs.get('category_name', '')
    old_cat = (tx.get('category_name') or '').strip()
    if merchant and new_cat and new_cat != old_cat:
        suggestions.append({
            'type': 'category',
            'hint': merchant,
            'old_value': old_cat,
            'new_value': new_cat,
        })
    # 账户变了
    account_hint = notice.get('account_hint', '')
    new_acct = kwargs.get('account_name', '')
    old_acct = (tx.get('account_name') or '').strip()
    if account_hint and new_acct and new_acct != old_acct:
        suggestions.append({
            'type': 'account',
            'hint': account_hint,
            'old_value': old_acct,
            'new_value': new_acct,
        })

    if suggestions:
        result['alias_suggestions'] = suggestions
        result['message'] += '。检测到通知解析的映射可能需更新'
    return result


def _validate_uuid(tx_uuid):
    """校验 UUID 有效性，返回 (tx, error_response)"""
    from db import get_transaction_by_uuid
    from datetime import datetime, timedelta
    tx = get_transaction_by_uuid(tx_uuid)
    if not tx:
        return None, (jsonify({'success': False, 'message': '交易不存在或已过期'}), 404)
    try:
        created = datetime.strptime(tx['created_at'], '%Y-%m-%d %H:%M:%S')
    except (ValueError, KeyError):
        created = datetime.now()
    if datetime.now() - created > timedelta(minutes=5):
        return None, (jsonify({'success': False, 'message': '链接已过期（创建超过5分钟）'}), 410)
    return tx, None


@bp.route('/api/transactions/by-uuid/alias-save', methods=['POST'])
def api_transactions_by_uuid_alias_save():
    """通过 UUID 页面保存 alias 映射建议（无需登录）"""
    data = request.get_json() or {}
    hint = (data.get('hint') or '').strip()
    target_type = (data.get('type') or '').strip()
    new_value = (data.get('new_value') or '').strip()
    if not hint or target_type not in ('category', 'account') or not new_value:
        return jsonify({'success': False, 'message': '参数不完整'}), 400
    try:
        from db import add_input_alias, get_connection
        target_id = ''
        conn = get_connection()
        try:
            if target_type == 'category':
                row = conn.execute("SELECT id FROM categories WHERE name=?", (new_value,)).fetchone()
            else:
                row = conn.execute("SELECT id FROM accounts WHERE name=?", (new_value,)).fetchone()
                if not row:
                    m = __import__('re').match(r'(.+?)\s*\(', new_value)
                    if m:
                        row = conn.execute("SELECT id FROM accounts WHERE name=?", (m.group(1).strip(),)).fetchone()
            if row:
                target_id = str(row['id'])
        finally:
            conn.close()
        ok = add_input_alias(hint, target_type, target_id, target_name=new_value)
        if ok:
            return jsonify({'success': True, 'message': f'已保存：{hint} → {new_value}'})
        return jsonify({'success': False, 'message': '保存失败'}), 500
    except Exception as e:
        logger.error(f"保存alias建议异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    except Exception as e:
        logger.error(f"保存alias建议异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/transactions/by-uuid/accounts', methods=['GET'])
def api_transactions_by_uuid_accounts():
    """通过 UUID 获取账户列表（按交易所属用户过滤，无需登录，无严格过期限制）"""
    tx_uuid = request.args.get('uuid', '')
    from db import get_connection, get_flat_accounts
    _conn = get_connection()
    _row = _conn.execute("SELECT user_code FROM \"transaction\" WHERE uuid=?", (tx_uuid,)).fetchone()
    _conn.close()
    if not _row:
        return jsonify({'success': False, 'message': '交易不存在'}), 404
    return jsonify({'success': True, 'data': get_flat_accounts(_row['user_code'] or '')})


@bp.route('/api/transactions/by-uuid/categories', methods=['GET'])
def api_transactions_by_uuid_categories():
    """通过 UUID 获取科目列表（无需登录，无严格过期限制）"""
    tx_uuid = request.args.get('uuid', '')
    bill_type = request.args.get('bill_type', 'expense')
    # 仅检查 UUID 是否存在（不强制 5 分钟过期）
    from db import get_connection
    _conn = get_connection()
    _exists = _conn.execute("SELECT id FROM \"transaction\" WHERE uuid=?", (tx_uuid,)).fetchone()
    _conn.close()
    if not _exists:
        return jsonify({'success': False, 'message': '交易不存在'}), 404
    try:
        if bill_type == 'transfer':
            return jsonify({'success': True, 'data': []})
        from books.client import BookkeepingClient
        bk = BookkeepingClient()
        cat_type = bill_type  # 'expense' 或 'income'
        categories = bk.get_categories(category_type=cat_type)
        leaf_cats = []
        for cat in categories:
            subs = cat.get('subCategories', [])
            if subs:
                for sub in subs:
                    leaf_cats.append({'id': sub.get('id', ''), 'name': sub.get('name', '')})
            else:
                leaf_cats.append({'id': cat.get('id', ''), 'name': cat.get('name', '')})
        return jsonify({'success': True, 'data': leaf_cats})
    except Exception as e:
        logger.error(f"UUID获取科目列表异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


# ============ 页面记账 ============

@bp.route('/add-transaction')
@login_required
def add_transaction_page():
    """页面记账页面"""
    from version import __app_name__, __version__
    from books.client import BookkeepingClient
    from db import get_flat_accounts, get_users

    bk = BookkeepingClient()

    # 获取支出科目（叶子节点列表）
    expense_cats = bk.get_categories(category_type='expense')
    expense_leaves = []
    for parent in expense_cats:
        subs = parent.get('subCategories', [])
        if subs:
            for sub in subs:
                expense_leaves.append({
                    'id': sub['id'],
                    'name': sub['name'],
                    'parent_name': parent['name'],
                })
        else:
            expense_leaves.append({
                'id': parent['id'],
                'name': parent['name'],
                'parent_name': '',
            })

    # 获取收入科目（叶子节点列表）
    income_cats = bk.get_categories(category_type='income')
    income_leaves = []
    for parent in income_cats:
        subs = parent.get('subCategories', [])
        if subs:
            for sub in subs:
                income_leaves.append({
                    'id': sub['id'],
                    'name': sub['name'],
                    'parent_name': parent['name'],
                })
        else:
            income_leaves.append({
                'id': parent['id'],
                'name': parent['name'],
                'parent_name': '',
            })

    # 获取扁平账户列表（过滤为当前用户可见或未绑定的）
    accounts = get_flat_accounts(session.get('user_code'))
    is_admin = session.get('is_admin', False)
    user_code = session.get('user_code', '')
    username = session.get('username', '')

    # 获取当前用户的默认账户和模板
    default_account_id = ''
    default_tx_type = 'expense'
    if user_code:
        from db import get_user_account, get_connection
        default_account_id = get_user_account(user_code, direction='expense') or ''
        if not default_account_id:
            default_account_id = get_user_account(user_code, direction='income') or ''
        # 读取默认交易类型
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT default_tx_type, account_id, income_account_id FROM user_default_account WHERE user_code=?",
                (user_code,)
            ).fetchone()
            if row:
                default_tx_type = row['default_tx_type'] or 'expense'
                if default_tx_type == 'expense':
                    aid = row['account_id'] or ''
                    if aid: default_account_id = aid
                elif default_tx_type == 'income':
                    aid = row['income_account_id'] or row['account_id'] or ''
                    if aid: default_account_id = aid
        finally:
            conn.close()

    # 获取启用用户列表
    users = [u for u in get_users(status=1) if not u.get('deleted_at')]

    return render_template(
        'add_transaction.html',
        app_name=__app_name__,
        version=__version__,
        now=datetime.now().strftime('%Y-%m-%d %H:%M'),
        expense_categories=expense_leaves,
        income_categories=income_leaves,
        accounts=accounts,
        users=users,
        session_is_admin=is_admin,
        session_user_code=user_code,
        session_username=username,
        default_account_id=default_account_id,
        default_tx_type=default_tx_type,
    )


@bp.route('/api/transactions/create', methods=['POST'])
@login_required
def api_transactions_create():
    """从页面创建交易记录"""
    data = request.get_json() or {}
    bill_type = data.get('bill_type', 'expense')  # expense / income
    category_name = data.get('category_name', '').strip()
    try:
        amount_val = float(data.get('amount', 0))
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': '金额格式错误'}), 400
    comment = (data.get('comment') or '').strip()
    user_code = data.get('user_code') or session.get('user_code')
    is_admin = session.get('is_admin', False)
    created_by = session.get('username', '')

    # 非管理员只能用自己
    if not is_admin:
        user_code = session.get('user_code')

    if not user_code:
        return jsonify({'success': False, 'message': '未指定记账人'}), 400

    transaction_time = data.get('transaction_time') or None
    account_id = data.get('account_id', '').strip()

    if not category_name:
        return jsonify({'success': False, 'message': '请选择科目'}), 400
    if amount_val <= 0:
        return jsonify({'success': False, 'message': '金额必须大于0'}), 400
    if not account_id:
        return jsonify({'success': False, 'message': '请选择账户'}), 400

    # 确定收支方向
    if bill_type == 'income':
        transaction_type = 2
    elif bill_type == 'transfer':
        transaction_type = 4  # transfer
    else:
        transaction_type = 3  # expense

    # 调用核心记账逻辑
    from books.client import BookkeepingClient
    bk = BookkeepingClient()

    # 转账处理
    if bill_type == 'transfer':
        to_account_id = data.get('to_account_id', '').strip()
        if not to_account_id:
            return jsonify({'success': False, 'message': '请选择转入账户'}), 400
        result = bk.create_transfer(
            from_account_id=account_id,
            to_account_id=to_account_id,
            amount=amount_val,
            comment=comment,
            transaction_time=transaction_time,
            created_by=created_by,
            user_code=user_code,
            source='web',
            source_user=created_by,
        )
        if result.get('success'):
            return jsonify({'success': True, 'message': '转账成功', 'data': result.get('result')})
        else:
            return jsonify({'success': False, 'message': result.get('errorMessage', '转账失败')}), 500

    # 查找科目ID
    from db import get_connection
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT id, name FROM categories WHERE name=? AND parent_id!='0' LIMIT 1",
            (category_name,)
        )
        cat_row = cur.fetchone()
        if not cat_row:
            return jsonify({'success': False, 'message': f'科目不存在: {category_name}'}), 400
        category_id = cat_row['id']
    finally:
        conn.close()

    # 创建交易（使用 web 作为 source）
    result = bk.create_transaction(
        category_id=category_id,
        amount=amount_val,
        account_id=account_id,
        comment=comment,
        transaction_time=transaction_time,
        transaction_type=transaction_type,
        created_by=created_by,
        user_code=user_code,
        source='web',
        source_user=created_by,
        raw_message=None,
        message_log_id=None,
    )

    if result.get('success'):
        return jsonify({'success': True, 'message': '交易创建成功', 'data': result.get('result')})
    else:
        return jsonify({'success': False, 'message': result.get('errorMessage', '创建交易失败')}), 500


@bp.route('/api/transactions/parse-notice', methods=['POST'])
@login_required
def api_parse_notice():
    """解析交易通知文本（银行短信等），返回结构化交易信息"""
    data = request.get_json() or {}
    text = data.get('text', '').strip()
    if not text:
        return jsonify({'success': False, 'message': '请输入文本'}), 400
    try:
        from services.transaction import parse_transaction_notice_text
        from db import resolve_alias
        from services.ocr import resolve_and_match
        result = parse_transaction_notice_text(text)
        if result.get('success'):
            merchant = result.get('merchant', '')
            account_hint = result.get('account_hint', '')
            result['merchant'] = merchant or ''
            result['account_name'] = account_hint or ''
            # 统一匹配：别名→字符匹配
            if merchant:
                r = resolve_and_match(merchant, 'category')
                if r.get('resolved_id'):
                    result['resolved_category_id'] = r['resolved_id']
                    result['resolved_category_name'] = r['resolved_name']
            if account_hint:
                r = resolve_and_match(account_hint, 'account')
                if r.get('resolved_id'):
                    result['resolved_account_id'] = r['resolved_id']
                    result['resolved_account_name'] = r['resolved_name']
            # 格式化时间
            if result.get('transaction_time'):
                result['transaction_time'] = result['transaction_time'].strftime('%Y-%m-%d %H:%M:%S')
            return jsonify(result)
        return jsonify({'success': False, 'message': result.get('message', '未识别')})
    except Exception as e:
        logger.error(f"解析交易通知异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
