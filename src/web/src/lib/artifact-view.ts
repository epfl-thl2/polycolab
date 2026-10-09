import type { ExactResearchRevisionView } from './research-structure-view';
import type { components } from '$lib/api-client';

export type ArtifactState = 'STAGING' | 'COMMITTED' | 'DELETING' | 'UNAVAILABLE' | 'DELETED';

export type ArtifactAttachmentView = {
  attachmentId: string;
  role: string;
  researchRevision: ExactResearchRevisionView;
  sourceRevision?: ExactResearchRevisionView;
  researchAttempt?: ExactResearchRevisionView;
  createdAt: string;
};

export type ArtifactView = {
  artifactId: string;
  digest: string;
  byteLength: number;
  mediaType: string;
  state: ArtifactState;
  role: string;
  researchRevision: ExactResearchRevisionView;
  researchAttempt?: ExactResearchRevisionView;
  attachments: ArtifactAttachmentView[];
  provenance: Array<{ label: string; value: string }>;
  downloadAvailable: boolean;
};

export type ArtifactUploadDraft = {
  file: File;
  role: components['schemas']['ArtifactResearchRole'];
  researchRevisionId: string;
  researchAttemptRevisionId?: string;
};

type ArtifactAttachmentItem = components['schemas']['ArtifactAttachmentItem'];

export function mapArtifactAttachments(
  items: ArtifactAttachmentItem[],
  resolve: (revisionId: string) => ExactResearchRevisionView,
): ArtifactView[] {
  const grouped = new Map<string, ArtifactView>();
  const seenAttachments = new Set<string>();
  for (const item of items) {
    if (seenAttachments.has(item.attachment_id)) continue;
    seenAttachments.add(item.attachment_id);
    const researchRevision = resolve(item.object_version_id);
    const researchAttempt = item.attempt_object_version_id
      ? resolve(item.attempt_object_version_id)
      : undefined;
    const attachment = {
      attachmentId: item.attachment_id,
      role: item.role,
      researchRevision,
      sourceRevision: item.source_object_version_id
        ? resolve(item.source_object_version_id)
        : undefined,
      researchAttempt,
      createdAt: item.created_at,
    };
    const existing = grouped.get(item.artifact.id);
    if (existing) {
      existing.attachments.push(attachment);
      continue;
    }
    grouped.set(item.artifact.id, {
      artifactId: item.artifact.id,
      digest: `sha256:${item.artifact.sha256}`,
      byteLength: item.artifact.byte_length,
      mediaType: item.artifact.media_type,
      state: item.artifact.state,
      role: item.role,
      researchRevision,
      researchAttempt,
      attachments: [attachment],
      provenance: [],
      downloadAvailable: item.artifact.state === 'COMMITTED',
    });
  }
  return [...grouped.values()];
}
