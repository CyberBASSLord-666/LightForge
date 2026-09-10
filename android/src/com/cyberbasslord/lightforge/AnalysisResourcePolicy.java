package com.cyberbasslord.lightforge;

/** Conservative admission for two unchanged GAME workers, using a fresh device snapshot. */
final class AnalysisResourcePolicy {
    private AnalysisResourcePolicy() {}
    static final long GIB=1024L*1024*1024;
    static int gameParallelism(long totalBytes,long availableBytes,int cores,boolean process64Bit,boolean lowMemory) {
        return process64Bit&&!lowMemory&&cores>=4&&totalBytes>=7*GIB&&availableBytes>=6*GIB&&availableBytes<=totalBytes?2:1;
    }
}
