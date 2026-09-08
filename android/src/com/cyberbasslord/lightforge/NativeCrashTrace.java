package com.cyberbasslord.lightforge;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/**
 * Allowlisted reader for Android 12+ ApplicationExitInfo native tombstone protobufs.
 * Schema: https://android.googlesource.com/platform/system/core/+/refs/heads/main/debuggerd/proto/tombstone.proto
 * This deliberately does not decode command lines, abort messages, registers, raw
 * addresses, thread names, memory, mappings, file descriptors or embedded logcat.
 * No protobuf runtime or Android classes are needed, so malformed input is host-testable.
 */
final class NativeCrashTrace {
    static final int MAX_INPUT_BYTES = 2 * 1024 * 1024;
    static final int MAX_FIELDS = 100000;
    static final int MAX_FRAMES = 80;
    static final int MAX_OUTPUT_CHARS = 48 * 1024;

    private NativeCrashTrace() {}

    static String read(InputStream input) {
        if (input == null) return "  No retained native tombstone.\n";
        byte[] bytes = new byte[MAX_INPUT_BYTES];
        int count = 0;
        State state = new State();
        try {
            while (count < bytes.length) {
                int read = input.read(bytes, count, bytes.length - count);
                if (read < 0) break;
                if (read == 0) {
                    int next = input.read();
                    if (next < 0) break;
                    bytes[count++] = (byte)next;
                } else count += read;
            }
        } catch (IOException unavailable) { state.readFailed = true; }
        // Do not perform another potentially blocking read just to detect EOF at the cap.
        state.inputLimited = count == bytes.length;
        if (count > 0) {
            scanHeader(new Reader(bytes, 0, count, state), state);
            if (state.tid != 0) scanThreads(new Reader(bytes, 0, count, state), state);
        }
        StringBuilder out = new StringBuilder();
        line(out, "Native tombstone (protobuf; crashing thread only):");
        if (state.signalSeen) {
            line(out, "signal=" + state.signalNumber + signalName(state.signalNumber) +
                " code=" + (state.signalCodeKnown ? String.valueOf(state.signalCode) : "unavailable") +
                (state.codeName.isEmpty() ? "" : " (" + state.codeName + ")"));
        } else line(out, "Native signal details unavailable within retained trace.");
        line(out, state.tid == 0 ? "Crashing thread ID unavailable." : "crashThreadId=" + state.tid);
        out.append(state.frames);
        if (state.frameCount == 0) line(out, "No crashing-thread frames available within retained trace.");
        if (state.inputLimited) line(out, "Native trace input limit reached; later fields may be unavailable.");
        if (state.truncated) line(out, "Native trace contains a truncated field; only decoded evidence is shown.");
        if (state.malformed) line(out, "Native trace contains malformed or unsupported protobuf data; only decoded evidence is shown.");
        if (state.workLimited) line(out, "Native trace parsing work limit reached.");
        if (state.readFailed) line(out, "Native trace read was interrupted; only retained bytes were inspected.");
        if (state.framesLimited) line(out, "Additional crashing-thread frames omitted at the output limit.");
        line(out, "Native trace bounds: 2 MiB input / 100000 fields / 80 frames / 48 KiB text; private data excluded.");
        return out.toString();
    }

    // The root tid and map key may appear after their values: do not depend on serialization order.
    private static void scanHeader(Reader reader, State state) {
        try {
            while (reader.hasNext()) {
                int tag = reader.tag();
                if (tag == (6 << 3)) state.tid = reader.uint32();
                else if (tag == ((10 << 3) | 2)) readSignal(reader.message(), state);
                else reader.skip(tag);
            }
        } catch (Invalid ignored) {}
    }

