package com.cyberbasslord.lightforge;

import java.lang.reflect.Method;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;

/**
 * Bounded, observational timing evidence for one native Deux passage.
 *
 * The collector deliberately has no compile-time Android dependency and never receives audio,
 * paths, job identifiers, exception text or model payloads. It records the fixed production
 * topology only: one summary, at most sixteen named stages, and at most the 27 Deux graphs.
 * Calling-thread and whole-process CPU time use their respective real runtime clocks;
 * process CPU includes other app threads and is not accelerator utilization. Missing
 * CPU/accelerator/cache telemetry is serialized as unavailable, never as a synthetic zero.
 */
final class NativeInferenceProfile {
    static final int MAX_GRAPH_RECORDS = 27;
    static final int MAX_STAGE_RECORDS = 16;
    static final int MAX_POLICY_RECORDS = 8, MAX_POLICY_RECORD_BYTES = 512;
    static final int MAX_RECORDS = 1 + MAX_STAGE_RECORDS + MAX_GRAPH_RECORDS + MAX_POLICY_RECORDS;
    private static final long NANOS_PER_MILLISECOND = 1000000L;
    private static final long UNSET = -1L;
    private static final CpuClock CPU_CLOCK = resolveCpuClock();
    private static final CpuClock PROCESS_CPU_CLOCK = processCpuClock();

    private final long startedNanos = System.nanoTime();
    private final LinkedHashMap<String, Stage> stages = new LinkedHashMap<String, Stage>();
    private final LinkedHashMap<String, Graph> graphs = new LinkedHashMap<String, Graph>();
    private final LinkedHashSet<String> rejectedGraphs = new LinkedHashSet<String>();
    private final Metric concurrentRuns = new Metric();
    private final Metric inferencePipelines = new Metric();
    private long finishedNanos = UNSET;
    private long directBufferBytes, schedulerCalibrationNanos;
    private int schedulerCalibrationCount;
    private String temporalConfig = "unavailable", frequencyConfig = "unavailable";
    private int temporalBaselineSessions, temporalFourWorkerSessions, temporalEightWorkerSessions, temporalUnobservedSessions;
    private int frequencyBaselineSessions, frequencyFourWorkerSessions, frequencyEightWorkerSessions, frequencyUnobservedSessions;
    private String[] passagePolicyRecords = new String[0];
    private long memoryStartUsed = UNSET, memoryStartLimit = UNSET, memoryEndUsed = UNSET, memoryEndLimit = UNSET;
    private long heapObservedPeak = UNSET;
    private int droppedGraphs, droppedStages, cacheHits, cacheMisses;
    private long cacheHitBytes, cacheMissBytes;
    private boolean cacheObserved, directBufferObserved, memoryUnavailable, cpuObserved, cpuUnavailable;
    private String outcome = "running";
    private Snapshot snapshot;
    private boolean candidateEvidenceRequested;
    private CandidateEvidence candidateEvidence;

    static Timing started() { return new Timing(System.nanoTime(), CPU_CLOCK.now(), PROCESS_CPU_CLOCK.now()); }
    static Measurement elapsed(Timing timing) {
        if (timing == null) return new Measurement(0L, UNSET);
        return new Measurement(Math.max(0L, System.nanoTime() - timing.wallStartedNanos), elapsedCpu(timing.cpuStartedNanos), elapsedProcessCpu(timing.processCpuStartedNanos));
    }
    static Measurement measurement(long wallNanos, long cpuNanos) { return new Measurement(Math.max(0L, wallNanos), cpuNanos < 0L ? UNSET : cpuNanos); }
    private static long elapsedCpu(long startedCpuNanos) {
        long now = CPU_CLOCK.now();
        return startedCpuNanos == UNSET || now == UNSET ? UNSET : Math.max(0L, now - startedCpuNanos);
    }

    private static long elapsedProcessCpu(long startedCpuNanos) {
        long now = PROCESS_CPU_CLOCK.now();
        return startedCpuNanos == UNSET || now == UNSET ? UNSET : Math.max(0L, now - startedCpuNanos);
    }

    synchronized void captureStartMemory() {
        if (memoryStartUsed != UNSET || memoryUnavailable) return;
        Heap heap = heap();
        if (heap == null) { memoryUnavailable = true; return; }
        memoryStartUsed = heap.used; memoryStartLimit = heap.limit; noteHeap(heap.used);
    }

    synchronized void addGateWait(long nanos) { addGateWait(measurement(nanos, UNSET)); }
    synchronized void addEngineInit(long nanos) { addEngineInit(measurement(nanos, UNSET)); }
    synchronized void addPreflight(long nanos) { addPreflight(measurement(nanos, UNSET)); }
    synchronized void addBufferInit(long nanos) { addBufferInit(measurement(nanos, UNSET)); }
    synchronized void addRuntimeInit(long nanos) { addRuntimeInit(measurement(nanos, UNSET)); }
    synchronized void addRead(long nanos) { addRead(measurement(nanos, UNSET)); }
    synchronized void addEncode(long nanos) { addEncode(measurement(nanos, UNSET)); }
    synchronized void addWrite(long nanos) { addWrite(measurement(nanos, UNSET)); }
    synchronized void addFlush(long nanos) { addFlush(measurement(nanos, UNSET)); }
    synchronized void addOutputCommit(long nanos) { addOutputCommit(measurement(nanos, UNSET)); }

