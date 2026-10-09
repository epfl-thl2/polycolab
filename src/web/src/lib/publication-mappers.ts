import type { components } from '$lib/api-client';
import { relationshipEndpoints } from './relationship-view';
import type {
  PublicationManifestView,
  PublicationPreviewMember,
  PublicationPreviewView,
  PublicationSelectionItem,
} from './publication-view';

type Selection = components['schemas']['PublicationVersionSelection'];
type Preview = components['schemas']['PublicationVersionPreview'];
type Manifest = components['schemas']['PublicationVersionManifestRead'];
type PublicManifest = components['schemas']['PublicPublicationVersionManifestRead'];
type Fields = components['schemas']['PublicationVersionFields'];

const privateRecordHref = (projectId: string, id: string) =>
  `/workspaces/${projectId}/records/${id}`;
const publicRecordHref = (id: string) => `/commons/records/${id}`;

function recordKind(kind: components['schemas']['ObjectKind']): PublicationSelectionItem['kind'] {
  if (kind === 'PROOF') return 'PROOF';
  if (kind === 'ATTEMPT') return 'RESEARCH_ATTEMPT';
  return 'RESEARCH_REVISION';
}

export function publicationSelection(
  projectId: string,
  available: PublicationSelectionItem[],
  selectedIds: string[],
): Selection {
  const selected = available.filter((item) => selectedIds.includes(item.id));
  return {
    workspace_id: projectId,
    review_ids: selected.filter((item) => item.kind === 'REVIEW').map((item) => item.id),
    object_version_ids: selected
      .filter((item) => ['RESEARCH_REVISION', 'PROOF', 'RESEARCH_ATTEMPT'].includes(item.kind))
      .map((item) => item.id),
    summary_revision_ids: selected
      .filter((item) => item.kind === 'AUTHORED_SUMMARY')
      .map((item) => item.id),
    comment_ids: selected.filter((item) => item.kind === 'COMMENT').map((item) => item.id),
    progress_ids: selected.filter((item) => item.kind === 'PROGRESS').map((item) => item.id),
    relation_ids: selected.filter((item) => item.kind === 'RELATION').map((item) => item.id),
    artifact_ids: selected.filter((item) => item.kind === 'ARTIFACT').map((item) => item.id),
  };
}

function members(
  selection: Selection,
  fields: Fields,
  requiredRevisionIds: string[],
  publicLinks: boolean,
): PublicationPreviewMember[] {
  const selectedRevisions = new Set(selection.object_version_ids);
  const selectedArtifacts = new Set(selection.artifact_ids ?? []);
  const link = publicLinks
    ? (_projectId: string, id: string) => publicRecordHref(id)
    : privateRecordHref;
  const values: PublicationPreviewMember[] = fields.object_versions.map((record) => ({
    id: record.id,
    kind: recordKind(record.kind),
    revisionId: record.id,
    title: record.content.title,
    href: link(selection.workspace_id, record.id),
    inclusion: selectedRevisions.has(record.id) ? 'SELECTED' : 'REQUIRED',
    reason: requiredRevisionIds.includes(record.id) ? 'Exact dependency closure' : undefined,
  }));
  values.push(
    ...(fields.reviews ?? []).map((review) => ({
      id: review.id,
      kind: 'REVIEW' as const,
      revisionId: review.object_version_id,
      title: `${review.actor_kind === 'HUMAN' ? 'Human' : 'AI'} review by ${review.reviewer_name}`,
      href: link(selection.workspace_id, review.object_version_id),
      inclusion: 'SELECTED' as const,
    })),
    ...fields.summaries.map((summary) => ({
      id: summary.id,
      kind: 'AUTHORED_SUMMARY' as const,
      revisionId: summary.id,
      title: `Authored summary revision ${summary.number}`,
      href: link(selection.workspace_id, summary.object_id),
      inclusion: 'SELECTED' as const,
    })),
    ...fields.comments.map((comment) => ({
      id: comment.id,
      kind: 'COMMENT' as const,
      revisionId: comment.object_version_id,
      title: `Comment by ${comment.author_display_name ?? comment.agent_display_name ?? 'Unknown contributor'}`,
      href: link(selection.workspace_id, comment.object_version_id),
      inclusion: 'SELECTED' as const,
    })),
    ...fields.progress.map((progress) => ({
      id: progress.id,
      kind: 'PROGRESS' as const,
      revisionId: progress.object_version_id,
      title: `${progress.status} progress`,
      href: link(selection.workspace_id, progress.object_version_id),
      inclusion: 'SELECTED' as const,
    })),
    ...fields.relationships.map((relation) => ({
      id: relation.id,
      kind: 'RELATION' as const,
      title: `${relation.relationship_type} relationship`,
      href: link(selection.workspace_id, relationshipEndpoints(relation)[0]),
      inclusion: 'SELECTED' as const,
    })),
    ...fields.artifacts.map((artifact) => ({
      id: artifact.id,
      kind: 'ARTIFACT' as const,
      revisionId: artifact.source_object_version_id ?? undefined,
      title: `Artifact ${artifact.id}`,
      href: publicLinks
        ? artifact.content_path
        : privateRecordHref(
            selection.workspace_id,
            artifact.source_object_version_id ?? artifact.links[0]?.object_version_id ?? '',
          ),
      description: `sha256:${artifact.sha256} · ${artifact.byte_length.toLocaleString()} bytes · ${artifact.media_type}`,
      inclusion: selectedArtifacts.has(artifact.id) ? ('SELECTED' as const) : ('REQUIRED' as const),
      reason: selectedArtifacts.has(artifact.id) ? undefined : 'Exact dependency closure',
    })),
  );
  return values;
}

