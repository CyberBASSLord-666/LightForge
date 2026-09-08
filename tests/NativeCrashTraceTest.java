package com.cyberbasslord.lightforge;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

/** Synthetic AOSP tombstones only: no device logs or user data are test fixtures. */
public final class NativeCrashTraceTest {
    private static int assertions;

    private static void check(boolean value, String message) {
        assertions++;
        if (!value) throw new AssertionError(message);
    }

    private static byte[] join(byte[]... fields) {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        for (byte[] field : fields) bytes.write(field, 0, field.length);
        return bytes.toByteArray();
    }

    private static byte[] varint(long value) {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        do {
            int next = (int)(value & 127); value >>>= 7;
            bytes.write(next | (value == 0 ? 0 : 128));
        } while (value != 0);
        return bytes.toByteArray();
    }

    private static byte[] number(int field, long value) { return join(varint((long)field << 3), varint(value)); }
    private static byte[] message(int field, byte[] value) { return join(varint(((long)field << 3) | 2), varint(value.length), value); }
    private static byte[] text(int field, String value) { return message(field, value.getBytes(StandardCharsets.UTF_8)); }
    private static String read(byte[] bytes) { return NativeCrashTrace.read(new ByteArrayInputStream(bytes)); }

    private static byte[] signal() {
        return message(10, join(text(4, "ILL_ILLOPC"), number(9, 0x7abcdeff0011L), number(3, 1), text(2, "SIGILL"), number(1, 4)));
    }

    private static byte[] frame(String module, String function, long pc) {
        return message(4, join(text(8, "00aBcDff"), number(2, 0x7abcdeff0011L), text(6, module),
            number(3, 0x7abcdefef111L), number(5, 8), text(4, function), number(1, pc)));
    }

    private static byte[] thread(long id, byte[] frames) {
        // protobuf map entries may put value before key; readers must handle both orders.
        return message(16, join(message(2, join(text(2, "PERSONAL_PAYLOAD_THREAD_NAME"), frames, number(1, id))), number(1, id)));
    }

    private static byte[] fixture() {
        byte[] unknown = join(number(1000, 25), join(varint((1001L << 3) | 1), new byte[8]),
            message(1002, "PERSONAL_PAYLOAD_VENDOR_FIELD".getBytes(StandardCharsets.UTF_8)),
            join(varint((1003L << 3) | 5), new byte[4]));
        return join(unknown, thread(44, frame("/data/private/libother.so", "UnrelatedThreadFunction", 0x44)),
            thread(72, join(frame("/data/app/PERSONAL_PAYLOAD_INSTALL/base.apk!lib/arm64-v8a/libonnxruntime.so", "MlasGemmKernel", 0x1234),
                frame("/apex/PERSONAL_PAYLOAD_PATH/lib64/libc.so", "std::__ndk1::thread::run()", 0x5678))),
            text(9, "PERSONAL_PAYLOAD_COMMAND"), signal(), number(6, 72), unknown);
    }

    private static void evidenceAndOrdering() {
        String report = read(fixture());
        check(report.contains("signal=4 (SIGILL) code=1 (ILL_ILLOPC)"), "Crash signal and code must be decoded.");
        check(report.contains("crashThreadId=72"), "Crash thread must come from root tid even when serialized last.");
        check(report.contains("#00 rel_pc=0x1234 libonnxruntime.so (MlasGemmKernel+0x8) build_id=00abcdff"), "First native frame must retain relative PC, library, symbol and build ID.");
        check(report.contains("#01 rel_pc=0x5678 libc.so (std::__ndk1::thread::run()+0x8)"), "Demangled symbols must remain usable.");
        check(!report.contains("UnrelatedThreadFunction") && !report.contains("libother.so"), "Only the crashing thread is exported.");
        check(!report.contains("PERSONAL_PAYLOAD") && !report.contains("/data/") && !report.contains("/apex/"), "Private payload and directory names must not leak.");
        check(!report.contains("7abcdeff0011") && !report.contains("7abcdefef111"), "Absolute PC, SP and fault addresses must not be exported.");
        check(!report.contains("malformed") && !report.contains("truncated"), "Unknown fields with supported wire types must be skipped.");
        String missingTid = read(join(signal(), thread(72, frame("libc.so", "SecretOtherThread", 1))));
        check(missingTid.contains("Crashing thread ID unavailable") && !missingTid.contains("SecretOtherThread"), "Never guess a crashing thread from another thread's stack.");
    }