    synchronized void addGateWait(Measurement timing) { stage("inference-gate-wait", timing); }
    synchronized void addEngineInit(Measurement timing) { stage("engine-init", timing); }
    synchronized void addPreflight(Measurement timing) { stage("cache-preflight", timing); }
    synchronized void addBufferInit(Measurement timing) { stage("buffer-init", timing); }
    synchronized void addRuntimeInit(Measurement timing) { stage("runtime-setup", timing); }
    synchronized void addRead(Measurement timing) { stage("pcm-read", timing); }
    synchronized void addEncode(Measurement timing) { stage("feature-encode", timing); }
    synchronized void addWrite(Measurement timing) { stage("output-write", timing); }
    synchronized void addFlush(Measurement timing) { stage("output-flush", timing); }
    synchronized void addOutputCommit(Measurement timing) { stage("output-commit", timing); }

    /** Fixed privacy-safe identity only; no dependency on the scheduler implementation. */
    synchronized void noteSchedulerConfiguration(String family, String config) {
        if (snapshot != null || config == null) return;
        boolean baseline = config.matches("cpu-i[1-6]-j1-d(?:0|4)-sequential");
        if ("temporal".equals(family) && (baseline || config.matches("cpu-i1-j1-d0-sequential-w(?:4|8)-b1"))) temporalConfig = config;
        else if ("frequency".equals(family) && (baseline || config.matches("cpu-i1-j1-d0-sequential-w(?:4|8)-b16"))) frequencyConfig = config;
    }

    /** Diagnostic opt-in only. Auxiliary observations never enter production records or totals. */
    synchronized void enableCandidateEvidence() { if (snapshot == null) candidateEvidenceRequested = true; }
    synchronized boolean wantsCandidateEvidence() { return candidateEvidenceRequested && snapshot == null; }
    synchronized void noteCandidateEvidence(CandidateEvidence evidence) {
        if (candidateEvidenceRequested && snapshot == null && candidateEvidence == null) candidateEvidence = evidence;
    }
    synchronized CandidateEvidence candidateEvidence() { return candidateEvidence; }

    /** Extra scheduler probes are observational overhead, never production graph runs/stages. */
    synchronized void noteSchedulerCalibration(long wallNanos) {
        if (snapshot != null) return;
        schedulerCalibrationNanos += Math.max(0L, wallNanos); schedulerCalibrationCount++;
    }

    /** Retain the controller's complete, bounded evidence snapshot; never arbitrary log text. */
    synchronized void notePassagePolicy(String[] evidenceRecords) {
        if (snapshot != null || evidenceRecords == null) return;
        String[] accepted = validatedPassagePolicy(evidenceRecords);
        if (accepted != null) passagePolicyRecords = accepted;
    }

    private static final String POLICY_REASONS = "(?:unmeasured|fresh-pair-required|nominated|initial-pair|qualification-wait|qualification-pair|slow-passage-recheck|lease-recheck|qualified-lease|measured-passage-improvement|qualification-pending|invalid-nomination|unfinished-pair|invalid-plan|memory-ineligible|short-job|probe-budget|missed-qualification|payback-unavailable|short-renewal|invalid-pair|pair-regression|invalid-pair-order|median-regression|invalid-timing|probe-aborted|external-baseline|cancelled|memory-fallback|thermal-guard|output-mismatch|memory-pressure|screen-budget|screen-no-win|runtime-rejected|unknown-work|control-required|slow-passage-control|control-accepted|control-regression|control-incomplete|unfinished-control)";
    private static final String POLICY_HEADER = "schema=native-passage-policy-v1 state=(?:baseline|qualified|provisional) workers=(?:0|4|8) reason=" + POLICY_REASONS +
        " extraNanos=[0-9]{1,19} extraCapNanos=360000000000 projectedAccruedSavingsNanos=[0-9]{1,19} qualificationPairs=[0-3] currentJobPairs=[0-9]{1,4} seeded=(?:true|false) activePassages=[0-9]{1,4} leasePassages=(?:8|12) paybackScope=projected-not-measured";
    private static final String POLICY_PAIR = "schema=native-passage-pair-v1 role=(?:qualification|recheck) index=[0-2] ordinal=[0-9]{1,4} candidateFirst=(?:true|false) workers=(?:4|8) baselineNanos=[0-9]{1,19} candidateNanos=[0-9]{1,19} extraNanos=[0-9]{1,19} outputSha256=[a-f0-9]{64} finite=(?:true|false) exact=(?:true|false) fullGeometry=(?:true|false) coldSessions=(?:true|false)";
    private static final String POLICY_CONTROL = "schema=native-passage-control-v1 ordinal=[0-9]{1,4} baselineNanos=[0-9]{1,19} previousBaselineNanos=[0-9]{1,19} candidateMaxNanos=[0-9]{1,19} candidateSamples=3 accepted=(?:true|false) comparisonScope=unmatched-inputs";

    /** Delimiters cannot occur in validated tokens. The durable summary needs no extra callback. */
    static String encodePassagePolicy(String[] records) {
        StringBuilder encoded = new StringBuilder();
        for (String record : records) {
            if (encoded.length() != 0) encoded.append('|');
            encoded.append(record.replace(' ', ','));
        }
        return encoded.toString();
    }

    static String[] decodePassagePolicy(String encoded) {
        if (encoded == null || encoded.length() > MAX_POLICY_RECORDS * (MAX_POLICY_RECORD_BYTES + 1)) return null;
        if (encoded.isEmpty()) return new String[0];
        String[] records = encoded.split("\\|", -1);
        for (int i = 0; i < records.length; i++) records[i] = records[i].replace(',', ' ');
        return validatedPassagePolicy(records);
    }