function publicFields(fields: Fields): Array<{ label: string; value: string }> {
  return [
    ...(fields.reviews ?? []).map((review) => ({
      label: `Review · ${review.reviewer_name} · ${review.withdrawn ? 'Withdrawn' : review.outcome}`,
      value: `${review.scope}: ${review.rationale}`,
    })),
    ...fields.object_versions.map((record) => ({
      label: `Record · ${record.content.title}`,
      value: record.content.content_md,
    })),
    ...fields.summaries.map((summary) => ({
      label: `Authored summary · revision ${summary.number}`,
      value: summary.body_md,
    })),
    ...fields.comments.map((comment) => ({ label: 'Comment', value: comment.body_md })),
    ...fields.progress.map((progress) => ({
      label: `Progress · ${progress.status}`,
      value: progress.detail_md,
    })),
    ...fields.relationships.map((relation) => ({
      label: `Relation · ${relation.relationship_type}`,
      value: relation.description ?? '',
    })),
    ...fields.artifacts.map((artifact) => ({
      label: `Artifact · ${artifact.id}`,
      value: `sha256:${artifact.sha256} · ${artifact.byte_length.toLocaleString()} bytes · ${artifact.media_type}`,
    })),
  ];
}

export function mapPublicationPreview(preview: Preview): PublicationPreviewView {
  const all = members(
    preview.selection,
    preview.public_fields,
    preview.required_object_version_ids,
    false,
  );
  return {
    previewId: preview.preview_digest,
    digest: preview.preview_digest,
    selected: all.filter((item) => item.inclusion === 'SELECTED'),
    required: all.filter((item) => item.inclusion === 'REQUIRED'),
    optional: [],
    publicFields: publicFields(preview.public_fields),
    blockers: [],
    artifactBytesReady: true,
  };
}

export function mapPublicationManifest(manifest: Manifest): PublicationManifestView {
  return {
    publicationId: manifest.id,
    digest: manifest.preview_digest,
    publishedAt: manifest.created_at,
    publisher: manifest.publisher_display_name ?? 'Unknown human',
    publicHref: `/commons/publications/${manifest.id}`,
    members: members(
      manifest.selection,
      manifest.public_fields,
      manifest.required_object_version_ids,
      true,
    ),
  };
}

export function mapPublicPublicationManifest(manifest: PublicManifest): PublicationManifestView {
  const selection: Selection = { ...manifest.selection, workspace_id: '' };
  return {
    publicationId: manifest.id,
    digest: manifest.preview_digest,
    publishedAt: manifest.created_at,
    publisher: manifest.publisher_display_name ?? 'Unknown human',
    publicHref: `/commons/publications/${manifest.id}`,
    members: members(selection, manifest.public_fields, manifest.required_object_version_ids, true),
  };
}

export const mapPublicationFields = publicFields;
