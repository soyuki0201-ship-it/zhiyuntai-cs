"""企业微信 / 微信客服 加解密模块

同一套算法家族（SHA1 签名 + AES-256-CBC + PKCS#7 + 43位 EncodingAESKey），
企微自建应用和微信客服共用此密码学内核，但需各自用独立的 Token/EncodingAESKey 初始化实例。

通用类 WecomMsgCrypto：适用于企微、微信客服、微信公众号等所有使用该算法的场景。
WeChatWorkCrypto：保留为别名，向后兼容。
"""
import hashlib
import struct
import time
import base64
import xml.etree.ElementTree as ET
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding


class WecomMsgCrypto:
    """企微体系通用加解密工具

    适用于企业微信自建应用、微信客服（WeChat KF）、微信公众号等所有使用
    "SHA1 签名 + AES-256-CBC + PKCS#7 + 43位 EncodingAESKey" 算法的场景。

    初始化参数各自独立，不同场景使用不同实例：
    - 企微自建应用：token/encoding_aes_key/corp_id
    - 微信客服：token/encoding_aes_key/corp_id（与企微同一家企业）
    - 微信公众号：token/encoding_aes_key/appid（与企微不同，receive_id 为 appid）

    Args:
        token: 回调配置中的 Token
        encoding_aes_key: 回调配置中的 EncodingAESKey（43位）
        receive_id: 接收方标识（企微/微信客服为 corpid，公众号为 appid）
    """

    def __init__(self, token: str, encoding_aes_key: str, receive_id: str):
        self.token = token
        self.receive_id = receive_id
        aes_key = base64.b64decode(encoding_aes_key + "=")
        self.aes_key = aes_key

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echo_str: str) -> str:
        """处理回调 URL 验证（GET 请求）"""
        if not self._verify_signature(msg_signature, timestamp, nonce, echo_str):
            raise ValueError("Signature verification failed")
        plain_text = self._decrypt(echo_str)
        msg_len = struct.unpack(">I", plain_text[16:20])[0]
        msg_content = plain_text[20:20 + msg_len].decode("utf-8")
        # 精确截取 receive_id（长度 = self.receive_id 长度），忽略尾部 padding
        recv_id = plain_text[20 + msg_len:20 + msg_len + len(self.receive_id)].decode("utf-8")
        if recv_id != self.receive_id:
            raise ValueError("Receive ID mismatch")
        return msg_content

    def decrypt_message(self, msg_signature: str, timestamp: str,
                        nonce: str, encrypted_xml: str) -> str:
        """解密回调消息（POST 请求）"""
        root = ET.fromstring(encrypted_xml)
        encrypt_node = root.find("Encrypt")
        if encrypt_node is None or encrypt_node.text is None:
            raise ValueError("No Encrypt node found in XML")
        encrypt_text = encrypt_node.text
        if not self._verify_signature(msg_signature, timestamp, nonce, encrypt_text):
            raise ValueError("Signature verification failed")
        plain_text = self._decrypt(encrypt_text)
        msg_len = struct.unpack(">I", plain_text[16:20])[0]
        msg_content = plain_text[20:20 + msg_len].decode("utf-8")
        # 精确截取 receive_id（长度 = self.receive_id 长度），忽略尾部 padding
        recv_id = plain_text[20 + msg_len:20 + msg_len + len(self.receive_id)].decode("utf-8")
        if recv_id != self.receive_id:
            raise ValueError("Receive ID mismatch")
        return msg_content

    def encrypt_message(self, reply_msg: str, nonce: str, timestamp: str) -> str:
        """加密回复消息并生成 XML

        用于微信客服等场景，将回复内容加密后返回 XML 格式响应。

        Args:
            reply_msg: 明文回复内容
            nonce: 随机字符串
            timestamp: 时间戳字符串

        Returns:
            str: 加密后的 XML 字符串
        """
        # 构造明文包：random(16B) + msg_len(4B) + msg + receive_id
        rand_bytes = struct.pack(">I", int(time.time())) + b"\x00" * 12
        msg_bytes = reply_msg.encode("utf-8")
        msg_len = struct.pack(">I", len(msg_bytes))
        receive_id_bytes = self.receive_id.encode("utf-8")
        plain_text = rand_bytes + msg_len + msg_bytes + receive_id_bytes

        # PKCS#7 填充
        padder = padding.PKCS7(128).padder()
        padded = padder.update(plain_text) + padder.finalize()

        # AES 加密
        cipher = Cipher(algorithms.AES(self.aes_key), modes.CBC(self.aes_key[:16]))
        encryptor = cipher.encryptor()
        encrypted = encryptor.update(padded) + encryptor.finalize()
        encrypt_text = base64.b64encode(encrypted).decode("utf-8")

        # 构造 XML
        signature = self._generate_signature(timestamp, nonce, encrypt_text)
        xml = f"""<xml>
<Encrypt><![CDATA[{encrypt_text}]]></Encrypt>
<MsgSignature><![CDATA[{signature}]]></MsgSignature>
<TimeStamp><![CDATA[{timestamp}]]></TimeStamp>
<Nonce><![CDATA[{nonce}]]></Nonce>
</xml>"""
        return xml

    def _verify_signature(self, msg_signature: str, timestamp: str,
                          nonce: str, msg: str) -> bool:
        expected = self._generate_signature(timestamp, nonce, msg)
        return expected == msg_signature

    def _generate_signature(self, timestamp: str, nonce: str, msg: str) -> str:
        sort_list = sorted([self.token, timestamp, nonce, msg])
        content = "".join(sort_list)
        return hashlib.sha1(content.encode("utf-8")).hexdigest()

    def _decrypt(self, encrypted_text: str) -> bytes:
        encrypted = base64.b64decode(encrypted_text)
        cipher = Cipher(algorithms.AES(self.aes_key), modes.CBC(self.aes_key[:16]))
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(encrypted) + decryptor.finalize()
        # 先尝试标准 PKCS7 unpadding（兼容标准实现）
        try:
            unpadder = padding.PKCS7(128).unpadder()
            return unpadder.update(decrypted) + unpadder.finalize()
        except ValueError:
            # PKCS7 失败：企微实际使用空格(0x20)填充而非标准PKCS7
            # 这是因为企微在 receive_id 之后用空格填充到 AES 块大小倍数
            # cryptography 库的 PKCS7 校验严格（padding长度≤16），会拒绝这种padding
            # 去除末尾的空格填充（安全：企微明文末尾是 receive_id，不含尾部空格）
            return decrypted.rstrip(b'\x20')


# 保留别名，向后兼容
WeChatWorkCrypto = WecomMsgCrypto
