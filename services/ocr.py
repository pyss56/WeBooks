#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OCR识别服务 - 识别消费截图中的交易信息

支持多引擎后端（按优先级自动选择）：
1. ddddocr  — 轻量级（~30MB），推荐
2. PaddleOCR — 重量级（~800MB，含 PyTorch）
"""
import logging
import os
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


def resolve_and_match(text: str, match_type: str) -> dict:
    """统一匹配：先搜索科目/账户表 → 再别名回退，返回 {resolved_id, resolved_name} 或 {}"""
    from db import resolve_alias, get_connection

    table = 'categories' if match_type == 'category' else 'accounts'
    id_col = 'id'
    name_col = 'name'

    # 1. 数据库表精确匹配
    try:
        conn = get_connection()
        rows = conn.execute(
            f"SELECT {id_col}, {name_col} FROM {table} WHERE deleted_at IS NULL"
        ).fetchall()
        conn.close()
        best = None
        best_score = 0
        for row in rows:
            name = row[name_col] or ''
            # 精确匹配优先
            if name == text:
                return {'resolved_id': str(row[id_col]), 'resolved_name': name}
            score = sum(1 for c in text if c in name)
            if score > best_score:
                best_score = score
                best = row
        if best and best_score > 0:
            return {'resolved_id': str(best[id_col]), 'resolved_name': best[name_col]}
    except Exception:
        pass

    # 2. 别名匹配回退
    try:
        eid, ename = resolve_alias(text, match_type)
        if eid:
            return {'resolved_id': str(eid), 'resolved_name': ename}
    except Exception:
        pass

    return {}

# 图片上传目录
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'ocr_uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 持久化图片目录（记账成功后移至此处，以交易 UUID 命名）
IMAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'ocr_images')
os.makedirs(IMAGES_DIR, exist_ok=True)

_ocr_backend = None  # 当前使用的后端名称
_ocr_engine = None   # OCR 引擎实例（detector/识别器取决于后端）
_ocr_detector = None # ddddocr 检测器（单独实例）
_ocr_recognizer = None  # ddddocr 识别器（单独实例）


def _get_ocr_engine():
    """延迟初始化 OCR 引擎（按优先级尝试多个后端）"""
    global _ocr_engine, _ocr_backend, _ocr_detector, _ocr_recognizer
    if _ocr_engine is not None:
        return _ocr_engine

    # 1. 尝试 ddddocr（轻量级）
    try:
        import ddddocr
        _ocr_engine = ddddocr.DdddOcr(det=True, show_ad=False)  # 检测器
        _ocr_detector = _ocr_engine
        _ocr_recognizer = ddddocr.DdddOcr(show_ad=False)       # 识别器（独立实例）
        _ocr_backend = 'ddddocr'
        logger.info("✅ OCR 引擎: ddddocr（轻量级）初始化成功")
        return _ocr_engine
    except ImportError:
        logger.debug("ddddocr 未安装，尝试下一个后端...")

    # 2. 尝试 PaddleOCR（重量级）
    try:
        from paddleocr import PaddleOCR
        _ocr_engine = PaddleOCR(use_angle_cls=True, lang='ch', show_log=False)
        _ocr_backend = 'paddleocr'
        _ocr_detector = None
        _ocr_recognizer = None
        logger.info("✅ OCR 引擎: PaddleOCR 初始化成功（重量级）")
        return _ocr_engine
    except ImportError:
        logger.warning("PaddleOCR 也未安装")

    _ocr_engine = False
    _ocr_backend = None
    _ocr_detector = None
    _ocr_recognizer = None
    return _ocr_engine


def is_ocr_available() -> bool:
    """检查 OCR 引擎是否可用"""
    engine = _get_ocr_engine()
    return engine is not None and engine is not False


def get_ocr_backend_name() -> str:
    """获取当前 OCR 后端名称"""
    _get_ocr_engine()
    return _ocr_backend or 'none'


def ocr_image(image_path: str) -> list:
    """对图片执行 OCR 识别，返回识别到的文本行列表

    返回格式: [{'text': str, 'confidence': float}, ...]
    """
    engine = _get_ocr_engine()
    if not engine:
        raise RuntimeError("OCR 引擎不可用，请安装 ddddocr 或 PaddleOCR\n"
                           "  pip install ddddocr     # 轻量版，推荐\n"
                           "  pip install paddleocr   # 重量版")

    backend = _ocr_backend

    if backend == 'ddddocr':
        return _ocr_ddddocr(image_path, engine)
    elif backend == 'paddleocr':
        return _ocr_paddleocr(image_path, engine)
    else:
        raise RuntimeError(f"未知 OCR 后端: {backend}")


def _ocr_ddddocr(image_path: str, detector) -> list:
    """使用 ddddocr 引擎识别

    策略：分多个垂直区域独立检测（放大+增强），
    合并去重后按行从左到右拼接。
    返回 [{text, y}, ...]，按 y 从上到下排序。
    """
    import cv2 as _cv2
    import numpy as _np
    global _ocr_recognizer

    img = _cv2.imread(image_path)
    if img is None:
        logger.error(f"无法读取图片: {image_path}")
        return []
    h, w = img.shape[:2]

    # ── 分区域检测 ──
    # 图片高度划分为多个重叠区域，每个区域独立做检测
    zone_height = 800
    overlap = 100
    all_boxes = []

    for y_start in range(0, h, zone_height - overlap):
        y_end = min(y_start + zone_height, h)
        roi = img[y_start:y_end, :]

        # 放大 1.5 倍
        roi_big = _cv2.resize(roi, None, fx=1.5, fy=1.5,
                              interpolation=_cv2.INTER_CUBIC)
        _, buf_orig = _cv2.imencode('.jpg', roi_big,
                                    [_cv2.IMWRITE_JPEG_QUALITY, 95])

        # 原始放大图检测
        boxes = detector.detection(buf_orig.tobytes())
        if boxes:
            for (x1, y1, x2, y2) in boxes:
                ox1 = int(x1 / 1.5)
                oy1 = int(y1 / 1.5) + y_start
                ox2 = int(x2 / 1.5)
                oy2 = int(y2 / 1.5) + y_start
                all_boxes.append((ox1, oy1, ox2, oy2))

        # CLAHE 增强图检测（仅补充原图未检测到的区域）
        gray = _cv2.cvtColor(roi_big, _cv2.COLOR_BGR2GRAY)
        clahe = _cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        _, buf_enhanced = _cv2.imencode('.jpg', enhanced,
                                        [_cv2.IMWRITE_JPEG_QUALITY, 95])
        boxes2 = detector.detection(buf_enhanced.tobytes())
        if boxes2:
            for (x1, y1, x2, y2) in boxes2:
                ox1 = int(x1 / 1.5)
                oy1 = int(y1 / 1.5) + y_start
                ox2 = int(x2 / 1.5)
                oy2 = int(y2 / 1.5) + y_start
                # 与原图检测框比较，重叠 > 0.3 则跳过（避免重复）
                dup = False
                for (ex1, ey1, ex2, ey2) in all_boxes:
                    ix1, iy1 = max(ox1, ex1), max(oy1, ey1)
                    ix2, iy2 = min(ox2, ex2), min(oy2, ey2)
                    if ix2 > ix1 and iy2 > iy1:
                        y_ov = iy2 - iy1
                        y_min = min(oy2 - oy1, ey2 - ey1)
                        if y_ov / y_min >= 0.4:
                            if (ix2 - ix1) / min(ox2 - ox1, ex2 - ex1) >= 0.3:
                                dup = True
                                break
                if not dup:
                    all_boxes.append((ox1, oy1, ox2, oy2))

    # ── 去重 ──
    all_boxes = [b for b in all_boxes if b[2] - b[0] >= 5 and b[3] - b[1] >= 5]
    merged = []
    for (x1, y1, x2, y2) in all_boxes:
        dup = False
        for (ex1, ey1, ex2, ey2) in merged:
            ix1, iy1 = max(x1, ex1), max(y1, ey1)
            ix2, iy2 = min(x2, ex2), min(y2, ey2)
            if ix2 > ix1 and iy2 > iy1:
                if (ix2 - ix1) * (iy2 - iy1) / ((x2 - x1) * (y2 - y1)) > 0.5:
                    dup = True
                    break
        if not dup:
            merged.append((x1, y1, x2, y2))

    if not merged:
        logger.info("OCR 未检测到任何文本区域")
        return []

    logger.info(f"OCR 检测到 {len(merged)} 个文本区域（去重后）")

    # ── 对每个框识别文字 ──
    chars = []
    for (x1, y1, x2, y2) in merged:
        crop = img[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        crop_gray = _cv2.cvtColor(crop, _cv2.COLOR_BGR2GRAY)

        # 默认：CLAHE 增强
        crop_clahe = _cv2.createCLAHE(clipLimit=1.5,
                                      tileGridSize=(8, 8)).apply(crop_gray)
        _, buf = _cv2.imencode('.png', crop_clahe)
        text = _ocr_recognizer.classification(buf.tobytes())
        text = text.strip() if text else ''

        # 对小字符框：若结果含可疑字母，尝试 OTSU 重新识别
        if text and (y2 - y1) < 55 and re.search(r'[CJIOScjliso]', text):
            _, otsu = _cv2.threshold(crop_gray, 0, 255,
                                     _cv2.THRESH_BINARY + _cv2.THRESH_OTSU)
            _, buf2 = _cv2.imencode('.png', otsu)
            text2 = _ocr_recognizer.classification(buf2.tobytes())
            text2 = text2.strip() if text2 else ''
            if text2 and (text2.isdigit() or not text2.isalpha()):
                text = text2

        if text:
            chars.append({'text': text, 'x': x1, 'y': y1})

    if not chars:
        return []

    # ── 按行合并 ──
    # 行高 = 各框高度中位数；行间距阈值取行高 * 1.2（防止相邻行合并）
    heights = sorted([b[3] - b[1] for b in merged])
    median_h = heights[len(heights) // 2] if heights else 20
    row_threshold = max(int(median_h * 1.0), 15)

    chars.sort(key=lambda c: c['y'])
    rows = []
    current_row = [chars[0]]
    for c in chars[1:]:
        if abs(c['y'] - current_row[-1]['y']) < row_threshold:
            current_row.append(c)
        else:
            rows.append(current_row)
            current_row = [c]
    rows.append(current_row)

    results = []
    for row in rows:
        row.sort(key=lambda c: c['x'])
        line_text = ''.join(c['text'] for c in row)
        y_avg = sum(c['y'] for c in row) // len(row)
        results.append({'text': line_text, 'y': y_avg})

    results.sort(key=lambda r: r['y'])
    logger.info(f"OCR 合并为 {len(results)} 行")
    return results


def _ocr_paddleocr(image_path: str, engine) -> list:
    """使用 PaddleOCR 引擎识别"""
    result = engine.ocr(image_path, cls=True)
    texts = []
    if result and result[0]:
        for line in result[0]:
            text = line[1][0] if len(line) > 1 else ''
            confidence = line[1][1] if len(line) > 1 else 0
            if text.strip():
                texts.append({'text': text.strip(), 'confidence': round(confidence, 4)})
    return texts


# ============ 支付截图解析 — 标签-值结构 ============

# 常见 OCR 误识别映射（中文→数字）
_CHAR_MAP = str.maketrans({
    '一': '1', '二': '2', '三': '3', '四': '4', '五': '5',
    '六': '6', '七': '7', '八': '8', '九': '9', '零': '0',
    'O': '0', 'o': '0',
})

# 标签名映射表（OCR 识别的错字 → 标准标签名）
_LABEL_ALIASES = {
    # ── 支付宝/微信通用 ──
    '支付时间': '支付时间', '付素方式': '付款方式', '付款方式': '付款方式',
    '转贝时间': '支付时间', '转账时间': '支付时间',
    '支付方式': '付款方式',
    '支付奖励': '支付奖励', '收单机松': '收单机构', '收单机构': '收单机构',
    '清机构': '清算机构', '清算机构': '清算机构',
    '收款方尘全称': '收款方全称', '收款方全称': '收款方全称',
    '商户全称': '商户全称', '商家': '商户',
    '交易单号': '交易单号', '商户单号': '商户单号',
    '当前状态': '当前状态',
    # ── 银行截图 ──
    '交易类型': '交易类型', '交易金额': '交易金额',
    '交易对象': '交易对象', '交易摘要': '交易摘要',
    '交易时间': '交易时间', '交易时间2': '交易时间',
    '交易账户': '交易账户', '交易币种': '交易币种',
    '对方账户': '对方账户',
    '账户余额': '账户余额', '可用余额': '可用余额',
}


def _extract_label_value(lines: list) -> list:
    """从识别行中提取标签-值对

    输入: [{'text': '支付时间2026-07-27', ...}, ...]
    输出: [('支付时间', '2026-07-27 11:50:25'), ('收款方全称', 'xxx'), ...]

    支持两种格式：
    1. 标准格式: "标签：值"
    2. 银行格式: "标签值"（无分隔符，适用于交易金额/交易类型等）
    """
    # 从 _LABEL_ALIASES 生成动态正则（所有标签名+别名）
    _all_labels = sorted(set(_LABEL_ALIASES.keys()), key=len, reverse=True)
    _label_pattern = '|'.join(re.escape(l) for l in _all_labels)

    # 银行截图专用标签（值紧跟在标签后，无分隔符）
    _bank_labels = ['交易金额', '交易类型', '交易时间', '交易对象', '交易摘要',
                    '交易币种', '账户余额', '可用余额', '对方账户']

    pairs = []
    for line in lines:
        text = line['text'].strip()

        # 1. 先尝试标准格式：标签(可带别名) + 可选分隔符(：: 或空白)，值紧跟其后
        m = re.match(rf'({_label_pattern})[：:\s]*(.*)', text)
        if m:
            raw_label = m.group(1).strip()
            raw_value = m.group(2).strip()
            label = _LABEL_ALIASES.get(raw_label, raw_label)
            if raw_value:
                pairs.append((label, raw_value))
            continue

        # 2. 银行格式兜底：标签紧接值（防止标签过长导致前面匹配错位）
        for bl in _bank_labels:
            if text.startswith(bl) and len(text) > len(bl):
                value = text[len(bl):]
                label = _LABEL_ALIASES.get(bl, bl)
                if value.strip():
                    pairs.append((label, value.strip()))
                break

    return pairs


def _extract_amount_from_lines(lines: list) -> Optional[float]:
    """从识别行中提取金额

    策略：
    1. 优先找含"金额"标签的行（如"交易金额5C0000"→5000, "金额4000"→4000）
    2. 带 ¥/￥ 的行
    3. 纯数字行（3-4 位无小数点，÷100 得到金额）
    4. 带负号的金额
    """

    def _clean_amount(text: str) -> Optional[float]:
        """从文本中清理并提取金额，返回 None 表示无法提取"""
        # 替换 OCR 常见误识: y/Y→¥, 十→去掉
        cleaned = text.replace('十', '').replace('y', '¥').replace('Y', '¥')

        # 如果原文本有 C/c（千位逗号），按逗号位置拆分
        if 'C' in text or 'c' in text:
            idx = text.lower().index('c')
            before = ''.join(re.findall(r'\d', text[:idx]))
            after = ''.join(re.findall(r'\d', text[idx+1:]))
            if before and after:
                int_part = before + after[:3]
                dec_part = after[3:]
                try:
                    val = float(f"{int_part}.{dec_part}" if dec_part else int_part)
                    if 1.0 < val < 999999:
                        return val
                except ValueError:
                    pass

        # 标准处理：尝试小数金额（¥1234.56 或带小数点的）
        # 要求有实际小数点 "."，或数字较短（≤4位且小于9999）
        m = re.search(r'(?:¥|￥)?(\d+\.\d{1,2})', cleaned)
        if m:
            try:
                v = float(m.group(1))
                if 1.0 <= v < 999999:
                    return v
            except ValueError:
                pass
        # 无小数点的独立短数字（前后都不是数字，且3-4位）
        m = re.search(r'(?:¥|￥)?(?<!\d)(\d{3,4})(?!\d)', cleaned)
        if m:
            try:
                v = float(m.group(1))
                if 1.0 <= v < 9999:
                    return v
            except ValueError:
                pass
        # 去掉所有非数字，再解析
        digits = re.sub(r'[^\d]', '', cleaned)
        if not digits:
            return None
        n = len(digits)
        try:
            val = float(digits)
            if val < 1.0:
                return None  # 过滤 0/00 等无效金额
            if n <= 4:
                if val < 9999:
                    return val
            elif n == 5:
                r = val / 100.0
                if 1.0 <= r < 99999:
                    return r
            elif n >= 6:
                r = float(f"{digits[:-2]}.{digits[-2:]}")
                if 1.0 <= r < 999999:
                    return r
        except ValueError:
            pass
        return None

    # ── 1. 含"金额"标签的行（最可靠） ──
    for line in lines:
        text = line['text'].strip()
        if '金额' not in text:
            continue
        r = _clean_amount(text)
        if r is not None:
            return r

    # ── 2. 带 ¥/￥ 前缀（含 y 误识） — 仅处理包含金额符号的行 ──
    for line in lines:
        text = line['text']
        if '¥' not in text and '￥' not in text and 'y' not in text and 'Y' not in text:
            continue
        text = text.replace('y', '¥').replace('Y', '¥').replace('十', '')
        r = _clean_amount(text)
        if r is not None:
            return r

    # ── 3. 带负号（退款/扣款） ──
    for line in lines:
        text = line['text']
        m = re.search(r'-(\d+(?:\.\d{1,2})?)', text)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass

    # ── 4. 纯数字行（排除余额/时间等干扰） ──
    for line in lines:
        text = line['text'].strip()
        if any(kw in text for kw in ('时间', '单号', '机构', '方式',
                                     '奖励', '状态', '账单', '商家',
                                     '收款', '商户', '商品', '推荐',
                                     '余额', '可用')):
            continue
        cleaned = text.translate(_CHAR_MAP)
        negative = False
        digits_part = cleaned
        if cleaned and cleaned[0] in ('—', '－', '-'):
            negative = True
            digits_part = cleaned[1:].lstrip()
        elif cleaned.startswith('一'):
            negative = True
            digits_part = cleaned[1:].lstrip()

        m = re.match(r'^(\d{3,5})$', digits_part)
        if m:
            try:
                val = float(m.group(1))
                if 100 <= val <= 999:
                    r = val / 100.0
                    if 0.01 < r < 9999:
                        return -r if negative else r
                if 1000 <= val <= 9999:
                    r = val / 100.0
                    if 0.01 < r < 9999:
                        return -r if negative else r
            except ValueError:
                pass

    # ── 5. 兜底：无英文字母的行中搜索独立数字 ──
    for line in lines:
        text = line['text'].strip()
        if re.search(r'[a-zA-Z]', text):
            continue
        if any(kw in text for kw in ('时间', '单号', '机构', '方式',
                                     '奖励', '状态', '账单', '商家',
                                     '收款', '商户', '商品', '推荐',
                                     '余额', '可用')):
            continue
        cleaned = text.translate(_CHAR_MAP)
        m = re.search(r'(?<!\d)(\d{3,5})(?!\d)', cleaned)
        if m:
            try:
                val = float(m.group(1))
                if 0.01 < val < 99999:
                    return val
            except ValueError:
                pass

    return None


def _extract_time_from_lines(lines: list) -> Optional[str]:
    """从识别行中提取支付时间"""
    from datetime import datetime as _dt
    for label, value in lines:
        if label in ('支付时间', '交易时间'):
            v = value.strip()
            # 先用 "年月日" 中文格式正则定位
            m = re.search(r'(\d{4})\s*年\s*(\d*)\s*月\s*(\d{1,2})\s*日', v)
            if m:
                year = m.group(1)
                month_str = m.group(2)
                day = m.group(3).zfill(2)
                if not month_str:
                    month = str(_dt.now().month).zfill(2)
                else:
                    month = month_str.zfill(2)
                rest = v[m.end():]
                nums = re.findall(r'\d+', rest)
                nums_str = ''.join(nums)
                if len(nums_str) >= 4:
                    h, mi, s = nums_str[:2], nums_str[2:4], nums_str[4:6].zfill(2) if len(nums_str) >= 6 else '00'
                else:
                    h, mi, s = '00', '00', '00'
                return f"{year}-{month}-{day} {h.zfill(2)}:{mi.zfill(2)}:{s}"

            # 回退：提取所有数字，按长度解析
            digits_only = re.sub(r'[^\d]', '', v)
            if len(digits_only) >= 8:
                year = digits_only[:4]
                month = digits_only[4:6]
                day = digits_only[6:8]
                rest = digits_only[8:]
                if len(rest) >= 4:
                    h, mi, s = rest[:2], rest[2:4], rest[4:6].zfill(2) if len(rest) >= 6 else '00'
                else:
                    h, mi, s = '00', '00', '00'
                try:
                    mo_i, d_i = int(month), int(day)
                    if 1 <= mo_i <= 12 and 1 <= d_i <= 31:
                        return f"{year}-{month}-{day} {h.zfill(2)}:{mi.zfill(2)}:{s}"
                except ValueError:
                    pass

    # 兜底：在全文中搜索 8-14 位纯数字（解决交易时间含 OCR 噪声）
    for label, value in lines:
        if label not in ('支付时间', '交易时间'):
            continue
        v = value.strip()
        # 替换常见 OCR 噪声：字母全去掉
        cleaned = re.sub(r'[a-zA-Z]', '', v)
        digits = re.sub(r'[^\d]', '', cleaned)
        if len(digits) >= 8:
            # 找第一个合法的日期串（前4位 2000-2099，月1-12，日1-31）
            for start in range(len(digits) - 7):
                candidate = digits[start:start+14] if len(digits[start:]) >= 14 else digits[start:]
                if len(candidate) < 8:
                    continue
                y, m, d = candidate[:4], candidate[4:6], candidate[6:8]
                try:
                    yi, mi, di = int(y), int(m), int(d)
                    if 2000 <= yi <= 2099 and 1 <= mi <= 12 and 1 <= di <= 31:
                        h = candidate[8:10] if len(candidate) >= 10 else '00'
                        mi2 = candidate[10:12] if len(candidate) >= 12 else '00'
                        s = candidate[12:14] if len(candidate) >= 14 else '00'
                        return f"{y}-{m}-{d} {h}:{mi2}:{s}"
                except ValueError:
                    continue
    return None


def _extract_amount_from_pairs(pairs: list, lines: list) -> Optional[float]:
    """综合提取金额"""
    # 先从标签值对找金额（目前无标准金额标签，后续可加）
    # 再从识别行找
    return _extract_amount_from_lines(lines)


def parse_screenshot(texts: list) -> dict:
    """解析支付截图文本，返回结构化交易信息"""
    # 1. 提取标签-值对
    pairs = _extract_label_value(texts)
    logger.info(f"OCR 标签-值对: {pairs}")

    # 2. 构建结果字典
    fields = {label: value for label, value in pairs}

    # 3. 金额
    amount = _extract_amount_from_lines(texts)

    # 4. 交易类型：优先判断支出关键词，避免"收款方"等标签名误触
    bill_type = 'expense'
    full_text = ' '.join([t['text'] for t in texts])
    # 先检查明确的支出关键词
    expense_kw = ('付款', '支付', '消费', '支出', '购买', '转账')
    income_kw = ('收入', '工资', '转入金额', '转入成功', '报销')
    has_expense_kw = any(kw in full_text for kw in expense_kw)
    has_income_kw = any(kw in full_text for kw in income_kw)
    if has_income_kw and not has_expense_kw:
        bill_type = 'income'
    # 既有支出也有收入关键词（如"收款方"是标签而非收入），默认支出
    # 退款和收款成功视为特殊情况
    if '退款' in full_text:
        bill_type = 'income'

    # 5. 收款方（用作科目/商户名）
    merchant = fields.get('收款方全称') or fields.get('商户全称') or fields.get('交易对象') or ''
    # 回退：从未标记的文本中提取"付款给XXX"或"交易对象XXX"
    if not merchant:
        m = re.search(r'付款给(.{2,20}?)(?:\s|$|收款|支付|转账)', full_text)
        if not m:
            m = re.search(r'扫二维码付款给(.{2,20}?)(?:\s|$|收款|支付|转账)', full_text)
        if not m:
            m = re.search(r'交易对象(.{2,20}?)(?:\s|$|交易|摘要)', full_text)
        if m:
            merchant = m.group(1).strip()

    # 6. 付款方式（用作账户）
    account_name = fields.get('付款方式') or fields.get('交易账户') or ''
    # 回退：识别账户类型 + 尾号（尾号即使不准也对别名匹配有用）
    if not account_name:
        _acct_map = {
            '储育账': '储蓄账户', '储畜账': '储蓄账户', '储蓄账': '储蓄账户',
            '储蓄': '储蓄账户', '活期': '活期账户',
            '社保卡': '社保卡', '信用十': '信用卡', '信用': '信用卡',
            '借记卡': '借记卡', '借计卡': '借记卡', '工资卡': '工资卡',
        }
        acct_type = ''
        for ocr_kw, std_name in _acct_map.items():
            if ocr_kw in full_text:
                acct_type = std_name
                break
        # 提取尾号（不管 OCR 读得准不准）
        m = re.search(r'尾号[为是](\d{3,6})', full_text)
        if acct_type and m:
            account_name = f"{acct_type}({m.group(1)})"
        elif m:
            account_name = f"银行账户({m.group(1)})"
        elif acct_type:
            account_name = acct_type

    # 7. 交易时间
    transaction_time = _extract_time_from_lines(pairs)
    # 兜底：直接从原始文本搜索时间
    if not transaction_time:
        for t in texts:
            txt = t['text']
            if '时间' not in txt:
                continue
            # 单字符 OCR 数字纠错（CJ 独立映射为 0/2，不整体替换）
            _ocr_digit_map = str.maketrans({
                'C': '0', 'c': '0',
                'J': '2', 'j': '2',
                'I': '1', 'l': '1',
                'O': '0', 'o': '0',
                'S': '5', 's': '5',
                'Z': '2', 'z': '2',
                'B': '8', 'b': '6',
                'D': '0', 'd': '0',
                '/': '', '-': '',  # 日期分隔符常被丢弃，直接忽略
            })
            cleaned = txt.translate(_ocr_digit_map)
            digits = re.sub(r'[^\d]', '', cleaned)
            # 找"20"开头的最长连续数字，从中提取有效时间
            idx = digits.find('20')
            if idx >= 0:
                chunk = digits[idx:idx+14]
                if len(chunk) >= 8:
                    for start in range(len(chunk) - 7):
                        cand = chunk[start:start+14] if len(chunk[start:]) >= 14 else chunk[start:]
                        if len(cand) < 8:
                            continue
                        try:
                            y, m, d = int(cand[:4]), int(cand[4:6]), int(cand[6:8])
                            if not (2000 <= y <= 2099 and 1 <= m <= 12 and 1 <= d <= 31):
                                continue
                            h = cand[8:10] if len(cand) >= 10 else '00'
                            mi2 = cand[10:12] if len(cand) >= 12 else '00'
                            s2 = cand[12:14] if len(cand) >= 14 else '00'
                            # 校验时/分/秒合理性
                            hi, mi_i, si = int(h), int(mi2), int(s2)
                            if not (0 <= hi <= 23 and 0 <= mi_i <= 59 and 0 <= si <= 59):
                                continue
                            transaction_time = f"{cand[:4]}-{cand[4:6]}-{cand[6:8]} {h}:{mi2}:{s2}"
                            break
                        except ValueError:
                            continue
            if transaction_time:
                break

    result = {
        'bill_type': bill_type,
        'amount': amount,
        'transaction_time': transaction_time,
        'merchant': merchant,
        'account_name': account_name,
        'raw_text': texts,
    }
    return result


def _retry_time_line(image_path: str, texts: list) -> Optional[str]:
    """时间识别失败时，仅对时间行区域用不同预处理重试"""
    import cv2 as _cv2
    import numpy as _np
    global _ocr_recognizer

    time_line = None
    for t in texts:
        if '时间' in t['text'] and '交易' in t['text']:
            time_line = t
            break
    if not time_line:
        return None

    img = _cv2.imread(image_path)
    if img is None:
        return None
    h, w = img.shape[:2]
    y = time_line['y']
    y1 = max(0, y - 5)
    y2 = min(h, y + 45)

    def _try_recognize(roi: _np.ndarray) -> str:
        if roi.size == 0:
            return ''
        _, buf = _cv2.imencode('.png', roi)
        t = _ocr_recognizer.classification(buf.tobytes())
        return t.strip() if t else ''

    def _try_parse_time(text: str) -> Optional[str]:
        if not text:
            return None
        import re
        # 先尝试直接去掉非数字（I/O等字母可能是分隔符）
        digits = re.sub(r'[^\d]', '', text)
        # 再试映射后去非数字
        if not digits or len(digits) < 8:
            _map = str.maketrans({
                'C': '0', 'c': '0', 'J': '2', 'j': '2',
                'I': '1', 'l': '1', 'O': '0', 'o': '0',
                'S': '5', 's': '5', 'Z': '2', 'z': '2',
                'B': '8', 'b': '6', 'D': '0', 'd': '0',
            })
            cleaned = text.translate(_map)
            digits = re.sub(r'[^\d]', '', cleaned)
        idx = digits.find('20')
        if idx < 0:
            return None
        chunk = digits[idx:idx+14]
        if len(chunk) < 8:
            return None
        for start in range(len(chunk) - 7):
            cand = chunk[start:start+14] if len(chunk[start:]) >= 14 else chunk[start:]
            if len(cand) < 8:
                continue
            try:
                y, m, d = int(cand[:4]), int(cand[4:6]), int(cand[6:8])
                if not (2000 <= y <= 2099 and 1 <= m <= 12 and 1 <= d <= 31):
                    continue
                h = cand[8:10] if len(cand) >= 10 else '00'
                mi = cand[10:12] if len(cand) >= 12 else '00'
                s = cand[12:14] if len(cand) >= 14 else '00'
                hi, mii, si = int(h), int(mi), int(s)
                if not (0 <= hi <= 23 and 0 <= mii <= 59 and 0 <= si <= 59):
                    continue
                return f"{cand[:4]}-{cand[4:6]}-{cand[6:8]} {h}:{mi}:{s}"
            except ValueError:
                continue
        return None

    roi = img[y1:y2, :]
    gray = _cv2.cvtColor(roi, _cv2.COLOR_BGR2GRAY)
    clahe = _cv2.createCLAHE(clipLimit=5.0, tileGridSize=(8, 8)).apply(gray)

    for desc, proc in [
        ('CLAHE 3x', _cv2.resize(clahe, None, fx=3, fy=3, interpolation=_cv2.INTER_CUBIC)),
        ('OTSU 3x', _cv2.resize(_cv2.threshold(clahe, 0, 255, _cv2.THRESH_BINARY + _cv2.THRESH_OTSU)[1], None, fx=3, fy=3, interpolation=_cv2.INTER_CUBIC)),
        ('反转 3x', _cv2.resize(_cv2.bitwise_not(clahe), None, fx=3, fy=3, interpolation=_cv2.INTER_CUBIC)),
    ]:
        text = _try_recognize(proc)
        t = _try_parse_time(text)
        if t:
            return t

    return None


def process_image(image_path: str) -> dict:
    """处理图片：OCR识别 + 解析，返回结构化交易数据"""
    texts = ocr_image(image_path)
    if not texts:
        return {
            'success': False,
            'message': '未能从图片中识别到文本',
            'raw_texts': [],
        }
    parsed = parse_screenshot(texts)
    # 时间未识别出时，仅对时间行区域重试
    if not parsed.get('transaction_time'):
        retry_time = _retry_time_line(image_path, texts)
        if retry_time:
            parsed['transaction_time'] = retry_time
    parsed['success'] = True
    parsed['raw_texts'] = texts
    return parsed
