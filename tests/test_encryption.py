"""
Tests para el módulo de encriptación.

Issue: #7 - HU12 Configuración de LLM
"""

import os
import pytest
from cryptography.fernet import Fernet

from app.core.encryption import encrypt, decrypt, EncryptionError


class TestEncryptDecrypt:
    """Tests del roundtrip encrypt/decrypt."""

    def test_roundtrip_simple_string(self):
        original = "sk-test123456"
        encrypted = encrypt(original)
        assert encrypted != original
        assert decrypt(encrypted) == original

    def test_roundtrip_with_special_chars(self):
        original = "sk-abc!@#$%^&*()_+-=[]{}|;:',.<>?/~`"
        encrypted = encrypt(original)
        assert decrypt(encrypted) == original

    def test_roundtrip_with_unicode(self):
        original = "🔐 API key con ñ y emojis 中文"
        encrypted = encrypt(original)
        assert decrypt(encrypted) == original

    def test_roundtrip_long_string(self):
        original = "x" * 1000
        encrypted = encrypt(original)
        assert len(encrypted) > 0
        assert decrypt(encrypted) == original

    def test_encrypt_produces_different_output_each_time(self):
        """Fernet incluye IV aleatorio, no debe ser determinístico."""
        plaintext = "test"
        enc1 = encrypt(plaintext)
        enc2 = encrypt(plaintext)
        assert enc1 != enc2
        # Pero ambos desencriptan al mismo valor
        assert decrypt(enc1) == plaintext
        assert decrypt(enc2) == plaintext


class TestEncryptErrors:
    """Tests de errores al encriptar."""

    def test_encrypt_empty_string_raises(self):
        with pytest.raises(EncryptionError, match="vacío"):
            encrypt("")

    def test_encrypt_without_key_raises(self):
        os.environ.pop("ENCRYPTION_KEY", None)
        with pytest.raises(EncryptionError, match="ENCRYPTION_KEY"):
            encrypt("test")

    def test_encrypt_with_invalid_key_raises(self):
        os.environ["ENCRYPTION_KEY"] = "esto-no-es-una-clave-valida"
        with pytest.raises(EncryptionError, match="inválida"):
            encrypt("test")


class TestDecryptErrors:
    """Tests de errores al desencriptar."""

    def test_decrypt_empty_string_raises(self):
        with pytest.raises(EncryptionError, match="vacío"):
            decrypt("")

    def test_decrypt_without_key_raises(self):
        os.environ.pop("ENCRYPTION_KEY", None)
        with pytest.raises(EncryptionError, match="ENCRYPTION_KEY"):
            decrypt("cualquier_cosa")

    def test_decrypt_with_wrong_key_raises(self):
        """Si la clave cambia, no se puede desencriptar."""
        original_encrypted = encrypt("secret")
        # Cambiamos la clave a otra nueva
        os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        with pytest.raises(EncryptionError, match="desencriptar"):
            decrypt(original_encrypted)

    def test_decrypt_corrupted_data_raises(self):
        with pytest.raises(EncryptionError):
            decrypt("esto-no-es-un-ciphertext-valido")

    def test_decrypt_random_string_raises(self):
        # Generamos un Fernet válido pero con otro contenido
        other_encrypted = encrypt("diferente")
        with pytest.raises(EncryptionError):
            decrypt("diferente_no_encrypted")
