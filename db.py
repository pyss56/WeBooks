#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLite数据库模块 - 用户配置持久化存储"""
import os
import sqlite3
import logging
from typing import Optional

logger = logging.getLogger(__name__)

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
DB_PATH = os.path.join(DB_DIR, 'data.db')

# ============ 数据库版本管理 ============
DB_VERSION = 4


def _get_schema_version(conn) -> int:
    """获取当前数据库的 schema 版本号。返回 0 表示尚未初始化。"""
    try:
        cursor = conn.execute("SELECT version FROM schema_version")
        row = cursor.fetchone()
        return row['version'] if row else 0
    except sqlite3.OperationalError:
        return 0


def _set_schema_version(conn, version: int):
    """记录数据库 schema 版本号。"""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))



def _create_all_tables(conn):
    """创建所有表（最终形态）"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_default_account (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            user_code           TEXT NOT NULL UNIQUE,
            account_id          TEXT NOT NULL,
            income_account_id   TEXT DEFAULT NULL,
            message_log_id      INTEGER DEFAULT NULL,
            source              TEXT DEFAULT NULL,
            source_user         TEXT DEFAULT NULL,
            created_by          TEXT DEFAULT NULL,
            created_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_by          TEXT DEFAULT NULL,
            updated_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            scope         TEXT NOT NULL DEFAULT 'personal',
            user_code     TEXT,
            category_id   TEXT NOT NULL,
            category_name TEXT NOT NULL,
            monthly_limit INTEGER NOT NULL,
            year_month    TEXT DEFAULT NULL,
            created_by    TEXT DEFAULT NULL,
            created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_by    TEXT DEFAULT NULL,
            updated_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE(scope, user_code, category_id, year_month)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_account (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id  TEXT NOT NULL,
            user_code   TEXT NOT NULL,
            user_name   TEXT NOT NULL,
            created_by  TEXT DEFAULT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_by  TEXT DEFAULT NULL,
            updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id      TEXT NOT NULL UNIQUE,
            name         TEXT NOT NULL,
            task_type    TEXT NOT NULL,
            hour         INTEGER NOT NULL DEFAULT 21,
            minute       INTEGER NOT NULL DEFAULT 0,
            day          INTEGER DEFAULT NULL,
            enabled      INTEGER NOT NULL DEFAULT 1,
            filter_user  TEXT DEFAULT NULL,
            push_user    TEXT DEFAULT NULL,
            range_config TEXT DEFAULT NULL,
            per_user_push INTEGER NOT NULL DEFAULT 0,
            custom_sql   TEXT DEFAULT NULL,
            custom_sql_title TEXT DEFAULT NULL,
            custom_sql_format TEXT DEFAULT NULL,
            created_by   TEXT DEFAULT NULL,
            created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_by   TEXT DEFAULT NULL,
            updated_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            deleted_at   TEXT DEFAULT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dict_header (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            code        TEXT NOT NULL UNIQUE,
            name        TEXT NOT NULL,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dict_detail (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            header_id   INTEGER NOT NULL,
            code        TEXT NOT NULL,
            value       TEXT NOT NULL,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dict_detail_header ON dict_detail(header_id)")
    # 初始化默认字典数据
    _init_dict_defaults(conn)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_summary (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid            TEXT NOT NULL UNIQUE,
            task_id         TEXT NOT NULL,
            task_name       TEXT NOT NULL,
            task_type       TEXT NOT NULL,
            verification    TEXT NOT NULL,
            period_name     TEXT NOT NULL,
            total_expense   REAL NOT NULL DEFAULT 0,
            total_budget    REAL NOT NULL DEFAULT 0,
            total_count     INTEGER NOT NULL DEFAULT 0,
            chart_data      TEXT NOT NULL,
            created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS message_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            msg_type    TEXT NOT NULL,
            input_json  TEXT DEFAULT NULL,
            output_json TEXT DEFAULT NULL,
            source_user TEXT DEFAULT NULL,
            source      TEXT DEFAULT NULL,
            result      TEXT DEFAULT NULL,
            created_by  TEXT DEFAULT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_by  TEXT DEFAULT NULL,
            updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS "transaction" (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_type           TEXT NOT NULL,
            category_name       TEXT DEFAULT NULL,
            category_id         INTEGER DEFAULT NULL,
            amount              INTEGER NOT NULL,
            comment             TEXT DEFAULT NULL,
            created_by          TEXT DEFAULT NULL,
            transaction_time    TEXT NOT NULL,
            reconciliation_flag TEXT NOT NULL DEFAULT '0',
            reconciliation_user TEXT DEFAULT NULL,
            reconciliation_time TEXT DEFAULT NULL,
            reconciliation_no   TEXT DEFAULT NULL,
            reconciliation_line_no INTEGER DEFAULT NULL,
            deleted_at          TEXT DEFAULT NULL,
            account_id          TEXT DEFAULT NULL,
            account_name        TEXT DEFAULT NULL,
            to_account_id       TEXT DEFAULT NULL,
            to_account_name     TEXT DEFAULT NULL,
            user_code           TEXT DEFAULT NULL,
            source              TEXT DEFAULT NULL,
            source_user         TEXT DEFAULT NULL,
            currency            TEXT DEFAULT 'CNY',
            raw_message         TEXT DEFAULT NULL,
            message_log_id      INTEGER DEFAULT NULL,
            uuid                TEXT DEFAULT NULL,
            verify_code         TEXT DEFAULT NULL,
            created_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_by          TEXT DEFAULT NULL,
            updated_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_transaction_uuid ON "transaction"(uuid)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reconciliation (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            reconciliation_no   TEXT NOT NULL UNIQUE,
            status              TEXT NOT NULL DEFAULT '草稿',
            income_amount       INTEGER NOT NULL DEFAULT 0,
            expense_amount      INTEGER NOT NULL DEFAULT 0,
            balance_amount      INTEGER NOT NULL DEFAULT 0,
            confirm_flag        TEXT NOT NULL DEFAULT '否',
            created_by          TEXT DEFAULT NULL,
            created_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_by          TEXT DEFAULT NULL,
            updated_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            type            INTEGER NOT NULL DEFAULT 2,
            parent_id       TEXT NOT NULL DEFAULT '0',
            icon            TEXT NOT NULL DEFAULT '1',
            color           TEXT NOT NULL DEFAULT 'ff6b22',
            comment         TEXT DEFAULT NULL,
            hidden          INTEGER NOT NULL DEFAULT 0,
            display_order   INTEGER NOT NULL DEFAULT 0,
            created_by      TEXT DEFAULT NULL,
            created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_by      TEXT DEFAULT NULL,
            updated_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            parent_id       TEXT NOT NULL DEFAULT '0',
            category        INTEGER NOT NULL DEFAULT 5,
            currency        TEXT NOT NULL DEFAULT 'CNY',
            icon            TEXT NOT NULL DEFAULT '1',
            color           TEXT NOT NULL DEFAULT 'ff6b22',
            comment         TEXT DEFAULT NULL,
            hidden          INTEGER NOT NULL DEFAULT 0,
            balance         INTEGER NOT NULL DEFAULT 0,
            balance_time    INTEGER DEFAULT NULL,
            created_by      TEXT DEFAULT NULL,
            created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_by      TEXT DEFAULT NULL,
            updated_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS "user" (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            code            TEXT NOT NULL UNIQUE,
            password_hash   TEXT DEFAULT NULL,
            is_admin        INTEGER NOT NULL DEFAULT 0,
            status          INTEGER NOT NULL DEFAULT 1,
            deleted_at      TEXT DEFAULT NULL,
            created_by      TEXT DEFAULT NULL,
            created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_by      TEXT DEFAULT NULL,
            updated_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_sourceuser (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_code       TEXT NOT NULL,
            source_user     TEXT NOT NULL,
            source          TEXT DEFAULT 'wecom',
            push_enabled    INTEGER NOT NULL DEFAULT 0,
            created_by      TEXT DEFAULT NULL,
            created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_by      TEXT DEFAULT NULL,
            updated_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS input_alias (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            input_text      TEXT NOT NULL,
            target_type     TEXT NOT NULL,
            target_id       TEXT NOT NULL,
            target_name     TEXT DEFAULT NULL,
            deleted_at      TEXT DEFAULT NULL,
            created_by      TEXT DEFAULT NULL,
            created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_by      TEXT DEFAULT NULL,
            updated_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE(input_text, target_type)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS account_category (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            created_by  TEXT DEFAULT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_by  TEXT DEFAULT NULL,
            updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS menu (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id   INTEGER NOT NULL DEFAULT 0,
            type        TEXT NOT NULL DEFAULT 'page',
            label       TEXT NOT NULL,
            icon        TEXT NOT NULL DEFAULT '📄',
            url         TEXT DEFAULT NULL,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            is_active   INTEGER NOT NULL DEFAULT 1,
            default_expanded INTEGER NOT NULL DEFAULT 1,
            created_by  TEXT DEFAULT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_by  TEXT DEFAULT NULL,
            updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS role (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            code        TEXT NOT NULL UNIQUE,
            name        TEXT NOT NULL,
            description TEXT DEFAULT NULL,
            is_default  INTEGER NOT NULL DEFAULT 0,
            created_by  TEXT DEFAULT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_by  TEXT DEFAULT NULL,
            updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS role_menu (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            role_code   TEXT NOT NULL,
            menu_id     INTEGER NOT NULL,
            created_by  TEXT DEFAULT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE(role_code, menu_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_role (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_code   TEXT NOT NULL,
            role_code   TEXT NOT NULL,
            created_by  TEXT DEFAULT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE(user_code, role_code)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS role_button (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            role_code   TEXT NOT NULL,
            menu_id     INTEGER NOT NULL,
            button_code TEXT NOT NULL,
            created_by  TEXT DEFAULT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE(role_code, menu_id, button_code)
        )
    """)

def get_connection() -> sqlite3.Connection:
    """获取数据库连接"""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_dict_defaults(conn):
    """初始化字典头表和明细表"""
    groups = [
        ('range_type', '时间范围', [
            ('this_month', '本月', 1),
            ('last_month', '上个月', 2),
            ('this_quarter', '本季度', 3),
            ('last_quarter', '上季度', 4),
            ('this_year', '本年', 5),
            ('last_year', '去年', 6),
            ('yesterday', '昨天', 7),
            ('today', '今天到现在', 8),
            ('custom', '自定义', 9),
        ]),
        ('task_type', '任务类型', [
            ('no_budget_summary', '无预算汇总', 1),
            ('with_budget_summary', '有预算汇总', 2),
            ('custom_sql', '自定义SQL', 3),
        ]),
        ('tx_type', '交易类型', [
            ('income', '收入', 1),
            ('expense', '支出', 2),
            ('transfer', '转账', 3),
        ]),
        ('sys_config', '系统配置', [
            ('summary_expire_days', '7', 1),
            ('tx_expire_minutes', '5', 2),
        ]),
    ]
    for hcode, hname, items in groups:
        conn.execute(
            "INSERT OR IGNORE INTO dict_header (code, name) VALUES (?, ?)",
            (hcode, hname))
        row = conn.execute("SELECT id FROM dict_header WHERE code=?", (hcode,)).fetchone()
        if not row:
            continue
        hid = row['id']
        for code, value, order in items:
            conn.execute(
                "INSERT OR IGNORE INTO dict_detail (header_id, code, value, sort_order) VALUES (?, ?, ?, ?)",
                (hid, code, value, order))
    conn.commit()


def get_dict(group_code: str, code: str, default: str = '') -> str:
    """获取单个字典值"""
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT d.value FROM dict_detail d JOIN dict_header h ON h.id=d.header_id WHERE h.code=? AND d.code=?",
            (group_code, code))
        row = cur.fetchone()
        return row['value'] if row else default
    except Exception:
        return default
    finally:
        conn.close()


