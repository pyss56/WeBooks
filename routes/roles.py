#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""角色管理 API 和页面"""
import logging
from flask import Blueprint, request, jsonify, render_template, session
from auth import login_required, admin_required, menu_button_required

logger = logging.getLogger(__name__)
bp = Blueprint('roles', __name__)


@bp.route('/roles')
@login_required
def roles_page():
    """角色管理页面"""
    from version import __app_name__, __version__
    return render_template('roles.html', app_name=__app_name__, version=__version__)


@bp.route('/api/roles/list', methods=['GET'])
@login_required
def api_roles_list():
    """获取角色列表"""
    try:
        from db import get_all_roles
        return jsonify({'success': True, 'data': get_all_roles()})
    except Exception as e:
        logger.error(f"获取角色列表异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/roles/create', methods=['POST'])
@menu_button_required('/api/roles/create')
def api_roles_create():
    """新增角色"""
    data = request.get_json() or {}
    code = data.get('code', '').strip()
    name = data.get('name', '').strip()
    description = data.get('description', '').strip() or None
    is_default = 1 if data.get('is_default') else 0
    if not code or not name:
        return jsonify({'success': False, 'message': '编码和名称不能为空'}), 400
    try:
        from db import add_role
        ok = add_role(code, name, description, is_default,
                      created_by=session.get('username', 'admin'))
        return jsonify({'success': ok, 'message': '已创建' if ok else '创建失败（编码可能已存在）'})
    except Exception as e:
        logger.error(f"创建角色异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/roles/update', methods=['POST'])
@menu_button_required('/api/roles/update')
def api_roles_update():
    """更新角色"""
    data = request.get_json() or {}
    role_id = data.get('id')
    if not role_id:
        return jsonify({'success': False, 'message': '缺少角色ID'}), 400
    try:
        from db import update_role
        kw = {}
        if 'name' in data:
            kw['name'] = data['name'].strip()
        if 'description' in data:
            kw['description'] = data['description'].strip()
        if 'is_default' in data:
            kw['is_default'] = 1 if data['is_default'] else 0
        ok = update_role(role_id, updated_by=session.get('username', 'admin'), **kw)
        return jsonify({'success': ok, 'message': '已更新' if ok else '更新失败'})
    except Exception as e:
        logger.error(f"更新角色异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/roles/delete', methods=['POST'])
@menu_button_required('/api/roles/delete')
def api_roles_delete():
    """删除角色"""
    data = request.get_json() or {}
    role_id = data.get('id')
    if not role_id:
        return jsonify({'success': False, 'message': '缺少角色ID'}), 400
    try:
        from db import delete_role
        ok = delete_role(role_id)
        return jsonify({'success': ok, 'message': '已删除' if ok else '删除失败'})
    except Exception as e:
        logger.error(f"删除角色异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/roles/set-menu-bindings', methods=['POST'])
@menu_button_required('/api/roles/set-menu-bindings')
def api_roles_set_menu_bindings():
    """设置角色可见菜单"""
    data = request.get_json() or {}
    role_code = data.get('role_code', '').strip()
    menu_ids = data.get('menu_ids', [])
    if not role_code:
        return jsonify({'success': False, 'message': '缺少角色编码'}), 400
    try:
        from db import set_role_menus
        ok = set_role_menus(role_code, menu_ids,
                            updated_by=session.get('username', 'admin'))
        return jsonify({'success': ok, 'message': '已更新' if ok else '更新失败'})
    except Exception as e:
        logger.error(f"设置角色菜单异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/roles/get-menu-bindings', methods=['GET'])
@login_required
def api_roles_get_menu_bindings():
    """获取角色可见菜单 ID 列表"""
    role_code = request.args.get('role_code', '').strip()
    if not role_code:
        return jsonify({'success': False, 'message': '缺少角色编码'}), 400
    try:
        from db import get_role_menu_ids
        ids = get_role_menu_ids(role_code)
        return jsonify({'success': True, 'data': ids})
    except Exception as e:
        logger.error(f"获取角色菜单异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/roles/users', methods=['GET'])
@login_required
def api_roles_users():
    """获取指定角色下的用户编码列表"""
    role_code = request.args.get('role_code', '').strip()
    if not role_code:
        return jsonify({'success': False, 'message': '缺少角色编码'}), 400
    try:
        from db import get_connection
        conn = get_connection()
        rows = conn.execute(
            "SELECT user_code FROM user_role WHERE role_code=?", (role_code,)).fetchall()
        conn.close()
        codes = [r['user_code'] for r in rows]
        return jsonify({'success': True, 'data': codes})
    except Exception as e:
        logger.error(f"获取角色用户异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/roles/set-users', methods=['POST'])
@menu_button_required('/api/roles/set-users')
def api_roles_set_users():
    """批量设置角色绑定的用户"""
    data = request.get_json() or {}
    role_code = data.get('role_code', '').strip()
    user_codes = data.get('user_codes', [])
    if not role_code:
        return jsonify({'success': False, 'message': '缺少角色编码'}), 400
    try:
        from db import get_connection, get_user_by_login
        conn = get_connection()
        cur = conn.execute("SELECT code FROM role WHERE code=?", (role_code,))
        if not cur.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': '角色不存在'}), 400
        # 清除原有绑定
        conn.execute("DELETE FROM user_role WHERE role_code=?", (role_code,))
        for uc in user_codes:
            conn.execute(
                "INSERT INTO user_role (user_code, role_code, created_by) VALUES (?, ?, ?)",
                (uc, role_code, session.get('username', 'admin')))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': '已更新'})
    except Exception as e:
        logger.error(f"设置角色用户异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
