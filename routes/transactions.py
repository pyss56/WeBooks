"""交易查询、修改、删除 API"""
import logging
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
            return jsonify({'success': True, 'message': '交易已更新'})
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


@bp.route('/api/transactions/by-uuid/accounts', methods=['GET'])
def api_transactions_by_uuid_accounts():
    """通过 UUID 获取账户列表（按交易所属用户过滤，展平为叶子列表，无需登录）"""
    tx_uuid = request.args.get('uuid', '')
    tx, err = _validate_uuid(tx_uuid)
    if err:
        return err
    from db import get_flat_accounts
    return jsonify({'success': True, 'data': get_flat_accounts(tx.get('user_code', ''))})


@bp.route('/api/transactions/by-uuid/categories', methods=['GET'])
def api_transactions_by_uuid_categories():
    """通过 UUID 获取科目列表（无需登录）"""
    tx_uuid = request.args.get('uuid', '')
    bill_type = request.args.get('bill_type', 'expense')
    tx, err = _validate_uuid(tx_uuid)
    if err:
        return err
    try:
        if bill_type == 'transfer':
            return jsonify({'success': True, 'data': []})
        from books.client import BookkeepingClient
        bk = BookkeepingClient()
        cat_type = 2 if bill_type == 'expense' else 1
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
        logger.error(f"UUID获取科目列表异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
