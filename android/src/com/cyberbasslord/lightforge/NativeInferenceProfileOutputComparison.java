package com.cyberbasslord.lightforge;

import java.io.BufferedInputStream;
import java.io.DataInputStream;
import java.io.File;
import java.io.FileInputStream;

/** Strict, streaming same-runtime output comparison for native inference evidence. */
final class NativeInferenceProfileOutputComparison {
    static final int STEM_COUNT = 2;
    static final int BYTES_PER_FLOAT = 4;
    static final boolean BYTE_IDENTITY_REQUIRED = true;
    static final double MAX_ABSOLUTE_ERROR = 0D;
    static final double MAX_RMSE = 0D;
    static final double MAX_RELATIVE_RMSE = 0D;

    private NativeInferenceProfileOutputComparison() {}

    static StemComparison[] compare(File reference, File candidate, int samplesPerStem) throws Exception {
        if (samplesPerStem < 1) throw new IllegalArgumentException("Sample inventory is invalid");
        long expected = expectedBytes(samplesPerStem);
        if (reference.length() != expected || candidate.length() != expected) throw new java.io.IOException("Output pair is incomplete");
        StemComparison[] result = new StemComparison[STEM_COUNT];
        try (DataInputStream baseline = new DataInputStream(new BufferedInputStream(new FileInputStream(reference), 262144));
             DataInputStream observed = new DataInputStream(new BufferedInputStream(new FileInputStream(candidate), 262144))) {
            for (int stem = 0; stem < STEM_COUNT; stem++) {
                double maxAbsoluteError = 0D, sumSquaredError = 0D, sumSquaredReference = 0D;
                boolean finite = true, identical = true;
                for (int sample = 0; sample < samplesPerStem; sample++) {
                    int expectedBits = Integer.reverseBytes(baseline.readInt());
                    int actualBits = Integer.reverseBytes(observed.readInt());
                    float expectedValue = Float.intBitsToFloat(expectedBits), actualValue = Float.intBitsToFloat(actualBits);
                    identical &= expectedBits == actualBits;
                    if (!Float.isFinite(expectedValue) || !Float.isFinite(actualValue)) { finite = false; continue; }
                    double error = Math.abs((double) expectedValue - (double) actualValue);
                    maxAbsoluteError = Math.max(maxAbsoluteError, error);
                    sumSquaredError += error * error;
                    sumSquaredReference += (double) expectedValue * (double) expectedValue;
                }
                double rmse = finite ? Math.sqrt(sumSquaredError / samplesPerStem) : Double.POSITIVE_INFINITY;
                double referenceRms = finite ? Math.sqrt(sumSquaredReference / samplesPerStem) : Double.POSITIVE_INFINITY;
                double relativeRmse = finite ? rmse / Math.max(referenceRms, 1e-12) : Double.POSITIVE_INFINITY;
                result[stem] = new StemComparison(stem == 0 ? "vocals" : "accompaniment", samplesPerStem, finite, identical, maxAbsoluteError, rmse, relativeRmse);
            }
            if (baseline.read() != -1 || observed.read() != -1) throw new java.io.IOException("Output pair contains trailing bytes");
        }
        return result;
    }

    static boolean withinPredeclaredLimits(StemComparison[] comparison) {
        if (comparison == null || comparison.length != STEM_COUNT) return false;
        for (StemComparison stem : comparison) {
            if (stem == null || !stem.finite || !stem.identical || stem.samples < 1 || !Double.isFinite(stem.maxAbsoluteError) ||
                !Double.isFinite(stem.rmse) || !Double.isFinite(stem.relativeRmse) ||
                stem.maxAbsoluteError > MAX_ABSOLUTE_ERROR || stem.rmse > MAX_RMSE || stem.relativeRmse > MAX_RELATIVE_RMSE) return false;
        }
        return true;
    }

    static long expectedBytes(int samplesPerStem) { return (long) STEM_COUNT * samplesPerStem * BYTES_PER_FLOAT; }
    static String json(StemComparison[] comparison) {
        StringBuilder out = new StringBuilder("[");
        for (int index = 0; index < comparison.length; index++) {
            if (index != 0) out.append(','); StemComparison stem = comparison[index];
            out.append("{\"stem\":\"").append(stem.stem).append("\",\"samples\":").append(stem.samples)
                .append(",\"finite\":").append(stem.finite).append(",\"identical\":").append(stem.identical)
                .append(",\"max_absolute_error\":").append(stem.maxAbsoluteError).append(",\"rmse\":").append(stem.rmse)
                .append(",\"relative_rmse\":").append(stem.relativeRmse).append('}');
        }
        return out.append(']').toString();
    }

    static final class StemComparison {
        final String stem; final int samples; final boolean finite, identical;
        final double maxAbsoluteError, rmse, relativeRmse;
        StemComparison(String stem, int samples, boolean finite, boolean identical, double maxAbsoluteError, double rmse, double relativeRmse) {
            this.stem = stem; this.samples = samples; this.finite = finite; this.identical = identical;
            this.maxAbsoluteError = maxAbsoluteError; this.rmse = rmse; this.relativeRmse = relativeRmse;
        }
    }
}
