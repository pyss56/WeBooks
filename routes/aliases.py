"""别名管理 API"""
import logging
from flask import Blueprint, request, jsonify
from auth import login_required

logger = logging.getLogger(__name__)
bp = Blueprint('aliases', __name__)


@bp.route('/api/aliases', methods=['GET'])
@login_required
def api_aliases_list():
    """获取别名列表"""
    try:
        from db import list_input_aliases
        target_type = request.args.get('target_type') or None
        aliases = list_input_aliases(target_type)
        return jsonify({'success': True, 'data': aliases})
    except Exception as e:
        logger.error(f"获取别名列表异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/aliases/modify', methods=['POST'])
@login_required
def api_aliases_modify():
    """修改别名（软删除旧记录 + 新建）"""
    data = request.get_json() or {}
    alias_id = data.get('id', 0)
    input_text = data.get('input_text', '').strip()
    target_type = data.get('target_type', '')
    target_id = data.get('target_id', '').strip()
    target_name = data.get('target_name', '').strip() or None

    if not alias_id or not input_text or not target_type or not target_id:
        return jsonify({'success': False, 'message': '缺少必要参数'}), 400
    if target_type not in ('category', 'account'):
        return jsonify({'success': False, 'message': '类型无效'}), 400

    try:
        from db import modify_input_alias
        ok = modify_input_alias(alias_id, input_text, target_type, target_id,
                               target_name=target_name,
                               updated_by='admin')
        if ok:
            return jsonify({'success': True, 'message': '别名已更新'})
        return jsonify({'success': False, 'message': '更新失败'}), 500
    except Exception as e:
        logger.error(f"修改别名异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/aliases/delete', methods=['POST'])
@login_required
def api_aliases_delete():
    """删除别名"""
    data = request.get_json() or {}
    alias_id = data.get('id', 0)
    if not alias_id:
        return jsonify({'success': False, 'message': '缺少ID'}), 400
    try:
        from db import delete_input_alias
        ok = delete_input_alias(alias_id)
        if ok:
            return jsonify({'success': True, 'message': '别名已删除'})
        return jsonify({'success': False, 'message': '删除失败'}), 500
    except Exception as e:
        logger.error(f"删除别名异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
