"""Policy and atomic workflows for human-authored agent resources."""

import re
from dataclasses import asdict
from uuid import UUID

import yaml

from polycolab.entities.accounts import User
from polycolab.entities.library import (
    LibraryContent,
    LibraryItem,
    LibraryKind,
    LibraryOwned,
    LibraryPublic,
    LibraryVersion,
)
from polycolab.transaction import Transaction


class LibraryError(Exception):
    def __init__(self, code: str, status: int = 409) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


def validate_skill(content: str) -> None:
    lines = content.splitlines()
    if not lines or lines[0] != "---":
        raise LibraryError("skill_frontmatter_required", 422)
    try:
        end = lines.index("---", 1)
        # Bound the parser input, reject YAML aliases, and use the safe loader.
        frontmatter = "\n".join(lines[1:end])
        if len(frontmatter) > 16_000 or any(
            isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken))
            for token in yaml.scan(frontmatter)
        ):
            raise ValueError
        metadata = yaml.safe_load(frontmatter)
        if not isinstance(metadata, dict):
            raise ValueError
        name = metadata.get("name")
        description = metadata.get("description")
        if (
            not isinstance(name, str)
            or len(name) > 64
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
        ):
            raise ValueError
        if not isinstance(description, str) or not description.strip() or len(description) > 1024:
            raise ValueError
    except ValueError, yaml.YAMLError, RecursionError:
        raise LibraryError("skill_frontmatter_invalid", 422) from None


def validate(kind: LibraryKind, content: LibraryContent, *, publishing: bool) -> None:
    if kind == "PLUGIN" and content.content:
        raise LibraryError("plugin_content_not_supported", 422)
    if kind != "PLUGIN" and (content.runtime or content.source_reference):
        raise LibraryError("plugin_fields_not_supported", 422)
    if kind == "SKILL":
        validate_skill(content.content)
    if kind == "PROMPT" and not content.content.strip():
        raise LibraryError("prompt_content_required", 422)
    if kind == "PLUGIN" and (
        not content.source_url or not content.runtime.strip() or not content.instructions.strip()
    ):
        raise LibraryError("plugin_source_runtime_instructions_required", 422)
    if publishing and not content.license.strip():
        raise LibraryError("publication_license_required", 422)


def required(tx: Transaction, item_id: UUID, *, lock: bool = False) -> LibraryItem:
    item = tx.library.item(item_id, lock=lock)
    if item is None:
        raise LibraryError("library_not_found", 404)
    return item


def owned(tx: Transaction, item_id: UUID, user: User, *, lock: bool = False) -> LibraryOwned:
    item = required(tx, item_id, lock=lock)
    if item.owner_user_id != user.id:
        raise LibraryError("library_not_found", 404)
    source = tx.library.version(item.source_version_id) if item.source_version_id else None
    return LibraryOwned(item, tx.library.draft(item_id), source.item_id if source else None)


def public(tx: Transaction, item_id: UUID, version_id: UUID | None = None) -> LibraryPublic:
    item = required(tx, item_id)
    if item.hidden or item.published_version_id is None:
        raise LibraryError("library_not_found", 404)
    version = tx.library.version(version_id or item.published_version_id)
    if version is None or version.item_id != item_id:
        raise LibraryError("library_not_found", 404)
    source = tx.library.version(item.source_version_id) if item.source_version_id else None
    return LibraryPublic(
        item.id,
        item.kind,
        item.source_version_id,
        item.archived,
        version,
        source.item_id if source else None,
    )


def guard(item: LibraryItem, expected_revision: int) -> None:
    if item.revision != expected_revision:
        raise LibraryError("library_stale_revision")


# Historical operation names and entry_id payload keys keep retry digests stable.
# Public DTOs use item/item_id; stored identities must not change on upgrade.
def create(
    tx: Transaction, user: User, kind: LibraryKind, content: LibraryContent, key: str
) -> LibraryOwned:
    validate(kind, content, publishing=False)
    payload = {"kind": kind, "content": asdict(content)}
    with tx:
        ids = tx.library.retry(user.id, "agent_library.create", key, payload)
        if ids is None:
            item_id = tx.library.create(user.id, kind, content)
            tx.library.remember(user.id, "agent_library.create", key, payload, [item_id])
        else:
            item_id = ids[0]
        result = owned(tx, item_id, user)
        tx.commit()
        return result


