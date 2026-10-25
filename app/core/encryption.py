"""
Encriptación de API keys usando Fernet.

Issue: #7 - HU12 Configuración de LLM
"""

import os
from cryptography.fernet import Fernet, InvalidToken


# Excepción específica para errores de encriptación
class EncryptionError(Exception):
    """Error al encriptar/desencriptar datos sensibles."""
    pass


def _get_cipher() -> Fernet:
    """
    Obtiene una instancia de Fernet usando ENCRYPTION_KEY del entorno.

    Raises:
        EncryptionError: si ENCRYPTION_KEY no está configurada o es inválida.
    """
    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        raise EncryptionError(
            "ENCRYPTION_KEY no está configurada. "
            "Ejecuta: python scripts/generate_encryption_key.py"
        )
    try:
        return Fernet(key.encode())
    except Exception as e:
        raise EncryptionError(f"ENCRYPTION_KEY inválida: {e}")


def encrypt(plaintext: str) -> str:
    """
    Encripta un string usando Fernet.

    Args:
        plaintext: texto plano a encriptar (ej: API key)

    Returns:
        String encriptado en base64 (safe para guardar en DB)

    Raises:
        EncryptionError: si no se puede encriptar
    """
    if not plaintext:
        raise EncryptionError("No se puede encriptar un string vacío")
    try:
        cipher = _get_cipher()
        encrypted = cipher.encrypt(plaintext.encode())
        return encrypted.decode()
    except EncryptionError:
        raise
    except Exception as e:
        raise EncryptionError(f"Error al encriptar: {e}")


def decrypt(ciphertext: str) -> str:
    """
    Desencripta un string previamente encriptado con encrypt().

    Args:
        ciphertext: string encriptado (de encrypt())

    Returns:
        Texto plano original

    Raises:
        EncryptionError: si no se puede desencriptar (clave incorrecta o dato corrupto)
    """
    if not ciphertext:
        raise EncryptionError("No se puede desencriptar un string vacío")
    try:
        cipher = _get_cipher()
        decrypted = cipher.decrypt(ciphertext.encode())
        return decrypted.decode()
    except InvalidToken:
        raise EncryptionError(
            "No se pudo desencriptar. La ENCRYPTION_KEY puede haber cambiado."
        )
    except EncryptionError:
        raise
    except Exception as e:
        raise EncryptionError(f"Error al desencriptar: {e}")
