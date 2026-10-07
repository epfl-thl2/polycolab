"""Disposable OpenBao cold-state recovery, real age encryption and adapter reads.

File storage and loopback HTTP are test-only, not a production reference profile.
No exportable keys, plaintext Transit backup or application credentials are used.
"""

from __future__ import annotations

import json
import os
import subprocess
import tarfile
import tempfile
import time
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import httpx

from polycolab.model_gateway.openbao import OpenBaoKeyWrapper
from polycolab.operations.recovery_set import extract_regular_archive


def main() -> int:
    prefix = "polycolab-key-drill-" + uuid4().hex[:12]
    names = [prefix + "-source", prefix + "-restore"]
    volumes = [name + "-data" for name in names]
    image = (
        "openbao/openbao:2.6.1@"
        "sha256:5b2486ab0fb90bbc788cc345b0a08616dfb375873ee8be5df3a2fd4d378a67e0"
    )
    with (
        tempfile.TemporaryDirectory(prefix="polycolab-key-drill-") as raw,
        tempfile.TemporaryFile() as log,
    ):
        temporary = Path(raw)

        def command(args, **kwargs):
            return subprocess.run(args, check=True, stdout=log, stderr=log, timeout=180, **kwargs)

        def endpoint(name):
            address = subprocess.check_output(
                ["docker", "port", name, "8200/tcp"], text=True
            ).strip()
            return "http://" + address

        def connect(name):
            client = httpx.Client(base_url=endpoint(name), timeout=10, trust_env=False)
            for _ in range(100):
                try:
                    if client.get("/v1/sys/seal-status").status_code == 200:
                        return client
                except httpx.TransportError:
                    pass
                time.sleep(0.2)
            client.close()
            raise RuntimeError("key_service_not_ready")

        def api(client, method, path, **kwargs):
            response = client.request(method, "/v1/" + path, **kwargs)
            if response.status_code not in {200, 204}:
                raise RuntimeError(f"key_operation_failed:{method}:{path}:{response.status_code}")
            return response.json() if response.content else {}

        def wrapper(name, token, version):
            return OpenBaoKeyWrapper(
                base_url=endpoint(name),
                token=token,
                backend_id="research-test",
                environment="local",
                key_name="polycolab-test-recovery",
                transit_version=version,
                allow_loopback_http=True,
            )

        try:
            config = temporary / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "storage": {"file": {"path": "/bao/data"}},
                        "listener": {"tcp": {"address": "0.0.0.0:8200", "tls_disable": True}},
                        "disable_mlock": True,
                        "api_addr": "http://127.0.0.1:8200",
                    }
                )
            )
            for name, volume in zip(names, volumes, strict=True):
                command(
                    [
                        "docker",
                        "create",
                        "--name",
                        name,
                        "--user",
                        "0:0",
                        "-p",
                        "127.0.0.1::8200",
                        "--mount",
                        f"type=volume,source={volume},target=/bao/data",
                        "--mount",
                        f"type=bind,source={config},target=/test/config.json,readonly",
                        "--entrypoint",
                        "bao",
                        image,
                        "server",
                        "-config=/test/config.json",
                    ]
                )
            command(["docker", "start", names[0]])
            with closing(connect(names[0])) as source:
                initialized = api(
                    source, "PUT", "sys/init", json={"secret_shares": 1, "secret_threshold": 1}
                )
                unseal = initialized["keys_base64"][0]
                token = initialized["root_token"]
                api(source, "PUT", "sys/unseal", json={"key": unseal})
                source.headers["X-Vault-Token"] = token
                api(source, "POST", "sys/mounts/transit", json={"type": "transit"})
                api(
                    source,
                    "POST",
                    "transit/keys/polycolab-test-recovery",
                    json={
                        "type": "aes256-gcm96",
                        "derived": True,
                        "exportable": False,
                        "allow_plaintext_backup": False,
                    },
                )
                context = b"research-key-restore-exact-context"
                plaintext = os.urandom(32)
                first = wrapper(names[0], token, 1)
                try:
                    old_wrapped = first.wrap(plaintext, context)
                finally:
                    first.close()
                api(source, "POST", "transit/keys/polycolab-test-recovery/rotate")
                second = wrapper(names[0], token, 2)
                try:
                    new_wrapped = second.wrap(plaintext, context)
                finally:
                    second.close()
            command(["docker", "stop", names[0]])
            snapshot = temporary / "snapshot"
            snapshot.mkdir(mode=0o700)
            command(["docker", "cp", names[0] + ":/bao/data/.", str(snapshot)])
            archive = temporary / "snapshot.tar"
            with tarfile.open(archive, "w") as output:
                output.add(snapshot, arcname=".")
            identity = temporary / "identity"
            command(["age-keygen", "-o", str(identity)])
            recipient = subprocess.check_output(
                ["age-keygen", "-y", str(identity)], text=True
            ).strip()
            ciphertext = temporary / "snapshot.age"
            command(["age", "-r", recipient, "-o", str(ciphertext), str(archive)])
            decrypted = temporary / "restored.tar"
            command(["age", "-d", "-i", str(identity), "-o", str(decrypted), str(ciphertext)])
            restored = temporary / "restored"
            extract_regular_archive(decrypted, restored, 100 * 1024**2, 10000)
            command(["docker", "cp", str(restored) + "/.", names[1] + ":/bao/data"])
            command(["docker", "start", names[1]])
            with closing(connect(names[1])) as target:
                status = api(target, "GET", "sys/seal-status")
                if not status["sealed"]:
                    raise RuntimeError("restored_state_not_sealed")
                api(target, "PUT", "sys/unseal", json={"key": unseal})
                for version, wrapped in ((1, old_wrapped), (2, new_wrapped)):
                    reader = wrapper(names[1], token, version)
                    try:
                        if reader.unwrap(wrapped, context) != plaintext:
                            raise RuntimeError("restored_key_mismatch")
                    finally:
                        reader.close()
            print(
                "PASS: encrypted OpenBao cold-state restore; sealed restart; "
                "exact v1/v2 adapter reads"
            )
            print(
                subprocess.check_output(
                    ["docker", "image", "inspect", image, "--format", "{{json .RepoDigests}}"],
                    text=True,
                ).strip()
            )
            return 0
        except Exception as error:
            print(f"FAIL: key restore ({type(error).__name__}); secret diagnostics suppressed")
            if isinstance(error, RuntimeError):
                print(str(error))
            return 1
        finally:
            for name in names:
                subprocess.run(
                    ["docker", "rm", "-f", name], stdout=log, stderr=log, timeout=30, check=False
                )
            for volume in volumes:
                subprocess.run(
                    ["docker", "volume", "rm", volume],
                    stdout=log,
                    stderr=log,
                    timeout=30,
                    check=False,
                )


if __name__ == "__main__":
    raise SystemExit(main())
