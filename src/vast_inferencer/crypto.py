from cryptography.fernet import Fernet, InvalidToken

from vast_inferencer.config import get_settings, remember_secret


def encrypt_secret(value: str) -> str:
    token = _fernet().encrypt(value.encode())
    return token.decode()


def decrypt_secret(token: str) -> str:
    try:
        value = _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise RuntimeError("Failed to decrypt stored secret") from None
    remember_secret(value)
    return value


def _fernet() -> Fernet:
    key = get_settings().secrets_encryption_key.get_secret_value().encode()
    return Fernet(key)