def get_dict_group(group_code: str) -> dict:
    """获取某组字典 {code: value}"""
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT d.code, d.value FROM dict_detail d JOIN dict_header h ON h.id=d.header_id WHERE h.code=? ORDER BY d.sort_order",
            (group_code,))
        return {row['code']: row['value'] for row in cur.fetchall()}
    except Exception:
        return {}
    finally:
        conn.close()


def init_db():
    """初始化数据库表结构"""
    conn = get_connection()
    try:
        current = _get_schema_version(conn)

        # 始终确保所有表结构存在（CREATE TABLE IF NOT EXISTS 幂等安全）
        _create_all_tables(conn)

        if current < DB_VERSION:
            # v4: 统一用户密码/管理员/菜单/角色系统
            logger.info("数据库迁移 v4: 统一用户/菜单/角色系统")
            for col, ddl in [
                ("password_hash", "ALTER TABLE \"user\" ADD COLUMN password_hash TEXT DEFAULT NULL"),
                ("is_admin", "ALTER TABLE \"user\" ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0"),
                ("default_expanded", "ALTER TABLE menu ADD COLUMN default_expanded INTEGER NOT NULL DEFAULT 1"),
                ("visible_to", "ALTER TABLE sidebar_menu ADD COLUMN visible_to TEXT DEFAULT 'all'"),
            ]:
                try:
                    conn.execute(ddl)
                except sqlite3.OperationalError:
                    pass
            # 清理过渡表（幂等）
            try:
                conn.execute("DROP TABLE IF EXISTS menu_button")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("DROP TABLE IF EXISTS role_menu_button")
            except sqlite3.OperationalError:
                pass
            # 从 sidebar_menu 迁移数据到 menu（如果 menu 为空）
            try:
                sm_count = conn.execute("SELECT COUNT(*) FROM sidebar_menu").fetchone()[0]
                m_count = conn.execute("SELECT COUNT(*) FROM menu").fetchone()[0]
                if sm_count > 0 and m_count == 0:
                    rows = conn.execute("SELECT * FROM sidebar_menu").fetchall()
                    for r in rows:
                        conn.execute(
                            "INSERT INTO menu (id, parent_id, type, label, icon, url, sort_order, is_active, default_expanded, created_by, created_at, updated_by, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
                            (r['id'], r.get('parent_id', 0), r.get('type', 'page'), r['label'], r['icon'],
                             r.get('url'), r['sort_order'], r['is_active'],
                             r['created_by'], r['created_at'], r['updated_by'], r['updated_at']))
                    logger.info(f"从 sidebar_menu 迁移 {sm_count} 条数据到 menu 表")
            except Exception as e:
                logger.warning(f"迁移 sidebar_menu→menu 失败: {e}")
            # 清理 sidebar_menu（如果 menu 已有数据则删除旧表）
            try:
                cur = conn.execute("SELECT COUNT(*) as cnt FROM menu")
                if cur.fetchone()['cnt'] > 0:
                    conn.execute("DROP TABLE IF EXISTS sidebar_menu")
            except sqlite3.OperationalError:
                pass
            # 移除 visible_to 列（如果存在）
            try:
                conn.execute("ALTER TABLE sidebar_menu DROP COLUMN visible_to")
            except sqlite3.OperationalError:
                pass
            # v4 续: 菜单数据更新
            logger.info("数据库迁移 v4: 菜单数据更新")
            # 默认折叠
            conn.execute("UPDATE menu SET default_expanded=0 WHERE label IN ('系统管理','记账管理','记账设置') AND type='dir'")
            # 更新账户设置图标
            conn.execute("UPDATE menu SET icon='💳' WHERE label='账户设置' AND icon='👤'")
            # 提取记账管理中的科目管理/预算管理/账户设置到独立记账设置目录
            jz = conn.execute("SELECT id FROM menu WHERE label='记账管理' AND type='dir'").fetchone()
            if jz:
                jz_id = jz[0]
                # 排序记账管理下的页面：页面记账、交易查询、对账管理
                for order, lab in [(1,'页面记账'),(2,'交易查询'),(3,'对账管理')]:
                    conn.execute("UPDATE menu SET sort_order=? WHERE label=? AND parent_id=?", (order, lab, jz_id))
            # 创建记账设置（一级目录）
            cur = conn.execute("SELECT id FROM menu WHERE label='记账设置' AND type='dir'")
            if not cur.fetchone():
                # 将科目管理、预算管理、账户设置设为一级，放到记账设置下面
                for lab in ('科目管理','预算管理','账户设置'):
                    conn.execute("UPDATE menu SET parent_id=0, sort_order=99 WHERE label=?", (lab,))
                conn.execute(
                    "INSERT INTO menu (parent_id, type, label, icon, url, sort_order, default_expanded, created_by) VALUES (0, 'dir', '记账设置', '⚙️', NULL, 3, 0, 'system')")
                jz_set_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                for idx, lab in enumerate([('科目管理','📂'),('预算管理','📊'),('账户设置','💳')], 1):
                    conn.execute(
                        "UPDATE menu SET parent_id=?, sort_order=? WHERE label=?", (jz_set_id, idx, lab[0]))
                # 调整记账管理排序
                conn.execute("UPDATE menu SET sort_order=4 WHERE label='记账管理' AND type='dir'")
            # 系统管理子项排序
            sys_mgr = conn.execute("SELECT id FROM menu WHERE label='系统管理' AND type='dir'").fetchone()
            if sys_mgr:
                sid = sys_mgr[0]
                for order, lab in [(1,'用户管理'),(2,'角色管理'),(3,'菜单管理'),(4,'计划任务'),(5,'消息日志')]:
                    conn.execute("UPDATE menu SET sort_order=? WHERE label=? AND parent_id=?", (order, lab, sid))
            conn.commit()

            # 初始化账户科目数据
            cursor = conn.execute("SELECT COUNT(*) as cnt FROM account_category")
            if cursor.fetchone()['cnt'] == 0:
                import json as _json, os as _os
                _cp = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'config', 'account_categories.json')
                try:
                    with open(_cp, 'r', encoding='utf-8') as _f:
                        _cd = _json.load(_f)
                    for _c in _cd:
                        conn.execute("INSERT INTO account_category (id, name) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET name=excluded.name",
                                     (_c['id'], _c['name']))
                    conn.commit()
                    logger.info(f"已初始化 {len(_cd)} 个账户科目")
                except Exception as e:
                    logger.warning(f"初始化账户科目失败: {e}")

            _set_schema_version(conn, DB_VERSION)
            conn.commit()
            logger.info(f"数据库初始化完成: {DB_PATH}, 版本: {DB_VERSION}")
        else:
            logger.info(f"数据库版本已是最新: {DB_PATH}, 版本: {DB_VERSION}")

        # 确保默认角色存在（无论是否迁移）
        init_default_roles()

    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        raise
    finally:
        conn.close()


def get_user_account(user_code: str, direction: str = 'expense') -> Optional[str]:
    """获取用户绑定的账户ID
    :param direction: 'expense' 或 'income'
    :param user_code: 项目用户编码（非微信ID）
    """
    conn = get_connection()
    try:
        col = 'income_account_id' if direction == 'income' else 'account_id'
        cursor = conn.execute(
            f"SELECT {col}, account_id FROM user_default_account WHERE user_code = ?",
            (user_code,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        # 收入账户优先用 income_account_id，若未设置则回退到 account_id
        if direction == 'income':
            return row['income_account_id'] or row['account_id'] or None
        return row['account_id'] or None
    except Exception as e:
        logger.error(f"查询用户账户失败: {e}")
        return None
    finally:
        conn.close()


# ============ 预算管理 ============
# 支持两种 scope：
#   'personal' - 个人预算（按 user_id 区分，带用户筛选）
#   'family'   - 家庭预算（全局统一，不含用户筛选）
# 预算按科目 ID 关联，不依赖科目名称。
# 即使科目被重命名或删除，预算记录仍在。


SCOPE_PERSONAL = 'personal'
SCOPE_FAMILY = 'family'


def get_budgets(scope: str, user_code: str = None, year_month: str = None) -> list:
    """获取预算列表。
    :param scope: 'personal' 或 'family'
    :param user_code: personal 时需要传入
    :param year_month: 'YYYY-MM' 格式，None 返回所有
    """
    conn = get_connection()
    try:
        sql = "SELECT * FROM budgets WHERE scope = ?"
        params = [scope]
        if scope == SCOPE_PERSONAL and user_code:
            sql += " AND user_code = ?"
            params.append(user_code)
        if year_month:
            sql += " AND year_month = ?"
            params.append(year_month)
        sql += " ORDER BY category_name"
        cursor = conn.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"查询预算列表失败: {e}")
        return []
    finally:
        conn.close()


def get_budget(scope: str, category_id: str, user_code: str = None,
               year_month: str = None) -> Optional[dict]:
    """获取指定科目预算。"""
    conn = get_connection()
    try:
        sql = "SELECT * FROM budgets WHERE scope = ? AND category_id = ?"
        params = [scope, category_id]
        if scope == SCOPE_PERSONAL and user_code:
            sql += " AND user_code = ?"
            params.append(user_code)
        if year_month:
            sql += " AND year_month = ?"
            params.append(year_month)
        cursor = conn.execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"查询预算失败: {e}")
        return None
    finally:
        conn.close()


def set_budget(scope: str, user_code: str, category_id: str,
               category_name: str, monthly_limit: float,
               year_month: str = None,
               updated_by: str = None) -> bool:
    """设置或更新预算。monthly_limit 为元，自动转为分存储。"""
    conn = get_connection()
    limit_cents = int(round(monthly_limit * 100))
    try:
        conn.execute("""
            INSERT INTO budgets (scope, user_code, category_id, category_name,
                                 monthly_limit, year_month, created_by, updated_by,
                                 updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
            ON CONFLICT(scope, user_code, category_id, year_month) DO UPDATE SET
                category_name = excluded.category_name,
                monthly_limit = excluded.monthly_limit,
                updated_by = excluded.updated_by,
                updated_at = datetime('now', 'localtime')
        """, (scope, user_code, category_id, category_name, limit_cents, year_month, updated_by, updated_by))
        conn.commit()
        ym = year_month or '全部'
        tag = '家庭' if scope == SCOPE_FAMILY else f'用户 {user_code}'
        logger.info(f"[{tag}][{ym}] 设置预算 [{category_name}](id={category_id}) = ¥{monthly_limit:.2f}")
        return True
    except Exception as e:
        logger.error(f"设置预算失败: {e}")
        return False
    finally:
        conn.close()


def refresh_budget_category_name(scope: str, category_id: str,
                                 new_name: str, user_code: str = None,
                                 year_month: str = None) -> bool:
    """当科目重命名时，更新快照名称"""
    conn = get_connection()
    try:
        sql = "UPDATE budgets SET category_name = ?, updated_at = datetime('now', 'localtime') WHERE scope = ? AND category_id = ?"
        params = [new_name, scope, category_id]
        if scope == SCOPE_PERSONAL and user_code:
            sql += " AND user_code = ?"
            params.append(user_code)
        if year_month:
            sql += " AND year_month = ?"
            params.append(year_month)
        conn.execute(sql, params)
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"刷新预算科目名称失败: {e}")
        return False
    finally:
        conn.close()


def delete_budget(scope: str, category_id: str, user_code: str = None,
                  year_month: str = None) -> bool:
    """删除预算。"""
    conn = get_connection()
    try:
        sql = "DELETE FROM budgets WHERE scope = ? AND category_id = ?"
        params = [scope, category_id]
        if scope == SCOPE_PERSONAL and user_code:
            sql += " AND user_code = ?"
            params.append(user_code)
        if year_month:
            sql += " AND year_month = ?"
            params.append(year_month)
        conn.execute(sql, params)
        conn.commit()
        ym = year_month or '全部'
        tag = '家庭' if scope == SCOPE_FAMILY else f'用户 {user_code}'
        logger.info(f"[{tag}][{ym}] 删除预算 category_id={category_id}")
        return True
    except Exception as e:
        logger.error(f"删除预算失败: {e}")
        return False
    finally:
        conn.close()


