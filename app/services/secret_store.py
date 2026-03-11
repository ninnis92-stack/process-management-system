"""Secret retrieval abstraction supporting Vault, AWS Secrets Manager, and env fallback.

Provides `resolve_secret_ref(ref)` which accepts either:
- a string like "env:NAME" to read from environment
- a dict like {"vault": "path#key"} to read from Vault
- a dict like {"aws_secrets_manager": "secret-name"} to read from AWS Secrets Manager

Falls back to environment variables for resilience in developer environments.
"""
from __future__ import annotations

import os
from typing import Any


def resolve_secret_ref(ref: Any) -> str | None:
    """Resolve a secret reference to a string value or None.

    Examples:
      - "env:MY_SECRET" -> os.getenv('MY_SECRET')
      - {"vault": "secret/path#key"}
      - {"aws_secrets_manager": "my-secret-name"}
    """
    if not ref:
        return None

    # simple env:NAME string or raw string value
    if isinstance(ref, str):
        if ref.startswith("env:"):
            return os.getenv(ref.split("env:", 1)[1])
        return ref

    if isinstance(ref, dict):
        # HashiCorp Vault KV v2
        if "vault" in ref:
            path = str(ref.get("vault") or "")
            if "#" in path:
                p, key = path.split("#", 1)
            else:
                p, key = path, None
            try:
                import hvac

                client = hvac.Client(url=os.getenv("VAULT_ADDR"))
                token = os.getenv("VAULT_TOKEN")
                if token:
                    client.token = token
                data = client.secrets.kv.v2.read_secret_version(path=p)
                vals = data.get("data", {}).get("data", {})
                if key:
                    return vals.get(key)
                return next(iter(vals.values())) if vals else None
            except Exception:
                # fallback: try env var naming convention
                env_key = (path or "").replace("/", "_").upper()
                return os.getenv(env_key)

        # AWS Secrets Manager
        if "aws_secrets_manager" in ref:
            name = str(ref.get("aws_secrets_manager") or "")
            try:
                import boto3

                client = boto3.client("secretsmanager")
                resp = client.get_secret_value(SecretId=name)
                if "SecretString" in resp and resp["SecretString"]:
                    return resp["SecretString"]
                if "SecretBinary" in resp:
                    return resp["SecretBinary"]
            except Exception:
                env_key = name.replace("/", "_").upper()
                return os.getenv(env_key)

    return None
