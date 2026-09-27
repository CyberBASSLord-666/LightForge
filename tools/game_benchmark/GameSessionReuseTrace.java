package com.cyberbasslord.lightforge;

import ai.onnxruntime.*;
import org.json.*;
import java.io.*;
import java.nio.file.*;
import java.util.*;

/** Serial call observer for isolated host experiments, never an Android dependency. */
public final class GameSessionReuseTrace {
    private static Path traces, output;
    private static String sourceHash;
    private static int sourceSamples, language, passage=-1, active=-1;
    private static final Map<String,Integer> counts=new HashMap<>();
    private static final Map<String,JSONObject> pending=new HashMap<>();
    private static final IdentityHashMap<OrtSession,JSONObject> identities=new IdentityHashMap<>();
    private static final JSONArray sessions=new JSONArray(), passages=new JSONArray();
    private static JSONObject current;
    private static long owner;
    static void configure(Path root,Path evidence,String hash,int samples,int lang)throws Exception {
        if(traces!=null)throw new IOException("Trace observer configured twice");
        traces=root;output=evidence;sourceHash=hash;sourceSamples=samples;language=lang;owner=Thread.currentThread().getId();
    }
    private static void owner()throws IOException {
        if(traces==null||Thread.currentThread().getId()!=owner)throw new IOException("One configured serial trace owner required");
    }
    static void beginPassage(int index,int first,int last,long seed,String pcmHash)throws Exception {
        owner();if(current!=null||active!=-1||index!=passages.length())throw new IOException("Invalid passage marker order");
        passage=index;current=new JSONObject().put("index",index).put("first",first).put("last",last).put("seed",seed)
            .put("pcmSha256",pcmHash).put("beginNanos",System.nanoTime()).put("calls",new JSONArray());
    }
    static String nextPrefix(String graph)throws Exception {
        owner();if(current==null||active!=-1||pending.containsKey(graph))throw new IOException("Invalid trace session construction");
        int ordinal=counts.containsKey(graph)?counts.get(graph):0;counts.put(graph,ordinal+1);
        String prefix=graph+"_s"+String.format(Locale.ROOT,"%03d",ordinal);
        pending.put(graph,new JSONObject().put("graph",graph).put("sessionOrdinal",ordinal).put("prefix",prefix)
            .put("createdPassage",passage).put("sessionIndex",sessions.length()).put("calls",0));
        return traces.resolve(prefix).toString();
    }
    static void sessionCreated(String graph,OrtSession session)throws Exception {
        owner();JSONObject row=pending.remove(graph);
        if(row==null||identities.containsKey(session))throw new IOException("Unbound or duplicate trace session");
        identities.put(session,row);sessions.put(row);
    }
    static int before(String graph,OrtSession session)throws Exception {
        owner();JSONObject row=identities.get(session);
        if(current==null||active!=-1||row==null||!row.getString("graph").equals(graph))throw new IOException("Unbound/overlapping trace call");
        JSONArray calls=current.getJSONArray("calls");active=calls.length();int ordinal=row.getInt("calls");row.put("calls",ordinal+1);
        calls.put(new JSONObject().put("callIndex",active).put("graph",graph).put("sessionIndex",row.getInt("sessionIndex"))
            .put("graphRunOrdinal",ordinal).put("beginNanos",System.nanoTime()));
        return active;
    }
    static void after(int ticket)throws Exception {
        owner();if(active!=ticket||current==null)throw new IOException("Invalid completed call marker");
        current.getJSONArray("calls").getJSONObject(ticket).put("endNanos",System.nanoTime());active=-1;
    }
    static void endPassage()throws Exception {
        owner();if(current==null||active!=-1||!pending.isEmpty())throw new IOException("Incomplete passage trace markers");
        current.put("endNanos",System.nanoTime());passages.put(current);current=null;
    }
    static void finish()throws Exception {
        owner();if(current!=null||active!=-1||!pending.isEmpty())throw new IOException("Incomplete source trace markers");
        JSONObject receipt=new JSONObject().put("schema","lightforge.game-session-reuse-trace-markers.v1")
            .put("sourcePcmSha256",sourceHash).put("sourceSamples",sourceSamples).put("language",language)
            .put("singleThreadOwner",true).put("sessions",sessions).put("passages",passages)
            .put("binding","One synchronous owner; each exact original run is bracketed. Serial per-session ORT model_run ordinal binds to the corresponding marker; independent monotonic clocks are not subtracted.");
        Files.write(output.resolve("trace-markers.json"),(receipt.toString(2)+"\n").getBytes("UTF-8"),StandardOpenOption.CREATE_NEW);
    }
}