    private static void privacy() {
        byte[] payload = text(1, "PERSONAL_PAYLOAD");
        byte[] rootPrivate = join(text(2, "PERSONAL_PAYLOAD_FINGERPRINT"), text(8, "PERSONAL_PAYLOAD_SELINUX"),
            text(9, "PERSONAL_PAYLOAD_COMMAND"), text(14, "PERSONAL_PAYLOAD_ABORT"), message(15, payload),
            message(17, payload), message(18, payload), message(19, payload), message(21, payload));
        byte[] privateThread = join(text(2, "PERSONAL_PAYLOAD_THREAD"), message(3, payload), message(5, payload),
            text(7, "PERSONAL_PAYLOAD_BACKTRACE_NOTE"), text(9, "/data/PERSONAL_PAYLOAD_UNREADABLE_ELF"));
        byte[] unsafeFrames = join(
            frame("/data/PERSONAL_PAYLOAD/recording.mp3", "/data/PERSONAL_PAYLOAD/hidden", 7),
            frame("C:\\Users\\PERSONAL_PAYLOAD\\libsafe.so", "\"PERSONAL_PAYLOAD\"", 8),
            message(4, join(text(6, "/data/PERSONAL_PAYLOAD/libsafe.so"), text(4, "fn\nPERSONAL_PAYLOAD"), text(8, "PERSONAL_PAYLOAD"))),
            frame("/system/bin/app_process64", "JavaVMExt::LoadNativeLibrary", 9));
        byte[] entry = message(16, join(number(1, 91), message(2, join(privateThread, unsafeFrames))));
        String report = read(join(rootPrivate, signal(), entry, number(6, 91)));
        check(!report.contains("PERSONAL_PAYLOAD") && !report.contains("recording.mp3"), "All excluded schema fields, media names, unsafe symbols and build IDs must be omitted.");
        check(report.contains("libsafe.so") && report.contains("app_process64"), "Allowed native module basenames survive path removal.");
        check(report.contains("<module unavailable>"), "Unknown module types must be explicitly unavailable.");
        String longSymbol = new String(new char[2000]).replace('\0', 'x');
        report = read(join(number(6, 1), thread(1, frame("libc.so", longSymbol, 3))));
        check(!report.contains("xxxxxxxx"), "Oversized symbols must be omitted, not partially exposed.");
    }

    private static void malformedAndTruncated() {
        check(NativeCrashTrace.read(null).contains("No retained native tombstone"), "Absent native trace must be explained.");
        check(read(new byte[0]).contains("Native signal details unavailable"), "Empty native trace must be explained.");
        byte[][] bad = {
            new byte[]{0}, // field zero
            new byte[]{11}, // proto2 group unsupported by Android's proto3 schema
            new byte[]{(byte)255, (byte)255, (byte)255, (byte)255, (byte)255, (byte)255, (byte)255, (byte)255, (byte)255, 2},
            join(varint(18), varint(-1)), // impossible unsigned length
            join(varint(48), varint(0x100000000L)) // tid outside uint32
        };
        for (byte[] bytes : bad) check(read(bytes).contains("malformed or unsupported"), "Malformed native records must be bounded and identified.");
        byte[] good = fixture();
        for (int length = 0; length < good.length; length++) {
            String report = read(Arrays.copyOf(good, length));
            check(report.length() <= NativeCrashTrace.MAX_OUTPUT_CHARS, "Every truncated prefix must remain within output bound.");
            check(!report.contains("PERSONAL_PAYLOAD"), "No truncated prefix may expose excluded data.");
            check(!report.contains("rel_pc=0x0 "), "A truncated prefix cannot invent a zero PC absent from this fixture.");
        }
        String report = read(join(good, varint((29 << 3) | 2), varint(Long.MAX_VALUE)));
        check(report.contains("truncated field") && report.contains("MlasGemmKernel"), "A truncated later field must retain already decoded crash evidence.");
        report = read(join(number(6, 1), thread(1, message(4, join(text(6, "libc.so"), varint(34), varint(80), new byte[]{'x', 'y'})))));
        check(!report.contains("(xy"), "A truncated symbol must never be presented as a complete symbol.");
        report = read(join(number(6, 0xffffffffL), thread(0xffffffffL, frame("libc.so", "function", -1)),
            message(10, join(number(1, 6), number(3, -6)))));
        check(report.contains("crashThreadId=4294967295") && report.contains("rel_pc=0xffffffffffffffff"), "Unsigned 32/64-bit fields must not overflow or become negative.");
        check(report.contains("code=-6"), "Signed protobuf int32 signal codes must be preserved.");

        report = read(join(number(6, 1), thread(1, message(4,
                join(text(6, "libc.so"), text(4, "function"), new byte[]{8, (byte)128})))));
        check(report.contains("rel_pc=unavailable") && !report.contains("rel_pc=0x0"),
                "An incomplete PC varint must be unavailable, never a fabricated zero.");
        check(report.contains("function; offset unavailable") && !report.contains("function+0x0"),
                "A missing offset in an incomplete frame must not be presented as zero.");
        report = read(join(number(6, 1), thread(1, message(4,
                join(number(1, 9), text(4, "function"), new byte[]{40, (byte)128})))));
        check(report.contains("rel_pc=0x9") && report.contains("offset unavailable"),
                "A decoded PC remains evidence when the following function offset is truncated.");
        report = read(join(number(6, 1), thread(1, message(4,
                join(number(1, 0), number(5, 0), text(4, "function"), new byte[]{80, (byte)128})))));
        check(report.contains("rel_pc=0x0") && report.contains("function+0x0"),
                "Explicitly decoded zero PC and offset remain valid despite later truncation.");
        report = read(join(number(6, 1), thread(1, message(4, text(4, "function")))));
        check(report.contains("rel_pc=0x0") && report.contains("function+0x0"),
                "Complete proto3 frames retain valid omitted numeric zero defaults.");
        report = read(message(10, join(number(1, 4), new byte[]{24, (byte)128})));
        check(report.contains("signal=4 (SIGILL) code=unavailable") && !report.contains("code=0"),
                "A truncated signal-code varint must not invent signal code zero.");
        report = read(join(varint((10 << 3) | 2), varint(20), number(1, 4)));
        check(report.contains("code=unavailable"), "A physically truncated signal message has no implied code default.");
        report = read(message(10, number(1, 4)));
        check(report.contains("signal=4 (SIGILL) code=0"), "Complete proto3 signal messages retain omitted zero code.");
        report = read(message(10, join(number(1, 4), number(3, 0), new byte[]{80, (byte)128})));
        check(report.contains("signal=4 (SIGILL) code=0"), "An explicitly decoded zero signal code survives later truncation.");
    }