    private static void readSignal(Reader reader, State state) {
        boolean parsed = true;
        try {
            while (reader.hasNext()) {
                int tag = reader.tag();
                if (tag == (1 << 3)) { state.signalNumber = (int)reader.varint(); state.signalSeen = true; }
                else if (tag == (3 << 3)) {
                    state.signalCodeKnown = false;
                    state.signalCode = (int)reader.varint(); state.signalCodeKnown = true;
                }
                else if (tag == ((4 << 3) | 2)) {
                    String code = reader.text(48);
                    state.codeName = code.matches("[A-Z][A-Z0-9_]{0,47}") ? code : "";
                } else reader.skip(tag);
            }
        } catch (Invalid ignored) { parsed = false; }
        // Proto3 omission means zero only when the containing message is complete.
        if (parsed && reader.complete) state.signalCodeKnown = true;
    }

    private static void scanThreads(Reader reader, State state) {
        try {
            while (reader.hasNext()) {
                int tag = reader.tag();
                if (tag == ((16 << 3) | 2)) {
                    Reader entry = reader.message(), thread = null;
                    long key = 0;
                    while (entry.hasNext()) {
                        int field = entry.tag();
                        if (field == (1 << 3)) key = entry.uint32();
                        else if (field == ((2 << 3) | 2)) thread = entry.message();
                        else entry.skip(field);
                    }
                    if (key == state.tid && thread != null) { readThread(thread, state); return; }
                } else reader.skip(tag);
            }
        } catch (Invalid ignored) {}
    }

    private static void readThread(Reader reader, State state) {
        try {
            while (reader.hasNext()) {
                int tag = reader.tag();
                if (tag == ((4 << 3) | 2)) {
                    if (state.frameCount >= MAX_FRAMES) { state.framesLimited = true; return; }
                    readFrame(reader.message(), state);
                } else reader.skip(tag);
            }
        } catch (Invalid ignored) {}
    }

    private static void readFrame(Reader reader, State state) {
        long relativePc = 0, functionOffset = 0;
        boolean relativePcSeen = false, functionOffsetSeen = false, parsed = true;
        String module = "<module unavailable>", function = "", buildId = "";
        try {
            while (reader.hasNext()) {
                int tag = reader.tag();
                if (tag == (1 << 3)) {
                    relativePcSeen = false; relativePc = reader.varint(); relativePcSeen = true;
                } else if (tag == (5 << 3)) {
                    functionOffsetSeen = false; functionOffset = reader.varint(); functionOffsetSeen = true;
                }
                else if (tag == ((4 << 3) | 2)) function = function(reader.text(512));
                else if (tag == ((6 << 3) | 2)) module = module(reader.text(4096));
                else if (tag == ((8 << 3) | 2)) {
                    String id = reader.text(128);
                    buildId = id.matches("[a-fA-F0-9]{2,128}") && id.length() % 2 == 0 ? id.toLowerCase(Locale.ROOT) : "";
                } else reader.skip(tag);
            }
        } catch (Invalid ignored) { parsed = false; }
        boolean complete = parsed && reader.complete;
        String frame = String.format(Locale.US, "#%02d rel_pc=%s %s", state.frameCount,
            relativePcSeen || complete ? "0x" + Long.toHexString(relativePc) : "unavailable", module);
        if (!function.isEmpty()) frame += " (" + function +
            (functionOffsetSeen || complete ? "+0x" + Long.toHexString(functionOffset) : "; offset unavailable") + ")";
        if (!buildId.isEmpty()) frame += " build_id=" + buildId;
        // Reserve space for the fixed header and all diagnostic notices, without splitting a frame.
        if (state.frames.length() + frame.length() + 3 <= MAX_OUTPUT_CHARS - 2048) {
            line(state.frames, frame); state.frameCount++;
        } else state.framesLimited = true;
    }