    private static String[] validatedPassagePolicy(String[] records) {
        if (records.length > MAX_POLICY_RECORDS) return null;
        if (records.length == 0) return new String[0];
        int qualification = 0, rechecks = 0, controls = 0;
        for (int i = 0; i < records.length; i++) {
            String record = records[i];
            if (record == null || record.length() > MAX_POLICY_RECORD_BYTES) return null;
            boolean control = i > 0 && record.matches(POLICY_CONTROL);
            if (!(control || record.matches(i == 0 ? POLICY_HEADER : POLICY_PAIR))) return null;
            for (String token : record.split(" ")) {
                int equal = token.indexOf('='); String key = token.substring(0, equal), value = token.substring(equal + 1);
                if (!"outputSha256".equals(key) && value.matches("[0-9]+")) {
                    try {
                        long number = Long.parseLong(value);
                        if (("ordinal".equals(key) && number > 4095) ||
                            (("currentJobPairs".equals(key) || "activePassages".equals(key)) && number > 4096)) return null;
                        if (control && ("baselineNanos".equals(key) || "previousBaselineNanos".equals(key) || "candidateMaxNanos".equals(key)) &&
                            (number < 1 || number > 3600000000000L)) return null;
                    } catch (NumberFormatException invalid) { return null; }
                }
            }
            if (i > 0) {
                if (control) { if (++controls > 1) return null; continue; }
                if (controls != 0) return null;
                if (record.contains(" role=qualification ")) {
                    if (rechecks != 0 || qualification >= 3 || !record.contains(" index=" + qualification + " ")) return null;
                    qualification++;
                } else if (++rechecks > 1 || !record.contains(" index=0 ")) return null;
            }
        }
        if (!records[0].contains(" qualificationPairs=" + qualification + " ")) return null;
        return records.clone();
    }

    synchronized void noteDirectBufferBytes(long bytes) { directBufferObserved = true; directBufferBytes = Math.max(directBufferBytes, nonnegative(bytes)); }
    synchronized void noteCacheModelHit(long bytes) { cacheObserved = true; cacheHits++; cacheHitBytes += nonnegative(bytes); }
    synchronized void noteCacheModelMiss(long bytes) { cacheObserved = true; cacheMisses++; cacheMissBytes += nonnegative(bytes); }

    synchronized void addModelPrepare(String graph, long nanos) { addModelPrepare(graph, measurement(nanos, UNSET)); }
    synchronized void addSessionInit(String graph, long nanos) { addSessionInit(graph, measurement(nanos, UNSET)); }
    synchronized void addTensorBind(String graph, long nanos) { addTensorBind(graph, measurement(nanos, UNSET)); }
    synchronized void addRun(String graph, long nanos) { addRun(graph, measurement(nanos, UNSET)); }
    synchronized void addPack(String graph, long nanos) { addPack(graph, measurement(nanos, UNSET)); }
    synchronized void addScatter(String graph, long nanos) { addScatter(graph, measurement(nanos, UNSET)); }
    synchronized void addDecode(String graph, long nanos) { addDecode(graph, measurement(nanos, UNSET)); }

    synchronized void addModelPrepare(String graph, Measurement timing) { Graph item = graph(graph); if (item != null) item.modelPrepare.add(timing); stage("model-init", timing); }
    synchronized void addSessionInit(String graph, Measurement timing) {
        if (snapshot != null) return;
        Graph item = graph(graph);
        if (item != null) {
            item.sessionInit.add(timing);
            if (graph.matches("block-(?:0[0-9]|1[01])-time")) {
                if ("cpu-i1-j1-d0-sequential-w4-b1".equals(temporalConfig)) temporalFourWorkerSessions++;
                else if ("cpu-i1-j1-d0-sequential-w8-b1".equals(temporalConfig)) temporalEightWorkerSessions++;
                else if (!"unavailable".equals(temporalConfig)) temporalBaselineSessions++;
                else temporalUnobservedSessions++;
            } else if (graph.matches("block-(?:0[0-9]|1[01])-frequency")) {
                if ("cpu-i1-j1-d0-sequential-w4-b16".equals(frequencyConfig)) frequencyFourWorkerSessions++;
                else if ("cpu-i1-j1-d0-sequential-w8-b16".equals(frequencyConfig)) frequencyEightWorkerSessions++;
                else if (!"unavailable".equals(frequencyConfig)) frequencyBaselineSessions++;
                else frequencyUnobservedSessions++;
            }
        }
        stage("model-init", timing);
    }
    synchronized void addTensorBind(String graph, Measurement timing) { Graph item = graph(graph); if (item != null) item.tensorBind.add(timing); stage("tensor-bind", timing); }
    synchronized void addRun(String graph, Measurement timing) { Graph item = graph(graph); if (item != null) item.run.add(timing); stage("inference", timing); }
    /**
     * One actual concurrent Run, measured on its worker. These call intervals overlap:
     * their wall time is an aggregate graph cost, and their process CPU must not be summed.
     * The coordinator records a nonoverlapping parent interval with addInferenceWave
     * or addInferencePipeline.
     */
    synchronized void addConcurrentRun(String graph, Measurement timing) {
        Graph item = graph(graph);
        if (item == null) return;
        Measurement worker = new Measurement(timing.wallNanos, timing.cpuNanos, UNSET);
        item.concurrent = true; item.run.add(worker); concurrentRuns.add(worker);
    }
    /** One coordinator interval, after every worker in this wave has retired. */
    synchronized void addInferenceWave(Measurement timing) { stage("inference", timing); }
    /**
     * One whole temporal pipeline, including initial packing, refill/scatter and worker
     * retirement. Reusable tensors must be bound before this interval starts. Nested
     * copies remain visible, but their caller CPU is deducted from the stage CPU sum.
     */
    synchronized void addInferencePipeline(Measurement timing) {
        if (snapshot != null) return;
        inferencePipelines.add(timing); stage("inference", timing);
    }
    synchronized void addPipelinePack(String graph, Measurement timing) { pipelineCopy(graph, timing, true); }
    synchronized void addPipelineScatter(String graph, Measurement timing) { pipelineCopy(graph, timing, false); }
    synchronized void addPack(String graph, Measurement timing) { Graph item = graph(graph); if (item != null) item.pack.add(timing); stage("pack", timing); }
    synchronized void addScatter(String graph, Measurement timing) { Graph item = graph(graph); if (item != null) item.scatter.add(timing); stage("scatter", timing); }
    synchronized void addDecode(String graph, Measurement timing) { Graph item = graph(graph); if (item != null) item.decode.add(timing); stage("decode", timing); }

