package com.cyberbasslord.lightforge;

import java.util.ArrayList;
import java.util.List;

public final class AppDiagnostics {
    public static final List<String> messages=new ArrayList<>();
    public static void initialize(Object context) {}
    public static void log(Object context,String level,String source,String message) { messages.add(message); }
}
