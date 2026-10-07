export function docsSite(): {
  name: string;
  apply: 'serve';
  configureServer: (server: unknown) => Promise<void>;
};
