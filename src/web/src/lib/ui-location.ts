export type NavigateQuery = (search: string) => void;
export function canonicalUiLocation(path: string, search: string) {
  return path + search;
}
