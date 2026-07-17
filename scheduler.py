#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定时任务 - 推送每日/每月消费汇总"""
import logging
from datetime import datetime
from typing import Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import get_config
from services.summary import SummaryService
from wecom.client import WeComClient

logger = logging.getLogger(__name__)
push_error_logger = logging.getLogger('push_error')


class SummaryScheduler:
    """汇总推送定时任务"""

    def __init__(self):
        self.config = get_config()
        self.summary_service = SummaryService(source='wecom')
        self.wecom_client = WeComClient()
        self.scheduler = BackgroundScheduler(timezone=self.config.TIMEZONE)

    def start(self):
        """启动定时任务（从数据库读取配置）"""
        tz = self.config.TIMEZONE

        from db import get_scheduled_tasks
        from functools import partial
        tasks = get_scheduled_tasks()
        if not tasks:
            logger.warning("数据库中没有计划任务配置，请在后台管理页面添加")
        else:
            for task in tasks:
                if not task.get('enabled'):
                    continue
                task_id = task['task_id']
                task_type = task.get('task_type', '')
                hour = task['hour']
                minute = task['minute']
                day = task.get('day')
                if day:
                    trigger = CronTrigger(day=day, hour=hour, minute=minute, timezone=tz)
                    logger.info(f"计划任务 [{task_id}] 已设置: 每月 {day} 号 {hour:02d}:{minute:02d}")
                else:
                    trigger = CronTrigger(hour=hour, minute=minute, timezone=tz)
                    logger.info(f"计划任务 [{task_id}] 已设置: 每天 {hour:02d}:{minute:02d}")
                # 传入 task_id 而非 task_type，确保 custom_sql 等任务能正确查找
                self.scheduler.add_job(
                    partial(self._push_with_config, task_id),
                    trigger, id=task_id, name=task.get('name', task_id), replace_existing=True)

        self.scheduler.start()
        logger.info("汇总推送定时任务已启动")

    def stop(self):
        """停止定时任务"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("汇总推送定时任务已停止")

    def get_task_funcs(self) -> dict:
        """从数据库读取所有任务类型，返回 task_type → 执行函数的映射"""
        from functools import partial
        # 始终支持标准任务类型
        funcs = {
            'no_budget_summary': partial(self._push_with_config, 'no_budget_summary'),
            'with_budget_summary': partial(self._push_with_config, 'with_budget_summary'),
            'custom_sql': partial(self._push_with_config, 'custom_sql'),
        }
        try:
            from db import get_scheduled_tasks
            tasks = get_scheduled_tasks()
            seen = {'no_budget_summary', 'with_budget_summary', 'custom_sql'}
            for task in tasks:
                tt = task.get('task_type', '')
                if tt and tt not in seen:
                    seen.add(tt)
                    funcs[tt] = partial(self._push_with_config, tt)
        except Exception:
            pass
        # 兜底：数据库没有任务时暴露默认类型
        if not funcs:
            from functools import partial
            funcs = {
                'no_budget_summary': partial(self._push_with_config, 'no_budget_summary'),
                'with_budget_summary': partial(self._push_with_config, 'with_budget_summary'),
            }
        # 总是暴露 custom_sql 类型
        if 'custom_sql' not in funcs:
            from functools import partial as _p
            funcs['custom_sql'] = _p(self._push_with_config, 'custom_sql')
        # 旧类型兼容映射
        aliases = {
            'daily_summary': 'no_budget_summary',
            'monthly_summary': 'with_budget_summary',
        }
        for old, new in aliases.items():
            if old not in funcs and new in funcs:
                funcs[old] = funcs[new]
        return funcs

    def _push_with_config(self, task_id: str):
        """从 DB 读取任务配置后执行推送"""
        logger.info(f"开始推送 [{task_id}]...")
        try:
            from db import get_scheduled_task
            task = get_scheduled_task(task_id)
            if not task:
                logger.warning(f"任务 [{task_id}] 未找到，跳过")
                return
            if not task.get('enabled'):
                logger.info(f"任务 [{task_id}] 已暂停，跳过")
                return

            # 构建用户筛选条件
            user_filter = None
            filter_user = task.get('filter_user') or ''
            if filter_user:
                user_filter = filter_user
                logger.info(f"[{task_id}] 筛选用户: {filter_user}")

            # 解析时间范围配置
            range_config = None
            rc_raw = task.get('range_config') or ''
            if rc_raw:
                try:
                    import json
                    range_config = json.loads(rc_raw)
                    logger.info(f"[{task_id}] 时间范围配置: {range_config}")
                except Exception as e:
                    logger.warning(f"[{task_id}] 解析 range_config 失败: {e}")

            # 解析推送目标 - JSON 数组格式: ["user_code_1", "user_code_2"]
            push_raw = task.get('push_user') or ''
            user_codes = self._parse_user_codes(push_raw)
            per_user = bool(task.get('per_user_push', 0))
            # 旧类型映射
            task_type = task['task_type']
            if task_type in ('daily_summary', 'monthly_summary'):
                task_type = 'with_budget_summary' if task_type == 'monthly_summary' else 'no_budget_summary'
            with_budget = task_type == 'with_budget_summary'

            # 有预算汇总默认本月
            if with_budget and (range_config is None or range_config.get('type') not in ('this_month','last_month','this_quarter','last_quarter','this_year','last_year')):
                range_config = {'type': 'this_month'}
                logger.info(f"[{task_id}] 有预算汇总，默认使用本月范围")

            if not user_codes:
                logger.warning(f"[{task_id}] 未配置推送目标，跳过推送")
                return

            task_name = task.get('name', '')
            if per_user and task_type in ('no_budget_summary', 'with_budget_summary'):
                # 按用户分别推送
                self._push_per_user(task_id, user_codes, range_config, with_budget, task_name=task_name)
            else:
                # 常规推送：查推送账号，生成一份汇总群发
                if task_type in ('no_budget_summary', 'with_budget_summary'):
                    summary = self.summary_service.get_push_summary(
                        user_filter=user_filter, range_config=range_config, with_budget=with_budget,
                        task_name=task_name)
                elif task_type == 'custom_sql':
                    summary = self._exec_custom_sql(task)
                    if summary is None:
                        return
                else:
                    logger.warning(f"未知任务类型: {task['task_type']}")
                    return

                if summary['has_data']:
                    push_targets = self._resolve_push_targets(user_codes)
                    if not push_targets:
                        logger.warning(f"[{task_id}] 勾选用户均无可用推送账号，跳过推送")
                        return
                    view_url = ''
                    # 有预算汇总：生成查看链接和验证码
                    if with_budget:
                        import uuid as uuid_mod
                        import random
                        import json
                        summary_uuid = str(uuid_mod.uuid4())
                        verification = f"{random.randint(0,9999):04d}"
                        # 构建结构化图表数据
                        start_time, end_time, period_str = self.summary_service._resolve_range(range_config, 'daily')
                        chart_data = self._build_chart_data(start_time, end_time, user_filter)
                        amounts = self.summary_service._get_user_amounts(start_time, end_time, user_filter)
                        total_expense = float(amounts.get('total_expense_amount', 0))
                        total_count = int(amounts.get('expense_transaction_count', 0))
                        total_budget = sum(p['budget'] for p in chart_data)
                        from db import save_task_summary
                        save_task_summary(
                            uuid=summary_uuid, task_id=task_id, task_name=task_name,
                            task_type=task_type,
                            verification=verification,
                            period_name=period_str,
                            total_expense=total_expense, total_budget=total_budget,
                            total_count=total_count,
                            chart_data=json.dumps(chart_data, ensure_ascii=False),
                        )
                        base_url = self.config.BASE_URL or ''
                        oauth_path = 's/go' if self.config.WECOM_OAUTH_ENABLED else 's/t'
                        view_url = f"{base_url}/{oauth_path}/{summary_uuid}".replace('//', '/') if base_url else ''
                        # 只保留汇总总计行（以 💰📊📝 开头），去掉科目明细
                        desc = summary.get('description', '')
                        brief_lines = []
                        for line in desc.replace('<br>', '\n').split('\n'):
                            line = line.strip()
                            if line.startswith(('💰', '📊', '📝')):
                                brief_lines.append(line)
                        brief = '<br>'.join(brief_lines)
                        if view_url:
                            brief += f'<br>📊 点击查看完整图表（验证码：{verification}）'
                        summary['description'] = brief
                    by_source = {}
                    for t in push_targets:
                        src = t.get('source', 'wecom')
                        by_source.setdefault(src, []).append(t['source_user'])
                    for source, users in by_source.items():
                        to_user = '|'.join(users)
                        self._send_with_source(source, summary, to_user, task_id, view_url=view_url)
                else:
                    logger.info(f"[{task_id}] 无消费记录，跳过推送")
        except Exception as e:
            logger.error(f"[{task_id}] 推送异常: {e}", exc_info=True)

    @staticmethod
    def _parse_user_codes(push_raw: str) -> list:
        """解析 push_user JSON 数组为用户编码列表
        格式: ["user_code_1", "user_code_2"]
        """
        if not push_raw:
            return []
        try:
            import json
            codes = json.loads(push_raw)
            if isinstance(codes, list) and codes:
                return codes
            return []
        except (json.JSONDecodeError, TypeError):
            return []

    @staticmethod
    def _resolve_push_targets(user_codes: list) -> list:
        """根据用户编码查询已启用推送的绑定平台账号"""
        if not user_codes:
            return []
        from db import get_push_targets_by_usercodes
        return get_push_targets_by_usercodes(user_codes)

    @staticmethod
    def _exec_custom_sql(task: dict) -> Optional[dict]:
        """执行自定义 SQL 查询，返回汇总结果
        支持变量 {filter_user} 替换为筛选用户编码
        配置字段:
          custom_sql:       SQL 查询语句
          custom_sql_title: 推送标题模板，支持 {column_name} 占位符（取第一行数据填充）
          custom_sql_format: 每行格式模板，支持 {column_name} 占位符
        """
        custom_sql = (task.get('custom_sql') or '').strip()
        if not custom_sql:
            logger.warning(f"[{task['task_id']}] 自定义 SQL 为空，跳过")
            return None

        title_tpl = (task.get('custom_sql_title') or '').strip()
        row_tpl = (task.get('custom_sql_format') or '').strip()

        # 变量替换
        filter_user = task.get('filter_user') or ''
        sql = custom_sql.replace('{filter_user}', filter_user)

        try:
            from db import get_connection
            conn = get_connection()
            try:
                cur = conn.execute(sql)
                rows = [dict(r) for r in cur.fetchall()]
                if not rows:
                    logger.info(f"[{task['task_id']}] 自定义 SQL 未返回数据，跳过推送")
                    return {'has_data': False, 'title': '', 'description': ''}

                first = rows[0]

                # 生成标题：优先用任务名称（configurable-title），其次模板
                task_name = task.get('name', '')
                if task_name:
                    title = task_name
                elif title_tpl:
                    title = SummaryScheduler._format_template(title_tpl, first)
                else:
                    title = first.get('title') or first.get('category_name') or '📊 自定义查询结果'
                    title = str(title)

                # 生成描述
                lines = []
                if not row_tpl:
                    # 无格式模板：默认取所有列拼接
                    for r in rows:
                        vals = [str(v) for v in r.values() if v is not None]
                        lines.append(' | '.join(vals))
                else:
                    for r in rows:
                        line = SummaryScheduler._format_template(row_tpl, r)
                        lines.append(line)
                desc = '\n'.join(lines)

                logger.info(f"[{task['task_id']}] 自定义 SQL 返回 {len(rows)} 行数据")
                return {
                    'has_data': True,
                    'title': str(title),
                    'description': desc.replace('\n', '<br>'),
                }
            except Exception as e:
                logger.error(f"[{task['task_id']}] 自定义 SQL 执行失败: {e}")
                push_error_logger.error(
                    f"[{task['task_id']}] 自定义 SQL 执行失败: {e}\nSQL: {sql}")
                return None
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[{task['task_id']}] 自定义 SQL 数据库连接失败: {e}")
            return None

    def _push_per_user(self, task_id: str, user_codes: list,
                       range_config: dict, with_budget: bool, task_name: str = None):
        """按用户分别推送：每人只看到自己的数据"""
        from db import get_push_targets_by_usercodes, get_users
        users = get_users()
        user_map = {u['code']: u for u in users}  # code → user dict

        for user_code in user_codes:
            user = user_map.get(user_code)
            if not user:
                logger.info(f"[{task_id}] 用户编码 {user_code} 不存在，跳过")
                continue
            user_name = user['name']
            user_id = user['id']
            try:
                # 查该用户的推送账号
                accounts = get_push_targets_by_usercodes([user_code])
                if not accounts:
                    logger.info(f"[{task_id}] 用户 {user_name} 无可用推送账号，跳过")
                    continue
                per_user_filter = user_code
                logger.info(f"[{task_id}] 用户 {user_name} 筛选条件: user_code={per_user_filter}, range={range_config}")
                summary = self.summary_service.get_push_summary(
                    user_filter=per_user_filter, range_config=range_config, with_budget=with_budget,
                    task_name=task_name)
                if summary['has_data']:
                    logger.info(f"[{task_id}] 用户 {user_name} 汇总结果: 总支出={summary.get('total_expense')}, 笔数={summary.get('transaction_count')}")
                else:
                    logger.info(f"[{task_id}] 用户 {user_name} 无消费记录，跳过")
                    continue
                # 按平台分组发送
                by_source = {}
                for acct in accounts:
                    src = acct['source']
                    by_source.setdefault(src, []).append(acct['source_user'])
                for src, users in by_source.items():
                    self._send_with_source(src, summary, '|'.join(users), task_id)
                logger.info(f"[{task_id}] 已向 {user_name} 推送个人数据")
            except Exception as e:
                logger.error(f"[{task_id}] 推送用户 {user_name} 异常: {e}")

    @staticmethod
    def _format_template(template: str, data: dict) -> str:
        """用 data 字典填充模板中的 {key} 占位符"""
        import re
        def replacer(m):
            key = m.group(1)
            val = data.get(key)
            return str(val) if val is not None else m.group(0)
        return re.sub(r'\{(\w+)\}', replacer, template)

    def _build_chart_data(self, start_time, end_time, user_filter=None) -> list:
        """构建图表结构化数据（科目层级 + 支出 + 预算）"""
        from db import get_budgets, SCOPE_FAMILY, get_transactions_statistics
        statistics = get_transactions_statistics(
            start_time.strftime('%Y-%m-%d %H:%M:%S'),
            end_time.strftime('%Y-%m-%d %H:%M:%S'),
            user_filter=user_filter)
        items = statistics.get('result', {}).get('items', [])

        categories = self.summary_service.client.get_categories()
        cat_info = {}
        parent_order = []

        def _walk(cats, parent_id='0'):
            for c in cats:
                cid = str(c.get('id'))
                cname = c.get('name', '')
                ctype = c.get('type')
                subs = c.get('subCategories', [])
                cat_info[cid] = {
                    'id': cid, 'name': cname, 'type': ctype,
                    'parent_id': parent_id,
                    'display_order': c.get('displayOrder') or 0,
                }
                if parent_id == '0' and ctype == 'expense':
                    parent_order.append(cid)
                if subs:
                    _walk(subs, cid)
        _walk(categories)

        # 按父科目汇总
        parent_data = {}
        child_data = {}
        for item in items:
            cat_id = str(item.get('categoryId', '0'))
            amount = abs(float(item.get('amount', 0))) / 100.0
            if amount <= 0:
                continue
            info = cat_info.get(cat_id, {})
            pid = info.get('parent_id', '0')
            if info.get('type') == 'income':
                continue
            if pid == '0':
                parent_data[cat_id] = parent_data.get(cat_id, 0) + amount
            else:
                parent_data[pid] = parent_data.get(pid, 0) + amount
                sub = child_data.setdefault(pid, {})
                sub[cat_id] = sub.get(cat_id, 0) + amount

        # 获取预算
        ym = start_time.strftime('%Y-%m')
        blist = get_budgets(SCOPE_FAMILY, year_month=ym)
        budgets = {b['category_id']: b['monthly_limit'] / 100.0 for b in blist}
        parent_budgets = {}
        for cid, amt in budgets.items():
            info = cat_info.get(cid, {})
            pid = info.get('parent_id', '0')
            key = pid if pid != '0' else cid
            parent_budgets[key] = parent_budgets.get(key, 0) + amt

        # 按 display_order 排序，合并有预算的科目
        seen = set(parent_order)
        for pid in parent_budgets:
            if pid not in seen:
                parent_order.append(pid)
        parent_order.sort(key=lambda p: cat_info.get(p, {}).get('display_order', 0))

        # 将只有预算没有支出的子科目也加入 child_data
        for cid, amt in budgets.items():
            info = cat_info.get(cid, {})
            pid = info.get('parent_id', '0')
            if pid != '0' and cid not in child_data.get(pid, {}):
                child_data.setdefault(pid, {})[cid] = 0

        result = []
        for pid in parent_order:
            pname = cat_info.get(pid, {}).get('name', f'#{pid}')
            children = []
            for cid, cspent in sorted(child_data.get(pid, {}).items(),
                                        key=lambda x: x[1], reverse=True):
                cname = cat_info.get(cid, {}).get('name', f'#{cid}')
                children.append({
                    'id': cid, 'name': cname,
                    'spent': round(cspent, 2),
                    'budget': round(budgets.get(cid, 0), 2),
                    'parent_name': pname,
                })
            result.append({
                'id': pid, 'name': pname,
                'spent': round(parent_data.get(pid, 0), 2),
                'budget': round(parent_budgets.get(pid, 0), 2),
                'children': children,
            })
        return result

    def _send_with_source(self, source: str, summary: dict, to_user: str, task_id: str,
                          view_url: str = None):
        """根据平台类型发送消息"""
        if source == 'wecom':
            # 有查看链接时使用链接 URL，否则使用 BASE_URL
            if not view_url:
                base = self.config.BASE_URL or 'https://work.weixin.qq.com/'
                view_url = base
            push_url = view_url
            result = self.wecom_client.send_text_card(
                title=summary['title'],
                description=summary['description'],
                url=push_url,
                btntxt="",
                to_user=to_user,
            )
            if result.get('errcode') == 0:
                logger.info(f"[{task_id}] 推送成功 to_user={to_user or '@all'}")
            else:
                logger.error(f"[{task_id}] 推送失败: {result}")
        else:
            logger.warning(f"[{task_id}] 不支持的推送平台: {source}")
