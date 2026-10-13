"""Policy and atomic workflows for human-authored agent resources."""

import re
from dataclasses import asdict
from uuid import UUID

import yaml

from polycolab.entities.accounts import User
from polycolab.entities.agent_library import (
    LibraryContent,
    LibraryEntry,
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


def required(tx: Transaction, entry_id: UUID, *, lock: bool = False) -> LibraryEntry:
    entry = tx.agent_library.entry(entry_id, lock=lock)
    if entry is None:
        raise LibraryError("agent_library_not_found", 404)
    return entry


def owned(tx: Transaction, entry_id: UUID, user: User, *, lock: bool = False) -> LibraryOwned:
    entry = required(tx, entry_id, lock=lock)
    if entry.owner_user_id != user.id:
        raise LibraryError("agent_library_not_found", 404)
    source = tx.agent_library.version(entry.source_version_id) if entry.source_version_id else None
    return LibraryOwned(
        entry, tx.agent_library.draft(entry_id), source.entry_id if source else None
    )


def public(tx: Transaction, entry_id: UUID, version_id: UUID | None = None) -> LibraryPublic:
    entry = required(tx, entry_id)
    if entry.hidden or entry.published_version_id is None:
        raise LibraryError("agent_library_not_found", 404)
    version = tx.agent_library.version(version_id or entry.published_version_id)
    if version is None or version.entry_id != entry_id:
        raise LibraryError("agent_library_not_found", 404)
    source = tx.agent_library.version(entry.source_version_id) if entry.source_version_id else None
    return LibraryPublic(
        entry.id,
        entry.kind,
        entry.source_version_id,
        entry.archived,
        version,
        source.entry_id if source else None,
    )


def guard(entry: LibraryEntry, expected_revision: int) -> None:
    if entry.revision != expected_revision:
        raise LibraryError("agent_library_stale_revision")


def create(
    tx: Transaction, user: User, kind: LibraryKind, content: LibraryContent, key: str
) -> LibraryOwned:
    validate(kind, content, publishing=False)
    payload = {"kind": kind, "content": asdict(content)}
    with tx:
        ids = tx.agent_library.retry(user.id, "agent_library.create", key, payload)
        if ids is None:
            entry_id = tx.agent_library.create(user.id, kind, content)
            tx.agent_library.remember(user.id, "agent_library.create", key, payload, [entry_id])
        else:
            entry_id = ids[0]
        result = owned(tx, entry_id, user)
        tx.commit()
        return result


def update(
    tx: Transaction,
    user: User,
    entry_id: UUID,
    content: LibraryContent,
    expected_revision: int,
    key: str,
) -> LibraryOwned:
    payload = {"entry_id": str(entry_id), "content": asdict(content), "revision": expected_revision}
    with tx:
        value = owned(tx, entry_id, user, lock=True)
        validate(value.entry.kind, content, publishing=False)
        ids = tx.agent_library.retry(user.id, "agent_library.update", key, payload)
        if ids is None:
            guard(value.entry, expected_revision)
            if value.entry.archived:
                raise LibraryError("agent_library_archived")
            tx.agent_library.update_draft(entry_id, content)
            tx.agent_library.remember(user.id, "agent_library.update", key, payload, [entry_id])
        result = owned(tx, entry_id, user)
        tx.commit()
        return result


def publish(
    tx: Transaction, user: User, entry_id: UUID, expected_revision: int, key: str
) -> LibraryVersion:
    payload = {"entry_id": str(entry_id), "revision": expected_revision}
    with tx:
        value = owned(tx, entry_id, user, lock=True)
        ids = tx.agent_library.retry(user.id, "agent_library.publish", key, payload)
        if ids is None:
            guard(value.entry, expected_revision)
            if value.entry.archived:
                raise LibraryError("agent_library_archived")
            validate(value.entry.kind, value.draft, publishing=True)
            version_id = tx.agent_library.publish(
                value.entry, value.draft, user.display_name or "Researcher"
            )
            tx.agent_library.remember(user.id, "agent_library.publish", key, payload, [version_id])
        else:
            version_id = ids[0]
        result = tx.agent_library.version(version_id)
        assert result is not None
        tx.commit()
        return result


def copy(tx: Transaction, user: User, entry_id: UUID, version_id: UUID, key: str) -> LibraryOwned:
    payload = {"entry_id": str(entry_id), "version_id": str(version_id)}
    with tx:
        required(tx, entry_id, lock=True)
        original = public(tx, entry_id, version_id)
        ids = tx.agent_library.retry(user.id, "agent_library.copy", key, payload)
        if ids is None:
            if original.archived:
                raise LibraryError("agent_library_archived")
            copied_id = tx.agent_library.create(
                user.id, original.kind, original.version.content, version_id
            )
            tx.agent_library.remember(user.id, "agent_library.copy", key, payload, [copied_id])
        else:
            copied_id = ids[0]
        result = owned(tx, copied_id, user)
        tx.commit()
        return result


def archive(
    tx: Transaction, user: User, entry_id: UUID, expected_revision: int, archived: bool, key: str
) -> LibraryOwned:
    payload = {"entry_id": str(entry_id), "revision": expected_revision, "archived": archived}
    with tx:
        value = owned(tx, entry_id, user, lock=True)
        if tx.agent_library.retry(user.id, "agent_library.archive", key, payload) is None:
            guard(value.entry, expected_revision)
            tx.agent_library.set_archived(entry_id, archived)
            tx.agent_library.remember(user.id, "agent_library.archive", key, payload, [entry_id])
        result = owned(tx, entry_id, user)
        tx.commit()
        return result


def moderate(
    tx: Transaction,
    user: User,
    entry_id: UUID,
    expected_revision: int,
    hidden: bool,
    reason: str,
    key: str,
    moderator_subjects: list[str],
) -> LibraryEntry:
    if user.subject not in moderator_subjects:
        raise LibraryError("agent_library_moderation_denied", 403)
    payload = {
        "entry_id": str(entry_id),
        "revision": expected_revision,
        "hidden": hidden,
        "reason": reason,
    }
    with tx:
        entry = required(tx, entry_id, lock=True)
        if tx.agent_library.retry(user.id, "agent_library.moderate", key, payload) is None:
            guard(entry, expected_revision)
            if not entry.published_version_id:
                raise LibraryError("agent_library_not_found", 404)
            tx.agent_library.moderate(entry_id, user.id, hidden, reason)
            tx.agent_library.remember(user.id, "agent_library.moderate", key, payload, [entry_id])
        result = required(tx, entry_id)
        tx.commit()
        return result
