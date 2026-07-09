"""Credential CRUD service — encrypt/decrypt secrets with AES-256-GCM.

Stores credentials in the ``credentials`` MongoDB collection. Sensitive data
is encrypted before storage and decrypted on demand only (never in list
responses).
"""
from __future__ import annotations

import json
from typing import Any

from loguru import logger

from app.core.crypto import (
    decrypt_secret,
    encrypt_secret,
    get_encryption_key,
    mask_secret,
)
from app.db.mongodb import get_database
from app.models.credential import Credential

COLLECTION = "credentials"


class CredentialService:
    @staticmethod
    async def create_credential(
        *,
        user_id: str,
        name: str,
        type: str,
        data: dict[str, Any],
    ) -> dict:
        """Create and store an encrypted credential.

        Args:
            user_id: Owner user ID.
            name: Human-readable name.
            type: Credential type (api_key/bearer/basic/oauth2).
            data: Secret payload dict, e.g. {"token": "ghp_xxx"}.
        """
        master_key = get_encryption_key()
        encrypted = encrypt_secret(json.dumps(data, ensure_ascii=False), master_key)

        cred = Credential(
            user_id=user_id,
            name=name,
            type=type,
            credential_data_encrypted=encrypted,
        )
        doc = cred.model_dump(by_alias=True)
        db = get_database()
        await db[COLLECTION].insert_one(doc)
        logger.info("credential_created", user_id=user_id, name=name)
        return doc

    @staticmethod
    async def list_credentials(user_id: str) -> list[dict]:
        """List all credentials for a user (masked, no plaintext)."""
        db = get_database()
        cursor = db[COLLECTION].find({"user_id": user_id}).sort("created_at", -1)
        docs = await cursor.to_list(100)
        return [CredentialService._to_masked_response(d) for d in docs]

    @staticmethod
    async def get_credential(credential_id: str, user_id: str) -> dict | None:
        """Get a single credential (masked response)."""
        db = get_database()
        doc = await db[COLLECTION].find_one({"_id": credential_id, "user_id": user_id})
        if doc is None:
            return None
        return CredentialService._to_masked_response(doc)

    @staticmethod
    async def decrypt_credential(credential_id: str) -> dict[str, Any] | None:
        """Decrypt and return the plaintext payload.

        This is the method called by ToolBuilder at runtime to inject
        credentials into tool execution.
        """
        db = get_database()
        doc = await db[COLLECTION].find_one({"_id": credential_id})
        if doc is None:
            return None
        encrypted = doc.get("credential_data_encrypted", "")
        if not encrypted:
            return {}
        master_key = get_encryption_key()
        plaintext = decrypt_secret(encrypted, master_key)
        return json.loads(plaintext)

    @staticmethod
    async def delete_credential(credential_id: str, user_id: str) -> bool:
        """Delete a credential. Returns True if deleted."""
        db = get_database()
        result = await db[COLLECTION].delete_one({"_id": credential_id, "user_id": user_id})
        if result.deleted_count:
            logger.info("credential_deleted", credential_id=credential_id, user_id=user_id)
        return result.deleted_count > 0

    @staticmethod
    async def is_referenced(credential_id: str) -> bool:
        """Check if any tool references this credential."""
        db = get_database()
        count = await db["tools"].count_documents({"credential_id": credential_id})
        return count > 0

    @staticmethod
    def _to_masked_response(doc: dict) -> dict:
        """Convert a DB doc to a masked API response (no plaintext)."""
        encrypted = doc.get("credential_data_encrypted", "")
        masked_data: dict[str, str] = {}
        if encrypted:
            try:
                master_key = get_encryption_key()
                plaintext = decrypt_secret(encrypted, master_key)
                data = json.loads(plaintext)
                masked_data = {k: mask_secret(str(v)) for k, v in data.items()}
            except Exception:
                masked_data = {"error": "***"}

        return {
            "_id": doc["_id"],
            "user_id": doc.get("user_id", ""),
            "name": doc.get("name", ""),
            "type": doc.get("type", "api_key"),
            "masked_data": masked_data,
            "created_at": doc.get("created_at", ""),
        }
