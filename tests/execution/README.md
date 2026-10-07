# Service integration tests

For the separately provisioned HTTPS key service, see the [live OpenBao gate](../../deploy/openbao/VERIFY.md).
It never starts Docker or modifies existing application credentials.
Without explicit opt-in it skips.

Run from the repository root with Docker available:

```sh
docker pull dxflrs/garage:v2.3.0
POLYCOLAB_TEST_GARAGE=1 uv run --directory backend pytest ../tests/execution/test_garage_storage.py -q
```

The fixture runs the actual [development profile](../../deploy/garage/README.md) in a unique, disposable Compose project.
It uses a dynamic loopback-only S3 port, random test credentials, and private test volumes.
It verifies byte retention after replacing the container, then removes its project and volumes at teardown.
It does not connect to an existing bucket, reset PostgreSQL or touch another worktree's services.
Without the opt-in variable the tests skip.
A skip is not integration evidence.

The adapter uses SigV4 path-style PutObject, GetObject and DeleteObject, supported by the [Garage compatibility reference](https://garagehq.deuxfleurs.fr/documentation/reference-manual/s3-compatibility/).
The pinned 2.3.0 fixture uses automatic single-node/default-bucket setup from the [official quick start](https://garagehq.deuxfleurs.fr/documentation/quick-start/).
The integration setup uses these references.
The adapter supplies Content-MD5 and independently verifies SHA-256 after upload and on reads.
It does not treat ETags as evidence.
It does not depend on ACLs, bucket versioning or bucket lifecycle GC.

This proves only the byte-storage boundary.
PostgreSQL authorization, commit/GC contention, exact publication and Linux execution isolation have separate gates.
This single-node fixture provides no replication or production recovery evidence.

## Hosted native controller

`test_hosted_native.py` is opt-in on an idle disposable Linux execution account.
It tests two actual VMs, cancellation containment, Codex initialization and work directory cleanup.
See the [hosted failure matrix](../../docs/architecture/hosted-failures.md) for prerequisites, invocation and remaining provider/browser/resource gates.
