#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""账本客户端"""
import logging
from datetime import datetime


from config import get_config

logger = logging.getLogger(__name__)

# 模块级缓存（跨实例共享，变更时自动失效）
_accounts_cache = None
_categories_cache = None


class BookkeepingClient:
    """账本客户端"""

    def __init__(self):
        self.config = get_config()

    @staticmethod
    def save_user_account(user_code: str, account_id: str, direction: str = 'expense',
                          updated_by: str = None,
                          message_log_id: int = None,
                          source: str = None,
                          source_user: str = None) -> bool:
        """保存用户账户映射到SQLite数据库（user_code 为项目用户编码）"""
        from db import set_user_account
        return set_user_account(user_code, account_id, direction,
                                updated_by=updated_by or user_code,
                                message_log_id=message_log_id,
                                source=source,
                                source_user=source_user)

    # ============ 科目管理 ============


    def get_categories(self, category_type=None):
        global _categories_cache
        if _categories_cache is None:
            from db import get_categories as _f
            _categories_cache = _f()
        if category_type is None:
            return _categories_cache
        return [c for c in _categories_cache if c.get('type') == category_type or any(s.get('type') == category_type for s in c.get('subCategories', []))]

    def find_category_by_name(self, name, category_type='expense'):
        from db import find_category_by_name as _f
        return _f(name, category_type)

    def find_category_by_id(self, cat_id, category_type=None):
        from db import find_category_by_id as _f
        return _f(cat_id, category_type)

    def find_account_by_id(self, acct_id):
        from db import find_account_by_id as _f
        return _f(acct_id)

    def create_category(self, name, category_type='expense', parent_id='0', icon='1', color='ff6b22', comment='', created_by=None):
        global _categories_cache
        from db import add_category as _f
        result = _f(name, category_type, parent_id, icon, color, comment, created_by=created_by)
        _categories_cache = None
        return result

    def modify_category(self, category_id, name=None, parent_id=None, icon=None, color=None, comment=None, hidden=None, updated_by=None):
        global _categories_cache
        from db import modify_category as _f
        kw = {}
        if name is not None: kw['name'] = name
        if parent_id is not None and parent_id != '0': kw['parent_id'] = parent_id
        if icon is not None: kw['icon'] = icon
        if color is not None: kw['color'] = color
        if comment is not None: kw['comment'] = comment
        if hidden is not None: kw['hidden'] = 1 if hidden else 0
        ok = _f(category_id, updated_by=updated_by, **kw)
        _categories_cache = None
        return {'id': category_id, 'name': name} if ok else None

    def move_category(self, category_id, new_display_order):
        return self.move_categories([(category_id, new_display_order)])

    def move_categories(self, order_pairs, updated_by=None):
        global _categories_cache
        from db import reorder_categories as _f
        result = _f(order_pairs, updated_by=updated_by)
        _categories_cache = None
        return result

    def delete_category(self, category_id):
        global _categories_cache
        from db import delete_category as _f
        result = _f(category_id)
        _categories_cache = None
        return result

    # ============ 账户管理 ============

    def get_accounts(self):
        global _accounts_cache
        if _accounts_cache is None:
            from db import get_accounts as _f
            _accounts_cache = _f()
        return _accounts_cache

    def get_default_account(self, from_user=None, direction='expense', source=None):
        if not from_user: return None
        from db import get_user_account, require_user_bound
        user_code, _ = require_user_bound(from_user, source=source or 'wecom')
        if not user_code:
            return None
        mid = get_user_account(user_code, direction)
        if not mid: return None
        for a in self.get_accounts():
            if str(a.get('id')) == str(mid): return a
            for s in a.get('subAccounts', []):
                if str(s.get('id')) == str(mid): return s
        return None

    def create_account(self, name, category, icon='1', color='ff6b22',
                       currency=None, balance=0, balance_time=None, comment='', sub_accounts=None,
                       parent_id='0', created_by=None):
        global _accounts_cache
        from db import add_account as _f
        if sub_accounts:
            p = _f(name, category, icon, color, currency or '---', comment, parent_id=parent_id, created_by=created_by)
            if p:
                for sa in sub_accounts:
                    _f(sa.get('name',''), category, sa.get('icon',icon),
                       sa.get('color',color), sa.get('currency',currency or 'CNY'),
                       sa.get('comment',''), parent_id=p['id'], created_by=created_by)
            _accounts_cache = None
            return p
        result = _f(name, category, icon, color, currency or 'CNY', comment, parent_id=parent_id, created_by=created_by)
        _accounts_cache = None
        return result

    def modify_account(self, account_id, name=None, icon=None, color=None, comment=None, hidden=None, category=None, updated_by=None):
        global _accounts_cache
        from db import modify_account as _f
        kw = {}
        if name is not None: kw['name'] = name
        if icon is not None: kw['icon'] = icon
        if color is not None: kw['color'] = color
        if comment is not None: kw['comment'] = comment
        if hidden is not None: kw['hidden'] = 1 if hidden else 0
        if category is not None: kw['category'] = category
        ok = _f(account_id, updated_by=updated_by, **kw)
        _accounts_cache = None
        return {'id': account_id, 'name': name} if ok else None

    def delete_account(self, account_id):
        global _accounts_cache
        from db import delete_account as _f
        result = _f(account_id)
        _accounts_cache = None
        return result

    # ============ 用户绑定检查（带缓存） ============

    def require_user_bound(self, source_user, source) -> tuple:
        """检查第三方账号是否已绑定项目用户，返回 (user_code, error_message)
        缓存由 db.require_user_bound 统一管理，绑定变更时自动失效。
        """
        from db import require_user_bound as _f
        return _f(source_user, source=source)

    # ============ 用户管理 ============

    def get_users(self):
        from db import get_users as _f
        return _f()

    def create_user(self, name, created_by=None):
        from db import add_user as _f
        return _f(name, created_by=created_by)

    def find_or_create_user(self, name, created_by=None):
        from db import find_or_create_user as _f
        return _f(name, created_by=created_by)

    # ============ 交易管理 ============

    def create_transaction(self, category_id, amount, account_id, comment='',
                           transaction_time=None, transaction_type=3,
                           created_by=None, user_code=None,
                           source=None, source_user=None,
                           raw_message=None, message_log_id=None):
        from db import add_transaction, get_connection
        from datetime import datetime
        if transaction_time is None: transaction_time = datetime.now()
        bt = transaction_time.strftime('%Y-%m-%d %H:%M:%S')
        bill_type = 'income' if transaction_type == 2 else 'expense'
        # 负值表示退款，保持原值不变
        if amount < 0:
            bamt = amount
        else:
            bamt = amount if transaction_type == 2 else -amount
        # 校验 user_code
        if user_code:
            conn = get_connection()
            try:
                cur = conn.execute("SELECT id FROM \"user\" WHERE code=?", (user_code,))
                if not cur.fetchone():
                    return {'success': False, 'errorMessage': f'用户不存在: {user_code}'}
            finally:
                conn.close()
        # 校验 account_id，获取账户名称和币种
        acct_name = ''
        acct_currency = 'CNY'
        found = False
        for a in self.get_accounts():
            if str(a.get('id')) == str(account_id):
                acct_name = a.get('name', ''); acct_currency = a.get('currency', 'CNY'); found = True; break
            for s in a.get('subAccounts', []):
                if str(s.get('id')) == str(account_id):
                    acct_name = s.get('name', ''); acct_currency = s.get('currency', 'CNY'); found = True; break
        if not found:
            return {'success': False, 'errorMessage': f'账户不存在: {account_id}'}
        # 查找科目名称
        cat_name = ''
        conn = get_connection()
        try:
            cur = conn.execute("SELECT name FROM categories WHERE id=?", (category_id,))
            r = cur.fetchone()
            if r: cat_name = r['name']
        finally:
            conn.close()
        if not cat_name:
            return {'success': False, 'errorMessage': f'科目不存在: {category_id}'}
        # created_by 使用 user_code（项目用户编码），source_user 保留原始来源用户
        effective_created_by = user_code or created_by
        tx_id, tx_uuid, verify_code = add_transaction(bill_type=bill_type, category_name=cat_name,
                                category_id=str(category_id),
                                amount=bamt, comment=comment, transaction_time=bt,
                                account_id=str(account_id), account_name=acct_name,
                                created_by=effective_created_by, user_code=user_code,
                                source=source, source_user=source_user,
                                raw_message=raw_message, message_log_id=message_log_id,
                                currency=acct_currency)
        if tx_id > 0: return {'success': True, 'result': {'id': str(tx_id), 'uuid': tx_uuid, 'verify_code': verify_code}}
        return {'success': False, 'errorMessage': '写入交易失败'}

    def delete_transaction(self, transaction_id, updated_by=None):
        from db import soft_delete_transaction as _f
        ok = _f(int(transaction_id), updated_by=updated_by) if transaction_id and str(transaction_id).lstrip('-').isdigit() else False
        return {'success': True} if ok else {'success': False, 'errorMessage': '未找到'}

    def modify_transaction(self, transaction_id, category_id=None, amount=None,
                           comment=None, transaction_time=None, account_id=None,
                           updated_by=None):
        from db import modify_transaction as _mod, get_connection
        kw = {}
        if category_id is not None:
            conn = get_connection()
            try:
                cur = conn.execute("SELECT name FROM categories WHERE id=?", (category_id,))
                r = cur.fetchone()
                if r: kw['category_name'] = r['name']
            finally: conn.close()
        if amount is not None: kw['amount'] = amount
        if comment is not None: kw['comment'] = comment
        if account_id is not None:
            kw['account_id'] = str(account_id)
            for a in self.get_accounts():
                if str(a.get('id')) == str(account_id): kw['account_name'] = a.get('name',''); break
                for s in a.get('subAccounts', []):
                    if str(s.get('id')) == str(account_id): kw['account_name'] = s.get('name',''); break
        if not kw: return {'success': False, 'errorMessage': '无修改字段'}
        ok = _mod(int(transaction_id), updated_by=updated_by, **kw)
        return {'success': True} if ok else {'success': False, 'errorMessage': '修改失败'}

    def create_transfer(self, from_account_id, to_account_id, amount,
                        comment='', transaction_time=None,
                        created_by=None, user_code=None,
                        source=None, source_user=None,
                        raw_message=None, message_log_id=None):
        from db import add_transaction, get_connection
        from datetime import datetime
        if transaction_time is None: transaction_time = datetime.now()
        bt = transaction_time.strftime('%Y-%m-%d %H:%M:%S')
        # 查账户名称和币种
        from_name = ''
        to_name = ''
        from_currency = 'CNY'
        for a in self.get_accounts():
            if str(a.get('id')) == str(from_account_id):
                from_name = a.get('name', ''); from_currency = a.get('currency', 'CNY'); break
            for s in a.get('subAccounts', []):
                if str(s.get('id')) == str(from_account_id):
                    from_name = s.get('name', ''); from_currency = s.get('currency', 'CNY'); break
            if from_name:
                break
        for a in self.get_accounts():
            if str(a.get('id')) == str(to_account_id):
                to_name = a.get('name', ''); break
            for s in a.get('subAccounts', []):
                if str(s.get('id')) == str(to_account_id):
                    to_name = s.get('name', ''); break
            if to_name:
                break
        effective_created_by = user_code or created_by
        tx_id, tx_uuid, verify_code = add_transaction(bill_type='transfer', category_name='转账', amount=amount,
                        comment=comment or f'从{from_name}转到{to_name}',
                        transaction_time=bt, created_by=effective_created_by,
                        account_id=str(from_account_id), account_name=from_name,
                        to_account_id=str(to_account_id), to_account_name=to_name,
                        user_code=user_code,
                        source=source, source_user=source_user,
                        raw_message=raw_message, message_log_id=message_log_id,
                        currency=from_currency)
        return {'success': True, 'result': {'id': str(tx_id), 'uuid': tx_uuid, 'verify_code': verify_code}}

    # ============ 统计查询 ============

    def get_transactions_statistics(self, start_time, end_time, user_filter=None):
        from db import get_transactions_statistics as _f
        return _f(start_time.strftime('%Y-%m-%d %H:%M:%S'), end_time.strftime('%Y-%m-%d %H:%M:%S'), user_filter)

    def get_transaction_amounts(self, start_time, end_time):
        from db import get_transaction_amounts as _f
        return _f(start_time.strftime('%Y-%m-%d %H:%M:%S'), end_time.strftime('%Y-%m-%d %H:%M:%S'))

    def get_transactions_list(self, start_time, end_time, page=0, count=50, with_count=False, user_filter=None):
        from db import get_transactions_list as _f
        return _f(start_time.strftime('%Y-%m-%d %H:%M:%S'), end_time.strftime('%Y-%m-%d %H:%M:%S'), page, count, with_count, user_filter)

    def _find_or_create_parent_category(self, category_type):
        cats = self.get_categories(category_type=category_type)
        for cat in cats:
            subs = cat.get('subCategories', [])
            if subs: return str(cat.get('id'))
            if cat.get('parentId') == '0' or not cat.get('parentId'): return str(cat.get('id'))
        label = '收入' if category_type == 'income' else '支出'
        nc = self.create_category(f'其他{label}', category_type)
        return str(nc.get('id', '0')) if nc else '0'

    @staticmethod
    def _find_transfer_leaf_category(cats):
        for cat in cats:
            if cat.get('type') == 3:
                subs = cat.get('subCategories', [])
                return str(subs[0]['id']) if subs else str(cat['id'])
        return None

    @staticmethod
    def _to_unix_timestamp(dt):
        return int(dt.timestamp())