    private void pipelineCopy(String name, Measurement timing, boolean packing) {
        if (snapshot != null) return;
        // Other native workers run during these copies. Their process CPU overlaps
        // the parent interval and cannot be attributed to copying or summed again.
        Measurement nested = new Measurement(timing.wallNanos, timing.cpuNanos, UNSET);
        Graph item = graph(name);
        if (item != null) (packing ? item.pack : item.scatter).add(nested, true);
        stage(packing ? "pack" : "scatter", nested, true);
    }

    /** Idempotent so failure/cancellation cleanup cannot mutate an already completed receipt. */
    synchronized Snapshot finish(String requestedOutcome) {
        if (snapshot != null) return snapshot;
        outcome = safeOutcome(requestedOutcome);
        finishedNanos = System.nanoTime();
        Heap heap = heap();
        if (heap == null) memoryUnavailable = true;
        else { memoryEndUsed = heap.used; memoryEndLimit = heap.limit; noteHeap(heap.used); }
        String[] records = new String[1 + stages.size() + graphs.size() + passagePolicyRecords.length];
        records[0] = summaryRecord();
        int index = 1;
        for (Stage stage : stages.values()) records[index++] = stageRecord(stage);
        for (Graph graph : graphs.values()) records[index++] = graphRecord(graph);
        for (String policy : passagePolicyRecords) records[index++] = policy;
        snapshot = new Snapshot(records);
        return snapshot;
    }

    private void stage(String name, Measurement timing) { stage(name, timing, false); }
    private void stage(String name, Measurement timing, boolean nested) {
        if (snapshot != null) return;
        Stage item = stages.get(name);
        if (item == null) {
            if (name == null || !name.matches("[a-z0-9-]{1,40}") || stages.size() >= MAX_STAGE_RECORDS) { droppedStages++; return; }
            item = new Stage(name); stages.put(name, item);
        }
        item.add(timing, nested); noteCpu(timing);
        // One bounded heap observation per named stage avoids turning high-frequency graph batches
        // into allocator probes while still exposing stage-adjacent memory pressure.
        if (item.heapObserved == UNSET && !memoryUnavailable) {
            Heap heap = heap();
            if (heap == null) memoryUnavailable = true;
            else { item.heapObserved = heap.used; noteHeap(heap.used); }
        }
    }

    private Graph graph(String name) {
        if (snapshot != null) return null;
        if (name == null || !name.matches("[a-z0-9-]{1,40}")) { noteRejected(name); return null; }
        Graph existing = graphs.get(name);
        if (existing != null) return existing;
        if (graphs.size() >= MAX_GRAPH_RECORDS) { noteRejected(name); return null; }
        Graph created = new Graph(name);
        if (!memoryUnavailable) {
            Heap heap = heap();
            if (heap == null) memoryUnavailable = true;
            else { created.heapObserved = heap.used; noteHeap(heap.used); }
        }
        graphs.put(name, created); return created;
    }

    private void noteRejected(String name) {
        String key = name == null || !name.matches("[a-z0-9-]{1,40}") ? "invalid" : name;
        if (rejectedGraphs.size() < MAX_GRAPH_RECORDS && rejectedGraphs.add(key)) droppedGraphs++;
    }
    private void noteCpu(Measurement timing) { if (timing.cpuNanos == UNSET) cpuUnavailable = true; else cpuObserved = true; }
    private void noteHeap(long used) { heapObservedPeak = heapObservedPeak == UNSET ? used : Math.max(heapObservedPeak, used); }

