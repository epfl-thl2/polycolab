import { spawn } from 'node:child_process';
import { setTimeout } from 'node:timers/promises';

export function createSupervisor({ cwd, graceMs = 5000, stdio = 'inherit' }) {
  const groups = new Set();
  let shutdown;
  function signal(group, name) {
    try {
      process.kill(-group, name);
      return true;
    } catch (error) {
      if (error.code !== 'ESRCH') throw error;
      groups.delete(group);
      return false;
    }
  }
  return {
    get stopping() {
      return shutdown !== undefined;
    },
    run(executable, args, env = process.env, directory = cwd) {
      if (shutdown) return Promise.resolve();
      return new Promise((accept, reject) => {
        const child = spawn(executable, args, { cwd: directory, env, stdio, detached: true });
        if (child.pid) groups.add(child.pid);
        child.once('error', reject);
        child.once('exit', (code, exitSignal) => {
          // A wrapper can exit while its descendants still own the process group.
          if (child.pid) signal(child.pid, 0);
          if (code === 0 || shutdown) accept();
          else reject(new Error(`${executable} exited with ${exitSignal || code}`));
        });
      });
    },
    stop() {
      shutdown ??= (async () => {
        for (const group of groups) signal(group, 'SIGTERM');
        const deadline = Date.now() + graceMs;
        while (groups.size && Date.now() < deadline) {
          // Keep the launcher alive until descendants exit or the grace period expires.
          await setTimeout(50);
          for (const group of groups) signal(group, 0);
        }
        for (const group of groups) signal(group, 'SIGKILL');
      })();
      return shutdown;
    },
  };
}
