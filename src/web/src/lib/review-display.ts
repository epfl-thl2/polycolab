import type { ReviewSummary } from './reviews-api';

/** Historical assessments count as reviews without implying a correctness result. */
export function reviewCount(counts: ReviewSummary['human']): number {
  return (counts.reviewed ?? 0) + counts.supports + counts.issues_found + counts.inconclusive;
}

export function reviewLabel(review: ReviewSummary): string {
  return `Human reviewed: ${reviewCount(review.human)}. AI reviewed: ${reviewCount(review.ai)}.`;
}