    private String summaryRecord() {
        Stage preprocess = combined("preprocess", "pcm-read", "feature-encode");
        Stage postprocess = combined("postprocess", "decode", "output-write", "output-flush", "output-commit");
        Stage modelInit = stages.get("model-init"), inference = stages.get("inference"), wait = stages.get("inference-gate-wait");
        Stage engineInit = stages.get("engine-init"), preflight = stages.get("cache-preflight");
        Stage bufferInit = stages.get("buffer-init"), runtimeInit = stages.get("runtime-setup");
        return "schema=native-inference-profile-v2" +
            " outcome=" + outcome +
            " wallMs=" + milliseconds(finishedNanos - startedNanos) +
            " temporalConfig=" + temporalConfig + " frequencyConfig=" + frequencyConfig +
            " temporalConfigCountScope=session-init-attempts" +
            " temporalBaselineSessionCount=" + temporalBaselineSessions +
            " temporalFourWorkerSessionCount=" + temporalFourWorkerSessions +
            " temporalEightWorkerSessionCount=" + temporalEightWorkerSessions +
            " temporalUnobservedSessionCount=" + temporalUnobservedSessions +
            " frequencyConfigCountScope=session-init-attempts" +
            " frequencyBaselineSessionCount=" + frequencyBaselineSessions +
            " frequencyFourWorkerSessionCount=" + frequencyFourWorkerSessions +
            " frequencyEightWorkerSessionCount=" + frequencyEightWorkerSessions +
            " frequencyUnobservedSessionCount=" + frequencyUnobservedSessions +
            " schedulerCalibrationWallMs=" + valueOrUnavailable(schedulerCalibrationNanos, schedulerCalibrationCount == 0) +
            " schedulerCalibrationCount=" + countOrUnavailable(schedulerCalibrationCount, schedulerCalibrationCount == 0) +
            " cpuScope=calling-thread processCpuScope=all-app-threads" +
            " cpuTelemetry=" + telemetry(cpuObserved, cpuUnavailable) +
            " instrumentedCpuMs=" + instrumentedCpu() + " instrumentedCpuScope=nonoverlapping-calling-thread" +
            " memoryTelemetry=" + (memoryUnavailable ? "unavailable" : "java-heap") +
            " acceleratorTelemetry=unavailable" +
            " waitWallMs=" + wall(wait) + " waitCpuMs=" + cpu(wait) +
            " engineInitWallMs=" + wall(engineInit) +
            " preflightWallMs=" + wall(preflight) +
            " bufferInitWallMs=" + wall(bufferInit) +
            " runtimeInitWallMs=" + wall(runtimeInit) +
            " preprocessWallMs=" + wall(preprocess) + " preprocessCpuMs=" + cpu(preprocess) +
            " modelInitWallMs=" + wall(modelInit) + " modelInitCpuMs=" + cpu(modelInit) +
            " inferenceWallMs=" + wall(inference) + " inferenceCpuMs=" + cpu(inference) +
            " inferenceThreadCpuMs=" + cpu(inference) + " inferenceProcessCpuMs=" + processCpu(inference) +
            " inferenceWallScope=critical-path inferenceThreadCpuScope=" + (concurrentRuns.count == 0 && inferencePipelines.count == 0 ? "calling-thread" : "coordinator") +
            " inferenceWorkScope=" + inferenceWorkScope() +
            " inferenceWorkerThreadCpuScope=sum-run-calling-threads" +
            " inferenceWorkerThreadCpuMs=" + valueOrUnavailable(concurrentRuns.cpuNanos, concurrentRuns.cpuUnavailable || !concurrentRuns.cpuObserved) +
            " inferenceWorkerCpuTelemetry=" + telemetry(concurrentRuns.cpuObserved, concurrentRuns.cpuUnavailable) +
            " inferenceWorkerRunCount=" + concurrentRuns.count +
            " inferenceCount=" + inferenceCount() + " sessionInitCount=" + sessionInitCount() +
            " postprocessWallMs=" + wall(postprocess) + " postprocessCpuMs=" + cpu(postprocess) +
            " directBufferTelemetry=" + (directBufferObserved ? "observed" : "unavailable") +
            " directBufferBytes=" + bytesOrUnavailable(directBufferBytes, !directBufferObserved) +
            " heapStartUsedBytes=" + bytesOrUnavailable(memoryStartUsed, memoryStartUsed == UNSET) +
            " heapStartLimitBytes=" + bytesOrUnavailable(memoryStartLimit, memoryStartLimit == UNSET) +
            " heapEndUsedBytes=" + bytesOrUnavailable(memoryEndUsed, memoryEndUsed == UNSET) +
            " heapEndLimitBytes=" + bytesOrUnavailable(memoryEndLimit, memoryEndLimit == UNSET) +
            " heapObservedPeakBytes=" + bytesOrUnavailable(heapObservedPeak, heapObservedPeak == UNSET) +
            " cacheTelemetry=" + (cacheObserved ? "observed" : "unavailable") +
            " cacheModelHits=" + countOrUnavailable(cacheHits, !cacheObserved) +
            " cacheModelMisses=" + countOrUnavailable(cacheMisses, !cacheObserved) +
            " cacheHitBytes=" + bytesOrUnavailable(cacheHitBytes, !cacheObserved) +
            " cacheMissBytes=" + bytesOrUnavailable(cacheMissBytes, !cacheObserved) +
            " stageRecords=" + stages.size() + " graphRecords=" + graphs.size() +
            " droppedStageRecords=" + droppedStages + " droppedGraphRecords=" + droppedGraphs +
            (passagePolicyRecords.length == 0 ? "" : " passagePolicy=" + encodePassagePolicy(passagePolicyRecords));
    }

