#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WeBooks - 企业微信记账助手
通过企业微信自建应用接收消息，调用记账API记账，并推送消费汇总
"""
import json
import logging
import os
import sys
from datetime import datetime

import pytz
from flask import Flask, request, jsonify, render_template, session, redirect, url_for

from config import get_config
from wecom.routes import init_wecom
from urllib.parse import urlparse
from scheduler import SummaryScheduler
from version import __version__, __app_name__, __description__
from auth import login_required, init_auth_routes

# 初始化
app = Flask(__name__)
config = get_config()
app.secret_key = config.SECRET_KEY
app.permanent_session_lifetime = 1800  # Session 30分钟过期
scheduler = SummaryScheduler()

# PC端入口编码保护：未带子路径的请求跳转到指定地址
_entry_code = config.WEB_ENTRY_CODE
if _entry_code:
    _entry_prefix = f"/{_entry_code}"

    class _EntryCodeMiddleware:
        """WSGI 中间件：
        - 已登录用户：有无前缀均可访问
        - 未登录用户：仅公开路径可访问（login、企微回调、消息卡片页等），其他一律跳转
        - 有前缀时剥离前缀，拦截 302 给 Location 补回前缀
        """
        # 无前缀也可访问的路径（企微回调、消息卡片跳转、PWA 资源）
        _no_prefix = ('/qywx/', '/s/t/', '/s/go/', '/s/cb/', '/tx/', '/static/', '/manifest.json', '/sw.js')
        # 需前缀但无需登录的路径
        _no_auth = ('/login', '/logout')

        def __init__(self, wsgi_app):
            self.wsgi_app = wsgi_app
        def _is_authenticated(self, environ):
            """解析 Flask session cookie 判断是否已登录"""
            cookie = environ.get('HTTP_COOKIE', '')
            for part in cookie.split(';'):
                part = part.strip()
                if part.startswith('session='):
                    raw = part[8:]
                    break
            else:
                return False
            try:
                from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
                from flask.json.tag import TaggedJSONSerializer
                import hashlib
                s = URLSafeTimedSerializer(
                    config.SECRET_KEY,
                    salt='cookie-session',
                    serializer=TaggedJSONSerializer(),
                    signer_kwargs={'key_derivation': 'hmac', 'digest_method': hashlib.sha1},
                )
                data = s.loads(raw)
                return bool(data and data.get('authenticated'))
            except (BadSignature, SignatureExpired, Exception):
                return False
        def __call__(self, environ, start_response):
            path = environ.get('PATH_INFO', '')
            has_prefix = path.startswith(_entry_prefix + '/') or path == _entry_prefix
            authed = self._is_authenticated(environ)

            if has_prefix:
                environ['PATH_INFO'] = path[len(_entry_prefix):] or '/'
                if authed:
                    # 已登录 + 有前缀 → 正常处理
                    return self._call_with_rewrite(environ, start_response)
                # 未登录 + 有前缀 → 仅 no_auth/no_prefix 路径放行
                stripped = environ['PATH_INFO']
                if any(stripped.startswith(p) for p in self._no_auth) or \
                   any(stripped.startswith(p) for p in self._no_prefix):
                    return self._call_with_rewrite(environ, start_response)
                # 未登录 + 有前缀 + 非公开路径 → 跳转登录页
                qs = environ.get('QUERY_STRING', '')
                login_url = f"{_entry_prefix}/login?next={stripped}"
                if qs:
                    login_url += '%3F' + qs
                start_response('302 Found', [('Location', login_url)])
                return []
            else:
                if authed:
                    # 已登录 + 无前缀 → 直接放行
                    return self.wsgi_app(environ, start_response)
                # 未登录 + 无前缀 → 仅 no_prefix 路径放行（login 必须有前缀）
                if any(path.startswith(p) for p in self._no_prefix):
                    return self.wsgi_app(environ, start_response)

            # 无前缀 + 未登录 + 非公开路径 → 跳转外部地址
            start_response('302 Found', [('Location', config.WEB_ENTRY_REDIRECT)])
            return []

        def _call_with_rewrite(self, environ, start_response):
            """处理并拦截 302 给 Location 加前缀"""
            def _wrap(status, headers, *args):
                if status.startswith('302'):
                    for i, (k, v) in enumerate(headers):
                        if k.lower() == 'location' and v.startswith('/') and not v.startswith(_entry_prefix):
                            headers[i] = (k, _entry_prefix + v)
                return start_response(status, headers, *args)
            return self.wsgi_app(environ, _wrap)

    app.wsgi_app = _EntryCodeMiddleware(app.wsgi_app)

# 日志配置
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
LOG_RETENTION_DAYS = int(os.getenv('LOG_RETENTION_DAYS', '60'))
LOG_RETENTION_HOURS = LOG_RETENTION_DAYS * 24
os.makedirs(LOG_DIR, exist_ok=True)
log_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                                   datefmt='%Y-%m-%d %H:%M:%S')

from logging.handlers import TimedRotatingFileHandler

def _make_log_handler(filename, level):
    h = TimedRotatingFileHandler(
        os.path.join(LOG_DIR, filename), when='H', interval=1,
        backupCount=LOG_RETENTION_HOURS, encoding='utf-8')
    h.setFormatter(log_formatter)
    h.setLevel(level)
    return h

# 主日志 - 按小时切分
log_handler = _make_log_handler('app.log',
    getattr(logging, os.getenv('LOG_LEVEL', 'INFO').upper(), logging.INFO))

# 推送异常日志
push_log_handler = _make_log_handler('push-error.log', logging.ERROR)

# 控制台日志
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
console_handler.setLevel(getattr(logging, os.getenv('LOG_LEVEL', 'INFO').upper(), logging.INFO))

# 根日志
root_logger = logging.getLogger()
root_logger.setLevel(getattr(logging, os.getenv('LOG_LEVEL', 'INFO').upper(), logging.INFO))
root_logger.addHandler(log_handler)
root_logger.addHandler(console_handler)

# 推送异常专用日志
push_logger = logging.getLogger('push_error')
push_logger.propagate = False
push_logger.addHandler(push_log_handler)
push_logger.setLevel(logging.ERROR)

# API 错误日志
api_error_handler = _make_log_handler('api-error.log', logging.ERROR)
api_error_logger = logging.getLogger('api_error')
api_error_logger.propagate = False
api_error_logger.addHandler(api_error_handler)
api_error_logger.setLevel(logging.ERROR)

# 第三方库日志降级
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('apscheduler').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# ============ API 错误日志拦截 ============

@app.after_request
def log_api_errors(response):
    """记录所有 /api/ 前缀的异常响应"""
    if request.path.startswith('/api/') and response.status_code >= 400:
        body = response.get_data(as_text=True)[:800] if response.get_data() else ''
        api_error_logger.error(
            f"[{response.status_code}] {request.method} {request.path}\n"
            f"  参数: {dict(request.args)}\n"
            f"  响应: {body}")
    return response


# ============ 管理接口 ============

@app.route('/api/status', methods=['GET'])
def api_status():
    """服务状态检查"""
    build_info = {}
    try:
        from version import __build_time__, __commit_sha__
        build_info = {'build_time': __build_time__, 'commit_sha': __commit_sha__}
    except (ImportError, AttributeError):
        pass
    return jsonify({
        'status': 'running',
        'app_name': __app_name__,
        'version': __version__,
        'description': __description__,
        'build_info': build_info,
        'wecom_configured': bool(config.WECOM_CORP_ID and config.WECOM_CORP_SECRET),
    })


@app.route('/api/account-categories')
@login_required
def api_account_categories():
    """获取账户科目列表"""
    from db import get_account_category
    cats = get_account_category()
    return jsonify({'success': True, 'categories': cats})


@app.route('/')
@login_required
def home_page():
    """首页（预算概览）"""
    return render_template('manage.html', app_name=__app_name__, version=__version__)


@app.route('/transaction')
@login_required
def transaction_page():
    """交易查询页面"""
    return render_template('transaction.html', app_name=__app_name__, version=__version__)


@app.route('/message-log')
@login_required
def message_log_page():
    """消息日志页面"""
    return render_template('message_log.html', app_name=__app_name__, version=__version__)


# ============ Blueprint 注册 ============

from routes.transactions import bp as bp_transactions
from routes.accounts import bp as bp_accounts
from routes.categories import bp as bp_categories
from routes.reconciliation import bp as bp_reconciliation
from routes.users import bp as bp_users
from routes.budgets import bp as bp_budgets
from routes.scheduler import bp as bp_scheduler, init_scheduler_routes
from routes.aliases import bp as bp_aliases
from routes.summary_view import bp as bp_summary_view
from routes.menus import bp as bp_menus
from routes.roles import bp as bp_roles

app.register_blueprint(bp_transactions)
app.register_blueprint(bp_accounts)
app.register_blueprint(bp_categories)
app.register_blueprint(bp_reconciliation)
app.register_blueprint(bp_users)
app.register_blueprint(bp_budgets)
app.register_blueprint(bp_scheduler)
app.register_blueprint(bp_aliases)
app.register_blueprint(bp_summary_view)
app.register_blueprint(bp_menus)
app.register_blueprint(bp_roles)

# 注入 scheduler 依赖到 scheduler blueprint
_TASK_FUNCS = {
    'no_budget_summary': None,
    'with_budget_summary': None,
}
init_scheduler_routes(scheduler, _TASK_FUNCS)

# ============ 通用认证 ============
init_auth_routes(app, config)


# ============ 模板上下文注入 ============

@app.context_processor
def inject_globals():
    """注入全局模板变量（按角色过滤菜单）"""
    from db import get_menus_for_user, get_all_menus
    is_admin = session.get('is_admin', False)
    if is_admin:
        menus = [m for m in get_all_menus() if m.get('is_active')]
    else:
        role_codes = session.get('role_codes', [])
        menus = get_menus_for_user(role_codes)
    # 构建菜单树（一级和二级）
    menu_tree = []
    for m in menus:
        if m['parent_id'] == 0:
            clone = dict(m)
            clone['children'] = [c for c in menus if c['parent_id'] == m['id']]
            menu_tree.append(clone)
    return dict(
        menus=menus,
        menu_tree=menu_tree,
        session_is_admin=is_admin,
        session_username=session.get('username', ''),
        session_user_code=session.get('user_code', ''),
        session_role_codes=session.get('role_codes', []),
    )


# ============ PWA 支持 ============

@app.route('/manifest.json')
def manifest_json():
    """PWA Web App Manifest"""
    from version import __app_name__, __description__, __version__
    manifest = {
        "name": __app_name__,
        "short_name": __app_name__,
        "description": __description__,
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f5f5f5",
        "theme_color": "#07c160",
        "orientation": "portrait",
        "icons": [
            {
                "src": "/static/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable"
            },
            {
                "src": "/static/icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable"
            }
        ]
    }
    return manifest, 200, {'Content-Type': 'application/manifest+json; charset=utf-8'}


@app.route('/sw.js')
def service_worker():
    """PWA Service Worker"""
    from flask import make_response
    sw_path = os.path.join(app.root_path, 'static', 'sw.js')
    if os.path.exists(sw_path):
        with open(sw_path, 'r', encoding='utf-8') as f:
            content = f.read()
        resp = make_response(content)
        resp.headers['Content-Type'] = 'application/javascript; charset=utf-8'
        resp.headers['Service-Worker-Allowed'] = '/'
        resp.headers['Cache-Control'] = 'no-cache'
        return resp
    return '', 404


def start_scheduler():
    """启动定时任务"""
    try:
        # 从 scheduler 读取任务类型映射，用于 web 管理页面重新调度
        _TASK_FUNCS.clear()
        _TASK_FUNCS.update(scheduler.get_task_funcs())
        scheduler.start()
    except Exception as e:
        logger.error(f"启动定时任务失败: {e}")


def _seed_data():
    """创建默认科目数据"""
    from db import get_connection
    conn = get_connection()
    try:
        cur = conn.execute("SELECT COUNT(*) as cnt FROM categories")
        if cur.fetchone()['cnt'] > 0:
            return  # 已有数据，跳过
    finally:
        conn.close()

    logger.info("创建默认科目数据...")
    from db import add_category
    expense_parents = [
        ('食品饮料', 'expense'), ('服饰外貌', 'expense'), ('住宅家居', 'expense'),
        ('交通出行', 'expense'), ('交流通讯', 'expense'), ('休闲娱乐', 'expense'),
        ('医疗健康', 'expense'), ('教育学习', 'expense'), ('其他支出', 'expense'),
    ]
    expense_children = {
        '食品饮料': ['食品', '饮料', '水果零食', '烟酒'],
        '服饰外貌': ['衣服', '饰品', '化妆品', '美容美发'],
        '住宅家居': ['家居用品', '电子产品', '维修保养', '家政服务', '水电煤气', '租金贷款'],
        '交通出行': ['公共交通', '打车租车', '私家车费用'],
        '交流通讯': ['电话费', '上网费', '快递费'],
        '休闲娱乐': ['运动健身', '聚会支出', '旅游度假'],
        '医疗健康': ['药品', '体检', '医疗'],
        '教育学习': ['书籍', '课程', '文具'],
        '其他支出': ['其他'],
    }
    for pname, ptype in expense_parents:
        p = add_category(pname, ptype, created_by='system')
        if p:
            for cname in expense_children.get(pname, []):
                add_category(cname, ptype, parent_id=p['id'], created_by='system')

    income_parents = [('工资收入', 'income'), ('投资收益', 'income'), ('其他收入', 'income')]
    income_children = {
        '工资收入': ['工资', '奖金', '补贴'],
        '投资收益': ['利息', '分红', '理财'],
        '其他收入': ['红包', '退款', '兼职'],
    }
    for pname, ptype in income_parents:
        p = add_category(pname, ptype, created_by='system')
        if p:
            for cname in income_children.get(pname, []):
                add_category(cname, ptype, parent_id=p['id'], created_by='system')
    logger.info("默认科目数据创建完成")

    # 创建默认账户（无数据时才创建）
    from db import get_connection
    conn = get_connection()
    try:
        cur = conn.execute("SELECT COUNT(*) as cnt FROM accounts")
        if cur.fetchone()['cnt'] == 0:
            logger.info("创建默认账户...")
            from db import add_account
            cash = add_account('现金', category=1, icon='1', color='ff6b22', currency='CNY', comment='现金账户', created_by='system')
            credit = add_account('信用卡', category=3, icon='8', color='e4393c', currency='CNY', comment='信用卡账户', created_by='system')
            if credit:
                add_account('信用卡1', category=3, icon='8', color='e4393c', currency='CNY', comment='', created_by='system', parent_id=credit['id'])
                add_account('信用卡2', category=3, icon='8', color='e4393c', currency='CNY', comment='', created_by='system', parent_id=credit['id'])
            debit = add_account('借记卡', category=4, icon='7', color='00a65a', currency='CNY', comment='借记卡账户', created_by='system')
            if debit:
                add_account('借记卡1', category=4, icon='7', color='00a65a', currency='CNY', comment='', created_by='system', parent_id=debit['id'])
                add_account('借记卡2', category=4, icon='7', color='00a65a', currency='CNY', comment='', created_by='system', parent_id=debit['id'])
            logger.info("默认账户创建完成")
    finally:
        conn.close()


if __name__ == '__main__':
    logger.info("=" * 50)
    logger.info(f"{__description__} v{__version__} 启动中...")
    logger.info("账本: 本地SQLite")
    logger.info("=" * 50)

    # 初始化数据库
    from db import init_db
    init_db()

    # 初始化数据
    _seed_data()

    # 从环境变量同步管理员到数据库
    from db import sync_admin_user, init_menus
    sync_admin_user(config)
    init_menus()

    # 消息平台初始化
    if config.WECOM_CORP_ID and config.WECOM_CORP_SECRET:
        init_wecom(app)
    else:
        logger.warning("⚠️ 企业微信未配置，消息功能不可用")

    # 启动定时汇总任务
    start_scheduler()

    # 启动Flask
    port = int(os.getenv('PORT', 5001))
    debug = os.getenv('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=port, debug=debug)