    private static void boundsAndReadFailures() {
        ByteArrayOutputStream frames = new ByteArrayOutputStream();
        for (int i = 0; i < 200; i++) {
            byte[] value = frame("libc.so", "Frame" + i, i); frames.write(value, 0, value.length);
        }
        String report = read(join(number(6, 1), thread(1, frames.toByteArray()), signal()));
        check(report.contains("#79 ") && !report.contains("#80 "), "Export must stop at 80 frames.");
        check(report.contains("Additional crashing-thread frames omitted"), "Frame truncation must be disclosed.");
        check(report.length() <= NativeCrashTrace.MAX_OUTPUT_CHARS, "Large backtraces must respect the output bound.");

        final int[] bytesRead = {0};
        report = NativeCrashTrace.read(new InputStream() {
            @Override public int read() { bytesRead[0]++; return (bytesRead[0] & 1) == 1 ? 8 : 1; }
            @Override public int read(byte[] bytes, int offset, int count) {
                for (int i = 0; i < count; i++) bytes[offset + i] = (byte)read();
                return count;
            }
        });
        check(bytesRead[0] == NativeCrashTrace.MAX_INPUT_BYTES, "Infinite input must stop exactly at the input cap without lookahead.");
        check(report.contains("input limit reached") && report.contains("parsing work limit reached"), "Input and work limits must both be explicit.");

        final byte[] complete = fixture();
        report = NativeCrashTrace.read(new InputStream() {
            int position;
            @Override public int read() throws IOException {
                if (position == complete.length) throw new IOException("PERSONAL_PAYLOAD_READ_ERROR");
                return complete[position++] & 255;
            }
            @Override public int read(byte[] bytes, int offset, int count) throws IOException {
                if (position == complete.length) throw new IOException("PERSONAL_PAYLOAD_READ_ERROR");
                int size = Math.min(count, complete.length - position);
                System.arraycopy(complete, position, bytes, offset, size); position += size; return size;
            }
        });
        check(report.contains("read was interrupted") && report.contains("MlasGemmKernel"), "Read failure after partial input must preserve available evidence.");
        check(!report.contains("PERSONAL_PAYLOAD"), "I/O exception messages must not expose provider details.");

        report = NativeCrashTrace.read(new InputStream() {
            int position;
            @Override public int read() { return position == complete.length ? -1 : complete[position++] & 255; }
            @Override public int read(byte[] bytes, int offset, int count) { return 0; }
        });
        check(report.contains("MlasGemmKernel"), "Zero-byte stream reads must make progress through bounded single-byte fallback.");
    }

    public static void main(String[] args) {
        evidenceAndOrdering(); privacy(); malformedAndTruncated(); boundsAndReadFailures();
        System.out.println("PASS: " + assertions + " native tombstone evidence, privacy, malformed input and bound checks.");
    }
}
