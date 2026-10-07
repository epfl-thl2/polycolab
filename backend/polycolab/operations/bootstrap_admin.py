"""Initialize the fixed built-in administrator before serving requests."""

from __future__ import annotations

import sys

from polycolab.accounts.builtin import bootstrap_admin
from polycolab.db.session import make_engine, make_session_factory
from polycolab.db.transaction import make_transaction_factory
from polycolab.platform.config import AuthMode, Settings, get_settings


def run(settings: Settings) -> bool:
    """Create the first local administrator and report whether it was created."""

    if settings.auth_mode is not AuthMode.LOCAL:
        return False
    engine = make_engine(settings)
    try:
        factory = make_transaction_factory(make_session_factory(engine))
        password = (
            settings.bootstrap_admin_password.get_secret_value()
            if settings.bootstrap_admin_password is not None
            else None
        )
        with factory() as transaction:
            return bootstrap_admin(transaction, password)
    finally:
        engine.dispose()


def main() -> int:
    try:
        created = run(get_settings())
    except ValueError as error:
        sys.stderr.write(f"Administrator bootstrap failed: {error}\n")
        return 1
    sys.stdout.write("Administrator initialized.\n" if created else "Administrator unchanged.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
