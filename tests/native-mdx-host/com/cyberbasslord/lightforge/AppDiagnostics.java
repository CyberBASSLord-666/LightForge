package com.cyberbasslord.lightforge;
public final class AppDiagnostics {
    public static final java.util.List<String> profileSummaries=new java.util.concurrent.CopyOnWriteArrayList<>();
    public static void record(android.content.Context context,String source,Throwable failure){}
    public static void log(android.content.Context context,String level,String source,String message){}
    public static void profileSummary(android.content.Context context,String jobId,String route,String summary){profileSummaries.add(route+" "+summary);}
}