def set_user_account(user_code: str, account_id: str, direction: str = 'expense',
                      updated_by: str = None,
                      message_log_id: int = None,
                      source: str = None,
                      source_user: str = None) -> bool:
    """设置或更新用户绑定的账户ID
    :param direction: 'expense' | 'income' | 'both'
    :param user_code: 项目用户编码（非微信ID）
    """
    conn = get_connection()
    try:
        if direction == 'both':
            conn.execute("""
                INSERT INTO user_default_account (user_code, account_id, income_account_id, message_log_id, source, source_user, updated_by, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                ON CONFLICT(user_code) DO UPDATE SET
                    account_id = excluded.account_id,
                    income_account_id = excluded.income_account_id,
                    updated_by = excluded.updated_by,
                    updated_at = datetime('now', 'localtime')
            """, (user_code, account_id, account_id, message_log_id, source, source_user, updated_by))
        elif direction == 'income':
            conn.execute("""
                INSERT INTO user_default_account (user_code, account_id, income_account_id, message_log_id, source, source_user, updated_by, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                ON CONFLICT(user_code) DO UPDATE SET
                    income_account_id = excluded.income_account_id,
                    updated_by = excluded.updated_by,
                    updated_at = datetime('now', 'localtime')
            """, (user_code, account_id, account_id, message_log_id, source, source_user, updated_by))
        else:
            conn.execute("""
                INSERT INTO user_default_account (user_code, account_id, income_account_id, message_log_id, source, source_user, updated_by, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                ON CONFLICT(user_code) DO UPDATE SET
                    account_id = excluded.account_id,
                    updated_by = excluded.updated_by,
                    updated_at = datetime('now', 'localtime')
            """, (user_code, account_id, None, message_log_id, source, source_user, updated_by))
        conn.commit()
        logger.info(f"用户 {user_code} 绑定{direction}账户 {account_id} 成功")
        return True
    except Exception as e:
        logger.error(f"保存用户账户失败: {e}")
        return False
    finally:
        conn.close()


# ============ 计划任务管理 ============

def get_scheduled_tasks() -> list:
    """获取所有未删除的计划任务"""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM scheduled_tasks WHERE deleted_at IS NULL ORDER BY task_type, hour, minute"
        )
        return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"查询计划任务失败: {e}")
        return []
    finally:
        conn.close()


def get_scheduled_task(task_id: str) -> Optional[dict]:
    """获取单个计划任务（含已删除的）"""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM scheduled_tasks WHERE task_id = ?", (task_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"查询计划任务失败: {e}")
        return None
    finally:
        conn.close()


def get_scheduled_task_active(task_id: str) -> Optional[dict]:
    """获取单个未删除的计划任务"""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM scheduled_tasks WHERE task_id = ? AND deleted_at IS NULL", (task_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"查询计划任务失败: {e}")
        return None
    finally:
        conn.close()


def upsert_scheduled_task(task_id: str, name: str, task_type: str,
                           hour: int, minute: int, day: int = None,
                           filter_user: str = '', push_user: str = '',
                           range_config: str = '',
                           custom_sql: str = None,
                           custom_sql_title: str = None,
                           custom_sql_format: str = None,
                           per_user_push: bool = False,
                           enabled: bool = True,
                           updated_by: str = None) -> bool:
    """创建或更新计划任务"""
    conn = get_connection()
    try:
        # 检测新列是否存在（兼容旧表结构）
        has_new_cols = False
        try:
            conn.execute("SELECT custom_sql FROM scheduled_tasks LIMIT 1")
            has_new_cols = True
        except Exception:
            has_new_cols = False

        if has_new_cols:
            conn.execute("""
                INSERT INTO scheduled_tasks (task_id, name, task_type, hour, minute, day,
                                             filter_user, push_user, range_config,
                                             per_user_push,
                                             custom_sql, custom_sql_title, custom_sql_format, enabled,
                                             created_by, updated_by, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                ON CONFLICT(task_id) DO UPDATE SET
                    name=excluded.name, task_type=excluded.task_type,
                    hour=excluded.hour, minute=excluded.minute,
                    day=excluded.day,
                    filter_user=excluded.filter_user, push_user=excluded.push_user,
                    range_config=excluded.range_config,
                    per_user_push=excluded.per_user_push,
                    custom_sql=excluded.custom_sql, custom_sql_title=excluded.custom_sql_title,
                    custom_sql_format=excluded.custom_sql_format,
                    enabled=excluded.enabled,
                    updated_by=excluded.updated_by,
                    updated_at=excluded.updated_at
            """, (task_id, name, task_type, hour, minute, day,
                  filter_user or None, push_user or None, range_config or None,
                  1 if per_user_push else 0,
                  custom_sql or None, custom_sql_title or None, custom_sql_format or None,
                  1 if enabled else 0, updated_by, updated_by))
        else:
            conn.execute("""
                INSERT INTO scheduled_tasks (task_id, name, task_type, hour, minute, day,
                                             filter_user, push_user, range_config, enabled,
                                             created_by, updated_by, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                ON CONFLICT(task_id) DO UPDATE SET
                    name=excluded.name, task_type=excluded.task_type,
                    hour=excluded.hour, minute=excluded.minute,
                    day=excluded.day,
                    filter_user=excluded.filter_user, push_user=excluded.push_user,
                    range_config=excluded.range_config,
                    enabled=excluded.enabled,
                    updated_by=excluded.updated_by,
                    updated_at=excluded.updated_at
            """, (task_id, name, task_type, hour, minute, day,
                  filter_user or None, push_user or None, range_config or None,
                  1 if enabled else 0, updated_by, updated_by))
        conn.commit()
        logger.info(f"计划任务 [{task_id}] 已保存")
        return True
    except Exception as e:
        logger.error(f"保存计划任务失败: {e}")
        return False
    finally:
        conn.close()


def save_task_summary(uuid: str, task_id: str, task_name: str, task_type: str,
                       verification: str, period_name: str,
                       total_expense: float, total_budget: float,
                       total_count: int, chart_data: str) -> bool:
    """保存任务执行结果（结构化数据）"""
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO task_summary (uuid, task_id, task_name, task_type, verification,
                                      period_name, total_expense, total_budget, total_count, chart_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (uuid, task_id, task_name, task_type, verification,
              period_name, total_expense, total_budget, total_count, chart_data))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"保存任务执行记录失败: {e}")
        return False
    finally:
        conn.close()


def get_task_summary(uuid: str) -> Optional[dict]:
    """获取任务执行记录"""
    conn = get_connection()
    try:
        cur = conn.execute("SELECT * FROM task_summary WHERE uuid = ?", (uuid,))
        row = cur.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"查询任务执行记录失败: {e}")
        return None
    finally:
        conn.close()


def delete_scheduled_task(task_id: str) -> bool:
    """软删除计划任务"""
    conn = get_connection()
    try:
        conn.execute("UPDATE scheduled_tasks SET deleted_at = datetime('now', 'localtime') WHERE task_id = ?", (task_id,))
        conn.commit()
        logger.info(f"计划任务 [{task_id}] 已软删除")
        return True
    except Exception as e:
        logger.error(f"软删除计划任务失败: {e}")
        return False
    finally:
        conn.close()


def get_user_accounts(account_id: str = None) -> list:
    """获取账户绑定的用户列表"""
    conn = get_connection()
    try:
        if account_id:
            cursor = conn.execute(
                "SELECT * FROM user_account WHERE account_id = ? ORDER BY user_name",
                (account_id,)
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM user_account ORDER BY account_id, user_name"
            )
        return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"查询账户用户绑定失败: {e}")
        return []
    finally:
        conn.close()


def set_user_accounts(account_id: str, bindings: list,
                           updated_by: str = None) -> bool:
    """设置账户的用户绑定（先清空再批量插入）
    :param bindings: [{'user_code': str, 'user_name': str}, ...]
    """
    conn = get_connection()
    try:
        conn.execute("DELETE FROM user_account WHERE account_id = ?", (account_id,))
        for b in bindings:
            conn.execute(
                "INSERT INTO user_account (account_id, user_code, user_name, created_by, updated_by) VALUES (?, ?, ?, ?, ?)",
                (account_id, b['user_code'], b['user_name'], updated_by, updated_by)
            )
        conn.commit()
        logger.info(f"账户 {account_id} 绑定 {len(bindings)} 个用户")
        return True
    except Exception as e:
        logger.error(f"保存账户用户绑定失败: {e}")
        return False
    finally:
        conn.close()


# ============ 消息日志管理 ============


def add_message_log(msg_type: str, input_json: str = None,
                    output_json: str = None, source_user: str = None,
                    source: str = None, result: str = None,
                    created_by: str = None) -> int:
    """添加消息日志记录"""
    conn = get_connection()
    try:
        cursor = conn.execute("""
            INSERT INTO message_log (msg_type, input_json, output_json, source_user, source, result, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (msg_type, input_json, output_json, source_user, source, result, created_by))
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        logger.error(f"添加消息日志失败: {e}")
        return -1
    finally:
        conn.close()


def get_message_logs(limit: int = 100, offset: int = 0,
                     source_user: str = None, msg_type: str = None) -> list:
    """查询消息日志列表"""
    conn = get_connection()
    try:
        sql = "SELECT * FROM message_log WHERE 1=1"
        params = []
        if source_user:
            sql += " AND source_user = ?"
            params.append(source_user)
        if msg_type:
            sql += " AND msg_type = ?"
            params.append(msg_type)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = conn.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"查询消息日志失败: {e}")
        return []
    finally:
        conn.close()


def get_available_sourceusers():
    """获取可绑定的消息平台账号列表（从 message_log 去重，排除已绑定的）"""
    conn = get_connection()
    try:
        cur = conn.execute("""
            SELECT DISTINCT ml.source_user, ml.source FROM message_log ml
            WHERE ml.source_user IS NOT NULL AND ml.source_user != ''
              AND ml.source_user NOT IN (SELECT source_user FROM user_sourceuser)
              AND ml.msg_type = 'receive'
              AND ml.created_at >= datetime('now', '-3 days', 'localtime')
            ORDER BY ml.source, ml.source_user
        """)
        seen = set()
        result = []
        for r in cur.fetchall():
            key = (r['source'], r['source_user'])
            if key not in seen:
                seen.add(key)
                result.append({'source_user': r['source_user'], 'source': r['source'] or 'wecom'})
        return result
    except Exception as e:
        logger.error(f"获取可用平台账号失败: {e}")
        return []
    finally:
        conn.close()


# ============ 交易管理 ============


def add_transaction(bill_type: str, category_name: str, amount: float,
                    comment: str = None, created_by: str = None,
                    transaction_time: str = None,
                    account_id: str = None,
                    account_name: str = None,
                    to_account_id: str = None,
                    to_account_name: str = None,
                    user_code: str = None,
                    source: str = None,
                    source_user: str = None,
                    raw_message: str = None,
                    message_log_id: int = None,
                    currency: str = 'CNY',
                    category_id: str = None,
                    verify_code: str = None) -> tuple:
    """添加交易记录（amount 为元，自动转为分存储）"""
    from datetime import datetime
    if not transaction_time:
        transaction_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    amount_cents = int(round(amount * 100))
    import uuid
    tx_uuid = str(uuid.uuid4())
    if not verify_code:
        verify_code = generate_verify_code()
    conn = get_connection()
    try:
        cursor = conn.execute("""
            INSERT INTO "transaction" (bill_type, category_name, category_id, amount, comment, created_by, transaction_time, account_id, account_name, to_account_id, to_account_name, user_code, source, source_user, currency, raw_message, message_log_id, uuid, verify_code)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (bill_type, category_name, category_id, amount_cents, comment, created_by, transaction_time, account_id, account_name, to_account_id, to_account_name, user_code, source, source_user, currency, raw_message, message_log_id, tx_uuid, verify_code))
        conn.commit()
        return cursor.lastrowid, tx_uuid, verify_code
    except Exception as e:
        logger.error(f"添加交易失败: {e}")
        return -1, None
    finally:
        conn.close()


