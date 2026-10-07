import { canonicalObjectKind } from './object-kind';
import {
  CircleHelp,
  BookOpen,
  MessageSquare,
  Pencil,
  FlaskConical,
  StickyNote,
  Code,
  FileText,
} from '@lucide/svelte';
import type { ObjectKind } from './research-api';
import { profileKindLabels } from './profile-view';

const visuals = {
  PROBLEM: { icon: CircleHelp, color: '--object-problem' },
  DEFINITION: { icon: BookOpen, color: '--object-definition' },
  STATEMENT: { icon: MessageSquare, color: '--object-statement' },
  PROOF: { icon: Pencil, color: '--object-proof' },
  ATTEMPT: { icon: FlaskConical, color: '--object-attempt' },
  NOTE: { icon: StickyNote, color: '--object-note' },
  FORMALIZATION: { icon: Code, color: '--object-formalization' },
} satisfies Record<ObjectKind, { icon: typeof FileText; color: string }>;

export const objectKinds = Object.keys(visuals) as ObjectKind[];

export function objectKindVisual(kind: string) {
  kind = canonicalObjectKind(kind);
  if (Object.hasOwn(visuals, kind)) {
    const key = kind as ObjectKind;
    return { ...visuals[key], label: profileKindLabels[key] };
  }
  return {
    icon: FileText,
    color: '--muted-foreground',
    label: kind === 'STATEMENT' ? 'Statement' : 'Research object',
  };
}
