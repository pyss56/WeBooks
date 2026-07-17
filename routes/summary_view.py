"""任务汇总查看页面"""
import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, render_template, redirect, session
from urllib.parse import quote

logger = logging.getLogger(__name__)
bp = Blueprint('summary_view', __name__)


@bp.route('/s/go/<uuid>')
def oauth_redirect(uuid):
    """企业微信 OAuth 跳转（需在企微后台开启，默认关闭）"""
    from config import get_config
    cfg = get_config()
    if not cfg.WECOM_OAUTH_ENABLED:
        return redirect(f"/s/t/{uuid}")
    corp_id = cfg.WECOM_CORP_ID
    if not corp_id:
        return redirect(f"/s/t/{uuid}")
    entry = cfg.WEB_ENTRY_CODE or ''
    base = cfg.BASE_URL.rstrip('/') if cfg.BASE_URL else ''
    if base and not base.startswith('https://'):
        logger.warning("OAuth 要求 BASE_URL 必须为 HTTPS")
    redirect_uri = f"{base}/{entry}/s/cb/{uuid}".replace('//', '/')
    oauth_url = (
        f"https://open.weixin.qq.com/connect/oauth2/authorize"
        f"?appid={corp_id}"
        f"&redirect_uri={quote(redirect_uri)}"
        f"&response_type=code&scope=snsapi_base"
        f"&state=view#wechat_redirect"
    )
    return redirect(oauth_url)


@bp.route('/s/cb/<uuid>')
def oauth_callback(uuid):
    """OAuth 回调：用 code 换取用户身份，绑定到 session"""
    from config import get_config
    if not get_config().WECOM_OAUTH_ENABLED:
        return redirect(f"/s/t/{uuid}")
    code = request.args.get('code', '')
    if code:
        from wecom.client import WeComClient
        from db import get_user_by_sourceuser
        client = WeComClient()
        userid = client.get_userid_by_oauth_code(code)
        if userid:
            user = get_user_by_sourceuser(userid, source='wecom')
            if user:
                from flask import session
                session['oauth_user'] = user['code']
    return redirect(f"/s/t/{uuid}")


def _is_expired(created_at_str: str) -> bool:
    """检查记录是否超过有效期（从数据字典读取配置，默认7天）"""
    try:
        from db import get_dict
        days = int(get_dict('sys_config', 'summary_expire_days', '7'))
        created = datetime.strptime(created_at_str, '%Y-%m-%d %H:%M:%S')
        return datetime.now() - created > timedelta(days=days)
    except Exception:
        return True


@bp.route('/s/t/<uuid>')
def view_summary(uuid):
    """汇总查看页面"""
    from db import get_task_summary
    record = get_task_summary(uuid)
    if not record:
        return '记录不存在或已过期', 404
    oauth_user = session.get('oauth_user')
    expired = _is_expired(record['created_at']) and not oauth_user
    return render_template('summary_view.html', uuid=uuid, task_name=record['task_name'],
                           executed_at=record['created_at'], expired=expired,
                           oauth_user=oauth_user or '')


@bp.route('/api/summary/<uuid>/data', methods=['POST'])
def api_summary_data(uuid):
    """获取汇总数据（验证码优先，OAuth 用户可免验证码）"""
    data = request.get_json() or {}
    verification = data.get('verification', '')

    from db import get_task_summary
    record = get_task_summary(uuid)
    if not record:
        return jsonify({'success': False, 'message': '记录不存在'}), 404

    # OAuth 已认证用户不受时间限制、免验证码
    oauth_user = session.get('oauth_user')
    if not oauth_user:
        if _is_expired(record['created_at']):
            return jsonify({'success': False, 'message': '已超过7天可见期，已失效'}), 403
        if record['verification'] != verification:
            return jsonify({'success': False, 'message': '验证码错误'}), 403

    import json
    period_name = record.get('period_name') or ''
    title = record.get('task_name', '') or f"📊 {period_name} 消费汇总"
    try:
        chart_data = json.loads(record['chart_data'])
    except Exception:
        chart_data = []
    return jsonify({
        'success': True, 'has_data': True,
        'title': title,
        'chart_data': chart_data,
        'total_expense': record['total_expense'],
        'total_count': record['total_count'],
        'total_budget': record['total_budget'],
    })
