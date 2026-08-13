"""企微加解密 边界矩阵测试

覆盖 crypto.decrypt_message / verify_url / encrypt_message 的各种边界：
- padding 变体：标准PKCS7 / 空格pad / 0x00 pad / 混合pad / 无pad(正好对齐)
- 消息长度边界：空消息 / 1字节 / 恰好16倍数 / 长消息 / 中文多字节
- receive_id 校验：正确 / 错误
- 签名校验：正确 / 错误
"""
import os
import sys
import types
import hashlib
import struct
import base64

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# stub 重依赖
for _name in ("sentence_transformers", "paddleocr", "apscheduler"):
    _m = types.ModuleType(_name)
    sys.modules[_name] = _m
class _FakeBackgroundScheduler:
    def start(self, *a, **k): pass
_s = types.ModuleType("apscheduler.schedulers")
_s2 = types.ModuleType("apscheduler.schedulers.background")
_s2.BackgroundScheduler = _FakeBackgroundScheduler
_s.background = _s2
sys.modules["apscheduler.schedulers"] = _s
sys.modules["apscheduler.schedulers.background"] = _s2

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from app.platforms.wechat_work.crypto import WecomMsgCrypto

TOKEN = "test_token_123456"
AES_KEY = "o82DPywEqN72TznzsoZui2pmdQwXzBa4Xr31Ee3pghz"
CORP_ID = "wwdb0952725fbeeb19"


def _encrypt(plain, aes_key, pad_mode):
    """按指定 padding 模式加密"""
    mb = plain.encode("utf-8")
    body = os.urandom(16) + struct.pack(">I", len(mb)) + mb + CORP_ID.encode("utf-8")
    if pad_mode == "pkcs7":
        from cryptography.hazmat.primitives import padding as crypto_pad
        padder = crypto_pad.PKCS7(128).padder()
        padded = padder.update(body) + padder.finalize()
    elif pad_mode == "space":
        pad = 16 - (len(body) % 16)
        padded = body + b"\x20" * pad
    elif pad_mode == "zero":
        pad = 16 - (len(body) % 16)
        padded = body + b"\x00" * pad
    elif pad_mode == "mixed":
        pad = 16 - (len(body) % 16)
        padded = body + b"\x20" * (pad - 1) + b"\x00"
    elif pad_mode == "exact":  # 无pad（恰好对齐）
        # 调整 body 长度使其恰好 16 倍数
        needed = (-len(body)) % 16
        body = body + b"\x20" * needed
        # 重新计算 msg_len 使明文长度恰好16倍数且无多余pad
        padded = body
    else:
        raise ValueError(f"unknown pad: {pad_mode}")
    c = Cipher(algorithms.AES(aes_key), modes.CBC(aes_key[:16]))
    e = c.encryptor()
    return base64.b64encode(e.update(padded) + e.finalize()).decode()


def _sign(token, ts, nonce, msg):
    return hashlib.sha1("".join(sorted([token, ts, nonce, msg])).encode()).hexdigest()


def _msg_xml(content):
    return (f"<xml><ToUserName><![CDATA[{CORP_ID}]]></ToUserName>"
            f"<FromUserName><![CDATA[19147955655]]></FromUserName>"
            f"<Content><![CDATA[{content}]]></Content>"
            f"<MsgId>123456</MsgId><AgentID>1000037</AgentID></xml>")


class TestCryptoPaddingMatrix:
    """不同 padding 变体都能正确解密"""

    @pytest.mark.parametrize("pad_mode", ["pkcs7", "space", "zero", "mixed", "exact"])
    def test_all_padding_modes_decrypt(self, pad_mode):
        crypto = WecomMsgCrypto(TOKEN, AES_KEY, CORP_ID)
        key = base64.b64decode(AES_KEY + "=")
        xml = _msg_xml("padding测试消息")
        enc = _encrypt(xml, key, pad_mode)
        ts, nonce = "1786529844", "1786724575"
        sig = _sign(TOKEN, ts, nonce, enc)
        wrapped = f"<xml><Encrypt><![CDATA[{enc}]]></Encrypt></xml>"
        plain = crypto.decrypt_message(sig, ts, nonce, wrapped)
        assert plain == xml, f"[{pad_mode}] 解密结果不对:\n{plain}"


