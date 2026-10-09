import { canonicalObjectKind } from './object-kind';
export type MapNodeShape =
  'diamond' | 'square' | 'card' | 'oval' | 'hexagon' | 'trapezoid' | 'cut-corner';

export function mapNodeShape(kind: string): MapNodeShape {
  switch (canonicalObjectKind(kind ?? '')) {
    case 'PROBLEM':
      return 'oval';
    case 'PROOF':
      return 'diamond';
    case 'STATEMENT':
      return 'hexagon';
    case 'ATTEMPT':
      return 'trapezoid';
    case 'FORMALIZATION':
      return 'cut-corner';
    default:
      return 'card';
  }
}