# ── 输入别名（用户输入的模糊名称 → 实际科目/账户ID） ─────

def add_input_alias(input_text: str, target_type: str, target_id: str,
                    target_name: str = None, created_by: str = None) -> bool:
    """保存输入别名映射"""
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO input_alias (input_text, target_type, target_id, target_name, created_by)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(input_text, target_type)
            DO UPDATE SET target_id=excluded.target_id, target_name=excluded.target_name,
                          updated_by=excluded.created_by,
                          updated_at=datetime('now', 'localtime')
        """, (input_text, target_type, target_id, target_name, created_by))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"添加别名失败: {e}")
        return False
    finally:
        conn.close()


def get_input_alias(input_text: str, target_type: str) -> Optional[dict]:
    """查询输入别名，返回 {id: target_id, name: target_name, type: target_type}"""
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT target_id, target_name, target_type FROM input_alias WHERE input_text=? AND target_type=?",
            (input_text, target_type)
        )
        row = cur.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"查询别名失败: {e}")
        return None
    finally:
        conn.close()


def resolve_alias(input_text: str, target_type: str) -> tuple:
    """通过别名解析文字对应的科目或账户，返回 (entity_id, entity_name)
    先查别名表获取 target_id，再按类型查找实际实体确保有效性。
    找不到时返回 (None, None)。
    """
    alias = get_input_alias(input_text, target_type)
    if not alias:
        return None, None
    target_id = alias['target_id']
    target_name = alias.get('target_name') or ''
    if target_type == 'category':
        from db import find_category_by_id
        cat = find_category_by_id(target_id)
        if cat:
            return cat['id'], cat.get('name', target_name)
    elif target_type == 'account':
        from db import find_account_by_id
        acc = find_account_by_id(target_id)
        if acc:
            return acc['id'], acc.get('name', target_name)
    return target_id, target_name


def list_input_aliases(target_type: str = None) -> list:
    """获取别名列表（排除已软删除的）"""
    conn = get_connection()
    try:
        sql = "SELECT * FROM input_alias WHERE deleted_at IS NULL"
        params = []
        if target_type:
            sql += " AND target_type = ?"
            params.append(target_type)
        sql += " ORDER BY target_type, input_text"
        cursor = conn.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"查询别名列表失败: {e}")
        return []
    finally:
        conn.close()


def delete_input_alias(alias_id: int) -> bool:
    """软删除别名"""
    conn = get_connection()
    try:
        from datetime import datetime
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "UPDATE input_alias SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
            (now, now, alias_id)
        )
        conn.commit()
        return conn.total_changes > 0
    except Exception as e:
        logger.error(f"删除别名失败: {e}")
        return False
    finally:
        conn.close()


def modify_input_alias(alias_id: int, new_input_text: str, new_target_type: str,
                       new_target_id: str, new_target_name: str = None,
                       updated_by: str = None) -> bool:
    """软删除旧别名并创建新别名"""
    if not delete_input_alias(alias_id):
        return False
    return add_input_alias(new_input_text, new_target_type, new_target_id,
                          target_name=new_target_name, created_by=updated_by)


def find_category_by_id(cat_id, cat_type=None):
    """通过 ID 查找科目"""
    conn = get_connection()
    try:
        sql = "SELECT * FROM categories WHERE id=?"
        params = [cat_id]
        if cat_type is not None:
            sql += " AND type=?"
            params.append(cat_type)
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"通过ID查找科目失败: {e}")
        return None
    finally:
        conn.close()


def find_account_by_id(acct_id):
    """通过 ID 查找账户（含子账户）"""
    from db import get_connection
    conn = get_connection()
    try:
        # 先查主账户
        cur = conn.execute("SELECT * FROM accounts WHERE id=?", (acct_id,))
        row = cur.fetchone()
        if row:
            return dict(row)
        # 按说子账户也在 accounts 表中通过 parent_id 关联
        # 再查一次确保
        return None
    except Exception as e:
        logger.error(f"通过ID查找账户失败: {e}")
        return None
    finally:
        conn.close()


def get_transaction_by_uuid(tx_uuid: str) -> Optional[dict]:
    """通过 UUID 查询交易（有效期从数据字典读取，默认5分钟）"""
    expire_min = get_dict('sys_config', 'tx_expire_minutes', '5')
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT * FROM \"transaction\" WHERE uuid=? AND deleted_at IS NULL"
            f" AND created_at >= datetime('now', 'localtime', '-{expire_min} minutes')",
            (tx_uuid,)
        )
        row = cur.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"通过 UUID 查询交易失败: {e}")
        return None
    finally:
        conn.close()


def get_transactions(limit: int = 500, offset: int = 0,
                     bill_type: str = None, created_by: str = None,
                     account_filter: str = None,
                     account_id: str = None,
                     reconciliation_flag: str = None,
                     transaction_time_from: str = None, transaction_time_to: str = None,
                     reconciliation_no: str = None,
                     include_deleted: bool = False,
                     exclude_transfer: bool = False) -> list:
    """查询交易列表"""
    conn = get_connection()
    try:
        sql = "SELECT * FROM \"transaction\" WHERE 1=1"
        params = []
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        if exclude_transfer:
            sql += " AND bill_type != 'transfer'"
        if bill_type:
            sql += " AND bill_type = ?"
            params.append(bill_type)
        if created_by:
            sql += " AND created_by = ?"
            params.append(created_by)
        if account_filter:
            sql += " AND category_name LIKE ?"
            params.append(f'%{account_filter}%')
        if account_id:
            sql += " AND (account_id = ? OR to_account_id = ?)"
            params.extend([account_id, account_id])
        if reconciliation_flag:
            sql += " AND reconciliation_flag = ?"
            params.append(reconciliation_flag)
        if transaction_time_from:
            sql += " AND transaction_time >= ?"
            params.append(transaction_time_from)
        if transaction_time_to:
            sql += " AND transaction_time <= ?"
            params.append(transaction_time_to)
        if reconciliation_no:
            sql += " AND reconciliation_no = ?"
            params.append(reconciliation_no)
        sql += " ORDER BY transaction_time DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = conn.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"查询交易失败: {e}")
        return []
    finally:
        conn.close()


def count_transactions(bill_type: str = None, created_by: str = None,
                       account_filter: str = None,
                       reconciliation_flag: str = None,
                       transaction_time_from: str = None, transaction_time_to: str = None,
                       reconciliation_no: str = None,
                       include_deleted: bool = False) -> int:
    """统计交易数量"""
    conn = get_connection()
    try:
        sql = "SELECT COUNT(*) as cnt FROM \"transaction\" WHERE 1=1"
        params = []
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        if bill_type:
            sql += " AND bill_type = ?"
            params.append(bill_type)
        if created_by:
            sql += " AND created_by = ?"
            params.append(created_by)
        if account_filter:
            sql += " AND category_name LIKE ?"
            params.append(f'%{account_filter}%')
        if reconciliation_flag:
            sql += " AND reconciliation_flag = ?"
            params.append(reconciliation_flag)
        if transaction_time_from:
            sql += " AND transaction_time >= ?"
            params.append(transaction_time_from)
        if transaction_time_to:
            sql += " AND transaction_time <= ?"
            params.append(transaction_time_to)
        if reconciliation_no:
            sql += " AND reconciliation_no = ?"
            params.append(reconciliation_no)
        cursor = conn.execute(sql, params)
        row = cursor.fetchone()
        return row['cnt'] if row else 0
    except Exception as e:
        logger.error(f"统计交易数量失败: {e}")
        return 0
    finally:
        conn.close()


def update_transaction_reconciliation(tx_ids: list, reconciliation_no: str,
                                       reconciliation_user: str = None,
                                       flag: str = '是',
                                       updated_by: str = None) -> bool:
    """更新交易的对账信息。flag='否' 时清除对账字段"""
    if not tx_ids:
        return False
    conn = get_connection()
    try:
        from datetime import datetime
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        placeholders = ','.join(['?'] * len(tx_ids))
        if flag == '0' or flag == '否':
            conn.execute(f"""
                UPDATE "transaction" SET
                    reconciliation_flag = '0',
                    reconciliation_user = NULL,
                    reconciliation_time = NULL,
                    reconciliation_no = NULL,
                    reconciliation_line_no = NULL,
                    updated_by = ?
                WHERE id IN ({placeholders})
            """, [updated_by] + tx_ids)
        else:
            conn.execute(f"""
                UPDATE "transaction" SET
                    reconciliation_flag = '1',
                    reconciliation_user = ?,
                    reconciliation_time = ?,
                    reconciliation_no = ?,
                    updated_by = ?
                WHERE id IN ({placeholders})
            """, [reconciliation_user, now, reconciliation_no, updated_by] + tx_ids)
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"更新交易对账信息失败: {e}")
        return False
    finally:
        conn.close()


def clear_transaction_reconciliation(reconciliation_no: str,
                                        updated_by: str = None) -> bool:
    """清除指定对账号的交易对账信息"""
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE "transaction" SET
                reconciliation_flag = '0',
                reconciliation_user = NULL,
                reconciliation_time = NULL,
                reconciliation_no = NULL,
                reconciliation_line_no = NULL,
                updated_by = ?
            WHERE reconciliation_no = ?
        """, (updated_by, reconciliation_no))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"清除交易对账信息失败: {e}")
        return False
    finally:
        conn.close()


# ============ 对账管理 ============


def create_reconciliation(reconciliation_no: str, created_by: str = None) -> int:
    """创建对账"""
    conn = get_connection()
    try:
        cursor = conn.execute("""
            INSERT INTO reconciliation (reconciliation_no, created_by, updated_by)
            VALUES (?, ?, ?)
        """, (reconciliation_no, created_by, created_by))
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        logger.error(f"创建对账失败: {e}")
        return -1
    finally:
        conn.close()


def get_reconciliations(limit: int = 100, offset: int = 0,
                        status: str = None,
                        reconciliation_no: str = None,
                        date_from: str = None,
                        date_to: str = None) -> list:
    """查询对账列表"""
    conn = get_connection()
    try:
        sql = "SELECT * FROM reconciliation WHERE 1=1"
        params = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if reconciliation_no:
            sql += " AND reconciliation_no LIKE ?"
            params.append(f'%{reconciliation_no}%')
        if date_from:
            sql += " AND created_at >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND created_at <= ?"
            params.append(date_to + ' 23:59:59')
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = conn.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"查询对账失败: {e}")
        return []
    finally:
        conn.close()


def count_reconciliations(status: str = None,
                          reconciliation_no: str = None,
                          date_from: str = None,
                          date_to: str = None) -> int:
    """统计对账记录总数"""
    conn = get_connection()
    try:
        sql = "SELECT COUNT(*) AS cnt FROM reconciliation WHERE 1=1"
        params = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if reconciliation_no:
            sql += " AND reconciliation_no LIKE ?"
            params.append(f'%{reconciliation_no}%')
        if date_from:
            sql += " AND created_at >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND created_at <= ?"
            params.append(date_to + ' 23:59:59')
        cursor = conn.execute(sql, params)
        row = cursor.fetchone()
        return row['cnt'] if row else 0
    except Exception as e:
        logger.error(f"统计对账失败: {e}")
        return 0
    finally:
        conn.close()


def get_reconciliation_by_no(reconciliation_no: str) -> dict:
    """根据对账号获取对账"""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM reconciliation WHERE reconciliation_no = ?",
            (reconciliation_no,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"查询对账失败: {e}")
        return None
    finally:
        conn.close()


