import type { Relation } from './research-api';

/** Drawing order only: symmetric endpoints do not imply source ownership. */
export function relationshipEndpoints(relationship: Relation): [string, string] {
  return relationship.direction === 'BIDIRECTIONAL'
    ? [relationship.first_object_version_id, relationship.second_object_version_id]
    : [relationship.source_object_version_id, relationship.target_object_version_id];
}