    private int sessionInitCount() { int count = 0; for (Graph graph : graphs.values()) count += graph.sessionInit.count; return count; }
    private int inferenceCount() { int count = 0; for (Graph graph : graphs.values()) count += graph.run.count; return count; }
    private String inferenceWorkScope() { return inferencePipelines.count == 0 ? "run-and-wave-coordination" : "run-and-pipeline-coordination"; }
    private String instrumentedCpu() {
        if (!cpuObserved || anyCpuUnavailable(stages.values())) return "unavailable";
        long nestedCpu = 0L; int nestedCount = 0;
        for (Stage stage : stages.values()) { nestedCpu += stage.nestedCpuNanos; nestedCount += stage.nestedCount; }
        // Missing parents and impossible nesting are invalid observations, not zero CPU.
        if (nestedCount > 0 && (inferencePipelines.count == 0 || !inferencePipelines.cpuObserved ||
                inferencePipelines.cpuUnavailable || nestedCpu > inferencePipelines.cpuNanos)) return "unavailable";
        long total = sumCpu(stages.values());
        return nestedCpu > total ? "unavailable" : String.valueOf(milliseconds(total - nestedCpu));
    }
    private static String processCpu(Metric metric) {
        return metric == null ? "unavailable" : valueOrUnavailable(metric.processCpuNanos, metric.processCpuUnavailable || !metric.processCpuObserved);
    }

    private String stageRecord(Stage stage) {
        return "schema=native-inference-stage-v1" +
            " stage=" + stage.name + " samples=" + stage.samples +
            " wallScope=" + ("inference".equals(stage.name) ? "critical-path" : intervalScope(stage)) +
            ("inference".equals(stage.name) ? " workScope=" + inferenceWorkScope() : "") +
            " cpuScope=calling-thread processCpuScope=" + (stage.nestedCount == 0 ? "all-app-threads" : "unavailable-overlapping-intervals") +
            " processCpuMs=" + processCpu(stage) +
            " wallMs=" + milliseconds(stage.wallNanos) +
            " cpuTelemetry=" + telemetry(stage.cpuObserved, stage.cpuUnavailable) +
            " cpuMs=" + valueOrUnavailable(stage.cpuNanos, stage.cpuUnavailable || !stage.cpuObserved) +
            " heapTelemetry=" + (stage.heapObserved == UNSET ? "unavailable" : "java-heap") +
            " heapObservedBytes=" + bytesOrUnavailable(stage.heapObserved, stage.heapObserved == UNSET);
    }

    private static String graphRecord(Graph graph) {
        return "schema=native-inference-graph-v2" +
            " graph=" + graph.name +
            " graphWallScope=" + (graph.concurrent ? "aggregate-call" : "sequential-intervals") +
            " runCpuScope=" + (graph.concurrent ? "run-calling-threads" : "calling-thread") +
            " runProcessCpuScope=" + (graph.concurrent ? "unavailable-overlapping-intervals" : "all-app-threads") +
            " packWallScope=" + intervalScope(graph.pack) + " scatterWallScope=" + intervalScope(graph.scatter) +
            " packProcessCpuScope=" + copyProcessCpuScope(graph.pack) + " scatterProcessCpuScope=" + copyProcessCpuScope(graph.scatter) +
            " cpuTelemetry=" + telemetry(graph.cpuObserved(), graph.cpuUnavailable()) +
            " heapTelemetry=" + (graph.heapObserved == UNSET ? "unavailable" : "java-heap") +
            " heapObservedBytes=" + bytesOrUnavailable(graph.heapObserved, graph.heapObserved == UNSET) +
            metric("modelPrepare", graph.modelPrepare) + metric("sessionInit", graph.sessionInit) +
            metric("tensorBind", graph.tensorBind) + metric("run", graph.run) +
            metric("pack", graph.pack) + metric("scatter", graph.scatter) + metric("decode", graph.decode);
    }

    private static String metric(String name, Metric value) {
        return " " + name + "Count=" + value.count + " " + name + "WallMs=" + wall(value) +
            " " + name + "CpuMs=" + valueOrUnavailable(value.cpuNanos, value.cpuUnavailable || !value.cpuObserved) +
            " " + name + "ProcessCpuMs=" + processCpu(value);
    }
    private static String intervalScope(Metric value) {
        return value.count == 0 ? "unavailable" : value.nestedCount == 0 ? "sequential-intervals" :
            value.nestedCount == value.count ? "nested-in-inference-pipeline" : "mixed-nested-and-sequential-intervals";
    }
    private static String copyProcessCpuScope(Metric value) {
        return value.count == 0 ? "unavailable" : value.nestedCount == 0 ? "all-app-threads" : "unavailable-overlapping-intervals";
    }
    private Stage combined(String name, String... names) {
        Stage result = null;
        for (String item : names) {
            Stage stage = stages.get(item);
            if (stage != null) {
                if (result == null) result = new Stage(name);
                result.merge(stage);
            }
        }
        return result;
    }
    private static String wall(Stage stage) { return stage == null ? "unavailable" : String.valueOf(milliseconds(stage.wallNanos)); }
    private static String wall(Metric metric) { return metric.count == 0 ? "unavailable" : String.valueOf(milliseconds(metric.wallNanos)); }
    private static String cpu(Stage stage) { return stage == null ? "unavailable" : valueOrUnavailable(stage.cpuNanos, stage.cpuUnavailable || !stage.cpuObserved); }
    private static long sumCpu(Iterable<Stage> values) { long total = 0L; for (Stage value : values) total += value.cpuNanos; return total; }
    private static boolean anyCpuUnavailable(Iterable<Stage> values) { for (Stage value : values) if (value.cpuUnavailable || !value.cpuObserved) return true; return false; }
    private static long nonnegative(long value) { return Math.max(0L, value); }
    private static long milliseconds(long nanos) { return nonnegative(nanos) / NANOS_PER_MILLISECOND; }
    private static String valueOrUnavailable(long nanos, boolean unavailable) { return unavailable ? "unavailable" : String.valueOf(milliseconds(nanos)); }
    private static String bytesOrUnavailable(long value, boolean unavailable) { return unavailable ? "unavailable" : String.valueOf(value); }
    private static String countOrUnavailable(int value, boolean unavailable) { return unavailable ? "unavailable" : String.valueOf(value); }
    private static String telemetry(boolean available, boolean unavailable) { return !available ? "unavailable" : unavailable ? "partial" : "available"; }
    private static String safeOutcome(String value) { return value != null && value.matches("(?:completed|failed|cancelled|released)") ? value : "unknown"; }

