package com.cyberbasslord.lightforge;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.NoSuchFileException;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.Objects;
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
        return commitRequest(prepareRequest(files,id));
    }

    /** Validated bytes plus the identities of the files that supplied them. */
    static final class PreparedRequest {
        private final File files,frozen;
        private final String id,requestHash;
        private final JSONObject job,request;
        private final SourceFiles source;
        private PreparedRequest(File files,File frozen,String id,String requestHash,JSONObject job,JSONObject request,SourceFiles source){
            this.files=files;this.frozen=frozen;this.id=id;this.requestHash=requestHash;this.job=job;this.request=request;this.source=source;
        }
    }

    static PreparedRequest prepareRequest(File files,String id)throws Exception{
        final JSONObject job,request;
        final String requestHash;
        File frozen=new File(AnalysisJobStore.directory(files),"request.json");
        synchronized(AnalysisJobStore.class){
            job=AnalysisJobStore.matching(files,id,true);request=AnalysisJobStore.request(files,id);
            requestHash=AnalysisJobStore.hash(frozen);
        }
        File project=AnalysisJobStore.project(files,job.getString("projectId"));
        if(job.optBoolean("hasCheckpoint")){
            File checkpoint=new File(AnalysisJobStore.directory(files),"checkpoint.json");
            if(!job.getString("checkpointSHA256").equals(AnalysisJobStore.hash(checkpoint)))
                throw new IOException("The saved analysis checkpoint changed.");
            JSONObject music=AnalysisJobStore.read(checkpoint,ProjectStore.MAX_PROJECT_BYTES);
            AnalysisJobStore.validateCheckpoint(music,request.getDouble("duration"));
            request.put("music",music).put("needAnalysis",false);
        }
        final SourceFiles source;
        // ProjectStore publishes supported edits and repaired analysis audio
        // by replacement while holding this monitor. Never acquire the job
        // monitor here: Cancel must not wait for full audio hashing.
        synchronized(ProjectStore.class){
            source=new SourceFiles(project);
            if(!job.getString("sourceSHA256").equals(AnalysisJobStore.hash(new File(project,"project.json")))
                ||!job.getString("analysisIdentity").equals(AnalysisJobStore.analysisIdentity(project,job.getString("projectId"),request)))
                throw new IOException("The source or settings changed. Automatic analysis recovery was stopped.");
            source.requireUnchanged();
        }
        return new PreparedRequest(files,frozen,id,requestHash,job,request,source);
    }

    static JSONObject commitRequest(PreparedRequest prepared)throws Exception{
        File files=prepared.files;String id=prepared.id;JSONObject job=prepared.job;
        synchronized(AnalysisJobStore.class){
        synchronized(ProjectStore.class){
            JSONObject current=AnalysisJobStore.matching(files,id,true);
            AnalysisJobStore.request(files,id); // Recheck cancellation and execution lineage after I/O.
            if(!job.getString("sourceSHA256").equals(current.getString("sourceSHA256"))
                ||!job.getString("analysisIdentity").equals(current.getString("analysisIdentity"))
                ||!job.optString("checkpointSHA256").equals(current.optString("checkpointSHA256"))
                ||!prepared.requestHash.equals(AnalysisJobStore.hash(prepared.frozen)))
                throw new IOException("The analysis request changed during recovery.");
            // Preserve the established job -> project lock order. Revalidate
            // the actual hashed files at the commit boundary, including
            // atomic replacement with identical length/modification time.
            prepared.source.requireUnchanged();
            if(job.optBoolean("hasCheckpoint"))AnalysisJobStore.write(prepared.frozen,prepared.request,ProjectStore.MAX_PROJECT_BYTES);
            return current;
        }
        }
    }

    private static final class SourceFiles {
        private final File[] files;
        private final BasicFileAttributes[] states;
        SourceFiles(File project)throws IOException{
            files=new File[]{new File(project,"project.json"),new File(project,"audio.wav"),new File(project,"analysis.wav")};
            states=new BasicFileAttributes[files.length];
            for(int i=0;i<files.length;i++)states[i]=state(files[i],i==2);
        }
        void requireUnchanged()throws IOException{
            for(int i=0;i<files.length;i++){
                BasicFileAttributes before=states[i],after=state(files[i],i==2);
                if(before==null&&after==null)continue;
                if(before==null||after==null||!Objects.equals(before.fileKey(),after.fileKey())||before.size()!=after.size()
                    ||!before.lastModifiedTime().equals(after.lastModifiedTime())||!before.creationTime().equals(after.creationTime()))
                    throw new IOException("The source changed while preparing analysis recovery. Its newer files were preserved.");
            }
        }
        private static BasicFileAttributes state(File file,boolean optional)throws IOException{
            try{
                BasicFileAttributes attributes=Files.readAttributes(file.toPath(),BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
                if(!attributes.isRegularFile())throw new IOException("The analysis source is not a regular file.");
                if(attributes.fileKey()==null)throw new IOException("The source file identity is unavailable. Resume analysis manually.");
                return attributes;
            }catch(NoSuchFileException missing){if(optional)return null;throw missing;}
        }
    }
}
