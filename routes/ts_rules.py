#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交易通知解析规则管理"""
import json
import logging
import re
from datetime import datetime

from flask import Blueprint, request, jsonify, render_template, session
from auth import login_required

logger = logging.getLogger(__name__)
bp = Blueprint('ts_rules', __name__)


# ── 页面路由 ──────────────────────────────

@bp.route('/ts/rules')
@login_required
def ts_rules_page():
    """解析规则配置页面"""
    from version import __app_name__, __version__
    from db import get_connection
    conn = get_connection()
    try:
        rules = [dict(r) for r in conn.execute(
            "SELECT * FROM ts_parse_rule ORDER BY priority, id"
        ).fetchall()]
    finally:
        conn.close()
    from db import get_dict_group
    _field_type_names = get_dict_group('field_type')
    return render_template('ts_rules.html', app_name=__app_name__, version=__version__,
                           rules=rules, field_type_names=_field_type_names)

# ── 解析规则 CRUD ──────────────────────────

@bp.route('/api/ts/rules', methods=['GET'])
@login_required
def api_ts_rules_list():
    """获取所有解析规则"""
    from db import get_connection
    conn = get_connection()
    try:
        rules = [dict(r) for r in conn.execute(
            "SELECT * FROM ts_parse_rule ORDER BY priority, id"
        ).fetchall()]
        for r in rules:
            if r.get('config'):
                try:
                    r['config'] = json.loads(r['config'])
                except (json.JSONDecodeError, TypeError):
                    r['config'] = {}
            else:
                r['config'] = {}
        return jsonify({'success': True, 'data': rules})
    except Exception as e:
        logger.error(f"获取解析规则失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()


@bp.route('/api/ts/rules/test', methods=['POST'])
@login_required
def api_ts_rules_test():
    """测试正则解析 — 传入通知文本，自动用所有启用规则提取结果"""
    data = request.get_json() or {}
    text = data.get('text', '').strip()
    if not text:
        return jsonify({'success': False, 'message': '请提供通知文本'}), 400

    from db import get_connection
    conn = get_connection()
    try:
        rules = [dict(r) for r in conn.execute(
            "SELECT * FROM ts_parse_rule WHERE enabled=1 ORDER BY priority, id"
        ).fetchall()]
    finally:
        conn.close()

    if not rules:
        return jsonify({'success': False, 'message': '没有启用的解析规则'}), 400

    results = []
    # 按字段类型分组，优先级遍历，首个匹配即停止
    from collections import OrderedDict
    field_rules = OrderedDict()
    for r in rules:
        ft = r['field_type']
        if ft not in field_rules:
            field_rules[ft] = []
        field_rules[ft].append(r)

    results = []
    for ft, ft_rules in field_rules.items():
        matched = None
        for r in ft_rules:
            pat = r.get('regex_pattern', '')
            if not pat:
                continue
            try:
                m = re.search(pat, text)
                if m:
                    groups = [g for g in m.groups() if g]
                    matched = {
                        'field_type': ft,
                        'matched': True,
                        'value': m.group(0),
                        'all_groups': groups,
                        'rule_id': r['id'],
                        'demo_text': r.get('demo_text', ''),
                        'regex_pattern': pat,
                    }
                    break
            except re.error:
                continue
        if matched:
            results.append(matched)
        else:
            last = ft_rules[-1]
            results.append({
                'field_type': ft, 'matched': False, 'value': None,
                'rule_id': last['id'], 'demo_text': last.get('demo_text', ''),
            })

    return jsonify({'success': True, 'data': results})


@bp.route('/api/ts/rules', methods=['POST'])
@login_required
def api_ts_rules_save():
    """新增或更新解析规则"""
    data = request.get_json() or {}
    rule_id = data.get('id')
    field_type = data.get('field_type', '').strip()
    regex_pattern = data.get('regex_pattern', '').strip()
    priority = int(data.get('priority', 5))
    demo_text = (data.get('demo_text') or '').strip()
    enabled = 1 if data.get('enabled', True) else 0
    config = data.get('config', {})

    if not field_type or not regex_pattern:
        return jsonify({'success': False, 'message': '字段类型和正则不能为空'}), 400

    config_json = json.dumps(config, ensure_ascii=False) if config else None
    username = session.get('username', 'admin')

    from db import get_connection
    conn = get_connection()
    try:
        if rule_id:
            conn.execute(
                "UPDATE ts_parse_rule SET field_type=?, regex_pattern=?, priority=?, demo_text=?, enabled=?, config=?, updated_by=? WHERE id=?",
                (field_type, regex_pattern, priority, demo_text, enabled, config_json, username, rule_id)
            )
        else:
            cur = conn.execute(
                "INSERT INTO ts_parse_rule (field_type, regex_pattern, priority, demo_text, enabled, config, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (field_type, regex_pattern, priority, demo_text, enabled, config_json, username)
            )
            rule_id = cur.lastrowid

        conn.commit()
        return jsonify({'success': True, 'id': rule_id, 'message': '规则已保存'})
    except Exception as e:
        logger.error(f"保存解析规则失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()


@bp.route('/api/ts/rules/<int:rule_id>', methods=['DELETE'])
@login_required
def api_ts_rules_delete(rule_id):
    """删除解析规则"""
    from db import get_connection
    conn = get_connection()
    try:
        conn.execute("DELETE FROM ts_parse_rule WHERE id=?", (rule_id,))
        conn.commit()
        return jsonify({'success': True, 'message': '规则已删除'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()
