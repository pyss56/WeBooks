"""用户管理 API 和页面"""
import logging
from flask import Blueprint, request, jsonify, render_template, session
from auth import login_required

logger = logging.getLogger(__name__)
bp = Blueprint('users', __name__)


@bp.route('/api/users/list', methods=['GET'])
@login_required
def api_users_list():
    try:
        from db import get_users, get_all_user_sourceusers
        # status: 不传=全部, 0=停用, 1=启用
        status = request.args.get('status', type=int)
        users = get_users(status=status)
        bindings = get_all_user_sourceusers()
        wx_map = {}
        for b in bindings:
            code = b['user_code']
            if code not in wx_map:
                wx_map[code] = []
            wx_map[code].append({
                'source_user': b['source_user'],
                'source': b.get('source', 'wecom'),
                'push_enabled': bool(b.get('push_enabled', 0)),
            })
        for u in users:
            u['sourceusers'] = wx_map.get(u['code'], [])
        return jsonify({'success': True, 'data': users})
    except Exception as e:
        logger.error(f"获取用户列表异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/users/create', methods=['POST'])
@login_required
def api_users_create():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    code = data.get('code', '').strip() or None
    if not name:
        return jsonify({'success': False, 'message': '请输入用户名称'}), 400
    try:
        from db import add_user
        user = add_user(name, code=code, created_by=session.get('username', 'admin'))
        if user:
            return jsonify({'success': True, 'user': user})
        return jsonify({'success': False, 'message': '创建失败（可能名称已存在）'}), 500
    except Exception as e:
        logger.error(f"创建用户异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/users/update', methods=['POST'])
@login_required
def api_users_update():
    data = request.get_json() or {}
    user_id = data.get('id', '')
    name = data.get('name')
    status = data.get('status')
    if not user_id:
        return jsonify({'success': False, 'message': '缺少用户ID'}), 400
    try:
        from db import update_user
        ok = update_user(user_id, name=name, status=status, updated_by=session.get('username', 'admin'))
        return jsonify({'success': ok, 'message': '已更新' if ok else '更新失败'})
    except Exception as e:
        logger.error(f"更新用户异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/users/delete', methods=['POST'])
@login_required
def api_users_delete():
    data = request.get_json() or {}
    user_id = data.get('id', '')
    if not user_id:
        return jsonify({'success': False, 'message': '缺少用户ID'}), 400
    try:
        from db import delete_user
        result = delete_user(user_id, updated_by=session.get('username', 'admin'))
        return jsonify({'success': result['success'], 'message': result['message']})
    except Exception as e:
        logger.error(f"删除用户异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/users/available-sourceusers', methods=['GET'])
@login_required
def api_users_available_sourceusers():
    try:
        from db import get_available_sourceusers
        sourceusers = get_available_sourceusers()
        return jsonify({'success': True, 'data': sourceusers})
    except Exception as e:
        logger.error(f"获取可用微信账号异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/users/bind-wx', methods=['POST'])
@login_required
def api_users_bind_wx():
    data = request.get_json() or {}
    user_code = data.get('user_code', '').strip()
    source_user = data.get('source_user', '').strip()
    source = data.get('source', 'wecom')
    push_enabled = data.get('push_enabled', False)
    if not user_code or not source_user:
        return jsonify({'success': False, 'message': '缺少参数'}), 400
    try:
        from db import add_user_sourceuser
        result = add_user_sourceuser(user_code, source_user, source,
                                     created_by=session.get('username', 'admin'),
                                     push_enabled=push_enabled)
        return jsonify(result)
    except Exception as e:
        logger.error(f"绑定异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/users/update-push', methods=['POST'])
@login_required
def api_users_update_push():
    """更新绑定记录的推送开关"""
    data = request.get_json() or {}
    user_code = data.get('user_code', '').strip()
    source_user = data.get('source_user', '').strip()
    source = data.get('source', 'wecom')
    push_enabled = data.get('push_enabled', False)
    if not user_code or not source_user:
        return jsonify({'success': False, 'message': '缺少参数'}), 400
    try:
        from db import update_user_sourceuser_push
        ok = update_user_sourceuser_push(user_code, source_user, source, push_enabled)
        return jsonify({'success': ok, 'message': '已更新' if ok else '更新失败'})
    except Exception as e:
        logger.error(f"更新推送开关异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/users/unbind-wx', methods=['POST'])
@login_required
def api_users_unbind_wx():
    data = request.get_json() or {}
    source_user = data.get('source_user', '').strip()
    source = data.get('source', 'wecom')
    if not source_user:
        return jsonify({'success': False, 'message': '缺少source_user'}), 400
    try:
        from db import delete_user_sourceuser
        ok = delete_user_sourceuser(source_user, source=source)
        return jsonify({'success': ok, 'message': '已解绑' if ok else '解绑失败'})
    except Exception as e:
        logger.error(f"解绑异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/user')
@login_required
def user_page():
    from version import __app_name__, __version__
    return render_template('users.html', app_name=__app_name__, version=__version__)


@bp.route('/api/message-logs/list', methods=['GET'])
@login_required
def api_message_logs_list():
    try:
        from db import get_message_logs
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))
        source_user = request.args.get('source_user') or None
        msg_type = request.args.get('msg_type') or None
        logs = get_message_logs(limit=limit, offset=offset, source_user=source_user, msg_type=msg_type)
        return jsonify({'success': True, 'data': logs})
    except Exception as e:
        logger.error(f"查询消息日志异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