    static final class Timing {
        final long wallStartedNanos, cpuStartedNanos, processCpuStartedNanos;
        Timing(long wallStartedNanos, long cpuStartedNanos, long processCpuStartedNanos) { this.wallStartedNanos = wallStartedNanos; this.cpuStartedNanos = cpuStartedNanos; this.processCpuStartedNanos = processCpuStartedNanos; }
    }
    static final class Measurement {
        final long wallNanos, cpuNanos, processCpuNanos;
        Measurement(long wallNanos, long cpuNanos) { this(wallNanos, cpuNanos, UNSET); }
        Measurement(long wallNanos, long cpuNanos, long processCpuNanos) { this.wallNanos = nonnegative(wallNanos); this.cpuNanos = cpuNanos < 0L ? UNSET : cpuNanos; this.processCpuNanos = processCpuNanos < 0L ? UNSET : processCpuNanos; }
    }
    static final class Snapshot {
        private final String[] records;
        Snapshot(String[] records) { this.records = records.clone(); }
        int recordCount() { return records.length; }
        String record(int index) { return records[index]; }
        String[] records() { return records.clone(); }
    }
    /** Cumulative direct model-I/O observations; reads include interrupted attempts. */
    static final class ModelSetup {
        final int verifiedModels;
        final long extractionAttempts, extractionBytesRead, existingFileChecksumAttempts, existingFileChecksumBytesRead;
        ModelSetup(int verified, long extractions, long extractedBytes, long checksums, long checksumBytes) {
            if (verified < 0 || verified > MAX_GRAPH_RECORDS || extractions < 0 || extractedBytes < 0 || checksums < 0 || checksumBytes < 0)
                throw new IllegalArgumentException("Invalid model setup observation");
            verifiedModels = verified; extractionAttempts = extractions; extractionBytesRead = extractedBytes;
            existingFileChecksumAttempts = checksums; existingFileChecksumBytesRead = checksumBytes;
        }
    }
    static final class ArmEvidence {
        final String outcome;
        final long armWallNanos;
        final ModelSetup before, after;
        ArmEvidence(String outcome, long nanos, ModelSetup before, ModelSetup after) {
            if (!("completed".equals(outcome) || "cancelled".equals(outcome) || "failed".equals(outcome)) ||
                ("completed".equals(outcome) ? nanos <= 0 : nanos != -1) || before == null || after == null ||
                after.extractionAttempts < before.extractionAttempts || after.extractionBytesRead < before.extractionBytesRead ||
                after.existingFileChecksumAttempts < before.existingFileChecksumAttempts || after.existingFileChecksumBytesRead < before.existingFileChecksumBytesRead)
                throw new IllegalArgumentException("Invalid paired arm observation");
            this.outcome = outcome; armWallNanos = nanos; this.before = before; this.after = after;
        }
    }
    static final class CandidateEvidence {
        final int ordinal, workers, commonPreflightVerifiedModelCount;
        final boolean candidateFirst;
        final ArmEvidence baseline, candidate;
        final Snapshot profile;
        CandidateEvidence(int ordinal, int workers, boolean first, int commonVerified, ArmEvidence baseline,
                ArmEvidence candidate, Snapshot profile) {
            if (ordinal < 0 || ordinal > 4095 || (workers != 4 && workers != 8) || commonVerified < 0 || commonVerified > MAX_GRAPH_RECORDS ||
                candidate == null || profile == null || profile.recordCount() < 1 || profile.recordCount() > MAX_RECORDS)
                throw new IllegalArgumentException("Invalid candidate evidence");
            this.ordinal = ordinal; this.workers = workers; candidateFirst = first;
            commonPreflightVerifiedModelCount = commonVerified; this.baseline = baseline; this.candidate = candidate; this.profile = profile;
        }
    }
    private static class Metric {
        long wallNanos, cpuNanos, processCpuNanos, nestedCpuNanos; int count, nestedCount; boolean cpuObserved, cpuUnavailable, processCpuObserved, processCpuUnavailable;
        void add(Measurement timing) { add(timing, false); }
        void add(Measurement timing, boolean nested) {
            wallNanos += timing.wallNanos; count++;
            if (nested) { nestedCount++; if (timing.cpuNanos != UNSET) nestedCpuNanos += timing.cpuNanos; }
            if (timing.cpuNanos == UNSET) cpuUnavailable = true; else { cpuObserved = true; cpuNanos += timing.cpuNanos; }
            if (timing.processCpuNanos == UNSET) processCpuUnavailable = true; else { processCpuObserved = true; processCpuNanos += timing.processCpuNanos; }
        }
    }
    private static final class Stage extends Metric {
        final String name; long heapObserved = UNSET; int samples;
        Stage(String name) { this.name = name; }
        @Override void add(Measurement timing, boolean nested) { super.add(timing, nested); samples++; }
        void merge(Stage other) { wallNanos += other.wallNanos; cpuNanos += other.cpuNanos; count += other.count; samples += other.samples; nestedCount += other.nestedCount; nestedCpuNanos += other.nestedCpuNanos; cpuObserved |= other.cpuObserved; cpuUnavailable |= other.cpuUnavailable; processCpuNanos += other.processCpuNanos; processCpuObserved |= other.processCpuObserved; processCpuUnavailable |= other.processCpuUnavailable; heapObserved = heapObserved == UNSET ? other.heapObserved : other.heapObserved == UNSET ? heapObserved : Math.max(heapObserved, other.heapObserved); }
    }
    private static final class Graph {
        final String name; long heapObserved = UNSET; boolean concurrent;
        final Metric modelPrepare = new Metric(), sessionInit = new Metric(), tensorBind = new Metric(), run = new Metric(), pack = new Metric(), scatter = new Metric(), decode = new Metric();
        Graph(String name) { this.name = name; }
        boolean cpuObserved() { return modelPrepare.cpuObserved || sessionInit.cpuObserved || tensorBind.cpuObserved || run.cpuObserved || pack.cpuObserved || scatter.cpuObserved || decode.cpuObserved; }
        boolean cpuUnavailable() { return modelPrepare.cpuUnavailable || sessionInit.cpuUnavailable || tensorBind.cpuUnavailable || run.cpuUnavailable || pack.cpuUnavailable || scatter.cpuUnavailable || decode.cpuUnavailable; }
    }
    private static final class Heap { final long used, limit; Heap(long used, long limit) { this.used = used; this.limit = limit; } }
    private Heap heap() {
        try { Runtime runtime = Runtime.getRuntime(); return new Heap(Math.max(0L, runtime.totalMemory() - runtime.freeMemory()), Math.max(0L, runtime.maxMemory())); }
        catch (Throwable ignored) { return null; }
    }
    private interface CpuClock { long now(); }
    private static CpuClock resolveCpuClock() {
        final CpuClock android = androidCpuClock();
        final CpuClock host = hostCpuClock();
        return new CpuClock() { @Override public long now() {
            long value = android.now(); return value == UNSET ? host.now() : value;
        }};
    }
    private static CpuClock processCpuClock() {
        final CpuClock android = androidProcessCpuClock();
        // Android stub jars may expose this method but throw when invoked on a host JVM.
        // Choose a working real clock once so an interval never mixes different clock sources.
        return android.now() != UNSET ? android : hostProcessCpuClock();
    }
    private static CpuClock androidProcessCpuClock() {
        final Method android = staticMethod("android.os.Process", "getElapsedCpuTime");
        if (android != null) return new CpuClock() { @Override public long now() {
            long milliseconds = invokeLong(android, null);
            return milliseconds < 0 || milliseconds > Long.MAX_VALUE / NANOS_PER_MILLISECOND ? UNSET : milliseconds * NANOS_PER_MILLISECOND;
        }};
        return unavailableCpuClock();
    }
    private static CpuClock hostProcessCpuClock() {
        // Host profiling uses the real process clock when exported by the operating-system bean.
        try {
            Object bean = Class.forName("java.lang.management.ManagementFactory").getMethod("getOperatingSystemMXBean").invoke(null);
            final Object operatingSystem = bean;
            final Method processTime = Class.forName("com.sun.management.OperatingSystemMXBean").getMethod("getProcessCpuTime");
            return new CpuClock() { @Override public long now() { return invokeLong(processTime, operatingSystem); } };
        } catch (Throwable ignored) { return unavailableCpuClock(); }
    }