def update(
    tx: Transaction,
    user: User,
    item_id: UUID,
    content: LibraryContent,
    expected_revision: int,
    key: str,
) -> LibraryOwned:
    payload = {"entry_id": str(item_id), "content": asdict(content), "revision": expected_revision}
    with tx:
        value = owned(tx, item_id, user, lock=True)
        validate(value.item.kind, content, publishing=False)
        ids = tx.library.retry(user.id, "agent_library.update", key, payload)
        if ids is None:
            guard(value.item, expected_revision)
            if value.item.archived:
                raise LibraryError("library_archived")
            tx.library.update_draft(item_id, content)
            tx.library.remember(user.id, "agent_library.update", key, payload, [item_id])
        result = owned(tx, item_id, user)
        tx.commit()
        return result


def publish(
    tx: Transaction, user: User, item_id: UUID, expected_revision: int, key: str
) -> LibraryVersion:
    payload = {"entry_id": str(item_id), "revision": expected_revision}
    with tx:
        value = owned(tx, item_id, user, lock=True)
        ids = tx.library.retry(user.id, "agent_library.publish", key, payload)
        if ids is None:
            guard(value.item, expected_revision)
            if value.item.archived:
                raise LibraryError("library_archived")
            validate(value.item.kind, value.draft, publishing=True)
            version_id = tx.library.publish(
                value.item, value.draft, user.display_name or "Researcher"
            )
            tx.library.remember(user.id, "agent_library.publish", key, payload, [version_id])
        else:
            version_id = ids[0]
        result = tx.library.version(version_id)
        assert result is not None
        tx.commit()
        return result


def copy(tx: Transaction, user: User, item_id: UUID, version_id: UUID, key: str) -> LibraryOwned:
    payload = {"entry_id": str(item_id), "version_id": str(version_id)}
    with tx:
        required(tx, item_id, lock=True)
        original = public(tx, item_id, version_id)
        ids = tx.library.retry(user.id, "agent_library.copy", key, payload)
        if ids is None:
            if original.archived:
                raise LibraryError("library_archived")
            copied_id = tx.library.create(
                user.id, original.kind, original.version.content, version_id
            )
            tx.library.remember(user.id, "agent_library.copy", key, payload, [copied_id])
        else:
            copied_id = ids[0]
        result = owned(tx, copied_id, user)
        tx.commit()
        return result


def archive(
    tx: Transaction, user: User, item_id: UUID, expected_revision: int, archived: bool, key: str
) -> LibraryOwned:
    payload = {"entry_id": str(item_id), "revision": expected_revision, "archived": archived}
    with tx:
        value = owned(tx, item_id, user, lock=True)
        if tx.library.retry(user.id, "agent_library.archive", key, payload) is None:
            guard(value.item, expected_revision)
            tx.library.set_archived(item_id, archived)
            tx.library.remember(user.id, "agent_library.archive", key, payload, [item_id])
        result = owned(tx, item_id, user)
        tx.commit()
        return result


def moderate(
    tx: Transaction,
    user: User,
    item_id: UUID,
    expected_revision: int,
    hidden: bool,
    reason: str,
    key: str,
    moderator_subjects: list[str],
) -> LibraryItem:
    if user.subject not in moderator_subjects:
        raise LibraryError("library_moderation_denied", 403)
    payload = {
        "entry_id": str(item_id),
        "revision": expected_revision,
        "hidden": hidden,
        "reason": reason,
    }
    with tx:
        item = required(tx, item_id, lock=True)
        if tx.library.retry(user.id, "agent_library.moderate", key, payload) is None:
            guard(item, expected_revision)
            if not item.published_version_id:
                raise LibraryError("library_not_found", 404)
            tx.library.moderate(item_id, user.id, hidden, reason)
            tx.library.remember(user.id, "agent_library.moderate", key, payload, [item_id])
        result = required(tx, item_id)
        tx.commit()
        return result