def update_reconciliation(reconciliation_no: str, updated_by: str = None,
                           **kwargs) -> bool:
    """更新对账信息"""
    conn = get_connection()
    try:
        from datetime import datetime
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        sets = ["updated_at = ?", "updated_by = ?"]
        params = [now, updated_by]
        for key, val in kwargs.items():
            if val is not None:
                sets.append(f"{key} = ?")
                params.append(val)
        params.append(reconciliation_no)
        sql = f"UPDATE reconciliation SET {', '.join(sets)} WHERE reconciliation_no = ?"
        conn.execute(sql, params)
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"更新对账失败: {e}")
        return False
    finally:
        conn.close()


def recalc_reconciliation_amounts(reconciliation_no: str, updated_by: str = None) -> bool:
    """重新计算对账的收入、支出、结余金额"""
    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN bill_type='income' THEN amount ELSE 0 END), 0) as income_amount,
                COALESCE(SUM(CASE WHEN bill_type='expense' THEN amount ELSE 0 END), 0) as expense_amount
            FROM "transaction" WHERE reconciliation_no = ? AND deleted_at IS NULL AND bill_type != 'transfer'
        """, (reconciliation_no,))
        row = cursor.fetchone()
        if row:
            income_amount = row['income_amount']
            expense_amount = abs(row['expense_amount'])
            balance_amount = income_amount - expense_amount
            conn.execute("""
                UPDATE reconciliation SET
                    income_amount = ?,
                    expense_amount = ?,
                    balance_amount = ?,
                    updated_by = ?,
                    updated_at = datetime('now', 'localtime')
                WHERE reconciliation_no = ?
            """, (income_amount, expense_amount, balance_amount, updated_by, reconciliation_no))
            conn.commit()
            return True
        return False
    except Exception as e:
        logger.error(f"重新计算对账金额失败: {e}")
        return False
    finally:
        conn.close()


def get_next_reconciliation_line_no(reconciliation_no: str) -> int:
    """获取对账下一行号"""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT COALESCE(MAX(reconciliation_line_no), 0) + 1 as next_no FROM \"transaction\" WHERE reconciliation_no = ?",
            (reconciliation_no,)
        )
        row = cursor.fetchone()
        return row['next_no'] if row else 1
    except Exception as e:
        logger.error(f"获取对账行号失败: {e}")
        return 1
    finally:
        conn.close()


def get_distinct_users() -> list:
    """获取交易中不同的创建人列表"""
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT DISTINCT created_by FROM \"transaction\" WHERE created_by IS NOT NULL ORDER BY created_by")
        return [r['created_by'] for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"获取创建人列表失败: {e}")
        return []
    finally:
        conn.close()


def soft_delete_transaction(tx_id: int, updated_by: str = None) -> bool:
    """按 ID 软删除交易"""
    if not tx_id:
        return False
    conn = get_connection()
    try:
        from datetime import datetime
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "UPDATE \"transaction\" SET deleted_at = ?, updated_by = ? WHERE id = ? AND deleted_at IS NULL",
            (now, updated_by, tx_id)
        )
        conn.commit()
        affected = conn.total_changes
        if affected > 0:
            logger.info(f"交易软删除成功: id={tx_id}")
            return True
        logger.warning(f"未找到对应交易: id={tx_id}")
        return False
    except Exception as e:
        logger.error(f"交易软删除失败: {e}")
        return False
    finally:
        conn.close()


def modify_transaction(tx_id: int, updated_by: str = None, **kwargs) -> bool:
    """修改交易信息（amount 为元，自动转为分存储）"""
    conn = get_connection()
    try:
        allowed = {'bill_type', 'category_name', 'category_id', 'amount', 'comment', 'created_by', 'transaction_time', 'deleted_at', 'account_id', 'account_name', 'to_account_id', 'to_account_name', 'updated_by'}
        sets = []
        params = []
        for key, val in kwargs.items():
            if key in allowed and val is not None:
                if key == 'amount':
                    val = int(round(val * 100))
                sets.append(f"{key} = ?")
                params.append(val)
        if not sets:
            return False
        params.append(tx_id)
        sql = f"UPDATE \"transaction\" SET {', '.join(sets)} WHERE id = ?"
        conn.execute(sql, params)
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"修改交易失败: {e}")
        return False
    finally:
        conn.close()

# ============ 科目管理 ============

def add_category(name, cat_type='expense', parent_id='0', icon='1', color='ff6b22', comment='', created_by=None):
    """添加科目"""
    conn = get_connection()
    try:
        cur = conn.execute("SELECT COALESCE(MAX(display_order),0)+1 FROM categories WHERE parent_id=?", (parent_id,))
        order = cur.fetchone()[0]
        cur = conn.execute("INSERT INTO categories (name,type,parent_id,icon,color,comment,display_order,created_by) VALUES (?,?,?,?,?,?,?,?)",
                          (name, cat_type, parent_id, icon, color, comment, order, created_by))
        conn.commit()
        cid = cur.lastrowid
        return {'id': str(cid), 'name': name, 'type': cat_type, 'parentId': parent_id,
                'icon': icon, 'color': color, 'comment': comment, 'hidden': False}
    except Exception as e:
        logger.error(f"添加科目失败: {e}")
        return None
    finally:
        conn.close()


def get_categories(cat_type=None):
    """获取科目列表（树形）"""
    conn = get_connection()
    try:
        sql = "SELECT * FROM categories WHERE 1=1"
        params = []
        if cat_type is not None:
            sql += " AND type=?"
            params.append(cat_type)
        sql += " ORDER BY parent_id, display_order"
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        # 统一转为驼峰命名
        items = []
        for r in rows:
            items.append({
                'id': str(r['id']),
                'name': r['name'],
                'type': r['type'],
                'parentId': str(r['parent_id']),
                'icon': r['icon'],
                'color': r['color'],
                'comment': r['comment'],
                'hidden': bool(r['hidden']),
                'displayOrder': r['display_order'],
                'subCategories': [],
            })
        m = {}
        for item in items:
            m[item['id']] = item
        roots = []
        for item in items:
            pid = item['parentId']
            if pid == '0' or pid not in m:
                roots.append(item)
            else:
                p = m.get(pid)
                if p: p['subCategories'].append(item)
        return roots
    except Exception as e:
        logger.error(f"获取科目失败: {e}")
        return []
    finally:
        conn.close()


def find_category_by_name(name, cat_type='expense'):
    """按名称查找科目（仅子科目，排除顶级科目）"""
    conn = get_connection()
    try:
        cur = conn.execute("SELECT * FROM categories WHERE name=? AND type=? AND parent_id != '0' LIMIT 1", (name, cat_type))
        r = cur.fetchone()
        if r:
            d = dict(r)
            return {
                'id': str(d['id']),
                'name': d['name'],
                'type': d['type'],
                'parentId': str(d['parent_id']),
                'icon': d['icon'],
                'color': d['color'],
                'comment': d['comment'],
                'hidden': bool(d['hidden']),
            }
        return None
    except Exception as e:
        logger.error(f"查找科目失败: {e}")
        return None
    finally:
        conn.close()


def modify_category(category_id, updated_by=None, **kwargs):
    """修改科目"""
    conn = get_connection()
    try:
        allowed = {'name', 'icon', 'color', 'comment', 'hidden', 'parent_id'}
        from datetime import datetime
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        sets = ["updated_at=?", "updated_by=?",]
        params = [now, updated_by]
        for k, v in kwargs.items():
            if k in allowed and v is not None:
                sets.append(f"{k}=?")
                params.append(v)
        params.append(category_id)
        conn.execute(f"UPDATE categories SET {', '.join(sets)} WHERE id=?", params)
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"修改科目失败: {e}")
        return False
    finally:
        conn.close()


def delete_category(category_id):
    """删除科目（检查是否被账单使用）"""
    conn = get_connection()
    try:
        cur = conn.execute("SELECT COUNT(*) FROM \"transaction\" WHERE category_name IN (SELECT name FROM categories WHERE id=?) AND deleted_at IS NULL", (category_id,))
        if cur.fetchone()[0] > 0: return False
        conn.execute("DELETE FROM categories WHERE id=?", (category_id,))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"删除科目失败: {e}")
        return False
    finally:
        conn.close()


def reorder_categories(order_pairs, updated_by=None):
    """批量调整排序"""
    conn = get_connection()
    try:
        for cid, order in order_pairs:
            conn.execute("UPDATE categories SET display_order=?, updated_by=?, updated_at=datetime('now','localtime') WHERE id=?", (order, updated_by, cid))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"排序科目失败: {e}")
        return False
    finally:
        conn.close()


# ============ 账户管理 ============

def add_account(name, category=5, icon='1', color='ff6b22',
                currency='CNY', comment='', parent_id='0', created_by=None):
    """添加账户"""
    conn = get_connection()
    try:
        cur = conn.execute("INSERT INTO accounts (name,category,icon,color,currency,comment,parent_id,created_by) VALUES (?,?,?,?,?,?,?,?)",
                          (name, category, icon, color, currency, comment, parent_id, created_by))
        conn.commit()
        return {'id': str(cur.lastrowid), 'name': name}
    except Exception as e:
        logger.error(f"添加账户失败: {e}")
        return None
    finally:
        conn.close()


def get_accounts():
    """获取账户列表（树形）"""
    conn = get_connection()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM accounts ORDER BY parent_id, id").fetchall()]
        m = {}
        for r in rows:
            r['subAccounts'] = []
            m[str(r['id'])] = r
        roots = []
        for r in rows:
            pid = r['parent_id']
            if pid == '0' or pid not in m:
                roots.append(r)
            else:
                p = m.get(pid)
                if p: p['subAccounts'].append(r)
        return roots
    except Exception as e:
        logger.error(f"获取账户失败: {e}")
        return []
    finally:
        conn.close()


def get_excluded_account_ids(user_code: str) -> set:
    """获取指定项目用户无权查看的账户 ID 集合
    如果一个账户有用户绑定(user_account)，但指定用户不在绑定列表中，则排除该账户。
    没有绑定的账户（公开账户）不排除。
    """
    excluded = set()
    if not user_code:
        return excluded
    try:
        all_bindings = get_user_accounts()
    except Exception as e:
        logger.error(f"查询账户绑定异常: {e}")
        return excluded
    bind_map = {}
    for b in all_bindings:
        aid = b['account_id']
        if aid not in bind_map:
            bind_map[aid] = []
        bind_map[aid].append(b['user_code'])
    for aid, users in bind_map.items():
        if user_code not in users:
            excluded.add(aid)
    return excluded


def get_user_accessible_accounts(user_code: str = None) -> list:
    """获取指定项目用户可用的账户列表（树形），排除其他用户私有的账户"""
    accounts = get_accounts()
    if not user_code:
        return accounts
    excluded = get_excluded_account_ids(user_code)
    result = []
    for acc in accounts:
        acc_id = str(acc.get('id', ''))
        if acc_id in excluded:
            continue
        sub = acc.get('subAccounts', [])
        sub_ids = [str(s.get('id', '')) for s in sub]
        if sub and all(sid in excluded for sid in sub_ids):
            continue
        if sub:
            allowed_subs = [s for s in sub if str(s.get('id', '')) not in excluded]
            if allowed_subs:
                acc = dict(acc)
                acc['subAccounts'] = allowed_subs
                result.append(acc)
        else:
            result.append(acc)
    return result


def get_flat_accounts(user_code: str = None) -> list:
    """获取指定用户可用的扁平账户列表（叶子节点），有子账户的父级不参与选择"""
    tree = get_user_accessible_accounts(user_code)
    flat = []
    for acc in tree:
        sub = acc.get('subAccounts', [])
        if sub:
            for s in sub:
                s['_display_name'] = f"{s.get('name', '')} ({acc.get('name', '')})"
                flat.append(s)
        else:
            flat.append(acc)
    return flat


def modify_account(account_id, updated_by=None, **kwargs):
    """修改账户"""
    conn = get_connection()
    try:
        allowed = {'name', 'icon', 'color', 'comment', 'hidden', 'category'}
        from datetime import datetime
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        sets = ["updated_at=?", "updated_by=?",]
        params = [now, updated_by]
        for k, v in kwargs.items():
            if k in allowed and v is not None:
                sets.append(f"{k}=?")
                params.append(v)
        params.append(account_id)
        conn.execute(f"UPDATE accounts SET {', '.join(sets)} WHERE id=?", params)
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"修改账户失败: {e}")
        return False
    finally:
        conn.close()


def delete_account(account_id):
    """删除账户"""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"删除账户失败: {e}")
        return False
    finally:
        conn.close()


# ============ 用户管理 ============

def add_user(name, code=None, created_by=None, is_admin=0):
    """添加用户"""
    conn = get_connection()
    try:
        if code:
            conn.execute("INSERT OR IGNORE INTO \"user\" (name, code, created_by, is_admin) VALUES (?, ?, ?, ?)",
                         (name, code, created_by, is_admin))
        else:
            conn.execute("INSERT OR IGNORE INTO \"user\" (name, code, created_by, is_admin) VALUES (?, ?, ?, ?)",
                         (name, name, created_by, is_admin))
        conn.commit()
        cur = conn.execute("SELECT * FROM \"user\" WHERE name=?", (name,))
        r = cur.fetchone()
        return dict(r) if r else None
    except Exception as e:
        logger.error(f"添加用户失败: {e}")
        return None
    finally:
        conn.close()


def get_users(include_deleted=False, status=None):
    """获取用户列表
    :param status: None=全部, 0=停用, 1=启用
    """
    conn = get_connection()
    try:
        sql = "SELECT * FROM \"user\""
        params = []
        conds = []
        if not include_deleted:
            conds.append("deleted_at IS NULL")
        if status is not None:
            conds.append("status=?")
            params.append(status)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY name"
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except Exception as e:
        logger.error(f"获取用户失败: {e}")
        return []
    finally:
        conn.close()


def find_or_create_user(name, created_by=None):
    """查找或创建用户，返回ID"""
    conn = get_connection()
    try:
        # 同时按 name 和 code 查找，避免 name≠code 时查找不到
        cur = conn.execute("SELECT id FROM \"user\" WHERE name=? OR code=?", (name, name))
        r = cur.fetchone()
        if r: return str(r['id'])
        # 使用 INSERT OR IGNORE 防止并发竞争
        conn.execute("INSERT OR IGNORE INTO \"user\" (name, code, created_by) VALUES (?, ?, ?)", (name, name, created_by))
        conn.commit()
        cur = conn.execute("SELECT id FROM \"user\" WHERE name=? OR code=?", (name, name))
        r = cur.fetchone()
        return str(r['id']) if r else None
    except Exception as e:
        logger.error(f"查找/创建用户失败: {e}")
        return None
    finally:
        conn.close()


def get_user_by_sourceuser(source_user, source):
    """根据第三方账号查找绑定的用户信息"""
    conn = get_connection()
    try:
        cur = conn.execute("""
            SELECT u.* FROM "user" u
            JOIN user_sourceuser us ON us.user_code = u.code
            WHERE us.source_user = ? AND us.source = ?
            LIMIT 1
        """, (source_user, source))
        r = cur.fetchone()
        return dict(r) if r else None
    except Exception as e:
        logger.error(f"查询用户绑定失败: {e}")
        return None
    finally:
        conn.close()


def get_user_code_by_sourceuser(source_user, source):
    """第三方账号 → 项目用户编码，未绑定时返回 None"""
    bound = get_user_by_sourceuser(source_user, source=source)
    return bound['code'] if bound else None


# require_user_bound 的缓存（模块级，变更时失效）
_user_bound_cache: dict = {}


def require_user_bound(source_user: str, source: str = 'wecom') -> tuple:
    """检查第三方账号是否已绑定项目用户，返回 (user_code, error_message)
    带缓存，调用 add_user_sourceuser/delete_user_sourceuser 时自动失效。
    """
    cache_key = (source_user, source)
    if cache_key in _user_bound_cache:
        return _user_bound_cache[cache_key]
    user_code = get_user_code_by_sourceuser(source_user, source=source)
    if not user_code:
        result = (None, f'⚠️ 未绑定账户（微信账号: {source_user}），请先联系管理员绑定微信账号')
    else:
        result = (user_code, None)
    _user_bound_cache[cache_key] = result
    return result


def clear_user_bound_cache(source_user: str = None, source: str = None):
    """清除绑定缓存，source_user=None 时清空全部"""
    if source_user and source:
        _user_bound_cache.pop((source_user, source), None)
    elif source_user:
        keys = [k for k in _user_bound_cache if k[0] == source_user]
        for k in keys:
            _user_bound_cache.pop(k, None)
    else:
        _user_bound_cache.clear()


# 账户/缓存版本号，变更时递增
_account_cache_version = 0


def invalidate_account_cache():
    """账户或绑定变更时调用，使缓存版本号递增"""
    global _account_cache_version
    _account_cache_version += 1


def add_user_sourceuser(user_code, source_user, source, created_by=None, push_enabled=False):
    """绑定用户和平台账号（一个用户可绑定多个账号，一个账号只能绑定一个用户）
    :param push_enabled: 是否将该账号作为定时推送目标
    """
    conn = get_connection()
    try:
        # 先检查该微信是否已被其他用户绑定
        cur = conn.execute("SELECT user_code FROM user_sourceuser WHERE source_user=? AND source=?", (source_user, source))
        existing = cur.fetchone()
        if existing:
            return {'success': False, 'message': '该平台账号已被其他用户绑定'}
        conn.execute("INSERT INTO user_sourceuser (user_code, source_user, source, push_enabled, created_by) VALUES (?, ?, ?, ?, ?)",
                     (user_code, source_user, source, 1 if push_enabled else 0, created_by))
        conn.commit()
        clear_user_bound_cache(source_user, source)
        return {'success': True, 'message': '绑定成功'}
    except Exception as e:
        logger.error(f"绑定用户失败: {e}")
        return {'success': False, 'message': f'绑定失败: {e}'}
    finally:
        conn.close()


def get_user_by_code(code):
    """按 code 查找用户"""
    conn = get_connection()
    try:
        cur = conn.execute("SELECT * FROM \"user\" WHERE code=?", (code,))
        r = cur.fetchone()
        return dict(r) if r else None
    except Exception as e:
        logger.error(f"查询用户失败: {e}")
        return None
    finally:
        conn.close()


def get_user_sourceusers(user_code):
    """获取用户绑定的所有平台账号"""
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM user_sourceuser WHERE user_code=?", (user_code,)).fetchall()]
    except Exception as e:
        logger.error(f"查询用户绑定失败: {e}")
        return []
    finally:
        conn.close()


def update_user_sourceuser_push(user_code, source_user, source, push_enabled):
    """更新指定绑定记录的推送开关"""
    conn = get_connection()
    try:
        conn.execute("UPDATE user_sourceuser SET push_enabled=? WHERE user_code=? AND source_user=? AND source=?",
                     (1 if push_enabled else 0, user_code, source_user, source))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"更新推送开关失败: {e}")
        return False
    finally:
        conn.close()


def get_push_targets_by_usercodes(user_codes: list) -> list:
    """根据项目用户编码列表，查询所有已启用推送的绑定平台账号
    返回: [{"source": "wecom", "source_user": "zhangsan", "user_code": "zs", "user_name": "张三"}, ...]
    """
    if not user_codes:
        return []
    conn = get_connection()
    try:
        placeholders = ','.join('?' for _ in user_codes)
        rows = conn.execute(f"""
            SELECT us.source, us.source_user, us.user_code, u.name AS user_name
            FROM user_sourceuser us
            JOIN "user" u ON u.code = us.user_code
            WHERE us.user_code IN ({placeholders})
              AND us.push_enabled = 1
        """, user_codes).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"查询推送目标失败: {e}")
        return []
    finally:
        conn.close()


def get_all_user_sourceusers():
    """获取所有绑定关系"""
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM user_sourceuser").fetchall()]
    except Exception as e:
        logger.error(f"查询所有绑定失败: {e}")
        return []
    finally:
        conn.close()


def delete_user_sourceuser(source_user, source):
    """解绑企业微信账号"""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM user_sourceuser WHERE source_user=? AND source=?", (source_user, source))
        conn.commit()
        clear_user_bound_cache(source_user, source)
        return True
    except Exception as e:
        logger.error(f"解绑失败: {e}")
        return False
    finally:
        conn.close()


def update_user(user_id, name=None, status=None, is_admin=None, updated_by=None):
    """更新用户信息（status=0 停用, status=1 启用）"""
    conn = get_connection()
    try:
        fields = []
        params = []
        if name is not None:
            fields.append("name=?")
            params.append(name)
        if status is not None:
            fields.append("status=?")
            params.append(status)
        if is_admin is not None:
            fields.append("is_admin=?")
            params.append(1 if is_admin else 0)
        if not fields:
            return True
        fields.append("updated_at=datetime('now','localtime')")
        if updated_by:
            fields.append("updated_by=?")
            params.append(updated_by)
        params.append(user_id)
        conn.execute(f"UPDATE \"user\" SET {', '.join(fields)} WHERE id=?", params)
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"更新用户失败: {e}")
        return False
    finally:
        conn.close()


def soft_delete_user(user_id, updated_by=None):
    """软删除用户（设置 hidden=1）"""
    return update_user(user_id, status=0, updated_by=updated_by)


def delete_user(user_id, updated_by=None):
    """删除用户（软删除 - 设置 deleted_at），仅当用户没有交易记录时可删除"""
    conn = get_connection()
    try:
        # 获取用户 code
        cur = conn.execute("SELECT code FROM \"user\" WHERE id=? AND deleted_at IS NULL", (user_id,))
        r = cur.fetchone()
        if not r:
            return {'success': False, 'message': '用户不存在或已删除'}
        user_code = r['code']

        # 检查是否有交易记录
        cur = conn.execute(
            "SELECT COUNT(*) as cnt FROM \"transaction\" WHERE user_code=? AND deleted_at IS NULL",
            (user_code,)
        )
        cnt = cur.fetchone()['cnt']
        if cnt > 0:
            return {'success': False, 'message': f'该用户有 {cnt} 条交易记录，无法删除'}

        # 执行软删除
        conn.execute(
            "UPDATE \"user\" SET deleted_at=datetime('now','localtime'), updated_by=?, updated_at=datetime('now','localtime') WHERE id=?",
            (updated_by, user_id)
        )
        conn.commit()
        return {'success': True, 'message': '已删除'}
    except Exception as e:
        logger.error(f"删除用户失败: {e}")
        return {'success': False, 'message': str(e)}
    finally:
        conn.close()


# ============ 验证码公用方法 ============


def generate_verify_code() -> str:
    """生成 4 位数字验证码"""
    import random as _r
    return f"{_r.randint(0, 9999):04d}"


# ============ 用户密码管理 ============


def set_user_password(user_code: str, password: str) -> bool:
    """设置或更新用户密码"""
    import hashlib
    password_hash = hashlib.sha256(password.encode('utf-8')).hexdigest()
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE \"user\" SET password_hash=?, updated_at=datetime('now','localtime') WHERE code=? AND deleted_at IS NULL",
            (password_hash, user_code))
        conn.commit()
        return conn.total_changes > 0
    except Exception as e:
        logger.error(f"设置用户密码失败: {e}")
        return False
    finally:
        conn.close()


def verify_user_password(user_code: str, password: str) -> bool:
    """校验用户密码"""
    import hashlib
    password_hash = hashlib.sha256(password.encode('utf-8')).hexdigest()
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT password_hash FROM \"user\" WHERE code=? AND deleted_at IS NULL AND status=1",
            (user_code,))
        r = cur.fetchone()
        if r and r['password_hash']:
            return r['password_hash'] == password_hash
        return False
    except Exception as e:
        logger.error(f"校验用户密码失败: {e}")
        return False
    finally:
        conn.close()


def get_user_by_login(login_name: str) -> dict:
    """根据登录名（name 或 code）查找启用用户"""
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT * FROM \"user\" WHERE (name=? OR code=?) AND deleted_at IS NULL AND status=1 LIMIT 1",
            (login_name, login_name))
        r = cur.fetchone()
        return dict(r) if r else None
    except Exception as e:
        logger.error(f"查找用户失败: {e}")
        return None
    finally:
        conn.close()


def sync_admin_user(config) -> bool:
    """从环境变量同步管理员账号到数据库
    当 ADMIN_USERNAME 和 ADMIN_PASSWORD 配置时，自动在数据库中创建/更新管理员用户。
    """
    import hashlib
    admin_name = config.ADMIN_USERNAME
    admin_pwd = config.ADMIN_PASSWORD
    if not admin_name or not admin_pwd:
        logger.warning("ADMIN_USERNAME 或 ADMIN_PASSWORD 未配置，跳过管理员同步")
        return False
    conn = get_connection()
    try:
        # 检查是否已存在该用户
        cur = conn.execute(
            "SELECT id, password_hash, is_admin FROM \"user\" WHERE (name=? OR code=?) AND deleted_at IS NULL LIMIT 1",
            (admin_name, admin_name))
        existing = cur.fetchone()
        password_hash = hashlib.sha256(admin_pwd.encode('utf-8')).hexdigest()
        if existing:
            # 已有账号，只确保 is_admin 标识，不覆盖密码
            conn.execute(
                "UPDATE \"user\" SET is_admin=1, updated_at=datetime('now','localtime') WHERE id=?",
                (existing['id'],))
            logger.info(f"管理员用户 '{admin_name}' 已存在，更新管理员标识（保留原有密码）")
        else:
            conn.execute(
                "INSERT INTO \"user\" (name, code, password_hash, is_admin, created_by) VALUES (?, ?, ?, 1, 'system')",
                (admin_name, admin_name, password_hash))
            logger.info(f"管理员用户 '{admin_name}' 已自动创建")
        # 赋予 admin 角色
        conn.execute(
            "INSERT OR IGNORE INTO user_role (user_code, role_code, created_by) VALUES (?, 'admin', 'system')",
            (admin_name,))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"同步管理员用户失败: {e}")
        return False
    finally:
        conn.close()


# ============ 侧边栏菜单管理 ============

DEFAULT_MENUS = [
    # (type, parent_1based_index, icon, label, url, sort_order)
    # 首页（一级）
    ('page', 0, '🏠', '首页', '/', 1),
    # 系统管理 (dir) - 默认折叠
    ('dir', 0, '⚙️', '系统管理', None, 2),
    ('page', 2, '👥', '用户管理', '/user', 1),
    ('page', 2, '👥', '角色管理', '/roles', 2),
    ('page', 2, '📐', '菜单管理', '/menu', 3),
    ('page', 2, '⏰', '计划任务', '/scheduled-tasks', 4),
    ('page', 2, '📋', '消息日志', '/message-log', 5),
    # 系统管理 - 按键权限（用户管理）
    ('btn', 3, '➕', '用户-新建', '/api/users/create', 99),
    ('btn', 3, '🔗', '用户-绑定微信', '/api/users/bind-wx', 99),
    ('btn', 3, '👥', '用户-分配角色', '/api/users/roles', 99),
    ('btn', 3, '🔑', '用户-设置密码', '/api/users/set-password', 99),
    ('btn', 3, '🔄', '用户-启用停用', '/api/users/update', 99),
    ('btn', 3, '🗑️', '用户-删除', '/api/users/delete', 99),
    # 系统管理 - 按键权限（角色管理）
    ('btn', 4, '➕', '角色-新建', '/api/roles/create', 99),
    ('btn', 4, '✏️', '角色-编辑', '/api/roles/update', 99),
    ('btn', 4, '🗑️', '角色-删除', '/api/roles/delete', 99),
    ('btn', 4, '🔐', '角色-菜单授权', '/api/roles/set-menu-bindings', 99),
    ('btn', 4, '👤', '角色-绑定用户', '/api/roles/set-users', 99),
    # 系统管理 - 按键权限（菜单管理）
    ('btn', 5, '➕', '菜单-新建', '/api/menus/create', 99),
    ('btn', 5, '✏️', '菜单-编辑', '/api/menus/update', 99),
    ('btn', 5, '🗑️', '菜单-删除', '/api/menus/delete', 99),
    # 记账设置 (dir) - 默认折叠
    ('dir', 0, '⚙️', '记账设置', None, 3),
    ('page', 22, '📂', '科目管理', '/categories', 1),
    ('page', 22, '📊', '预算管理', '/budgets', 2),
    ('page', 22, '💳', '账户设置', '/accounts', 3),
    # 记账管理 (dir) - 默认折叠
    ('dir', 0, '📒', '记账管理', None, 4),
    ('page', 26, '✏️', '页面记账', '/add-transaction', 1),
    ('page', 26, '💰', '交易查询', '/transaction', 2),
    ('page', 26, '✅', '对账管理', '/reconciliation', 3),
    # 按键权限（科目管理）
    ('btn', 23, '➕', '科目-新建', '/api/categories/add', 99),
    ('btn', 23, '✏️', '科目-修改', '/api/categories/modify', 99),
    ('btn', 23, '🗑️', '科目-删除', '/api/categories/delete', 99),
    # 按键权限（账户管理）
    ('btn', 25, '➕', '账户-新建', '/api/accounts/create', 99),
    ('btn', 25, '✏️', '账户-修改', '/api/accounts/modify', 99),
    ('btn', 25, '🗑️', '账户-删除', '/api/accounts/delete', 99),
]


def init_menus():
    """初始化默认菜单（仅当表为空时写入）并绑定到 admin 角色"""
    conn = get_connection()
    try:
        # 确保 menu 表中有数据——如果 sidebar_menu 还存在则迁移
        has_sidebar = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sidebar_menu'").fetchone()
        if has_sidebar:
            sm_count = conn.execute("SELECT COUNT(*) FROM sidebar_menu").fetchone()[0]
            m_count = conn.execute("SELECT COUNT(*) FROM menu").fetchone()[0]
            if sm_count > 0 and m_count == 0:
                rows = conn.execute("SELECT * FROM sidebar_menu").fetchall()
                for r in rows:
                    conn.execute(
                        "INSERT INTO menu (id, parent_id, type, label, icon, url, sort_order, is_active, created_by, created_at, updated_by, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (r['id'], r.get('parent_id', 0), r.get('type', 'page'), r['label'], r['icon'],
                         r.get('url'), r['sort_order'], r['is_active'],
                         r['created_by'], r['created_at'], r['updated_by'], r['updated_at']))
                conn.commit()
                logger.info(f"从 sidebar_menu 迁移 {sm_count} 条数据到 menu 表")
                return

        cur = conn.execute("SELECT COUNT(*) as cnt FROM menu")
        if cur.fetchone()['cnt'] > 0:
            return
        menu_ids = []
        for idx, (typ, parent_ref, icon, label, url, sort_order) in enumerate(DEFAULT_MENUS):
            pid = 0
            if isinstance(parent_ref, int) and parent_ref > 0:
                # parent_ref 是 1-based 索引，指向 menu_ids 中的位置
                pid = menu_ids[parent_ref - 1] if parent_ref <= len(menu_ids) else 0
            elif isinstance(parent_ref, str) and parent_ref:
                pid = (menu_ids[idx] if idx > 0 else 0)  # fallback, won't happen
            conn.execute(
                "INSERT INTO menu (parent_id, type, label, icon, url, sort_order, default_expanded, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, 'system')",
                (pid, typ, label, icon, url, sort_order,
                 0 if label in ('系统管理','记账管理','记账设置') else (1 if typ == 'dir' else 0)))
            mid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            menu_ids.append(mid)
        conn.commit()
        for mid in menu_ids:
            conn.execute(
                "INSERT OR IGNORE INTO role_menu (role_code, menu_id, created_by) VALUES ('admin', ?, 'system')",
                (mid,))
        user_page_labels = ['首页', '交易查询', '页面记账']
        for row in conn.execute("SELECT id, label FROM menu WHERE type='page'").fetchall():
            if row['label'] in user_page_labels:
                conn.execute(
                    "INSERT OR IGNORE INTO role_menu (role_code, menu_id, created_by) VALUES ('user', ?, 'system')",
                    (row['id'],))
                p = conn.execute("SELECT parent_id FROM menu WHERE id=?", (row['id'],)).fetchone()
                if p and p['parent_id']:
                    conn.execute(
                        "INSERT OR IGNORE INTO role_menu (role_code, menu_id, created_by) VALUES ('user', ?, 'system')",
                        (p['parent_id'],))
        conn.commit()
        logger.info(f"已初始化 {len(DEFAULT_MENUS)} 个默认菜单")
    except Exception as e:
        logger.error(f"初始化菜单失败: {e}")
    finally:
        conn.close()


def get_menus_for_user(role_codes: list = None) -> list:
    """获取用户有权限看到的菜单（含父子结构）"""
    conn = get_connection()
    try:
        if not role_codes:
            return []
        placeholders = ','.join(['?'] * len(role_codes))
        rows = [dict(r) for r in conn.execute(
            f"""SELECT DISTINCT m.* FROM menu m
                LEFT JOIN role_menu rm ON rm.menu_id = m.id
                WHERE m.is_active = 1
                  AND rm.role_code IN ({placeholders})
                ORDER BY m.sort_order, m.id""",
            role_codes).fetchall()]
        all_ids = set(r['id'] for r in rows)
        parent_ids = set(r['parent_id'] for r in rows if r['parent_id'])
        missing_parents = parent_ids - all_ids
        if missing_parents:
            extras = [dict(r) for r in conn.execute(
                f"SELECT * FROM menu WHERE id IN ({','.join('?' * len(missing_parents))})",
                list(missing_parents)).fetchall()]
            rows.extend(extras)
        rows.sort(key=lambda x: (x['sort_order'], x['id']))
        return rows
    except Exception as e:
        logger.error(f"获取用户菜单失败: {e}")
        return []
    finally:
        conn.close()


def get_all_menus() -> list:
    """获取所有菜单（含停用的，用于管理页面）"""
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM menu ORDER BY sort_order, id").fetchall()]
    except Exception as e:
        logger.error(f"获取所有菜单失败: {e}")
        return []
    finally:
        conn.close()


def add_menu(label: str, icon: str, url: str = None, sort_order: int = 0,
             parent_id: int = 0, typ: str = 'page',
             default_expanded: int = 1,
             created_by: str = None) -> bool:
    """添加菜单项"""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO menu (parent_id, type, label, icon, url, sort_order, default_expanded, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (parent_id, typ, label, icon, url, sort_order, default_expanded, created_by))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"添加菜单失败: {e}")
        return False
    finally:
        conn.close()


def update_menu(menu_id: int, label: str = None, icon: str = None,
                url: str = None, sort_order: int = None,
                parent_id: int = None, typ: str = None,
                is_active: int = None,
                default_expanded: int = None,
                updated_by: str = None) -> bool:
    """更新菜单项"""
    conn = get_connection()
    try:
        fields = ["updated_at=datetime('now','localtime')"]
        params = []
        if label is not None:
            fields.append("label=?")
            params.append(label)
        if icon is not None:
            fields.append("icon=?")
            params.append(icon)
        if url is not None:
            fields.append("url=?")
            params.append(url)
        if sort_order is not None:
            fields.append("sort_order=?")
            params.append(sort_order)
        if parent_id is not None:
            fields.append("parent_id=?")
            params.append(parent_id)
        if typ is not None:
            fields.append("type=?")
            params.append(typ)
        if is_active is not None:
            fields.append("is_active=?")
            params.append(is_active)
        if default_expanded is not None:
            fields.append("default_expanded=?")
            params.append(1 if default_expanded else 0)
        if updated_by:
            fields.append("updated_by=?")
            params.append(updated_by)
        if not fields:
            return True
        params.append(menu_id)
        conn.execute(f"UPDATE menu SET {', '.join(fields)} WHERE id=?", params)
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"更新菜单失败: {e}")
        return False
    finally:
        conn.close()


def delete_menu(menu_id: int) -> bool:
    """删除菜单项"""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM menu WHERE id=?", (menu_id,))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"删除菜单失败: {e}")
        return False
    finally:
        conn.close()


# ============ 角色管理 ============

DEFAULT_ROLES = [
    ('admin', '管理员', '拥有所有管理权限', 1),
    ('user', '普通用户', '可使用记账、查询等基础功能', 1),
]


def init_default_roles():
    """初始化默认角色（仅当表为空时写入）"""
    conn = get_connection()
    try:
        cur = conn.execute("SELECT COUNT(*) as cnt FROM role")
        if cur.fetchone()['cnt'] > 0:
            return
        for code, name, desc, is_default in DEFAULT_ROLES:
            conn.execute(
                "INSERT INTO role (code, name, description, is_default, created_by) VALUES (?, ?, ?, ?, 'system')",
                (code, name, desc, is_default))
        conn.commit()
        logger.info(f"已初始化 {len(DEFAULT_ROLES)} 个默认角色")
    except Exception as e:
        logger.error(f"初始化角色失败: {e}")
    finally:
        conn.close()


def get_all_roles() -> list:
    """获取所有角色"""
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM role ORDER BY id").fetchall()]
    except Exception as e:
        logger.error(f"获取角色失败: {e}")
        return []
    finally:
        conn.close()


def get_user_role_codes(user_code: str) -> list:
    """获取用户拥有的所有角色编码"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT role_code FROM user_role WHERE user_code=?", (user_code,)).fetchall()
        return [r['role_code'] for r in rows]
    except Exception as e:
        logger.error(f"获取用户角色失败: {e}")
        return []
    finally:
        conn.close()