    private static String module(String value) {
        // Never expose even a basename for arbitrary media/documents. Only native libraries and
        // the known Android loader/app executables are diagnostic module names.
        int slash = Math.max(value.lastIndexOf('/'), value.lastIndexOf('\\'));
        String name = value.substring(slash + 1);
        if (name.matches("[A-Za-z0-9_.+\\-]{1,120}\\.so(?:\\.[0-9]{1,8})?")) return name;
        if (name.matches("(?:app_process(?:32|64)?|linker(?:64)?|crash_dump(?:32|64)|base\\.apk)")) return name;
        return "<module unavailable>";
    }

    private static String function(String value) {
        // Demangled C/C++ identifiers are useful; paths, controls, quoted strings and arbitrary
        // payloads are not. Omit an invalid/oversized symbol rather than partially revealing it.
        return value.matches("[A-Za-z_$?][A-Za-z0-9_.$:@?<>~*&(), +\\-\\[\\]]{0,239}") ? value : "";
    }

    private static String signalName(int signal) {
        switch (signal) {
            case 4: return " (SIGILL)";
            case 5: return " (SIGTRAP)";
            case 6: return " (SIGABRT)";
            case 7: return " (SIGBUS)";
            case 8: return " (SIGFPE)";
            case 9: return " (SIGKILL)";
            case 11: return " (SIGSEGV)";
            case 31: return " (SIGSYS)";
            default: return "";
        }
    }

    private static void line(StringBuilder out, String value) { out.append("  ").append(value).append('\n'); }

    private static final class State {
        int fields, frameCount, signalNumber, signalCode;
        long tid;
        String codeName = "";
        final StringBuilder frames = new StringBuilder();
        boolean signalSeen, signalCodeKnown, inputLimited, truncated, malformed, workLimited, readFailed, framesLimited;
    }

    private static final class Invalid extends Exception {
        private static final long serialVersionUID = 1L;
    }

    private static final class Reader {
        final byte[] bytes;
        final int end;
        final State state;
        int position;
        boolean complete = true;

        Reader(byte[] bytes, int start, int end, State state) {
            this.bytes = bytes; this.position = start; this.end = end; this.state = state;
        }

        boolean hasNext() { return position < end; }

        int tag() throws Invalid {
            if (++state.fields > MAX_FIELDS) { state.workLimited = true; throw new Invalid(); }
            long value = varint();
            if (value <= 0 || value > 0xffffffffL || (value >>> 3) == 0) throw malformed();
            return (int)value;
        }

        long uint32() throws Invalid {
            long value = varint();
            if (value < 0 || value > 0xffffffffL) throw malformed();
            return value;
        }

        long varint() throws Invalid {
            long result = 0;
            for (int index = 0; index < 10; index++) {
                if (position >= end) { state.truncated = true; throw new Invalid(); }
                int value = bytes[position++] & 255;
                if (index == 9 && (value & 254) != 0) throw malformed();
                result |= (long)(value & 127) << (index * 7);
                if ((value & 128) == 0) return result;
            }
            throw malformed();
        }

        Reader message() throws Invalid {
            long length = varint();
            if (length < 0) throw malformed();
            int available = end - position;
            int size = (int)Math.min(length, available);
            if (length > available) { state.truncated = true; complete = false; }
            Reader child = new Reader(bytes, position, position + size, state);
            child.complete = length <= available;
            position += size;
            return child;
        }

        String text(int maximum) throws Invalid {
            Reader value = message();
            int size = value.end - value.position;
            // Decode no oversized strings; unknown fields are skipped without allocation.
            if (!value.complete || size > maximum) return "";
            return new String(bytes, value.position, size, StandardCharsets.UTF_8);
        }

        void skip(int tag) throws Invalid {
            switch (tag & 7) {
                case 0: varint(); break;
                case 1: fixed(8); break;
                case 2: message(); break;
                case 5: fixed(4); break;
                default: throw malformed(); // Groups do not occur in Android's proto3 schema.
            }
        }

        void fixed(int size) throws Invalid {
            if (size > end - position) { state.truncated = true; throw new Invalid(); }
            position += size;
        }

        Invalid malformed() { state.malformed = true; return new Invalid(); }
    }
}
