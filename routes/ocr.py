#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OCR识别路由 - 截图上传、识别与记账"""
import logging
import os
import uuid
from datetime import datetime

from flask import Blueprint, request, jsonify, render_template, session
from werkzeug.utils import secure_filename

from auth import login_required

logger = logging.getLogger(__name__)
bp = Blueprint('ocr', __name__)

# 允许的图片格式
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'bmp'}
# 上传大小限制：20MB
MAX_FILE_SIZE = 20 * 1024 * 1024


def allowed_file(filename: str) -> bool:
    """检查文件扩展名是否允许"""
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@bp.route('/ocr')
@login_required
def ocr_page():
    """OCR识别页面"""
    from version import __app_name__, __version__
    from services.ocr import is_ocr_available
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

    # 获取账户列表
    accounts = get_flat_accounts(session.get('user_code'))

    # 获取启用用户列表
    users = [u for u in get_users(status=1) if not u.get('deleted_at')]

    return render_template('ocr.html',
                           app_name=__app_name__,
                           version=__version__,
                           ocr_available=is_ocr_available(),
                           expense_categories=expense_leaves,
                           income_categories=income_leaves,
                           accounts=accounts,
                           users=users)


@bp.route('/api/ocr/upload', methods=['POST'])
@login_required
def api_ocr_upload():
    """上传截图并进行OCR识别"""
    from services.ocr import UPLOAD_DIR, process_image, is_ocr_available

    if not is_ocr_available():
        return jsonify({'success': False, 'message': 'OCR 引擎不可用，请先安装 PaddleOCR'}), 503

    # 检查是否有文件
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '未选择文件'}), 400

    file = request.files['file']
    if file.filename == '' or not file.filename:
        return jsonify({'success': False, 'message': '未选择文件'}), 400

    if not allowed_file(file.filename):
        return jsonify({'success': False,
                        'message': f'不支持的文件格式，仅支持: {", ".join(ALLOWED_EXTENSIONS)}'}), 400

    # 检查文件大小
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    if file_size > MAX_FILE_SIZE:
        return jsonify({'success': False, 'message': '文件大小超过限制（20MB）'}), 400

    # 保存文件
    ext = file.filename.rsplit('.', 1)[1].lower()
    saved_name = f"{uuid.uuid4().hex}.{ext}"
    saved_path = os.path.join(UPLOAD_DIR, saved_name)
    file.save(saved_path)

    try:
        # OCR 识别
        result = process_image(saved_path)
        result['file_path'] = f'/data/ocr_uploads/{saved_name}'

        # 后端统一匹配：商户名→科目，账户名→账户
        merchant = result.get('merchant', '')
        account_name = result.get('account_name', '')
        from services.ocr import resolve_and_match
        if merchant:
            try:
                r = resolve_and_match(merchant, 'category')
                if r.get('resolved_id'):
                    result['resolved_category_id'] = r['resolved_id']
                    result['resolved_category_name'] = r['resolved_name']
            except Exception:
                pass
        if account_name:
            try:
                r = resolve_and_match(account_name, 'account')
                if r.get('resolved_id'):
                    result['resolved_account_id'] = r['resolved_id']
                    result['resolved_account_name'] = r['resolved_name']
            except Exception:
                pass

        return jsonify(result)
    except Exception as e:
        logger.error(f"OCR 处理异常: {e}")
        return jsonify({'success': False, 'message': f'OCR 识别失败: {str(e)}'}), 500


@bp.route('/api/ocr/status', methods=['GET'])
@login_required
def api_ocr_status():
    """检查 OCR 引擎状态"""
    from services.ocr import is_ocr_available
    return jsonify({
        'success': True,
        'available': is_ocr_available(),
    })


# 提供 OCR 上传图片的访问
# 注意：防止路径遍历攻击，send_from_directory 已提供安全保障
@bp.route('/data/ocr_uploads/<filename>')
@login_required
def serve_ocr_upload(filename):
    """提供 OCR 上传图片的访问"""
    from services.ocr import UPLOAD_DIR
    from flask import send_from_directory
    return send_from_directory(UPLOAD_DIR, filename)


# 提供持久化 OCR 图片的访问（以交易 UUID 命名，无需登录，需验证码）
@bp.route('/ts_img/<uuid>.jpg')
def serve_ocr_image(uuid):
    """提供已入账交易的截图访问（与 /tx/<uuid> 共用验证码机制）"""
    from services.ocr import IMAGES_DIR
    from flask import send_from_directory, abort

    # 1. 已登录用户直接放行
    from flask import session as _session
    if _session.get('authenticated'):
        return send_from_directory(IMAGES_DIR, f'ts_{uuid}.jpg')
    # 2. 未登录：校验验证码
    from flask import request as _req
    code = _req.args.get('code', '')
    if code:
        from db import get_connection
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT verify_code FROM \"transaction\" WHERE uuid=?", (uuid,)
            ).fetchone()
            if row and row['verify_code'] and code == row['verify_code']:
                return send_from_directory(IMAGES_DIR, f'ts_{uuid}.jpg')
        finally:
            conn.close()

    abort(403)
