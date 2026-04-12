"""
firebase_client.py — Khởi tạo Firebase Admin SDK và gửi FCM push notification.

Cần thiết lập:
  1. Tạo project trên https://console.firebase.google.com
  2. Project Settings → Service accounts → Generate new private key → tải file JSON
  3. Đặt file JSON vào thư mục project (ví dụ: firebase_credentials.json)
  4. Set biến môi trường: FIREBASE_CREDENTIALS_JSON=firebase_credentials.json
     Hoặc đổi tên file thành đúng tên mặc định bên dưới.
"""

import os
import logging

logger = logging.getLogger(__name__)

_CREDENTIAL_PATH = os.getenv("FIREBASE_CREDENTIALS_JSON", "firebase_credentials.json")
_initialized = False


def _init():
    global _initialized
    if _initialized:
        return
    try:
        import firebase_admin
        from firebase_admin import credentials
        try:
            firebase_admin.get_app()
        except ValueError:
            if not os.path.isfile(_CREDENTIAL_PATH):
                raise FileNotFoundError(
                    f"Firebase credentials không tìm thấy tại '{_CREDENTIAL_PATH}'. "
                    "Đặt biến môi trường FIREBASE_CREDENTIALS_JSON hoặc đặt file "
                    "firebase_credentials.json vào thư mục gốc của project."
                )
            cred = credentials.Certificate(_CREDENTIAL_PATH)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin SDK đã khởi tạo.")
        _initialized = True
    except ImportError:
        raise ImportError("Thiếu thư viện firebase-admin. Chạy: pip install firebase-admin")


def send_notification(token: str, title: str, body: str) -> bool:
    """
    Gửi FCM push notification đến device token.
    Trả về True nếu thành công, False nếu thất bại.
    """
    _init()
    try:
        from firebase_admin import messaging
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            token=token,
            android=messaging.AndroidConfig(priority="high"),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound="default")
                )
            ),
        )
        response = messaging.send(message)
        logger.info(f"FCM gửi thành công: {response}")
        return True
    except Exception as exc:
        logger.error(f"FCM gửi thất bại: {exc}")
        return False