def add_role(code: str, name: str, description: str = None,
             is_default: int = 0, created_by: str = None) -> bool:
    """添加角色"""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO role (code, name, description, is_default, created_by) VALUES (?, ?, ?, ?, ?)",
            (code, name, description, is_default, created_by))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"添加角色失败: {e}")
        return False
    finally:
        conn.close()


def update_role(role_id: int, name: str = None, description: str = None,
                is_default: int = None, updated_by: str = None) -> bool:
    """更新角色"""
    conn = get_connection()
    try:
        fields = ["updated_at=datetime('now','localtime')"]
        params = []
        if name is not None:
            fields.append("name=?")
            params.append(name)
        if description is not None:
            fields.append("description=?")
            params.append(description)
        if is_default is not None:
            fields.append("is_default=?")
            params.append(is_default)
        if updated_by:
            fields.append("updated_by=?")
            params.append(updated_by)
        if not fields:
            return True
        params.append(role_id)
        conn.execute(f"UPDATE role SET {', '.join(fields)} WHERE id=?", params)
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"更新角色失败: {e}")
        return False
    finally:
        conn.close()


def delete_role(role_id: int) -> bool:
    """删除角色（同时清理关联的 role_menu 和 user_role）"""
    conn = get_connection()
    try:
        cur = conn.execute("SELECT code FROM role WHERE id=?", (role_id,))
        r = cur.fetchone()
        if not r:
            return False
        code = r['code']
        conn.execute("DELETE FROM role_menu WHERE role_code=?", (code,))
        conn.execute("DELETE FROM user_role WHERE role_code=?", (code,))
        conn.execute("DELETE FROM role WHERE id=?", (role_id,))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"删除角色失败: {e}")
        return False
    finally:
        conn.close()


