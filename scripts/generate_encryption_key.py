#!/usr/bin/env python3
"""
Genera una clave Fernet para encriptar API keys de LLM.

Uso:
    python scripts/generate_encryption_key.py

Copia el output a tu archivo .env como ENCRYPTION_KEY=...
"""

from cryptography.fernet import Fernet


def generate_key() -> str:
    """Genera una clave Fernet nueva."""
    return Fernet.generate_key().decode()


if __name__ == "__main__":
    key = generate_key()
    print("=" * 60)
    print("Clave Fernet generada. Agrega esto a tu archivo .env:")
    print("=" * 60)
    print()
    print(f"ENCRYPTION_KEY={key}")
    print()
    print("=" * 60)
    print("IMPORTANTE:")
    print("- Guarda esta clave en un lugar SEGURO (1Password, vault)")
    print("- Si pierdes esta clave, NO se podran desencriptar las API keys")
    print("- NO commitees el archivo .env al repo")
