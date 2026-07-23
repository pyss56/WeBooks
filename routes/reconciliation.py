"""对账管理 API 和页面"""
import logging
from flask import Blueprint, request, jsonify, render_template, session
from auth import login_required

logger = logging.getLogger(__name__)
bp = Blueprint('reconciliation', __name__)


@bp.route('/api/reconciliation/list', methods=['GET'])
@login_required
def api_reconciliation_list():
    try:
        from db import get_reconciliations, count_reconciliations
        limit = int(request.args.get('limit', 20))
        offset = int(request.args.get('offset', 0))
        status = request.args.get('status') or None
        reconciliation_no = request.args.get('reconciliation_no') or None
        date_from = request.args.get('date_from') or None
        date_to = request.args.get('date_to') or None
        data = get_reconciliations(limit=limit, offset=offset, status=status, reconciliation_no=reconciliation_no, date_from=date_from, date_to=date_to)
        total = count_reconciliations(status=status, reconciliation_no=reconciliation_no, date_from=date_from, date_to=date_to)
        return jsonify({'success': True, 'data': data, 'total': total})
    except Exception as e:
        logger.error(f"查询对账列表异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/reconciliation/create', methods=['POST'])
@login_required
def api_reconciliation_create():
    try:
        from datetime import datetime
        from db import create_reconciliation
        now = datetime.now()
        reconciliation_no = now.strftime('RC%Y%m%d%H%M%S')
        created_by = session.get('username', 'admin')
        rid = create_reconciliation(reconciliation_no, created_by)
        if rid > 0:
            return jsonify({'success': True, 'message': '创建成功', 'reconciliation_no': reconciliation_no})
        else:
            return jsonify({'success': False, 'message': '创建失败'}), 500
    except Exception as e:
        logger.error(f"创建对账异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/reconciliation/detail', methods=['GET'])
@login_required
def api_reconciliation_detail():
    try:
        from db import get_reconciliation_by_no, get_transactions
        reconciliation_no = request.args.get('reconciliation_no', '')
        if not reconciliation_no:
            return jsonify({'success': False, 'message': '缺少对账号'}), 400
        header = get_reconciliation_by_no(reconciliation_no)
        if not header:
            return jsonify({'success': False, 'message': '对账不存在'}), 404
        txs = get_transactions(reconciliation_no=reconciliation_no)
        return jsonify({'success': True, 'header': header, 'transactions': txs})
    except Exception as e:
        logger.error(f"获取对账详情异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/reconciliation/add-transactions', methods=['POST'])
@login_required
def api_reconciliation_add_transactions():
    try:
        from db import (update_transaction_reconciliation, get_next_reconciliation_line_no, recalc_reconciliation_amounts)
        data = request.get_json() or {}
        reconciliation_no = data.get('reconciliation_no', '')
        tx_ids = data.get('tx_ids', [])
        if not reconciliation_no or not tx_ids:
            return jsonify({'success': False, 'message': '缺少参数'}), 400
        reconciliation_user = session.get('username', 'admin')
        updated_by = session.get('username', 'admin')
        ok = update_transaction_reconciliation(tx_ids, reconciliation_no, reconciliation_user, updated_by=updated_by)
        if ok:
            from db import get_connection
            conn = get_connection()
            try:
                for tid in tx_ids:
                    line_no = get_next_reconciliation_line_no(reconciliation_no)
                    conn.execute("UPDATE \"transaction\" SET reconciliation_line_no = ? WHERE id = ?", (line_no, tid))
                conn.commit()
            finally:
                conn.close()
            recalc_reconciliation_amounts(reconciliation_no, updated_by=updated_by)
            return jsonify({'success': True, 'message': '添加成功'})
        else:
            return jsonify({'success': False, 'message': '添加失败'}), 500
    except Exception as e:
        logger.error(f"添加交易到对账异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/reconciliation/remove-transactions', methods=['POST'])
@login_required
def api_reconciliation_remove_transactions():
    try:
        from db import update_transaction_reconciliation, recalc_reconciliation_amounts
        data = request.get_json() or {}
        reconciliation_no = data.get('reconciliation_no', '')
        tx_ids = data.get('tx_ids', [])
        if not reconciliation_no or not tx_ids:
            return jsonify({'success': False, 'message': '缺少参数'}), 400
        updated_by = session.get('username', 'admin')
        ok = update_transaction_reconciliation(tx_ids, reconciliation_no, flag='否', updated_by=updated_by)
        if ok:
            recalc_reconciliation_amounts(reconciliation_no, updated_by=updated_by)
            return jsonify({'success': True, 'message': '移除成功'})
        else:
            return jsonify({'success': False, 'message': '移除失败'}), 500
    except Exception as e:
        logger.error(f"移除交易异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/reconciliation/cancel', methods=['POST'])
@login_required
def api_reconciliation_cancel():
    try:
        from db import (get_reconciliation_by_no, update_reconciliation, clear_transaction_reconciliation, get_transactions)
        data = request.get_json() or {}
        reconciliation_no = data.get('reconciliation_no', '')
        if not reconciliation_no:
            return jsonify({'success': False, 'message': '缺少对账号'}), 400
        header = get_reconciliation_by_no(reconciliation_no)
        if not header:
            return jsonify({'success': False, 'message': '对账不存在'}), 404
        txs = get_transactions(reconciliation_no=reconciliation_no)
        if txs:
            return jsonify({'success': False, 'message': '对账有明细记录，无法取消'}), 400
        ok = update_reconciliation(reconciliation_no, status='取消', updated_by=session.get('username', 'admin'))
        if ok:
            return jsonify({'success': True, 'message': '已取消'})
        else:
            return jsonify({'success': False, 'message': '取消失败'}), 500
    except Exception as e:
        logger.error(f"取消对账异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/reconciliation/confirm', methods=['POST'])
@login_required
def api_reconciliation_confirm():
    try:
        from db import (get_reconciliation_by_no, update_reconciliation, get_transactions)
        data = request.get_json() or {}
        reconciliation_no = data.get('reconciliation_no', '')
        if not reconciliation_no:
            return jsonify({'success': False, 'message': '缺少对账号'}), 400
        header = get_reconciliation_by_no(reconciliation_no)
        if not header:
            return jsonify({'success': False, 'message': '对账不存在'}), 404
        txs = get_transactions(reconciliation_no=reconciliation_no)
        if not txs:
            return jsonify({'success': False, 'message': '对账没有明细记录，无法确认'}), 400
        updated_by = session.get('username', 'admin')
        ok = update_reconciliation(reconciliation_no, status='确认', confirm_flag='是', updated_by=updated_by)
        if ok:
            return jsonify({'success': True, 'message': '已确认'})
        else:
            return jsonify({'success': False, 'message': '确认失败'}), 500
    except Exception as e:
        logger.error(f"确认对账异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/reconciliation')
@login_required
def reconciliation_page():
    from version import __app_name__, __version__
    return render_template('reconciliation.html', app_name=__app_name__, version=__version__)


@bp.route('/reconciliation/<reconciliation_no>/edit')
@login_required
def reconciliation_edit_page(reconciliation_no):
    from version import __app_name__, __version__
    return render_template('reconciliation_edit.html', app_name=__app_name__, version=__version__, reconciliation_no=reconciliation_no)
