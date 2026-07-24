"""企业微信加解密模块"""
import hashlib
import struct
import time
import base64
import xml.etree.ElementTree as ET
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding


class WeChatWorkCrypto:
    """企业微信消息加解密"""

    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        self.token = token
        self.corp_id = corp_id
        aes_key = base64.b64decode(encoding_aes_key + "=")
        self.aes_key = aes_key

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echo_str: str) -> str:
        if not self._verify_signature(msg_signature, timestamp, nonce, echo_str):
            raise ValueError("Signature verification failed")
        plain_text = self._decrypt(echo_str)
        msg_len = struct.unpack(">I", plain_text[16:20])[0]
        msg_content = plain_text[20:20 + msg_len].decode("utf-8")
        recv_corp_id = plain_text[20 + msg_len:].decode("utf-8")
        if recv_corp_id != self.corp_id:
            raise ValueError("Corp ID mismatch")
        return msg_content

    def decrypt_message(self, msg_signature: str, timestamp: str,
                        nonce: str, encrypted_xml: str) -> str:
        if not self._verify_signature(msg_signature, timestamp, nonce, encrypted_xml):
            raise ValueError("Signature verification failed")
        root = ET.fromstring(encrypted_xml)
        encrypt_node = root.find("Encrypt")
        if encrypt_node is None or encrypt_node.text is None:
            raise ValueError("No Encrypt node found in XML")
        encrypt_text = encrypt_node.text
        plain_text = self._decrypt(encrypt_text)
        msg_len = struct.unpack(">I", plain_text[16:20])[0]
        msg_content = plain_text[20:20 + msg_len].decode("utf-8")
        recv_corp_id = plain_text[20 + msg_len:].decode("utf-8")
        if recv_corp_id != self.corp_id:
            raise ValueError("Corp ID mismatch")
        return msg_content

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
        unpadder = padding.PKCS7(128).unpadder()
        return unpadder.update(decrypted) + unpadder.finalize()
