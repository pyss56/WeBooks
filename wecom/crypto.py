#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""企业微信消息加解密模块
参考企业微信官方文档：https://developer.work.weixin.qq.com/document/path/90968
"""
import base64
import hashlib
import random
import string
import struct
import xml.etree.ElementTree as ET

from Crypto.Cipher import AES


class WXBizMsgCrypt:
    """企业微信消息加解密"""

    def __init__(self, token, encoding_aes_key, corp_id):
        """
        :param token: 企业微信后台配置的Token
        :param encoding_aes_key: 企业微信后台配置的EncodingAESKey
        :param corp_id: 企业微信CorpID
        """
        self.token = token
        self.corp_id = corp_id
        # EncodingAESKey 是 base64 编码的，需要解码
        aes_key_base64 = encoding_aes_key + '='
        self.aes_key = base64.b64decode(aes_key_base64)

    def decrypt(self, encrypted_text):
        """
        解密回调消息
        :param encrypted_text: 加密的密文
        :return: 解密后的明文XML
        """
        iv = self.aes_key[:16]
        cipher = AES.new(self.aes_key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(base64.b64decode(encrypted_text))

        # PKCS7 去除填充
        pad_len = decrypted[-1]
        if pad_len < 1 or pad_len > 32:
            pad_len = 0
        decrypted = decrypted[:len(decrypted) - pad_len]

        # 解析结构：16字节随机串 + 4字节消息长度 + 消息内容 + CorpID
        msg_len = struct.unpack('>I', decrypted[16:20])[0]
        msg = decrypted[20:20 + msg_len].decode('utf-8')
        receive_id = decrypted[20 + msg_len:].decode('utf-8')

        if receive_id != self.corp_id:
            raise ValueError(f"CorpID不匹配: 期望 {self.corp_id}, 实际 {receive_id}")

        return msg

    def encrypt(self, reply_msg):
        """
        加密回复消息
        :param reply_msg: 回复的明文XML
        :return: 加密后的密文(base64)
        """
        # 生成16字节随机串
        random_str = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
        msg_bytes = reply_msg.encode('utf-8')
        msg_len = struct.pack('>I', len(msg_bytes))
        corp_id_bytes = self.corp_id.encode('utf-8')

        # 拼接：随机串 + 消息长度 + 消息内容 + CorpID
        raw_bytes = random_str.encode('utf-8') + msg_len + msg_bytes + corp_id_bytes

        # PKCS7 填充
        pad_len = 32 - (len(raw_bytes) % 32)
        if pad_len == 0:
            pad_len = 32
        raw_bytes += bytes([pad_len] * pad_len)

        # AES-CBC 加密
        iv = self.aes_key[:16]
        cipher = AES.new(self.aes_key, AES.MODE_CBC, iv)
        encrypted = cipher.encrypt(raw_bytes)

        return base64.b64encode(encrypted).decode('utf-8')

    def get_signature(self, timestamp, nonce, encrypted):
        """
        生成签名
        """
        sort_list = [self.token, timestamp, nonce, encrypted]
        sort_list.sort()
        sha1 = hashlib.sha1()
        sha1.update(''.join(sort_list).encode('utf-8'))
        return sha1.hexdigest()

    def verify_url(self, msg_signature, timestamp, nonce, echostr):
        """
        验证URL并解密echostr
        :return: 解密后的echostr明文
        """
        # 验证签名
        signature = self.get_signature(timestamp, nonce, echostr)
        if signature != msg_signature:
            raise ValueError("签名验证失败")

        # 解密echostr
        return self.decrypt(echostr)


def parse_xml(xml_str):
    """解析XML字符串为字典"""
    root = ET.fromstring(xml_str)
    result = {}
    for child in root:
        result[child.tag] = child.text
    return result


def build_reply_xml(to_user, from_user, content, nonce, timestamp):
    """构建回复文本消息XML"""
    xml = f"""<xml>
<ToUserName><![CDATA[{to_user}]]></ToUserName>
<FromUserName><![CDATA[{from_user}]]></FromUserName>
<CreateTime>{timestamp}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{content}]]></Content>
</xml>"""
    return xml


def build_encrypted_reply_xml(encrypt, msg_signature, timestamp, nonce):
    """构建加密回复XML"""
    xml = f"""<xml>
<Encrypt><![CDATA[{encrypt}]]></Encrypt>
<MsgSignature><![CDATA[{msg_signature}]]></MsgSignature>
<TimeStamp>{timestamp}</TimeStamp>
<Nonce><![CDATA[{nonce}]]></Nonce>
</xml>"""
    return xml