    private static CpuClock androidCpuClock() {
        final Method android = staticMethod("android.os.Debug", "threadCpuTimeNanos");
        if (android != null) return new CpuClock() { @Override public long now() { return invokeLong(android, null); } };
        return unavailableCpuClock();
    }
    private static CpuClock hostCpuClock() {
        try {
            Class<?> management = Class.forName("java.lang.management.ManagementFactory");
            final Object bean = management.getMethod("getThreadMXBean").invoke(null);
            Class<?> type = Class.forName("java.lang.management.ThreadMXBean");
            Object supported = type.getMethod("isCurrentThreadCpuTimeSupported").invoke(bean);
            if (!Boolean.TRUE.equals(supported)) return unavailableCpuClock();
            Method enabled = type.getMethod("isThreadCpuTimeEnabled");
            // Observation must not modify a process-wide JVM switch. If the host disables this
            // clock, report it as unavailable rather than changing inference conditions.
            if (!Boolean.TRUE.equals(enabled.invoke(bean))) return unavailableCpuClock();
            final Method current = type.getMethod("getCurrentThreadCpuTime");
            return new CpuClock() { @Override public long now() { return invokeLong(current, bean); } };
        } catch (Throwable ignored) { return unavailableCpuClock(); }
    }
    private static Method staticMethod(String className, String name) {
        try { return Class.forName(className).getMethod(name); } catch (Throwable ignored) { return null; }
    }
    private static long invokeLong(Method method, Object receiver) {
        try { Object value = method.invoke(receiver); return value instanceof Long && ((Long)value).longValue() >= 0L ? ((Long)value).longValue() : UNSET; }
        catch (Throwable ignored) { return UNSET; }
    }
    private static CpuClock unavailableCpuClock() { return new CpuClock() { @Override public long now() { return UNSET; } }; }
}
