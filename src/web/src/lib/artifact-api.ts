import type { components } from '$lib/api-client';
import {
  authenticatedClient,
  result,
  type AuthenticatedClientOptions,
} from './authenticated-client';

type ArtifactRead = components['schemas']['ArtifactRead'];

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

export function createArtifactApi(options: AuthenticatedClientOptions = {}) {
  const client = authenticatedClient(options);
  return {
    async upload(projectId: string, file: File): Promise<ArtifactRead> {
      return result(
        client.POST('/api/v1/projects/{project_id}/artifacts', {
          params: {
            path: { project_id: projectId },
            query: {
              sha256: await sha256(file),
              byte_length: file.size,
              media_type: file.type || 'application/octet-stream',
            },
          },
          headers: { 'Content-Type': 'application/octet-stream' },
          body: file as unknown as string,
          bodySerializer: (body) => body as unknown as BodyInit,
        }),
      );
    },
    download: (projectId: string, artifactId: string) =>
      result(
        client.GET('/api/v1/projects/{project_id}/artifacts/{artifact_id}/content', {
          params: { path: { project_id: projectId, artifact_id: artifactId } },
          parseAs: 'blob',
        }),
      ),
  };
}
