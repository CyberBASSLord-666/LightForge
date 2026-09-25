# Executed host session-reuse lifecycle controls

On September 25, 2026, both generated provider variants compiled against the
SHA-256-pinned ONNX Runtime 1.25.1 Java API. Each then passed 50 executed Java
ownership and fault cases with controlled native boundaries, for 100 case
executions. No generator or application change was needed.

This is **mock-boundary lifecycle evidence**, not native/JNI qualification.
The executed fixture uses the exact generated candidate with only its
`prepareModels` method replaced by a controlled hook. The complete prediction,
eight-step numerical/control-flow path, cancellation, cleanup, retirement query
and tensor/result ownership source remain unchanged. The manifest constructor
uses the real pinned manifest and JSON implementation. Tiny synthetic tensors
stand in for graph outputs; no original models or GPU kernels execute here.
The separately compiled `exact-api` snapshot has no preparation substitution
and is compiled against the real pinned ORT JAR, never the ORT controls.

Cases exercise successful retention over two bounded passages; five initial or
partial session-constructor failures; all twelve inference-call failure
positions; exception and Error retirement failures for five resource kinds;
invalid source clocks and passage counts; wrong-owner prediction; cancellation
before, during and between calls; cross-thread cancel and close; nested listener
and cancellation predictions; listener failures; idle and reentrant close;
detached RunOptions retirement; and unexpected drain iterator/clear failures.
A latched idle destructor proves that retirement remains false while close is
blocked and the lifecycle query can still complete. Every ordinary resource
gets exactly one retirement attempt, and failed destruction remains explicitly
unconfirmed. Reflection-based unexpected-map failures intentionally prove only
the unconfirmed-ownership state, not resource recovery.

Neither `cancel()` nor `close()` is nonblocking in this host candidate. Nothing
here authorizes using it on Android UI/lifecycle threads. Native destructor
semantics, JNI races, GPU execution, default/reuse numerical equivalence,
repeated timing, musical quality and the 75% end-to-end target still require
their distinct gates.

Run using the pinned JSON and ORT host JARs already described by the repository:

```sh
python3 tools/game_benchmark/session_reuse_lifecycle/run.py \
  --dependencies /absolute/path/to/dependencies \
  --java-home /absolute/path/to/jdk17 \
  --output /absolute/path/to/new-lifecycle-evidence
```

The dependencies directory must contain `test-json.jar` and
`onnxruntime-1.25.1.jar`; size and SHA-256 pins are mandatory. The tool does not
download dependencies. When a Java installation lacks a `javac` launcher but
contains `jdk.compiler`, it invokes that compiler module through `java`.
The actual runtime executable and modules are hashed and its version is saved.
The initial local execution used OpenJDK 17.0.20. The preserved repeat used the
repository-pinned Temurin 17.0.20.1 toolchain and also passed all 100 cases.
Both runtime identities remain in their separate evidence receipts; neither
mock execution establishes native runtime equivalence.

The fresh output directory retains exact and fixture Java snapshots, copied
control sources, compiled classes, compile/run logs, per-case results and a
source/dependency/output hash receipt. A failed run remains `INCOMPLETE`.
Every broader approval flag stays false even when all controlled cases pass.
