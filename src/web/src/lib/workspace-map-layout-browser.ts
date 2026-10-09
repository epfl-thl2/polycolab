import ELK from 'elkjs/lib/elk-api';
import ElkWorker from 'elkjs/lib/elk-worker.min.js?worker';
import { layoutWorkspaceMap } from './workspace-map-layout';
import type { WorkspaceMap } from './workspace-map';
export async function layoutMap(data: WorkspaceMap) {
  const engine = new ELK({ workerFactory: () => new ElkWorker() });
  try {
    return await layoutWorkspaceMap(data, engine);
  } finally {
    engine.terminateWorker();
  }
}
