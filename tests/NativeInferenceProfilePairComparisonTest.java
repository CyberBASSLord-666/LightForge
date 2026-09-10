package com.cyberbasslord.lightforge;

import java.io.DataOutputStream;
import java.io.File;
import java.io.FileOutputStream;

/** Unit contract for the same-runtime profile/unprofiled numerical gate. */
public final class NativeInferenceProfilePairComparisonTest {
    public static void main(String[] args) throws Exception {
        File reference = File.createTempFile("lightforge-profile-reference-", ".f32");
        File candidate = File.createTempFile("lightforge-profile-candidate-", ".f32");
        try {
            float[] values = new float[]{0.25F, -0.5F, 1.0F, 0.0F, -0.25F, 0.5F, -1.0F, 0.75F};
            write(reference, values); write(candidate, values);
            NativeInferenceProfileOutputComparison.StemComparison[] identical = NativeInferenceProfileOutputComparison.compare(reference, candidate, 4);
            require(identical.length == 2 && identical[0].finite && identical[0].identical && identical[1].identical &&
                NativeInferenceProfileOutputComparison.withinPredeclaredLimits(identical), "exact paired outputs pass");

            float[] near = values.clone(); near[0] += 0.000001F; write(candidate, near);
            NativeInferenceProfileOutputComparison.StemComparison[] withinLimits = NativeInferenceProfileOutputComparison.compare(reference, candidate, 4);
            require(!withinLimits[0].identical && withinLimits[0].maxAbsoluteError > NativeInferenceProfileOutputComparison.MAX_ABSOLUTE_ERROR &&
                !NativeInferenceProfileOutputComparison.withinPredeclaredLimits(withinLimits), "non-byte-identical pair fails the zero-error criterion");

            float[] outside = values.clone(); outside[0] += 0.001F; write(candidate, outside);
            require(!NativeInferenceProfileOutputComparison.withinPredeclaredLimits(NativeInferenceProfileOutputComparison.compare(reference, candidate, 4)),
                "measurable paired-output regression fails closed");

            float[] nonfinite = values.clone(); nonfinite[3] = Float.NaN; write(candidate, nonfinite);
            require(!NativeInferenceProfileOutputComparison.withinPredeclaredLimits(NativeInferenceProfileOutputComparison.compare(reference, candidate, 4)),
                "non-finite paired output fails closed");
            System.out.println("NativeInferenceProfile paired equivalence: exact, finite, tolerance and regression checks passed.");
        } finally {
            reference.delete(); candidate.delete();
        }
    }

    private static void write(File output, float[] values) throws Exception {
        try (DataOutputStream stream = new DataOutputStream(new FileOutputStream(output))) {
            for (float value : values) stream.writeInt(Integer.reverseBytes(Float.floatToRawIntBits(value)));
        }
    }
    private static void require(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
}
