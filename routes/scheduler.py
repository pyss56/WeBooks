"""计划任务管理 API 和页面"""
import logging
from flask import Blueprint, request, jsonify, render_template, session
from auth import login_required

logger = logging.getLogger(__name__)
bp = Blueprint('scheduler', __name__)

# 这些会在 app.py 注册时注入
_scheduler = None
_task_funcs = {}

def init_scheduler_routes(scheduler, task_funcs):
    global _scheduler, _task_funcs
    _scheduler = scheduler
    _task_funcs = task_funcs


@bp.route('/scheduled-tasks')
@login_required
def scheduled_tasks_page():
    from version import __app_name__, __version__
    return render_template('scheduled_tasks.html', app_name=__app_name__, version=__version__)


@bp.route('/api/scheduler/jobs')
@login_required
def api_scheduler_jobs():
    try:
        from db import get_scheduled_tasks
        db_tasks = get_scheduled_tasks()
        jobs = []
        for t in db_tasks:
            task_id = t['task_id']
            sched_job = _scheduler.scheduler.get_job(task_id) if _scheduler else None
            next_run = sched_job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if sched_job and sched_job.next_run_time else ''
            running = sched_job is not None and sched_job.next_run_time is not None
            day = t.get('day')
            if day:
                cron_desc = f'每月 {day} 号 {t["hour"]:02d}:{t["minute"]:02d}'
            else:
                cron_desc = f'每天 {t["hour"]:02d}:{t["minute"]:02d}'
            push_user_raw = t.get('push_user') or ''
            push_user_display = _format_push_user_display(push_user_raw)
            jobs.append({
                'id': task_id, 'name': t['name'], 'task_type': t['task_type'],
                'cron_desc': cron_desc, 'hour': t['hour'], 'minute': t['minute'],
                'day': day, 'enabled': bool(t['enabled']),
                'filter_user': t.get('filter_user') or '',
                'push_user': push_user_raw,
                'push_user_display': push_user_display,
                'range_config': t.get('range_config') or '',
                'per_user_push': bool(t.get('per_user_push', 0)),
                'custom_sql': t.get('custom_sql') or '',
                'custom_sql_title': t.get('custom_sql_title') or '',
                'custom_sql_format': t.get('custom_sql_format') or '',
                'next_run': next_run, 'running': running,
            })
        return jsonify({'success': True, 'jobs': jobs})
    except Exception as e:
        logger.error(f"获取计划任务列表异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


def _format_push_user_display(push_raw: str) -> str:
    """将 push_user (JSON 用户编码数组) 转为友好显示文本"""
    if not push_raw:
        return ''
    try:
        import json
        codes = json.loads(push_raw)
        if not isinstance(codes, list) or not codes:
            return ''
        from db import get_users
        all_users = get_users()
        name_map = {u['code']: u['name'] for u in all_users}
        names = [name_map.get(c, c) for c in codes]
        return ', '.join(names)
    except (json.JSONDecodeError, TypeError):
        return push_raw


def _reschedule_job(task_id, task_type, hour, minute, day=None):
    from apscheduler.triggers.cron import CronTrigger
    from config import get_config
    from functools import partial
    cfg = get_config()
    tz = cfg.TIMEZONE
    # custom_sql 任务的 task_id 与 task_type 不同，需要创建绑定实际 task_id 的偏函数
    if task_type == 'custom_sql':
        func = partial(_scheduler._push_with_config, task_id)
    else:
        func = _task_funcs.get(task_type)
    if not func:
        logger.warning(f"未知任务类型: {task_type}")
        return
    if day:
        trigger = CronTrigger(day=day, hour=hour, minute=minute, timezone=tz)
    else:
        trigger = CronTrigger(hour=hour, minute=minute, timezone=tz)
    existing = _scheduler.scheduler.get_job(task_id)
    if existing:
        _scheduler.scheduler.reschedule_job(task_id, trigger=trigger)
    else:
        _scheduler.scheduler.add_job(func, trigger, id=task_id, name=task_id, replace_existing=True)


@bp.route('/api/scheduler/jobs/<job_id>/run', methods=['POST'])
@login_required
def api_scheduler_job_run(job_id):
    logger.info(f"[执行任务] 收到请求 job_id={job_id}")
    try:
        from db import get_scheduled_task_active
        task = get_scheduled_task_active(job_id)
        if not task:
            return jsonify({'success': False, 'message': '任务不存在'}), 404
        _scheduler._push_with_config(job_id)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"[执行任务] 异常: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/scheduler/jobs/<job_id>/toggle', methods=['POST'])
@login_required
def api_scheduler_job_toggle(job_id):
    try:
        data = request.get_json() or {}
        enable = data.get('enable', True)
        from db import get_scheduled_task_active, upsert_scheduled_task
        task = get_scheduled_task_active(job_id)
        if not task:
            return jsonify({'success': False, 'message': '任务不存在'}), 404
        updated_by = session.get('username', 'admin')
        ok = upsert_scheduled_task(task_id=job_id, name=task['name'], task_type=task['task_type'],
            hour=task['hour'], minute=task['minute'], day=task.get('day'),
            filter_user=task.get('filter_user'), push_user=task.get('push_user'),
            range_config=task.get('range_config'), custom_sql=task.get('custom_sql'),
            custom_sql_title=task.get('custom_sql_title'), custom_sql_format=task.get('custom_sql_format'),
            per_user_push=bool(task.get('per_user_push', 0)),
            enabled=enable, updated_by=updated_by)
        if not ok:
            return jsonify({'success': False, 'message': '保存失败'}), 500
        if enable:
            _reschedule_job(job_id, task['task_type'], task['hour'], task['minute'], task.get('day'))
        else:
            _scheduler.scheduler.pause_job(job_id)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"切换任务状态异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/scheduler/jobs/<job_id>/update', methods=['POST'])
@login_required
def api_scheduler_job_update(job_id):
    try:
        from db import get_scheduled_task_active, upsert_scheduled_task
        data = request.get_json() or {}
        time_str = data.get('time', '21:00')
        hour, minute = map(int, time_str.split(':'))
        day = data.get('day')
        if day:
            day = int(day)
        task = get_scheduled_task_active(job_id)
        if not task:
            return jsonify({'success': False, 'message': '任务不存在'}), 404
        filter_user = data.get('filter_user', task.get('filter_user') or '')
        push_user = data.get('push_user', task.get('push_user') or '')
        range_config = data.get('range_config', task.get('range_config') or '')
        custom_sql = data.get('custom_sql', task.get('custom_sql') or '')
        custom_sql_title = data.get('custom_sql_title', task.get('custom_sql_title') or '')
        custom_sql_format = data.get('custom_sql_format', task.get('custom_sql_format') or '')
        per_user_push = data.get('per_user_push', bool(task.get('per_user_push', 0)))
        updated_by = session.get('username', 'admin')
        ok = upsert_scheduled_task(task_id=job_id, name=task['name'], task_type=task['task_type'],
            hour=hour, minute=minute, day=day,
            filter_user=filter_user, push_user=push_user, range_config=range_config,
            custom_sql=custom_sql, custom_sql_title=custom_sql_title, custom_sql_format=custom_sql_format,
            per_user_push=per_user_push, enabled=task['enabled'], updated_by=updated_by)
        if not ok:
            return jsonify({'success': False, 'message': '保存失败'}), 500
        _reschedule_job(job_id, task['task_type'], hour, minute, day)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"更新任务异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/scheduler/jobs/create', methods=['POST'])
@login_required
def api_scheduler_job_create():
    try:
        from db import upsert_scheduled_task
        data = request.get_json() or {}
        name = data.get('name', '').strip()
        time_str = data.get('time', '21:00')
        day = data.get('day')
        task_type = data.get('task_type', name)
        if not name:
            return jsonify({'success': False, 'message': '请输入任务名称'}), 400
        hour, minute = map(int, time_str.split(':'))
        if day:
            day = int(day)
        if task_type not in _task_funcs:
            return jsonify({'success': False, 'message': f'不支持的任务类型: {task_type}'}), 400
        filter_user = data.get('filter_user') or ''
        push_user = data.get('push_user') or ''
        range_config = data.get('range_config') or ''
        custom_sql = data.get('custom_sql') or ''
        custom_sql_title = data.get('custom_sql_title') or ''
        custom_sql_format = data.get('custom_sql_format') or ''
        per_user_push = data.get('per_user_push', False)

        # 所有任务都生成唯一 task_id，支持同一类型创建多个任务
        import uuid
        actual_task_id = f"{task_type}_{uuid.uuid4().hex[:12]}"

        updated_by = session.get('username', 'admin')
        ok = upsert_scheduled_task(task_id=actual_task_id, name=name, task_type=task_type,
            hour=hour, minute=minute, day=day,
            filter_user=filter_user, push_user=push_user, range_config=range_config,
            custom_sql=custom_sql, custom_sql_title=custom_sql_title, custom_sql_format=custom_sql_format,
            per_user_push=per_user_push, enabled=True, updated_by=updated_by)
        if not ok:
            return jsonify({'success': False, 'message': '保存失败'}), 500
        _reschedule_job(actual_task_id, task_type, hour, minute, day)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"创建任务异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/scheduler/jobs/<job_id>/delete', methods=['POST'])
@login_required
def api_scheduler_job_delete(job_id):
    try:
        from db import delete_scheduled_task, get_scheduled_task_active
        task = get_scheduled_task_active(job_id)
        if not task:
            return jsonify({'success': False, 'message': '任务不存在'}), 404
        # 从调度器移除
        try:
            _scheduler.scheduler.remove_job(job_id)
        except Exception:
            pass  # 可能不在运行中
        delete_scheduled_task(job_id)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"删除任务异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/dict/<group>')
def api_dict(group):
    """获取字典配置组"""
    from db import get_dict_group
    data = get_dict_group(group)
    return jsonify({'success': True, 'data': data})


@bp.route('/api/scheduler/jobs/reset-defaults', methods=['POST'])
@login_required
def api_scheduler_job_reset_defaults():
    try:
        from db import upsert_scheduled_task
        from apscheduler.triggers.cron import CronTrigger
        from config import get_config
        cfg = get_config()
        tz = cfg.TIMEZONE
        defaults = [
            ('daily_summary', '前一天消费汇总推送', 'daily_summary', 21, 0, None),
            ('monthly_summary', '上个月消费汇总推送', 'monthly_summary', 10, 0, 1),
        ]
        for task_id, name, task_type, hour, minute, day in defaults:
            upsert_scheduled_task(task_id, name, task_type, hour, minute, day, filter_user='', push_user='', range_config='', enabled=True, updated_by='system')
            _reschedule_job(task_id, task_type, hour, minute, day)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"恢复默认任务异常: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
