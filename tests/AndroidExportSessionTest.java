package com.cyberbasslord.lightforge;

import java.io.*;
import java.nio.file.Files;
import org.json.JSONObject;

/** Real production export state, without an Android Activity or document provider. */
public final class AndroidExportSessionTest {
    private static int checks;
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);checks++;}
    private static void rejects(IO action,String message)throws Exception{
        try{action.run();throw new AssertionError(message);}catch(IOException expected){checks++;}
    }
    interface IO{void run()throws Exception;}
    public static void main(String[] args)throws Exception{
        File root=Files.createTempDirectory("export-session-").toFile();
        try{
            File file=new File(root,"sequence.fseq");
            MainActivity.ExportSession session=new MainActivity.ExportSession("owner",new JSONObject(),root,file,"{}");
            check(session.accepts("owner"),"Owner cannot append");
            check(!session.accepts("old-owner")&&!session.accepts(null),"Stale owner accepted");
            session.append(new byte[]{1,2,3});
            check(session.size==3,"Append length wrong");
            session.finish();session.finish();
            check(session.finishing&&!session.accepts("owner"),"Finishing session accepts append");
            rejects(()->session.append(new byte[]{4}),"Append after finish accepted");
            check(Files.readAllBytes(file.toPath()).length==3,"Rejected append changed output");
            session.abort();session.abort();
            check(!file.exists()&&!session.accepts("owner"),"Aborted output retained");
            rejects(session::finish,"Aborted session can finish");
            rejects(()->session.append(new byte[]{5}),"Aborted session can append");
            MainActivity.ExportSession bounded=new MainActivity.ExportSession("next",new JSONObject(),root,file,"{}");
            bounded.size=200_100_000L;
            rejects(()->bounded.append(new byte[]{1}),"Size bound not checked before write");
            check(bounded.size==200_100_000L&&file.length()==0,"Over-limit append changed file or size");
            bounded.abort();
            System.out.println("PASS: "+checks+" production export session lifecycle checks");
        }finally{for(File child:root.listFiles())child.delete();root.delete();}
    }
}
