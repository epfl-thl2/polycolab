"""Apply finite process limits before execing the service-owned Git executable."""

import os
import resource
import sys


def main() -> None:
    ceiling = int(sys.argv[1])
    resource.setrlimit(resource.RLIMIT_FSIZE, (ceiling, ceiling))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    if sys.platform == "linux":
        memory = 1024 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    os.execvp("git", ["git", *sys.argv[2:]])


if __name__ == "__main__":
    main()
