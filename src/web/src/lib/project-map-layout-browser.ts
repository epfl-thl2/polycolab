import ELK from 'elkjs/lib/elk-api';
import ElkWorker from 'elkjs/lib/elk-worker.min.js?worker';
import { layoutProjectMap } from './project-map-layout';
import type { ProjectMap } from './project-map';
export async function layoutMap(data: ProjectMap) {
  const engine = new ELK({ workerFactory: () => new ElkWorker() });
  try {
    return await layoutProjectMap(data, engine);
  } finally {
    engine.terminateWorker();
  }
}
