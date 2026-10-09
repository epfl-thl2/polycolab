import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkMath from 'remark-math';
import { renderMarkdown } from '../svelte-lib/markdown';

// Use parser positions to keep complete Markdown/math blocks, never cut a formula.
export function excerptBlocks(content: string) {
  const root = unified().use(remarkParse).use(remarkMath).parse(content);
  let end = 0;
  for (const block of root.children.slice(0, 3)) {
    const next = block.position?.end.offset ?? end;
    if (end && next > 800) break;
    end = next;
  }
  return content.slice(0, end);
}
export function highlightParts(text: string, query: string) {
  const term = query.trim();
  if (!term) return [{ text, match: false }];
  const parts: { text: string; match: boolean }[] = [];
  const needle = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  let start = 0;
  for (const match of text.matchAll(new RegExp(needle, 'giu'))) {
    const index = match.index!;
    if (index > start) parts.push({ text: text.slice(start, index), match: false });
    parts.push({ text: match[0], match: true });
    start = index + match[0].length;
  }
  if (start < text.length) parts.push({ text: text.slice(start), match: false });
  return parts;
}
export function renderSearchExcerpt(content: string, query: string) {
  const safeHtml = renderMarkdown(excerptBlocks(content));
  if (!query.trim() || typeof document === 'undefined') return safeHtml;
  const template = document.createElement('template');
  template.innerHTML = safeHtml;
  const walker = document.createTreeWalker(template.content, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  while (walker.nextNode()) nodes.push(walker.currentNode as Text);
  for (const node of nodes) {
    if (node.parentElement?.closest('a, pre, code, .katex, math')) continue;
    const parts = highlightParts(node.textContent ?? '', query);
    if (!parts.some((part) => part.match)) continue;
    node.replaceWith(
      ...parts.map((part) => {
        if (!part.match) return document.createTextNode(part.text);
        const mark = document.createElement('mark');
        mark.textContent = part.text;
        return mark;
      }),
    );
  }
  return template.innerHTML;
}
