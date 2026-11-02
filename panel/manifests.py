"""Strict, dry-run-only application definition schema.

This module does not execute or render Docker commands. Reject unknown fields,
host networking, bind mounts, privileged options, secrets, and mutable image tags.
"""
from pydantic import BaseModel, ConfigDict, Field, field_validator
import re

DIGEST = re.compile(r"^[a-z0-9][a-z0-9._:/-]*@sha256:[0-9a-f]{64}$")
SLUG = re.compile(r"^[a-z][a-z0-9-]{1,47}$")


class ServiceDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=2, max_length=72)
    slug: str = Field(min_length=2, max_length=48)
    image: str = Field(min_length=72, max_length=320)
    container_port: int = Field(ge=1, le=65535)
    cpu_limit: float = Field(default=1.0, ge=0.1, le=8.0)
    memory_mb: int = Field(default=512, ge=64, le=16384)
    read_only_rootfs: bool = True

    @field_validator("slug")
    @classmethod
    def valid_slug(cls, value):
        if not SLUG.fullmatch(value):
            raise ValueError("Expected a lowercase, hyphenated slug")
        return value

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        if value != value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("Name must be printable and have no surrounding whitespace")
        return value

    @field_validator("image")
    @classmethod
    def image_digest_only(cls, value):
        if not DIGEST.fullmatch(value):
            raise ValueError("Use a container image pinned to an immutable sha256 digest")
        return value

    @field_validator("read_only_rootfs")
    @classmethod
    def require_readonly(cls, value):
        if value is not True:
            raise ValueError("Draft services must use a read-only root filesystem")
        return value