class TestCryptoMessageSizes:
    """不同消息长度的边界"""

    @pytest.mark.parametrize("content", [
        "",               # 空消息
        "a",              # 1字节
        "a" * 15,         # 15字节
        "a" * 16,         # 恰好16字节
        "a" * 17,         # 17字节
        "中文测试内容" * 10,  # 多字节中文
        "x" * 1000,       # 长消息
    ])
    def test_message_sizes(self, content):
        crypto = WecomMsgCrypto(TOKEN, AES_KEY, CORP_ID)
        key = base64.b64decode(AES_KEY + "=")
        xml = _msg_xml(content)
        enc = _encrypt(xml, key, "space")
        ts, nonce = "1786529844", "1786724575"
        sig = _sign(TOKEN, ts, nonce, enc)
        wrapped = f"<xml><Encrypt><![CDATA[{enc}]]></Encrypt></xml>"
        plain = crypto.decrypt_message(sig, ts, nonce, wrapped)
        assert plain == xml, f"长度[{len(content)}] 解密结果不对"


class TestCryptoSignatureAndReceiveId:
    """签名错误 / receive_id 错误 → 明确异常"""

    def test_bad_signature_raises(self):
        crypto = WecomMsgCrypto(TOKEN, AES_KEY, CORP_ID)
        key = base64.b64decode(AES_KEY + "=")
        enc = _encrypt(_msg_xml("签名测试"), key, "space")
        wrapped = f"<xml><Encrypt><![CDATA[{enc}]]></Encrypt></xml>"
        with pytest.raises(ValueError, match="Signature"):
            crypto.decrypt_message("wrongsig", "1", "2", wrapped)

    def test_wrong_receive_id_raises(self):
        # 用不同 corp_id 加密（接收方不匹配）
        crypto = WecomMsgCrypto(TOKEN, AES_KEY, CORP_ID)
        key = base64.b64decode(AES_KEY + "=")
        mb = _msg_xml("receive测试").encode("utf-8")
        body = os.urandom(16) + struct.pack(">I", len(mb)) + mb + "ww_wrong_corp_12345".encode("utf-8")
        pad = 16 - (len(body) % 16)
        padded = body + b"\x20" * pad
        c = Cipher(algorithms.AES(key), modes.CBC(key[:16]))
        e = c.encryptor()
        enc = base64.b64encode(e.update(padded) + e.finalize()).decode()
        wrapped = f"<xml><Encrypt><![CDATA[{enc}]]></Encrypt></xml>"
        with pytest.raises(ValueError, match="Receive ID mismatch"):
            crypto.decrypt_message(_sign(TOKEN, "1", "2", enc), "1", "2", wrapped)

    def test_no_encrypt_node_raises(self):
        crypto = WecomMsgCrypto(TOKEN, AES_KEY, CORP_ID)
        with pytest.raises(ValueError, match="No Encrypt node"):
            crypto.decrypt_message("s", "1", "2", "<xml><foo>bar</foo></xml>")

    def test_verify_url_roundtrip(self):
        """URL 验证 echostr 往返"""
        crypto = WecomMsgCrypto(TOKEN, AES_KEY, CORP_ID)
        key = base64.b64decode(AES_KEY + "=")
        echo = "random_echo_abc123"
        mb = echo.encode("utf-8")
        body = os.urandom(16) + struct.pack(">I", len(mb)) + mb + CORP_ID.encode("utf-8")
        pad = 16 - (len(body) % 16)
        padded = body + b"\x20" * pad
        c = Cipher(algorithms.AES(key), modes.CBC(key[:16]))
        e = c.encryptor()
        echostr = base64.b64encode(e.update(padded) + e.finalize()).decode()
        sig = _sign(TOKEN, "1786529844", "1786724575", echostr)
        result = crypto.verify_url(sig, "1786529844", "1786724575", echostr)
        assert result == echo

    def test_encrypt_decrypt_roundtrip_pkcs7(self):
        """encrypt_message → decrypt_message 往返（自洽）"""
        crypto = WecomMsgCrypto(TOKEN, AES_KEY, CORP_ID)
        reply = "这是AI回复内容"
        xml = crypto.encrypt_message(reply, "nonce123", "1786529844")
        # 从返回 XML 提取并解密
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml)
        enc = root.find("Encrypt").text
        sig = root.find("MsgSignature").text
        ts = root.find("TimeStamp").text
        nonce = root.find("Nonce").text
        # decrypt_message 需要完整 wrapped xml
        plain = crypto.decrypt_message(sig, ts, nonce, xml)
        assert plain == reply
