#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""侧边栏菜单管理 API"""
import logging
from flask import Blueprint, request, jsonify, render_template, session
from auth import login_required, admin_required, menu_button_required

logger = logging.getLogger(__name__)
bp = Blueprint('menus', __name__)


@bp.route('/menu')
@login_required
def menus_page():
    """菜单管理页面"""
    from version import __app_name__, __version__
    return render_template('menus.html', app_name=__app_name__, version=__version__)


@bp.route('/api/menus/list', methods=['GET'])
@login_required
def api_menus_list():
    """获取菜单列表"""
    try:
        from db import get_all_menus
        menus = get_all_menus()
        return jsonify({'success': True, 'data': menus})
    except Exception as e:
        logger.error(f"获取菜单列表异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/menus/create', methods=['POST'])
@menu_button_required('/api/menus/create')
def api_menus_create():
    """新增菜单"""
    data = request.get_json() or {}
    label = data.get('label', '').strip()
    icon = data.get('icon', '📄').strip()
    url = data.get('url', '').strip() or None
    sort_order = int(data.get('sort_order', 0))
    parent_id = int(data.get('parent_id', 0))
    typ = data.get('type', 'page')
    if not label:
        return jsonify({'success': False, 'message': '请输入菜单名称'}), 400
    if typ == 'page' and (not url or not url.startswith('/')):
        return jsonify({'success': False, 'message': '页面类型必须填写以 / 开头的链接'}), 400
    try:
        from db import add_menu
        ok = add_menu(label, icon, url, sort_order, parent_id, typ,
                      created_by=session.get('username', 'admin'))
        return jsonify({'success': ok, 'message': '已创建' if ok else '创建失败'})
    except Exception as e:
        logger.error(f"创建菜单异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/menus/update', methods=['POST'])
@menu_button_required('/api/menus/update')
def api_menus_update():
    """更新菜单"""
    data = request.get_json() or {}
    menu_id = data.get('id')
    if not menu_id:
        return jsonify({'success': False, 'message': '缺少菜单ID'}), 400
    try:
        from db import update_menu
        kw = {}
        if 'label' in data:
            kw['label'] = data['label'].strip()
        if 'icon' in data:
            kw['icon'] = data['icon'].strip()
        if 'url' in data:
            kw['url'] = (data['url'] or '').strip() or None
        if 'sort_order' in data:
            kw['sort_order'] = int(data['sort_order'])
        if 'parent_id' in data:
            kw['parent_id'] = int(data['parent_id'])
        if 'type' in data:
            kw['typ'] = data['type']
        if 'default_expanded' in data:
            kw['default_expanded'] = 1 if data.get('default_expanded') else 0
        if 'is_active' in data:
            kw['is_active'] = 1 if data['is_active'] else 0
        ok = update_menu(menu_id, updated_by=session.get('username', 'admin'), **kw)
        return jsonify({'success': ok, 'message': '已更新' if ok else '更新失败'})
    except Exception as e:
        logger.error(f"更新菜单异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/menus/delete', methods=['POST'])
@menu_button_required('/api/menus/delete')
def api_menus_delete():
    """删除菜单"""
    data = request.get_json() or {}
    menu_id = data.get('id')
    if not menu_id:
        return jsonify({'success': False, 'message': '缺少菜单ID'}), 400
    try:
        from db import delete_menu
        ok = delete_menu(menu_id)
        return jsonify({'success': ok, 'message': '已删除' if ok else '删除失败'})
    except Exception as e:
        logger.error(f"删除菜单异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
