export type PublicationSelectionKind =
  | 'RESEARCH_REVISION'
  | 'PROOF'
  | 'RESEARCH_ATTEMPT'
  | 'AUTHORED_SUMMARY'
  | 'COMMENT'
  | 'PROGRESS'
  | 'RELATION'
  | 'ARTIFACT'
  | 'REVIEW';

export type PublicationSelectionItem = {
  id: string;
  kind: PublicationSelectionKind;
  revisionId?: string;
  title: string;
  href: string;
  description?: string;
};

export type PublicationPreviewMember = PublicationSelectionItem & {
  inclusion: 'SELECTED' | 'REQUIRED' | 'OPTIONAL';
  reason?: string;
};

export type PublicationBlocker = {
  code: string;
  message: string;
};

export type PublicationPreviewView = {
  previewId: string;
  digest: string;
  selected: PublicationPreviewMember[];
  required: PublicationPreviewMember[];
  optional: PublicationPreviewMember[];
  publicFields: Array<{ label: string; value: string }>;
  blockers: PublicationBlocker[];
  artifactBytesReady: boolean;
};

export type PublicationManifestView = {
  publicationId: string;
  digest: string;
  publishedAt: string;
  publisher: string;
  publicHref: string;
  members: PublicationPreviewMember[];
};

export type PublicationSelectionDraft = { selectedIds: string[] };
export type PublicationConfirmation = { previewId: string; digest: string; reason: string };
