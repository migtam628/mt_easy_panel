"""Canonical, narrowly scoped local deployment request authentication.

The Ed25519 *remote host identity* protocol remains separate. These HMAC
requests only authenticate a loopback control-plane -> local agent operation,
using a dedicated lab execution secret, never the browser session.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from panel.manifests import ServiceDraft

HEX32 = re.compile(r"[0-9a-f]{32}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class LocalAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    job_id: str
    draft_id: str
    operation: Literal["deploy", "start", "stop", "restart"]
    issued_at: int = Field(ge=1)
    nonce: str
    manifest: ServiceDraft | None = None

    @field_validator("job_id", "draft_id", "nonce")
    @classmethod
    def strict_identifiers(cls, value: str) -> str:
        if not HEX32.fullmatch(value):
            raise ValueError("Expected 32 lowercase hexadecimal characters")
        return value

    @model_validator(mode="after")
    def action_manifest(self):
        if self.operation == "deploy" and self.manifest is None:
            raise ValueError("Deployment requires the immutable draft manifest")
        if self.operation != "deploy" and self.manifest is not None:
            raise ValueError("Lifecycle operations cannot change manifests")
        return self


def canonical(action: LocalAction) -> bytes:
    return b"mtpanel-local-action-v1\n" + json.dumps(
        action.model_dump(mode="json"), sort_keys=True,
        separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")


def sign_action(key: str, action: LocalAction) -> str:
    if len(key) < 32:
        raise ValueError("Dedicated execution key must have at least 32 characters")
    return hmac.new(key.encode(), canonical(action), hashlib.sha256).hexdigest()


def verify_action(key: str, action: LocalAction, signature: str) -> bool:
    return bool(HEX64.fullmatch(signature)) and hmac.compare_digest(
        sign_action(key, action), signature
    )
