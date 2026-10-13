"""Content-free, capability-based deployment checks (not release acceptance)."""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from polycolab.artifacts.storage import garage_storage
from polycolab.platform.config import Environment, Settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "db" / "migrations" / "postgresql"


def configuration_failures(
    settings: Settings, *, require_moderation_operator: bool = False
) -> list[str]:
    """Return fixed diagnostic codes only; never echo settings or validation errors."""
    checks = {
        "placeholders": not any(
            marker in settings.model_dump_json()
            or any(
                marker in value.get_secret_value()
                for value in settings.model_dump().values()
                if isinstance(value, SecretStr)
            )
            for marker in ("CHANGE_ME", "REPLACE_WITH")
        ),
        "production": settings.app_env is Environment.PRODUCTION,
        "storage_configuration": settings.artifact_storage_configured,
        "https_origin": settings.public_app_origin is not None
        and settings.public_app_origin.scheme == "https",
        "same_origin": settings.public_app_origin is not None
        and [str(origin) for origin in settings.allowed_origins]
        == [str(settings.public_app_origin)],
        "release_identifier": settings.release_sha not in {"unknown", "latest", ""},
        "admission_limit": settings.registration_requests_per_minute > 0,
        "hmac_secret": settings.admission_scope_hmac_key is not None
        and len(settings.admission_scope_hmac_key.get_secret_value()) >= 32,
        "worker_secret": settings.runtime_worker_token is not None
        and len(settings.runtime_worker_token.get_secret_value()) >= 32,
        "proxy_scope": not any(
            cidr in {"0.0.0.0/0", "::/0"} for cidr in settings.admission_trusted_proxy_cidrs
        ),
    }
    failures = [name for name, passed in checks.items() if not passed]
    if require_moderation_operator and not settings.public_project_moderator_subjects:
        failures.append("moderation_operators")
    return failures


def live_checks(settings: Settings, health_url: str) -> dict[str, bool]:
    """Read-only dependency probes; no migrations, uploads or secret diagnostics."""
    results = {"schema_head": False, "health": False, "storage_bucket": False}
    engine = None
    try:
        if not settings.database_url.startswith("postgresql"):
            raise ValueError("PostgreSQL required")
        engine = create_engine(
            settings.database_url,
            poolclass=NullPool,
            connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
        )
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS_DIR))
        expected = set(ScriptDirectory.from_config(config).get_heads())
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            actual = set(MigrationContext.configure(connection).get_current_heads())
        results["schema_head"] = bool(expected) and actual == expected
    except Exception:
        pass
    finally:
        if engine is not None:
            engine.dispose()
    if settings.artifact_storage_configured:
        storage = None
        try:
            assert settings.artifact_s3_access_key is not None
            assert settings.artifact_s3_secret_key is not None
            storage = garage_storage(
                endpoint=str(settings.artifact_s3_endpoint),
                bucket=settings.artifact_s3_bucket or "",
                region=settings.artifact_s3_region or "",
                access_key=settings.artifact_s3_access_key.get_secret_value(),
                secret_key=settings.artifact_s3_secret_key.get_secret_value(),
            )
            storage.client.head_bucket(Bucket=storage.bucket)
            results["storage_bucket"] = True
        except Exception:
            pass
        finally:
            if storage is not None:
                storage.client.close()
    try:
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", health_url) as response:
                results["health"] = response.status_code == 200
    except Exception:
        pass
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Read-only schema, bucket and health probes"
    )
    parser.add_argument("--health-url", default="http://api:8000/health/ready")
    args = parser.parse_args(argv)
    try:
        settings = Settings()
        # The first local account's subject does not exist until restricted
        # bootstrap completes. Normal startup therefore permits an empty,
        # fail-closed moderation allowlist; the post-bootstrap live release gate
        # requires it before ingress may open.
        failures = configuration_failures(settings, require_moderation_operator=args.live)
    except Exception:
        # Pydantic errors can contain input values, including credentials.
        print("deployment configuration: INVALID_SETTINGS")
        return 1
    if failures:
        print("deployment configuration: FAIL " + ",".join(failures))
        return 1
    print("deployment configuration: PASS (live acceptance still required)")
    if args.live:
        results = live_checks(settings, args.health_url)
        for name, passed in results.items():
            print(f"deployment {name}: {'PASS' if passed else 'FAIL'}")
        return 0 if all(results.values()) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
