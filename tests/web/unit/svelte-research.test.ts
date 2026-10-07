import { describe, it, expect } from 'vitest';
import { renderMarkdown } from '../../../web/src/svelte-lib/markdown';
import { advancesCursor, statusFromEvent } from '../../../web/src/svelte-lib/session-events';
import type { AgentEvent } from '../../../web/src/lib/agent-sessions-api';

describe('Svelte research content and event boundaries', () => {
  it('renders accessible mathematics without enabling injected HTML or unsafe links', () => {
    const html = renderMarkdown(
      'A bound $x^2$\n\n<script>alert(1)</script>\n\n[unsafe](javascript:alert(1))',
    );
    expect(html).toContain('<math');
    expect(html).not.toContain('<script');
    expect(html).not.toContain('href="javascript:');
  });
  it('rejects duplicate, old, and malformed session cursors across run boundaries', () => {
    expect(advancesCursor(undefined, '1:1')).toBe(true);
    expect(advancesCursor('1:10', '1:2')).toBe(false);
    expect(advancesCursor('1:10', '1:10')).toBe(false);
    expect(advancesCursor('1:10', '2:1')).toBe(true);
    expect(advancesCursor('2:1', 'malformed')).toBe(false);
  });
  it('keeps cancellation pending until the committed terminal event', () => {
    const event = { kind: 'CANCEL_REQUESTED' } as AgentEvent;
    expect(statusFromEvent(event)).toBe('CANCELLING');
    expect(statusFromEvent({ ...event, kind: 'RUN_CANCELLED' })).toBe('CANCELLED');
    expect(statusFromEvent({ ...event, kind: 'ASSISTANT_DELTA' })).toBeUndefined();
  });
});