# ============ 角色-菜单绑定 ============

def set_role_menus(role_code: str, menu_ids: list, updated_by: str = None) -> bool:
    """批量设置角色可见的菜单"""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM role_menu WHERE role_code=?", (role_code,))
        for mid in menu_ids:
            conn.execute(
                "INSERT INTO role_menu (role_code, menu_id, created_by) VALUES (?, ?, ?)",
                (role_code, mid, updated_by))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"设置角色菜单失败: {e}")
        return False
    finally:
        conn.close()


def get_role_menu_ids(role_code: str) -> list:
    """获取角色可见的菜单 ID 列表"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT menu_id FROM role_menu WHERE role_code=?", (role_code,)).fetchall()
        return [r['menu_id'] for r in rows]
    except Exception as e:
        logger.error(f"获取角色菜单失败: {e}")
        return []
    finally:
        conn.close()


def check_user_menu_permission(user_code: str, menu_url: str) -> bool:
    """检查用户是否有某个菜单/按钮的权限（通过角色）"""
    if not user_code or not menu_url:
        return False
    conn = get_connection()
    try:
        # 获取用户角色
        role_codes = [r['role_code'] for r in conn.execute(
            "SELECT role_code FROM user_role WHERE user_code=?", (user_code,)).fetchall()]
        if not role_codes:
            return False
        # 查找菜单 ID
        menu = conn.execute(
            "SELECT id FROM menu WHERE url=? AND is_active=1 LIMIT 1", (menu_url,)).fetchone()
        if not menu:
            return False
        menu_id = menu['id']
        # 检查角色是否有权限
        placeholders = ','.join(['?'] * len(role_codes))
        result = conn.execute(
            f"SELECT 1 FROM role_menu WHERE menu_id=? AND role_code IN ({placeholders}) LIMIT 1",
            [menu_id] + role_codes).fetchone()
        return result is not None
    except Exception as e:
        logger.error(f"检查菜单权限失败: {e}")
        return False
    finally:
        conn.close()


# ============ 用户-角色绑定 ============

def set_user_roles(user_code: str, role_codes: list, updated_by: str = None) -> bool:
    """批量设置用户拥有的角色"""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM user_role WHERE user_code=?", (user_code,))
        for rc in role_codes:
            conn.execute(
                "INSERT INTO user_role (user_code, role_code, created_by) VALUES (?, ?, ?)",
                (user_code, rc, updated_by))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"设置用户角色失败: {e}")
        return False
    finally:
        conn.close()


def get_users_with_roles(status=None) -> list:
    """获取用户列表（含角色信息）"""
    conn = get_connection()
    try:
        sql = "SELECT * FROM \"user\" WHERE deleted_at IS NULL"
        params = []
        if status is not None:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY name"
        users = [dict(r) for r in conn.execute(sql, params).fetchall()]
        # 获取所有角色
        role_rows = conn.execute(
            "SELECT ur.user_code, r.code, r.name FROM user_role ur JOIN role r ON r.code=ur.role_code"
        ).fetchall()
        role_map = {}
        for rr in role_rows:
            role_map.setdefault(rr['user_code'], []).append({
                'code': rr['code'], 'name': rr['name']})
        for u in users:
            code = u['code']
            u['roles'] = role_map.get(code, [])
        return users
    except Exception as e:
        logger.error(f"获取用户列表失败: {e}")
        return []
    finally:
        conn.close()


# ============ 统计查询 ============

def get_transactions_statistics(start_time, end_time, user_filter=None):
    """获取交易统计"""
    conn = get_connection()
    try:
        params = [start_time, end_time]
        user_code_filter = None
        if user_filter:
            user_code_filter = user_filter

        sql = "SELECT category_id, category_name, SUM(CASE WHEN bill_type='income' THEN amount ELSE 0 END) as income_amount, ABS(SUM(CASE WHEN bill_type='expense' THEN amount ELSE 0 END)) as expense_amount FROM \"transaction\" WHERE transaction_time>=? AND transaction_time<=? AND deleted_at IS NULL AND bill_type != 'transfer'"
        if user_code_filter:
            sql += " AND user_code=?"
            params.append(user_code_filter)
        sql += " GROUP BY category_id, category_name ORDER BY expense_amount DESC"
        rows = conn.execute(sql, params).fetchall()
        logger.info(f"[预算统计] SQL: {sql}, params={params}, 返回{len(rows)}行")
        for r in rows:
            logger.info(f"[预算统计]   category_id={r['category_id']}, name={r['category_name']}, income={r['income_amount']}, expense={r['expense_amount']}")
        items = [{'categoryName': r['category_name'], 'categoryId': str(r['category_id'] or ''), 'amount': int(r['income_amount'] - r['expense_amount']), 'incomeAmount': int(r['income_amount']), 'expenseAmount': int(r['expense_amount'])} for r in rows]
        return {'result': {'items': items}}
    except Exception as e:
        logger.error(f"获取统计失败: {e}")
        return {'result': {'items': []}}
    finally:
        conn.close()


def get_transaction_amounts(start_time, end_time):
    """获取金额汇总"""
    conn = get_connection()
    try:
        cur = conn.execute("SELECT COALESCE(SUM(CASE WHEN bill_type='income' THEN amount ELSE 0 END),0) as ti, COALESCE(ABS(SUM(CASE WHEN bill_type='expense' THEN amount ELSE 0 END)),0) as te FROM \"transaction\" WHERE transaction_time>=? AND transaction_time<=? AND deleted_at IS NULL AND bill_type != 'transfer'", (start_time, end_time))
        r = cur.fetchone()
        if r:
            return {'summary': {'amounts': [{'incomeAmount': int(r['ti']), 'expenseAmount': int(r['te'])}]}}
        return {'summary': {'amounts': []}}
    except Exception as e:
        logger.error(f"获取金额汇总失败: {e}")
        return {'summary': {'amounts': []}}
    finally:
        conn.close()


def get_transactions_list(start_time, end_time, page=0, count=50, with_count=False, user_filter=None):
    """获取交易列表"""
    conn = get_connection()
    try:
        params = [start_time, end_time]
        user_code_filter = None
        if user_filter:
            user_code_filter = user_filter

        result = {'transactions': []}
        if with_count:
            csql = "SELECT COUNT(*) FROM \"transaction\" WHERE transaction_time>=? AND transaction_time<=? AND deleted_at IS NULL AND bill_type != 'transfer'"
            cp = [start_time, end_time]
            if user_code_filter:
                csql += " AND user_code=?"
                cp.append(user_code_filter)
            result['count'] = conn.execute(csql, cp).fetchone()[0]

        sql = "SELECT * FROM \"transaction\" WHERE transaction_time>=? AND transaction_time<=? AND deleted_at IS NULL AND bill_type != 'transfer'"
        if user_code_filter:
            sql += " AND user_code=?"
            params.append(user_code_filter)
        sql += " ORDER BY transaction_time DESC LIMIT ? OFFSET ?"
        params.extend([count, page * count])

        for r in conn.execute(sql, params).fetchall():
            d = dict(r)
            result['transactions'].append({
                'id': str(d['id']),
                'type': 2 if d['bill_type'] == 'income' else 3,
                'categoryId': '',
                'categoryName': d['category_name'],
                'sourceAccountId': d.get('account_id') or '',
                'sourceAmount': abs(d['amount']),
                'time': 0,
                'comment': d['comment'],
            })
        return result
    except Exception as e:
        logger.error(f"获取交易列表失败: {e}")
        return {'transactions': []}
    finally:
        conn.close()


# ============ 账户科目管理 ============


def get_account_category() -> list:
    """获取账户科目列表"""
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT * FROM account_category ORDER BY id")
        return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"获取账户分类失败: {e}")
        return []
    finally:
        conn.close()
