"""科目管理 API 和页面"""
import json
import logging
import os
from flask import Blueprint, request, jsonify, render_template, session
from auth import login_required

logger = logging.getLogger(__name__)
bp = Blueprint('categories', __name__)

# 加载科目图标映射
_CATEGORY_ICONS_MAP = {}
_CATEGORY_ICONS_LIST = []
_icons_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'category_icons.json')
try:
    with open(_icons_path, 'r', encoding='utf-8') as f:
        _CATEGORY_ICONS_LIST = json.load(f)
        _CATEGORY_ICONS_MAP = {item['id']: item for item in _CATEGORY_ICONS_LIST}
    logger.info(f"已加载 {len(_CATEGORY_ICONS_LIST)} 个科目图标映射")
except Exception as e:
    logger.warning(f"加载科目图标映射文件失败: {e}")


@bp.route('/categories')
@login_required
def categories_page():
    """科目管理页面"""
    try:
        from books.client import BookkeepingClient
        bk = BookkeepingClient()
        from version import __version__
        return render_template('categories.html', version=__version__)
    except Exception as e:
        logger.error(f"加载科目管理页面异常: {e}")
        return f"加载失败: {e}", 500


@bp.route('/api/categories/income', methods=['GET'])
def api_income_categories():
    """获取收入科目列表"""
    try:
        from books.client import BookkeepingClient
        bk = BookkeepingClient()
        categories = bk.get_categories(category_type='income')
        return jsonify({'success': True, 'data': categories})
    except Exception as e:
        logger.error(f"获取收入科目异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/categories/expense', methods=['GET'])
def api_expense_categories():
    """获取支出科目列表"""
    try:
        from books.client import BookkeepingClient
        bk = BookkeepingClient()
        categories = bk.get_categories(category_type='expense')
        return jsonify({'success': True, 'data': categories})
    except Exception as e:
        logger.error(f"获取支出科目异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/icons/category')
@login_required
def api_category_icons():
    """获取可用的科目图标列表"""
    try:
        from books.client import BookkeepingClient
        bk = BookkeepingClient()
        all_cats = bk.get_categories(category_type=None)
        used_ids = []
        seen = set()
        def _walk(items):
            for item in items:
                cid = str(item.get('icon', ''))
                if cid and cid not in seen:
                    used_ids.append(cid)
                    seen.add(cid)
                subs = item.get('subCategories', [])
                if subs:
                    _walk(subs)
        _walk(all_cats)
        result = []
        result_seen = set()
        for cid in used_ids:
            if cid in _CATEGORY_ICONS_MAP:
                result.append(_CATEGORY_ICONS_MAP[cid])
                result_seen.add(cid)
        for item in _CATEGORY_ICONS_LIST:
            if item['id'] not in result_seen:
                result.append(item)
                result_seen.add(item['id'])
        for cid in used_ids:
            if cid not in result_seen:
                result.append({'id': cid, 'css': 'las la-question-circle', 'emoji': '❓', 'name': f'图标{cid}'})
                result_seen.add(cid)
        return jsonify({'success': True, 'icons': result})
    except Exception:
        return jsonify({'success': True, 'icons': _CATEGORY_ICONS_LIST})


@bp.route('/api/categories/list')
@login_required
def api_categories_list():
    """获取科目列表"""
    try:
        from books.client import BookkeepingClient
        bk = BookkeepingClient()
        all_cats = bk.get_categories(category_type=None)
        def _sort_key(c):
            return c.get('displayOrder', 0) or 0
        for cat in all_cats:
            subs = cat.get('subCategories', [])
            if subs:
                subs.sort(key=_sort_key)
        all_cats.sort(key=_sort_key)
        return jsonify({'success': True, 'categories': all_cats})
    except Exception as e:
        logger.error(f"获取科目列表异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/categories/add', methods=['POST'])
@login_required
def api_categories_add():
    """创建科目"""
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    cat_type = data.get('type', 'expense')
    parent_id = data.get('parentId', '0')
    icon = data.get('icon', '1')
    color = data.get('color', 'ff6b22')
    comment = data.get('comment', '')
    if not name:
        return jsonify({'success': False, 'message': '请输入科目名称'}), 400
    try:
        from books.client import BookkeepingClient
        bk = BookkeepingClient()
        created_by = session.get('username', 'admin')
        category = bk.create_category(name, cat_type, parent_id, icon=icon, color=color, comment=comment, created_by=created_by)
        if category:
            return jsonify({'success': True, 'category': category})
        else:
            return jsonify({'success': False, 'message': '创建科目失败'}), 500
    except Exception as e:
        logger.error(f"创建科目异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/categories/modify', methods=['POST'])
@login_required
def api_categories_modify():
    """修改科目"""
    data = request.get_json() or {}
    category_id = data.get('id', '')
    name = data.get('name', '').strip()
    parent_id = data.get('parentId')
    icon = data.get('icon', '1')
    color = data.get('color')
    comment = data.get('comment')
    hidden = data.get('hidden')
    if not category_id:
        return jsonify({'success': False, 'message': '缺少科目ID'}), 400
    if not name:
        return jsonify({'success': False, 'message': '请输入科目名称'}), 400
    try:
        from books.client import BookkeepingClient
        bk = BookkeepingClient()
        kwargs = {'name': name, 'icon': icon}
        if parent_id and parent_id != '0':
            kwargs['parent_id'] = parent_id
        if color is not None:
            kwargs['color'] = color
        if comment is not None:
            kwargs['comment'] = comment
        if hidden is not None:
            kwargs['hidden'] = hidden
        updated_by = session.get('username', 'admin')
        category = bk.modify_category(category_id, updated_by=updated_by, **kwargs)
        if category:
            return jsonify({'success': True, 'category': category})
        else:
            return jsonify({'success': False, 'message': '修改科目失败'}), 500
    except Exception as e:
        logger.error(f"修改科目异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/categories/delete', methods=['POST'])
@login_required
def api_categories_delete():
    """删除科目"""
    data = request.get_json() or {}
    category_id = data.get('id', '')
    if not category_id:
        return jsonify({'success': False, 'message': '缺少科目ID'}), 400
    try:
        from books.client import BookkeepingClient
        bk = BookkeepingClient()
        ok = bk.delete_category(category_id)
        if ok:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': '该科目已被使用，无法删除'})
    except Exception as e:
        err_msg = str(e)
        logger.error(f"删除科目异常: {err_msg}")
        if 'used' in err_msg.lower() or '存在' in err_msg or 'delete' in err_msg.lower():
            return jsonify({'success': False, 'message': '该科目已被使用，无法删除'})
        return jsonify({'success': False, 'message': f'删除失败: {err_msg}'})


@bp.route('/api/categories/reorder', methods=['POST'])
@login_required
def api_categories_reorder():
    """批量调整科目排序"""
    data = request.get_json() or {}
    orders = data.get('orders', [])
    if not orders:
        return jsonify({'success': False, 'message': '缺少排序数据'}), 400
    try:
        from books.client import BookkeepingClient
        bk = BookkeepingClient()
        updated_by = session.get('username', 'admin')
        pairs = [(o['id'], o['displayOrder']) for o in orders]
        ok = bk.move_categories(pairs, updated_by=updated_by)
        if ok:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': '排序失败'}), 500
    except Exception as e:
        logger.error(f"排序科目异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
