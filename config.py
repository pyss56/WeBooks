#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置管理模块"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """应用配置"""

    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', os.urandom(24).hex())

    # 企业微信配置
    WECOM_CORP_ID = os.getenv('WECOM_CORP_ID', '')
    WECOM_AGENT_ID = os.getenv('WECOM_AGENT_ID', '')
    WECOM_CORP_SECRET = os.getenv('WECOM_CORP_SECRET', '')
    WECOM_TOKEN = os.getenv('WECOM_TOKEN', '')
    WECOM_ENCODING_AES_KEY = os.getenv('WECOM_ENCODING_AES_KEY', '')
    WECOM_API_BASE_URL = os.getenv('WECOM_API_BASE_URL', 'https://qyapi.weixin.qq.com')
    WECOM_AGENT_URL = os.getenv('WECOM_AGENT_URL', '')  # 代理转发URL，用于规避IP白名单限制

    # 账本配置
    LEDGER_BASE_URL = os.getenv('LEDGER_BASE_URL', '')

    # 时区
    TIMEZONE = os.getenv('TIMEZONE', 'Asia/Shanghai')

    # 推送用户（默认推送给全部人员）
    WECOM_TO_USER = os.getenv('WECOM_TO_USER', '@all')

    # 管理员用户名和密码（用于登录管理后台）
    ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '')
    # 是否在启动时使用环境变量中的 ADMIN_PASSWORD 强制重置/设置管理员密码
    ADMIN_RESET_ON_START = os.getenv('ADMIN_RESET_ON_START', 'false').strip().lower() in ('true', '1', 'yes')

    # 服务外部访问地址（用于生成菜单链接等）
    BASE_URL = os.getenv('BASE_URL', '').rstrip('/')

    # PC端访问入口编码（企业微信自建应用主页URL拼接用）
    WEB_ENTRY_CODE = os.getenv('WEB_ENTRY_CODE', '').strip()

    # 未带入口编码时的跳转地址
    WEB_ENTRY_REDIRECT = os.getenv('WEB_ENTRY_REDIRECT', 'https://example.com').strip()

    # 企业微信 OAuth 登录开关（用于汇总图表免验证码，需 HTTPS + 可信域名）
    WECOM_OAUTH_ENABLED = os.getenv('WECOM_OAUTH_ENABLED', 'false').strip().lower() in ('true', '1', 'yes')




config = Config()


def get_config():
    return config
