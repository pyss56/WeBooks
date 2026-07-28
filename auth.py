#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用认证模块 - 管理员登录/登出/装饰器/频率限制"""
import time
from functools import wraps

from flask import session, request, redirect, url_for, render_template_string

# 登录失败频率限制（内存）
_login_attempts = {}  # IP -> {'count': int, 'first_attempt': timestamp}


def _check_rate_limit(ip: str) -> bool:
    """5分钟内失败5次则锁定10分钟"""
    now = time.time()
    record = _login_attempts.get(ip)
    if record:
        if record.get('locked_until') and now < record['locked_until']:
            return False
        if now - record['first_attempt'] < 300 and record['count'] >= 5:
            record['locked_until'] = now + 600
            return False
        if now - record['first_attempt'] >= 300:
            _login_attempts[ip] = {'count': 0, 'first_attempt': now}
    return True


def _record_fail(ip: str):
    now = time.time()
    if ip not in _login_attempts:
        _login_attempts[ip] = {'count': 0, 'first_attempt': now}
    _login_attempts[ip]['count'] += 1


def _clear_attempts(ip: str):
    _login_attempts.pop(ip, None)


def login_required(f):
    """需要登录的页面装饰器（管理员或项目用户），未登录跳转到 /login"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated') and not session.get('user_code'):
            return redirect(url_for('auth_login', next=request.path))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """需要管理员权限的装饰器，非管理员返回 403"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('auth_login', next=request.path))
        if not session.get('is_admin'):
            return '权限不足，仅管理员可操作', 403
        return f(*args, **kwargs)
    return decorated


def menu_button_required(menu_url=None):
    """需要菜单按键权限的装饰器，通过角色检查是否有 button 权限
    用法: @menu_button_required('/api/users/bind-wx')
    管理员自动拥有所有权限（跳过检查）。
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get('authenticated'):
                return redirect(url_for('auth_login', next=request.path))
            # 管理员直接放行
            if session.get('is_admin'):
                return f(*args, **kwargs)
            # 非管理员检查菜单权限
            user_code = session.get('user_code')
            if not user_code:
                return '未登录', 401
            from db import check_user_menu_permission
            if not check_user_menu_permission(user_code, menu_url):
                return '权限不足，请联系管理员', 403
            return f(*args, **kwargs)
        return decorated
    if callable(menu_url):
        # 无参数用法 @menu_button_required
        f = menu_url
        menu_url = None
        return decorator(f)
    return decorator


LOGIN_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>登录 - WeBooks</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, 'Microsoft YaHei', sans-serif; background: #f0f2f5;
  display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 20px; }
.card { background: #fff; border-radius: 12px; padding: 40px; width: 380px; max-width: 100%;
  box-shadow: 0 2px 12px rgba(0,0,0,.08); text-align: center; }
.card h1 { font-size: 22px; color: #07c160; margin-bottom: 4px; }
.card .sub { font-size: 14px; color: #999; margin-bottom: 24px; }
.card .field { margin-bottom: 16px; text-align: left; }
.card .field label { display: block; font-size: 13px; color: #666; margin-bottom: 4px; }
.card .field input { width: 100%; padding: 10px 14px; border: 1px solid #d9d9d9; border-radius: 6px;
  font-size: 15px; outline: none; transition: border-color .2s; box-sizing: border-box; }
.card .field input:focus { border-color: #07c160; box-shadow: 0 0 0 2px rgba(7,193,96,.15); }
.card .btn { width: 100%; padding: 10px; border: none; border-radius: 6px; font-size: 15px;
  cursor: pointer; background: #07c160; color: #fff; }
.card .btn:hover { background: #06ad56; }
.card .error { color: #e4393c; font-size: 13px; margin-top: 12px; }
</style>
</head>
<body>
<div class="card">
  <h1>WeBooks</h1>
  <div class="sub">微记账</div>
  <form method="post" action="{% if entry_code %}/{{ entry_code }}{% endif %}/login">
    <div class="field">
      <label>用户名</label>
      <input type="text" name="username" placeholder="请输入用户名" value="{{ username }}" autofocus>
    </div>
    <div class="field">
      <label>密码</label>
      <input type="password" name="password" placeholder="请输入密码">
    </div>
    <input type="hidden" name="next" value="{{ next }}">
    <button class="btn" type="submit">登 录</button>
    {% if error %}<div class="error">{{ error }}</div>{% endif %}
  </form>
</div>
</body>
</html>
"""


def init_auth_routes(app, config):
    """注册登录/登出路由到 Flask 应用"""

    _entry_code = config.WEB_ENTRY_CODE or ''

    @app.route('/login', methods=['GET', 'POST'])
    def auth_login():
        error = ''
        username = ''
        ip = request.remote_addr or 'unknown'
        next_url = request.args.get('next') or request.form.get('next') or '/'
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            if not username:
                error = '请输入用户名'
            elif not password:
                error = '请输入密码'
            elif not _check_rate_limit(ip):
                error = '登录尝试过于频繁，请10分钟后再试'
            else:
                # 全部走数据库验证
                from db import get_user_by_login, verify_user_password
                user = get_user_by_login(username)
                if not user:
                    _record_fail(ip)
                    error = '用户名或密码错误'
                elif not verify_user_password(user['code'], password):
                    _record_fail(ip)
                    remaining = 5 - _login_attempts.get(ip, {}).get('count', 0)
                    error = f'用户名或密码错误，还可尝试 {remaining} 次'
                else:
                    from db import get_user_role_codes
                    session.permanent = True
                    session['authenticated'] = True
                    session['user_code'] = user['code']
                    session['username'] = user['name']
                    session['is_admin'] = bool(user.get('is_admin', 0))
                    session['role_codes'] = get_user_role_codes(user['code'])
                    _clear_attempts(ip)
                    return redirect(next_url)
        return app.response_class(
            render_template_string(LOGIN_HTML, error=error, next=next_url, username=username, entry_code=_entry_code),
            mimetype='text/html'
        )

    @app.route('/logout')
    def auth_logout():
        session.clear()
        # 强制跳转到登录页，确保入口编码前缀正确
        from config import get_config
        cfg = get_config()
        if cfg.WEB_ENTRY_CODE:
            return redirect(f'/{cfg.WEB_ENTRY_CODE}/login')
        return redirect(url_for('auth_login'))
