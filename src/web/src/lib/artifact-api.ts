import type { components } from '$lib/api-client';
import { commonsClient, result, type CommonsClientOptions } from './commons-client';
import type { ArtifactUploadDraft } from './artifact-view';

type ArtifactRead = components['schemas']['ArtifactRead'];
type ArtifactAttachmentPage = components['schemas']['Collection_ArtifactAttachmentItem_'];

export const MAX_ARTIFACT_UPLOAD_BYTES = 16 * 1024 * 1024;

export async function sha256(file: File): Promise<string> {
  const bytes = await new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error('Could not read the artifact.'));
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.readAsArrayBuffer(file);
  });
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export function saveArtifactDownload(blob: Blob, artifactId: string) {
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = href;
  anchor.download = `artifact-${artifactId}`;
  anchor.rel = 'noopener';
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(href), 0);
}

export function createArtifactApi(options: CommonsClientOptions = {}) {
  const client = commonsClient(options);
  const retries = new Map<string, { upload: string; attach: string }>();
  const publicClient = commonsClient({ baseUrl: options.baseUrl });
  return {
    attachments: (
      projectId: string,
      query: { object_version_id?: string; limit?: number; cursor?: string } = {},
    ): Promise<ArtifactAttachmentPage> =>
      result(
        client.GET('/api/v1/workspaces/{workspace_id}/artifacts', {
          params: { path: { workspace_id: projectId }, query },
        }),
      ),
    publicAttachments: (
      projectId: string,
      query: { object_version_id?: string; limit?: number; cursor?: string } = {},
    ): Promise<ArtifactAttachmentPage> =>
      result(
        publicClient.GET('/api/v1/workspaces/{workspace_id}/artifacts', {
          params: { path: { workspace_id: projectId }, query },
        }),
      ),
    async uploadAndAttach(projectId: string, draft: ArtifactUploadDraft): Promise<ArtifactRead> {
      const digest = await sha256(draft.file);
      const fingerprint = JSON.stringify([
        projectId,
        digest,
        draft.researchRevisionId,
        draft.researchAttemptRevisionId,
        draft.role,
        draft.file.type,
      ]);
      const keys = retries.get(fingerprint) ?? {
        upload: crypto.randomUUID(),
        attach: crypto.randomUUID(),
      };
      retries.set(fingerprint, keys);
      const uploaded = await result(
        client.POST('/api/v1/artifacts', {
          params: {
            header: { 'Idempotency-Key': keys.upload },
            query: {
              workspace_id: projectId,
              sha256: digest,
              byte_length: draft.file.size,
              media_type: draft.file.type || 'application/octet-stream',
              source_object_version_id: draft.researchRevisionId,
            },
          },
          headers: { 'Content-Type': 'application/octet-stream' },
          body: draft.file as unknown as string,
          bodySerializer: (body) => body as unknown as BodyInit,
        }),
      );
      await result(
        client.POST('/api/v1/attachments', {
          params: { header: { 'Idempotency-Key': keys.attach } },
          body: {
            artifact_id: uploaded.id,
            object_version_id: draft.researchRevisionId,
            attempt_object_version_id: draft.researchAttemptRevisionId,
            role: draft.role,
          },
        }),
      );
      const committed = (await result(
        client.GET('/api/v1/artifacts/{artifact_id}', {
          params: { path: { artifact_id: uploaded.id } },
        }),
      )) as ArtifactRead;
      retries.delete(fingerprint);
      return committed;
    },
    download: (_projectId: string, artifactId: string) =>
      result(
        client.GET('/api/v1/artifacts/{artifact_id}/content', {
          params: { path: { artifact_id: artifactId } },
          parseAs: 'blob',
        }),
      ),
    publicDownload: (artifactId: string) =>
      result(
        publicClient.GET('/api/v1/artifacts/{artifact_id}/content', {
          params: { path: { artifact_id: artifactId } },
          parseAs: 'blob',
        }),
      ),
  };
}
