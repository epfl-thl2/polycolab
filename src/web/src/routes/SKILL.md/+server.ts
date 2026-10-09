import skill from '../../../../../skills/polycolab/SKILL.md?raw';

export const prerender = true;

export function GET() {
  return new Response(skill, {
    headers: {
      'Content-Type': 'text/markdown; charset=utf-8',
      'Cache-Control': 'no-cache',
      'X-Content-Type-Options': 'nosniff',
    },
  });
}
