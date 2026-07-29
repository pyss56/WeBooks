#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版本信息"""
import os

__version__ = "1.3.2-beta"
__app_name__ = "WeBooks"
__description__ = "微记账"

# Docker 构建信息（如果存在）
_build_info_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'build_info')
if os.path.exists(_build_info_path):
    with open(_build_info_path, 'r') as f:
        for line in f:
            line = line.strip()
            if '=' in line:
                key, value = line.split('=', 1)
                if key == 'VERSION' and value != 'unknown':
                    __version__ = value
                elif key == 'BUILD_TIME':
                    __build_time__ = value
                elif key == 'COMMIT_SHA':
                    __commit_sha__ = value
