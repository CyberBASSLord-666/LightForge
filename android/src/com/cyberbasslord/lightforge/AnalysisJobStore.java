package com.cyberbasslord.lightforge;

import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.util.UUID;

/** Durable single-writer analysis jobs. A stopped process never leaves a job claiming to run. */
final class AnalysisJobStore {
    private AnalysisJobStore() {}
    static boolean active(JSONObject job) {
        if(job==null)return false;
        String state=job.optString("state");
        return state.equals("queued")||state.equals("running")||state.equals("cancelling");
    }
    static File directory(File files) {return new File(files,"analysis-work");}
    static synchronized JSONObject status(File files) throws Exception {
        File file=new File(directory(files),"job.json");
        return file.isFile()?read(file,32768):null;
    }
    static synchronized void requireIdle(File files) throws Exception {
        if(active(status(files)))throw new IOException("Finish or cancel the background analysis first.");
    }
    static File project(File files,String id) throws IOException {
        if(id==null||!id.matches("[A-Za-z0-9_-]{1,80}"))throw new IOException("Invalid project identifier.");
        File root=new File(files,"projects").getCanonicalFile(),dir=new File(root,id);
        if(!dir.getCanonicalFile().equals(dir)||!dir.isDirectory())throw new IOException("The project is unavailable.");
        return dir;
    }
    static synchronized JSONObject prepare(File files,String projectId) throws Exception {
        requireIdle(files);
        File dir=project(files,projectId),source=new File(dir,"project.json");
        JSONObject request=read(source,ProjectStore.MAX_PROJECT_BYTES);
        if(!new File(dir,"audio.wav").isFile())throw new IOException("This project's audio is missing.");
        JSONObject meta=ProjectStore.describe(new File(files,"projects"),projectId);
        request.put("projectId",projectId).put("name",meta.getString("name")).put("duration",meta.getDouble("duration"));
        String sourceHash=hash(source);
        // Reuse only a completed analysis checkpoint belonging to these exact saved inputs.
        JSONObject old=status(files);
        File checkpoint=new File(directory(files),"checkpoint.json");
        boolean reuse=old!=null&&!"completed".equals(old.optString("state"))&&projectId.equals(old.optString("projectId"))
            &&sourceHash.equals(old.optString("sourceSHA256"))&&checkpoint.isFile();
        if(reuse){request.put("music",read(checkpoint,ProjectStore.MAX_PROJECT_BYTES));request.put("needAnalysis",false);}
        else Files.deleteIfExists(checkpoint.toPath());
        write(new File(directory(files),"request.json"),request,ProjectStore.MAX_PROJECT_BYTES);
        JSONObject job=new JSONObject().put("id",UUID.randomUUID().toString()).put("projectId",projectId)
            .put("name",meta.getString("name")).put("sourceSHA256",sourceHash).put("state","queued")
            .put("stage",reuse?"Restoring completed analysis":"Preparing background analysis").put("progress",0)
            .put("createdAt",System.currentTimeMillis()).put("updatedAt",System.currentTimeMillis()).put("hasCheckpoint",reuse);
        persist(files,job);return job;
    }
    static synchronized JSONObject request(File files,String id) throws Exception {
        matching(files,id,true);
        return read(new File(directory(files),"request.json"),ProjectStore.MAX_PROJECT_BYTES);
    }
    static JSONObject matching(File files,String id,boolean running) throws Exception {
        JSONObject job=status(files);
        if(job==null||!job.optString("id").equals(id)||(running&&(!active(job)||"cancelling".equals(job.optString("state")))))
            throw new IOException("The analysis job has ended.");
        return job;
    }
    static synchronized JSONObject progress(File files,String id,double progress,String stage) throws Exception {
        JSONObject job=matching(files,id,true);
        if(!Double.isFinite(progress))throw new IOException("Invalid analysis progress.");
        job.put("state","running").put("progress",Math.max(job.optDouble("progress"),Math.min(.999,Math.max(0,progress))))
            .put("stage",limited(stage,240));persist(files,job);return job;
    }
    static synchronized void checkpoint(File files,String id,String contents) throws Exception {
        JSONObject job=matching(files,id,true),music=parse(contents);
        if(music.optInt("analysisVersion")<5||music.optDouble("duration")<=0)throw new IOException("Invalid analysis checkpoint.");
        write(new File(directory(files),"checkpoint.json"),music,ProjectStore.MAX_PROJECT_BYTES);
        job.put("hasCheckpoint",true);persist(files,job);
    }
    static synchronized JSONObject complete(File files,String id,String contents) throws Exception {
        JSONObject job=matching(files,id,true),value=parse(contents);
        String projectId=job.getString("projectId");
        if(!projectId.equals(value.optString("projectId"))||value.optJSONObject("music")==null||value.optJSONObject("compiled")==null||value.optBoolean("needAnalysis",true))
            throw new IOException("The completed show is incomplete or belongs to another project.");
        if(!job.getString("sourceSHA256").equals(hash(new File(project(files,projectId),"project.json"))))
            throw new IOException("This project changed while analysis was running. Its newer edits were preserved.");
        value.put("backgroundJobId",id);
        ProjectStore.save(new File(files,"projects"),projectId,value);
        job.put("state","completed").put("progress",1).put("stage","Your show is ready");persist(files,job);
        Files.deleteIfExists(new File(directory(files),"checkpoint.json").toPath());
        return job;
    }
    static synchronized JSONObject finish(File files,String id,String state,String message) throws Exception {
        if(!state.matches("cancelled|failed|interrupted|cancelling"))throw new IOException("Invalid job state.");
        JSONObject job=matching(files,id,false);
        if(!active(job))return job;
        job.put("state",state).put("stage",limited(message,500));persist(files,job);return job;
    }
    static synchronized JSONObject recover(File files) throws Exception {
        JSONObject job=status(files);
        if(!active(job))return job;
        try {
            JSONObject project=read(new File(project(files,job.getString("projectId")),"project.json"),ProjectStore.MAX_PROJECT_BYTES);
            if(job.getString("id").equals(project.optString("backgroundJobId"))) {
                job.put("state","completed").put("progress",1).put("stage","Your show is ready");persist(files,job);return job;
            }
        }catch(Exception ignored){}
        return finish(files,job.getString("id"),"interrupted","Android stopped the previous analysis. Your saved show is intact. Retry to continue.");
    }
    static void persist(File files,JSONObject job) throws Exception {
        job.put("updatedAt",System.currentTimeMillis());write(new File(directory(files),"job.json"),job,32768);
    }
    static JSONObject parse(String text) throws Exception {
        if(text==null||text.length()>ProjectStore.MAX_PROJECT_BYTES)throw new IOException("Analysis metadata is too large.");
        return new JSONObject(text);
    }
    static JSONObject read(File file,int max) throws Exception {
        if(!file.isFile()||file.length()>max)throw new IOException("Analysis metadata is missing or too large.");
        byte[] bytes=Files.readAllBytes(file.toPath());
        if(bytes.length>max)throw new IOException("Analysis metadata is too large.");
        return new JSONObject(new String(bytes,StandardCharsets.UTF_8));
    }
    static void write(File target,JSONObject value,int max) throws Exception {
        byte[] bytes=value.toString().getBytes(StandardCharsets.UTF_8);
        if(bytes.length>max)throw new IOException("Analysis metadata is too large.");
        target.getParentFile().mkdirs();File temporary=new File(target.getPath()+".tmp");
        try(FileOutputStream out=new FileOutputStream(temporary)){out.write(bytes);out.getFD().sync();}
        Files.move(temporary.toPath(),target.toPath(),StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE);
    }
    static String limited(String text,int max){return text==null?"Working":text.substring(0,Math.min(text.length(),max));}
    static String hash(File file) throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        try(InputStream in=new FileInputStream(file)){byte[] bytes=new byte[65536];int n;while((n=in.read(bytes))!=-1)digest.update(bytes,0,n);}
        StringBuilder out=new StringBuilder();for(byte b:digest.digest())out.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return out.toString();
    }
}
