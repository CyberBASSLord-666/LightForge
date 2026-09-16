package com.cyberbasslord.lightforge;

import java.io.File;
import java.io.IOException;
import org.json.JSONObject;

/** Bounded recovery of a reclaimed renderer; never retries a renderer crash. */
final class AnalysisRendererRecovery {
    static final int MAX_ATTEMPTS=2;
    static final long FIRST_DELAY_MS=10000L,SECOND_DELAY_MS=30000L,MAX_WAIT_MS=120000L;
    private AnalysisRendererRecovery(){}

    static boolean eligible(JSONObject job,boolean crashed){
        if(crashed||!AnalysisJobStore.active(job)||"cancelling".equals(job.optString("state"))
            ||!job.optBoolean("resumeAvailable")||job.optLong("checkpointAt")<=0)return false;
        double attempts=job.optDouble("rendererRecoveryAttempts",0),progress=job.optDouble("progress",Double.NaN);
        if(!Double.isFinite(attempts)||attempts!=Math.rint(attempts)||attempts<0||attempts>=MAX_ATTEMPTS
            ||!Double.isFinite(progress)||progress<0||progress>=1)return false;
        // Re-reading the same cached passages can emit a newer checkpointAt.
        // Require advancement beyond the prior high-water mark, not just a
        // new timestamp, before allowing the second and final replacement.
        return attempts==0||progress>job.optDouble("rendererRecoveryProgress",1);
    }

    static JSONObject reserve(File files,String id,boolean crashed)throws Exception{
        synchronized(AnalysisJobStore.class){
            JSONObject job=AnalysisJobStore.matching(files,id,true);
            if(!eligible(job,crashed))return null;
            job.put("rendererRecoveryAttempts",job.optInt("rendererRecoveryAttempts",0)+1)
                .put("rendererRecoveryProgress",job.getDouble("progress"))
                .put("stage","Android reclaimed the analysis engine. Resuming saved progress automatically…");
            AnalysisJobStore.persist(files,job);return job;
        }
    }

    static long delayMillis(int attempt){return attempt==1?FIRST_DELAY_MS:SECOND_DELAY_MS;}
    static boolean ready(long elapsedMs,int attempt,boolean nativeRetired,boolean lowMemory){
        return attempt>=1&&attempt<=MAX_ATTEMPTS&&elapsedMs>=delayMillis(attempt)
            &&elapsedMs<MAX_WAIT_MS&&nativeRetired&&!lowMemory;
    }

    /**
     * Preserve the exact job, runtime, quality and fresh epoch. Partial OPFS
     * checkpoints are validated by the normal worker cache loaders; the status
     * flag is only permission to attempt recovery, never proof of cache validity.
     * Expensive source hashes run outside the store monitor so Cancel stays live.
     */
    static JSONObject restoreRequest(File files,String id)throws Exception{
        final JSONObject job,request;
        final String requestHash;
        File frozen=new File(AnalysisJobStore.directory(files),"request.json");
        synchronized(AnalysisJobStore.class){
            job=AnalysisJobStore.matching(files,id,true);request=AnalysisJobStore.request(files,id);
            requestHash=AnalysisJobStore.hash(frozen);
        }
        File project=AnalysisJobStore.project(files,job.getString("projectId"));
        if(!job.getString("sourceSHA256").equals(AnalysisJobStore.hash(new File(project,"project.json")))
            ||!job.getString("analysisIdentity").equals(AnalysisJobStore.analysisIdentity(project,job.getString("projectId"),request)))
            throw new IOException("The source or settings changed. Automatic analysis recovery was stopped.");
        if(job.optBoolean("hasCheckpoint")){
            File checkpoint=new File(AnalysisJobStore.directory(files),"checkpoint.json");
            if(!job.getString("checkpointSHA256").equals(AnalysisJobStore.hash(checkpoint)))
                throw new IOException("The saved analysis checkpoint changed.");
            JSONObject music=AnalysisJobStore.read(checkpoint,ProjectStore.MAX_PROJECT_BYTES);
            AnalysisJobStore.validateCheckpoint(music,request.getDouble("duration"));
            request.put("music",music).put("needAnalysis",false);
        }
        synchronized(AnalysisJobStore.class){
            JSONObject current=AnalysisJobStore.matching(files,id,true);
            AnalysisJobStore.request(files,id); // Recheck cancellation and execution lineage after I/O.
            if(!job.getString("sourceSHA256").equals(current.getString("sourceSHA256"))
                ||!requestHash.equals(AnalysisJobStore.hash(frozen)))
                throw new IOException("The analysis request changed during recovery.");
            if(job.optBoolean("hasCheckpoint"))AnalysisJobStore.write(frozen,request,ProjectStore.MAX_PROJECT_BYTES);
            return current;
        }
    }
}
