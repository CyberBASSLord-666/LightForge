package com.cyberbasslord.lightforge;

import java.io.IOException;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import org.json.JSONObject;

/** Research observer only: each passage owns its trace paths for their entire lifetime. */
public final class DeuxSourceTrace {
    public static final String LAYOUT="passage-owned-no-move-v1";
    private static Path configuredRoot,directory;
    private static Thread owner;
    private static final Set<String> requested=new HashSet<>();
    private DeuxSourceTrace(){}

    private static Set<String> graphs(){
        Set<String> names=new TreeSet<>(Arrays.asList("front","head-0","head-1"));
        for(int i=0;i<12;i++)for(String axis:Arrays.asList("time","frequency"))
            names.add(String.format(Locale.ROOT,"block-%02d-%s",i,axis));
        return names;
    }
    public static void begin(Path expectedRoot,Path passage)throws Exception {
        if(directory!=null||owner!=null)throw new IOException("Trace passage already active");
        if(!expectedRoot.isAbsolute()||Files.isSymbolicLink(expectedRoot)||!Files.isDirectory(expectedRoot))
            throw new IOException("Invalid bound trace control directory");
        Path target=passage.resolve("traces").toAbsolutePath().normalize();
        Files.createDirectory(target); // Never reuse or move a prior passage's trace directory.
        configuredRoot=expectedRoot.toAbsolutePath().normalize();directory=target;owner=Thread.currentThread();requested.clear();
    }
    public static String prefix(String graph,String expectedRoot)throws Exception {
        if(directory==null||owner!=Thread.currentThread()||!configuredRoot.equals(Paths.get(expectedRoot).toAbsolutePath().normalize())||
           !graphs().contains(graph)||!requested.add(graph))throw new IOException("Unbound or duplicate passage trace prefix");
        return directory.resolve(graph).toString();
    }
    public static void end(){configuredRoot=null;directory=null;owner=null;requested.clear();}

    public static JSONObject inventory(Path source)throws Exception {
        if(Files.isSymbolicLink(source)||!Files.isDirectory(source))throw new IOException("Missing owned passage traces");
        List<Path> paths=new ArrayList<>();
        try(DirectoryStream<Path> stream=Files.newDirectoryStream(source)){for(Path path:stream)paths.add(path);}
        if(paths.size()!=27)throw new IOException("Exactly 27 completed passage traces required");
        JSONObject result=new JSONObject();
        for(String graph:graphs()){
            Path found=null;
            for(Path path:paths)if(path.getFileName().toString().startsWith(graph+"_")&&path.toString().endsWith(".json")){
                if(found!=null||Files.isSymbolicLink(path)||!Files.isRegularFile(path))throw new IOException("Invalid graph trace");
                found=path;
            }
            if(found==null)throw new IOException("Missing graph trace: "+graph);
            byte[] digest=MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(found));StringBuilder value=new StringBuilder();
            for(byte x:digest)value.append(String.format(Locale.ROOT,"%02x",x&255));
            result.put(found.getFileName().toString(),value.toString());
        }
        return result;
    }
}
