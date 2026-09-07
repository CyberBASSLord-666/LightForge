package com.cyberbasslord.lightforge;

import org.json.JSONObject;
import java.io.*;
import java.nio.file.Files;

/** Executes durable job transactions against real project files on the host JVM. */
public final class AnalysisJobStoreTest {
    interface Operation{void run()throws Exception;}
    static void check(boolean ok,String label){if(!ok)throw new AssertionError(label);}
    static void reject(Operation op)throws Exception{try{op.run();}catch(Exception expected){return;}throw new AssertionError("Invalid transaction accepted");}
    static JSONObject read(File file)throws Exception{return AnalysisJobStore.read(file,ProjectStore.MAX_PROJECT_BYTES);}
    public static void main(String[] args)throws Exception{
        File files=new File(args[0]);files.mkdirs();File projects=new File(files,"projects");projects.mkdirs();
        File audio=new File(files,"input.wav"),mono=new File(files,"input-mono.wav");
        float[] pcm=new float[2*44100*2];
        for(int i=0;i<pcm.length;i++)pcm[i]=(float)(.2*Math.sin(2*Math.PI*220*(i/2)/44100));
        try(WavConverter writer=new WavConverter(audio,mono,44100)){writer.accept(pcm,pcm.length/2);writer.finish();}
        JSONObject meta;
        try(InputStream in=new FileInputStream(audio)){meta=ProjectStore.importAudio(projects,in,"Background fixture",new AudioImporter.Progress(){public void update(double p,String s){}public void check(){}});}
        String projectId=meta.getString("id");File saved=new File(new File(projects,projectId),"project.json");
        String original=AnalysisJobStore.hash(saved);
        reject(()->AnalysisJobStore.prepare(files,"../escape"));
        JSONObject first=AnalysisJobStore.prepare(files,projectId);String id=first.getString("id");
        reject(()->AnalysisJobStore.prepare(files,projectId));
        AnalysisJobStore.progress(files,id,.6,"Separating");AnalysisJobStore.progress(files,id,.2,"Late progress");
        check(AnalysisJobStore.status(files).getDouble("progress")==.6,"Progress went backwards");
        reject(()->AnalysisJobStore.progress(files,id,Double.NaN,"Invalid"));
        JSONObject music=new JSONObject().put("duration",2).put("analysisVersion",6).put("bpm",120);
        AnalysisJobStore.checkpoint(files,id,music.toString());
        AnalysisJobStore.recover(files);
        check("interrupted".equals(AnalysisJobStore.status(files).getString("state")),"Dead process left running status");
        JSONObject retry=AnalysisJobStore.prepare(files,projectId);String retryId=retry.getString("id");
        check(retry.getBoolean("hasCheckpoint"),"Matching checkpoint was lost");
        check(AnalysisJobStore.request(files,retryId).getJSONObject("music").getInt("analysisVersion")==6,"Checkpoint not reused");
        reject(()->AnalysisJobStore.progress(files,id,.9,"Stale owner"));
        AnalysisJobStore.finish(files,retryId,"cancelling","Cancelling");
        JSONObject result=read(saved).put("projectId",projectId).put("music",music).put("needAnalysis",false).put("compiled",new JSONObject().put("sha256","host-transaction-fixture"));
        reject(()->AnalysisJobStore.complete(files,retryId,result.toString()));
        check(original.equals(AnalysisJobStore.hash(saved)),"Cancelled work overwrote the saved show");
        AnalysisJobStore.finish(files,retryId,"cancelled","Cancelled");
        JSONObject conflict=AnalysisJobStore.prepare(files,projectId);String conflictId=conflict.getString("id");
        ProjectStore.save(projects,projectId,read(saved).put("name","Newer edit"));String newer=AnalysisJobStore.hash(saved);
        reject(()->AnalysisJobStore.complete(files,conflictId,result.toString()));
        check(newer.equals(AnalysisJobStore.hash(saved)),"Newer edit was overwritten");
        AnalysisJobStore.finish(files,conflictId,"failed","Conflict");
        JSONObject finalJob=AnalysisJobStore.prepare(files,projectId);String finalId=finalJob.getString("id");
        check(!finalJob.getBoolean("hasCheckpoint"),"Mismatched checkpoint reused");
        reject(()->AnalysisJobStore.complete(files,finalId,new JSONObject(result.toString()).put("projectId","other").toString()));
        result.put("name","Newer edit");AnalysisJobStore.complete(files,finalId,result.toString());
        check(finalId.equals(read(saved).getString("backgroundJobId")),"Completion not durable");
        check("completed".equals(AnalysisJobStore.status(files).getString("state")),"Completion not terminal");
        reject(()->AnalysisJobStore.complete(files,finalId,result.toString()));
        // Reproduce process death after project commit but before the job terminal write.
        JSONObject pending=AnalysisJobStore.status(files).put("state","running");AnalysisJobStore.persist(files,pending);
        check("completed".equals(AnalysisJobStore.recover(files).getString("state")),"Committed result misclassified after crash");
        check(!new File(AnalysisJobStore.directory(files),"checkpoint.json").exists(),"Completed checkpoint leaked");
        System.out.println("PASS: job ownership, monotonic progress, checkpoint reuse, cancellation, conflict preservation, durable completion and crash recovery");
    }
}
