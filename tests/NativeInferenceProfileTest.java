package com.cyberbasslord.lightforge;

/** Host-only contract for bounded, privacy-safe native inference profiling. */
public final class NativeInferenceProfileTest {
    public static void main(String[] args) {
        NativeInferenceProfile profile = new NativeInferenceProfile();
        profile.captureStartMemory();
        NativeInferenceProfile.Measurement measured = NativeInferenceProfile.measurement(1000000L, 500000L);
        profile.addGateWait(measured); profile.addEngineInit(measured); profile.addPreflight(measured);
        profile.addBufferInit(measured); profile.addRuntimeInit(measured); profile.addRead(measured);
        profile.addEncode(measured); profile.addWrite(measured); profile.addFlush(measured);
        profile.addOutputCommit(measured); profile.noteDirectBufferBytes(123456L);
        profile.noteCacheModelHit(10L); profile.noteCacheModelHit(20L); profile.noteCacheModelMiss(30L);
        for (int i = 0; i < 30; i++) {
            String graph = "graph-" + i;
            profile.addModelPrepare(graph, measured); profile.addSessionInit(graph, measured);
            profile.addTensorBind(graph, measured); profile.addRun(graph, measured);
            profile.addPack(graph, measured); profile.addScatter(graph, measured); profile.addDecode(graph, measured);
        }
        NativeInferenceProfile.Snapshot first = profile.finish("completed");
        NativeInferenceProfile.Snapshot second = profile.finish("failed");
        require(first.recordCount() <= NativeInferenceProfile.MAX_RECORDS, "bounded summary, stages and graphs");
        require(second.recordCount() == first.recordCount() && first.record(0).equals(second.record(0)), "finish is immutable");
        String summary = first.record(0);
        require(summary.contains("schema=native-inference-profile-v2") && summary.contains("outcome=completed") &&
            summary.contains("cpuTelemetry=available") && summary.contains("memoryTelemetry=java-heap") &&
            summary.contains("acceleratorTelemetry=unavailable") && summary.contains("directBufferBytes=123456") &&
            summary.contains("cacheTelemetry=observed") && summary.contains("cacheModelHits=2") &&
            summary.contains("cacheModelMisses=1") && summary.contains("cacheHitBytes=30") && summary.contains("cacheMissBytes=30") &&
            summary.contains("graphRecords=27") && summary.contains("droppedGraphRecords=3") &&
            summary.contains("inferenceCount=27"), "summary fields and accepted graph call counts");
        int stages = 0, graphs = 0;
        for (int i = 1; i < first.recordCount(); i++) {
            String record = first.record(i);
            require(record.indexOf('"') < 0 && record.indexOf('\n') < 0, "safe bounded record " + i);
            if (record.startsWith("schema=native-inference-stage-v1")) {
                stages++;
                require(record.contains("wallMs=") && record.contains("cpuTelemetry=available") && record.contains("cpuMs=") &&
                    record.contains("heapTelemetry=java-heap"), "stage telemetry " + i);
            } else {
                graphs++;
                require(record.startsWith("schema=native-inference-graph-v2 graph=graph-") && record.contains("runCount=1 runWallMs=1") &&
                    record.contains("runCpuMs=0") && record.contains("heapTelemetry=java-heap"), "graph telemetry " + i);
            }
        }
        require(stages == NativeInferenceProfile.MAX_STAGE_RECORDS && graphs == NativeInferenceProfile.MAX_GRAPH_RECORDS,
            "fixed stage and graph inventory");

        NativeInferenceProfile unavailable = new NativeInferenceProfile();
        unavailable.addGateWait(1000000L);
        NativeInferenceProfile.Snapshot unavailableSnapshot = unavailable.finish("completed");
        String unavailableSummary = unavailableSnapshot.record(0);
        require(unavailableSummary.contains("cpuTelemetry=unavailable") && unavailableSummary.contains("instrumentedCpuMs=unavailable") &&
            unavailableSummary.contains("acceleratorTelemetry=unavailable") && unavailableSummary.contains("directBufferTelemetry=unavailable") &&
            unavailableSummary.contains("directBufferBytes=unavailable") && unavailableSummary.contains("cacheTelemetry=unavailable") &&
            unavailableSummary.contains("cacheModelHits=unavailable") && unavailableSummary.contains("cacheModelMisses=unavailable") &&
            unavailableSummary.contains("heapStartUsedBytes=unavailable"),
            "unavailable telemetry is explicit rather than fabricated");
        require(unavailableSnapshot.record(1).contains("cpuTelemetry=unavailable") &&
            unavailableSnapshot.record(1).contains("cpuMs=unavailable"), "stage CPU unavailability is explicit");
        String emptySummary = new NativeInferenceProfile().finish("cancelled").record(0);
        require(emptySummary.contains("cpuTelemetry=unavailable") && emptySummary.contains("instrumentedCpuMs=unavailable") &&
            emptySummary.contains("waitWallMs=unavailable") && emptySummary.contains("preprocessWallMs=unavailable") &&
            emptySummary.contains("cacheModelHits=unavailable"), "empty profile does not fabricate zero-valued telemetry");
        NativeInferenceProfile partial = new NativeInferenceProfile();
        partial.addModelPrepare("front", measured);
        String partialGraph = partial.finish("failed").record(2);
        require(partialGraph.contains("modelPrepareCount=1") && partialGraph.contains("modelPrepareWallMs=1") &&
            partialGraph.contains("sessionInitCount=0") && partialGraph.contains("sessionInitWallMs=unavailable") &&
            partialGraph.contains("sessionInitCpuMs=unavailable"), "unexecuted graph metrics are unavailable rather than zero");
        NativeInferenceProfile process = new NativeInferenceProfile();
        process.addRun("front", new NativeInferenceProfile.Measurement(100000000L, 25000000L, 175000000L));
        process.addSessionInit("front", measured);
        process.noteSchedulerCalibration(20000000L); process.noteSchedulerCalibration(5000000L);
        String processSummary = process.finish("completed").record(0);
        require(processSummary.contains("cpuScope=calling-thread processCpuScope=all-app-threads") &&
            processSummary.contains("inferenceThreadCpuMs=25 inferenceProcessCpuMs=175") &&
            processSummary.contains("inferenceCount=1 sessionInitCount=1"), "CPU scopes and kernel counts are explicit");
        require(processSummary.contains("schedulerCalibrationWallMs=25 schedulerCalibrationCount=2") && process.finish("completed").recordCount() == 4, "calibration is counted separately without expanding stage or graph topology");
        require(emptySummary.contains("schedulerCalibrationWallMs=unavailable schedulerCalibrationCount=unavailable"), "unobserved scheduler calibration is not a fabricated zero");
        require(unavailableSummary.contains("inferenceProcessCpuMs=unavailable"), "missing process clock is unavailable");
        NativeInferenceProfile mixedProcess = new NativeInferenceProfile();
        mixedProcess.addRun("front", new NativeInferenceProfile.Measurement(100000000L, 25000000L, 175000000L));
        mixedProcess.addRun("front", measured);
        require(mixedProcess.finish("completed").record(0).contains("inferenceProcessCpuMs=unavailable"), "partial process CPU is not presented as complete");
        checkConcurrentAccounting();
        checkPipelineAccounting();
        checkB1Topology(false);
        checkB1Topology(true);
        NativeInferenceProfile configurations = new NativeInferenceProfile();
        configurations.noteSchedulerConfiguration("temporal", "cpu-i4-j1-d0-sequential");
        configurations.noteSchedulerConfiguration("frequency", "cpu-i4-j1-d0-sequential");
        configurations.noteSchedulerConfiguration("temporal", "cpu-i2-j1-d4-sequential");
        configurations.noteSchedulerConfiguration("frequency", "cpu-i6-j1-d4-sequential");
        configurations.noteSchedulerConfiguration("temporal", "private-track-name");
        configurations.noteSchedulerConfiguration("frequency", "cpu-i99-j1-d4-sequential");
        configurations.noteSchedulerConfiguration("unknown-family", "cpu-i1-j1-d0-sequential");
        configurations.noteSchedulerConfiguration(null, "cpu-i1-j1-d0-sequential");
        configurations.noteSchedulerConfiguration("temporal", null);
        NativeInferenceProfile.Snapshot configurationReceipt = configurations.finish("completed");
        require(configurationReceipt.recordCount() == 1 && configurationReceipt.record(0).contains(
            "temporalConfig=cpu-i2-j1-d4-sequential frequencyConfig=cpu-i6-j1-d4-sequential"),
            "latest valid family configurations survive unknown values without creating graph or stage records");
        configurations.noteSchedulerConfiguration("temporal", "cpu-i1-j1-d0-sequential");
        require(configurationReceipt.record(0).equals(configurations.finish("completed").record(0)), "final configuration receipt remains immutable");
        require(emptySummary.contains("temporalConfig=unavailable frequencyConfig=unavailable"), "unobserved scheduler identity is not invented");
        NativeInferenceProfile parallelConfiguration = new NativeInferenceProfile();
        parallelConfiguration.noteSchedulerConfiguration("temporal", "cpu-i1-j1-d0-sequential-w4-b1");
        parallelConfiguration.noteSchedulerConfiguration("temporal", "cpu-i1-j1-d0-sequential-w8-b1");
        parallelConfiguration.noteSchedulerConfiguration("frequency", "cpu-i4-j1-d0-sequential");
        for (String invalid : new String[]{"cpu-i1-j1-d0-sequential-w2-b1", "cpu-i1-j1-d0-sequential-w16-b1",
                "cpu-i1-j1-d0-sequential-w8-b4", "cpu-i2-j1-d0-sequential-w8-b1", "cpu-i1-j1-d4-sequential-w8-b1"})
            parallelConfiguration.noteSchedulerConfiguration("temporal", invalid);
        parallelConfiguration.noteSchedulerConfiguration("frequency", "cpu-i1-j1-d0-sequential-w8-b1");
        require(parallelConfiguration.finish("completed").record(0).contains(
            "temporalConfig=cpu-i1-j1-d0-sequential-w8-b1 frequencyConfig=cpu-i4-j1-d0-sequential"),
            "only supported parallel temporal configurations are observable");
        checkConfigurationCounts();
        checkPassagePolicy();
        if (args.length > 0 && "require-process-clock".equals(args[0])) {
            NativeInferenceProfile.Timing realClock = NativeInferenceProfile.started();
            require(realClock.processCpuStartedNanos >= 0, "real host process clock survives a throwing Android stub");
            require(NativeInferenceProfile.elapsed(realClock).processCpuNanos >= 0, "elapsed process CPU uses the same available real clock");
        }
        System.out.println("NativeInferenceProfile: bounded stage/graph telemetry, cache evidence and unavailable-metric checks passed.");
    }
    private static void checkConfigurationCounts() {
        NativeInferenceProfile profile = new NativeInferenceProfile();
        profile.noteSchedulerConfiguration("temporal", "cpu-i4-j1-d0-sequential");
        profile.addSessionInit("front", ms(1, 1, 1));
        for (int graph = 0; graph < 12; graph++) {
            profile.noteSchedulerConfiguration("temporal", graph < 3 ? "cpu-i4-j1-d0-sequential" :
                graph < 7 ? "cpu-i1-j1-d0-sequential-w4-b1" : "cpu-i1-j1-d0-sequential-w8-b1");
            profile.addSessionInit(String.format(java.util.Locale.ROOT, "block-%02d-time", graph), ms(1, 1, 1));
        }
        String summary = profile.finish("completed").record(0);
        require(summary.contains("temporalConfigCountScope=session-init-attempts temporalBaselineSessionCount=3 temporalFourWorkerSessionCount=4 temporalEightWorkerSessionCount=5 temporalUnobservedSessionCount=0"),
            "mixed session counts exclude the initial identity observation and non-temporal sessions");
        profile.addSessionInit("block-00-time", ms(1, 1, 1));
        require(summary.equals(profile.finish("completed").record(0)), "terminal session counters cannot change");
        NativeInferenceProfile unobserved = new NativeInferenceProfile();
        unobserved.addSessionInit("block-00-time", ms(1, 1, 1));
        unobserved.addSessionInit("block-00-time", ms(1, 1, 1));
        require(unobserved.finish("failed").record(0).contains("temporalUnobservedSessionCount=2"),
            "missing configuration remains explicitly unobserved and repeated initialization attempts are counted");
    }
    static String[] policyEvidence() {
        String[] records = new String[5];
        records[0] = "schema=native-passage-policy-v1 state=qualified workers=8 reason=measured-passage-improvement extraNanos=240000000000 extraCapNanos=360000000000 projectedAccruedSavingsNanos=0 qualificationPairs=3 currentJobPairs=4 seeded=false activePassages=0 leasePassages=8 paybackScope=projected-not-measured";
        for (int i = 0; i < 4; i++) records[i + 1] = "schema=native-passage-pair-v1 role=" + (i == 3 ? "recheck" : "qualification") +
            " index=" + (i == 3 ? 0 : i) + " ordinal=" + (i * 4) + " candidateFirst=" + ((i & 1) != 0) +
            " workers=8 baselineNanos=75000000000 candidateNanos=50000000000 extraNanos=60000000000 outputSha256=" +
            "0000000000000000000000000000000000000000000000000000000000000000" +
            " finite=true exact=true fullGeometry=true coldSessions=true";
        return records;
    }
    private static void checkPassagePolicy() {
        NativeInferenceProfile profile = new NativeInferenceProfile();
        String[] evidence = policyEvidence();
        String encoded = NativeInferenceProfile.encodePassagePolicy(evidence);
        profile.notePassagePolicy(evidence);
        evidence[0] = "private-song-name";
        for (String[] invalid : new String[][]{
                new String[]{"schema=native-passage-policy-v1 title=private"},
                new String[]{policyEvidence()[0].replace("workers=8", "workers=16")},
                new String[]{policyEvidence()[0].replace("measured-passage-improvement", "private-song-name")},
                new String[]{policyEvidence()[0] + "\nprivate"},
                new String[NativeInferenceProfile.MAX_POLICY_RECORDS + 1]}) profile.notePassagePolicy(invalid);
        NativeInferenceProfile.Snapshot result = profile.finish("completed");
        require(result.recordCount() == 6 && result.record(0).contains(" passagePolicy=" + encoded),
            "complete policy evidence is cloned and retained in the terminal summary and readable records");
        require(result.record(1).equals(policyEvidence()[0]) && result.record(5).contains("role=recheck"),
            "invalid or incomplete evidence cannot erase the prior complete snapshot");
        require(result.record(0).length() < 8192 && encoded.length() <= NativeInferenceProfile.MAX_POLICY_RECORDS * (NativeInferenceProfile.MAX_POLICY_RECORD_BYTES + 1),
            "terminal summary and compact policy respect durable receipt bounds");
        require(java.util.Arrays.equals(policyEvidence(), NativeInferenceProfile.decodePassagePolicy(encoded)),
            "safe tokens round trip including numeric-only SHA256 hashes");
        for (String invalid : new String[]{encoded + "|", encoded.replace("finite=true", "finite=private"),
                encoded.replace("baselineNanos=75000000000", "baselineNanos=9223372036854775808"),
                encoded.replace("ordinal=12", "ordinal=4096"), encoded.replace("outputSha256=", "title=")})
            require(NativeInferenceProfile.decodePassagePolicy(invalid) == null, "malformed/unsafe policy payload is rejected");
        profile.notePassagePolicy(new String[0]);
        require(result.record(0).equals(profile.finish("failed").record(0)), "terminal policy evidence is immutable");
        String[] returned = result.records(); returned[1] = "changed";
        require(result.record(1).equals(policyEvidence()[0]), "callers cannot mutate exported policy snapshots");
    }
    private static NativeInferenceProfile.Measurement ms(long wall, long thread, long process) {
        return new NativeInferenceProfile.Measurement(wall * 1000000L, thread < 0 ? -1 : thread * 1000000L,
            process < 0 ? -1 : process * 1000000L);
    }
    private static String record(NativeInferenceProfile.Snapshot snapshot, String identity) {
        for (String value : snapshot.records()) if (value.contains(identity)) return value;
        throw new AssertionError("Missing record: " + identity);
    }
    private static void checkConcurrentAccounting() {
        NativeInferenceProfile profile = new NativeInferenceProfile();
        profile.addRun("front", ms(5, 2, 4));
        profile.addConcurrentRun("block-00-time", ms(100, 60, 180));
        profile.addConcurrentRun("block-00-time", ms(100, 70, 190));
        profile.addInferenceWave(ms(110, 3, 150));
        profile.addConcurrentRun("block-00-time", ms(40, 30, 90));
        profile.addInferenceWave(ms(45, 2, 50));
        profile.addRun("block-00-frequency", ms(10, 4, 8));
        NativeInferenceProfile.Snapshot receipt = profile.finish("completed");
        String summary = receipt.record(0);
        require(summary.contains("inferenceWallMs=170 inferenceCpuMs=11") &&
            summary.contains("inferenceThreadCpuMs=11 inferenceProcessCpuMs=212"),
            "coordinator waves and serial intervals form the critical path without double counting workers");
        require(summary.contains("inferenceWallScope=critical-path inferenceThreadCpuScope=coordinator") &&
            summary.contains("inferenceWorkerThreadCpuScope=sum-run-calling-threads") &&
            summary.contains("inferenceWorkerThreadCpuMs=160 inferenceWorkerCpuTelemetry=available") &&
            summary.contains("inferenceWorkerRunCount=3 inferenceCount=5"),
            "worker CPU is separate from coordinator CPU and actual run count differs from wave count");
        String time = record(receipt, "graph=block-00-time ");
        require(time.contains("graphWallScope=aggregate-call runCpuScope=run-calling-threads") &&
            time.contains("runProcessCpuScope=unavailable-overlapping-intervals") &&
            time.contains("runCount=3 runWallMs=240 runCpuMs=160 runProcessCpuMs=unavailable"),
            "overlapping graph wall is explicitly aggregate and overlapping process CPU is discarded");
        require(record(receipt, "stage=inference ").contains("samples=4 wallScope=critical-path"),
            "inference stage samples are intervals, not graph run counts");
        require(record(receipt, "graph=front ").contains("graphWallScope=sequential-intervals runCpuScope=calling-thread"),
            "serial graph metrics retain their original timing scope");
        profile.addConcurrentRun("block-00-time", ms(1000, 1000, 1000));
        profile.addInferenceWave(ms(1000, 1000, 1000));
        require(summary.equals(profile.finish("cancelled").record(0)), "parallel observations cannot mutate a finalized receipt");

        NativeInferenceProfile missingWave = new NativeInferenceProfile();
        missingWave.addConcurrentRun("block-00-time", ms(100, 60, 180));
        missingWave.addConcurrentRun("block-00-time", ms(100, -1, 180));
        String partial = missingWave.finish("cancelled").record(0);
        require(partial.contains("inferenceWallMs=unavailable inferenceCpuMs=unavailable") &&
            partial.contains("inferenceProcessCpuMs=unavailable") &&
            partial.contains("inferenceWorkerThreadCpuMs=unavailable inferenceWorkerCpuTelemetry=partial") &&
            partial.contains("inferenceWorkerRunCount=2 inferenceCount=2"),
            "worker-only and partial-clock observations never invent a critical-path or complete CPU measurement");
    }
    private static void checkPipelineAccounting() {
        NativeInferenceProfile profile = new NativeInferenceProfile();
        profile.addRun("front", ms(10, 1, 2));
        profile.addTensorBind("block-00-time", ms(3, 1, 2));
        profile.addPipelinePack("block-00-time", ms(5, 3, 150));
        profile.addConcurrentRun("block-00-time", ms(90, 80, 200));
        profile.addConcurrentRun("block-00-time", ms(90, 70, 190));
        profile.addPipelineScatter("block-00-time", ms(7, 2, 150));
        profile.addInferencePipeline(ms(100, 10, 170));
        profile.addPack("block-00-frequency", ms(4, 1, 2));
        profile.addRun("block-00-frequency", ms(20, 2, 4));
        NativeInferenceProfile.Snapshot receipt = profile.finish("completed");
        String summary = receipt.record(0);
        require(summary.contains("inferenceWallMs=130 inferenceCpuMs=13") &&
            summary.contains("inferenceThreadCpuMs=13 inferenceProcessCpuMs=176") &&
            summary.contains("instrumentedCpuMs=15 instrumentedCpuScope=nonoverlapping-calling-thread"),
            "pipeline counts parent CPU once while retaining ordinary copy and prebinding CPU");
        require(summary.contains("inferenceWorkScope=run-and-pipeline-coordination") &&
            summary.contains("inferenceWorkerThreadCpuMs=150 inferenceWorkerCpuTelemetry=available") &&
            summary.contains("inferenceWorkerRunCount=2 inferenceCount=4"),
            "pipeline work scope explicitly includes coordinator copies without changing graph call counts");
        String inference = record(receipt, "stage=inference ");
        require(inference.contains("samples=3 wallScope=critical-path workScope=run-and-pipeline-coordination") &&
            inference.contains("processCpuMs=176 wallMs=130"), "pipeline and serial intervals define the inference critical path");
        String pack = record(receipt, "stage=pack ");
        require(pack.contains("samples=2 wallScope=mixed-nested-and-sequential-intervals") &&
            pack.contains("processCpuScope=unavailable-overlapping-intervals processCpuMs=unavailable") &&
            pack.contains("wallMs=9") && pack.contains("cpuMs=4"),
            "mixed copy stage retains its own durations and explicitly marks overlap");
        String time = record(receipt, "graph=block-00-time ");
        require(time.contains("packWallScope=nested-in-inference-pipeline scatterWallScope=nested-in-inference-pipeline") &&
            time.contains("packProcessCpuScope=unavailable-overlapping-intervals scatterProcessCpuScope=unavailable-overlapping-intervals") &&
            time.contains("packCount=1 packWallMs=5 packCpuMs=3 packProcessCpuMs=unavailable") &&
            time.contains("scatterCount=1 scatterWallMs=7 scatterCpuMs=2 scatterProcessCpuMs=unavailable"),
            "nested graph copies report caller cost without attributing concurrent worker process CPU to copying");
        require(record(receipt, "graph=block-00-frequency ").contains("packWallScope=sequential-intervals scatterWallScope=unavailable"),
            "ordinary frequency copying remains outside the pipeline");
        profile.addPipelinePack("block-00-time", ms(1, 1, 1));
        profile.addPipelineScatter("block-00-time", ms(1, 1, 1));
        profile.addInferencePipeline(ms(1, 1, 1));
        require(summary.equals(profile.finish("failed").record(0)), "pipeline observations cannot mutate a finalized receipt");

        NativeInferenceProfile orphan = new NativeInferenceProfile();
        orphan.addPipelinePack("block-00-time", ms(1, 1, 1));
        require(orphan.finish("failed").record(0).contains("instrumentedCpuMs=unavailable"),
            "nested copying without an observed parent cannot produce a complete CPU sum");
        NativeInferenceProfile impossible = new NativeInferenceProfile();
        impossible.addPipelinePack("block-00-time", ms(5, 5, 10));
        impossible.addInferencePipeline(ms(10, 4, 20));
        require(impossible.finish("failed").record(0).contains("instrumentedCpuMs=unavailable"),
            "nested CPU exceeding its parent is unavailable rather than clamped to an invented value");
        NativeInferenceProfile missingParentClock = new NativeInferenceProfile();
        missingParentClock.addPipelineScatter("block-00-time", ms(1, 1, 2));
        missingParentClock.addInferencePipeline(ms(10, -1, 20));
        String missing = missingParentClock.finish("cancelled").record(0);
        require(missing.contains("instrumentedCpuMs=unavailable") && missing.contains("inferenceProcessCpuMs=20"),
            "missing parent caller clock does not discard an independently measured process clock");
        NativeInferenceProfile missingCopyClock = new NativeInferenceProfile();
        missingCopyClock.addPipelinePack("block-00-time", ms(1, -1, 2));
        missingCopyClock.addInferencePipeline(ms(10, 4, 20));
        require(missingCopyClock.finish("cancelled").record(0).contains("instrumentedCpuMs=unavailable"),
            "missing nested caller clock cannot yield a fabricated deduplicated total");
    }
    private static void checkB1Topology(boolean pipeline) {
        NativeInferenceProfile profile = new NativeInferenceProfile();
        NativeInferenceProfile.Measurement timing = ms(1, 1, 1);
        profile.addRun("front", timing);
        for (int block = 0; block < 12; block++) {
            String graph = "block-" + (block < 10 ? "0" : "") + block;
            for (int band = 0; band < 60; band++) profile.addConcurrentRun(graph + "-time", timing);
            if (pipeline) profile.addInferencePipeline(timing);
            else for (int wave = 0; wave < 8; wave++) profile.addInferenceWave(timing);
            for (int batch = 0; batch < 11; batch++) profile.addRun(graph + "-frequency", timing);
        }
        for (int head = 0; head < 2; head++) for (int batch = 0; batch < 11; batch++) profile.addRun("head-" + head, timing);
        NativeInferenceProfile.Snapshot receipt = profile.finish("completed");
        String summary = receipt.record(0);
        require(summary.contains("inferenceWorkerRunCount=720 inferenceCount=875") && summary.contains("graphRecords=27"),
            "B1 records every full-context band call while retaining the 27 original graphs");
        if (pipeline) require(record(receipt, "stage=inference ").contains("samples=167 wallScope=critical-path"),
            "twelve pipeline parents and 155 serial calls are distinct from the 875 actual graph calls");
    }
    private static void require(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
}
