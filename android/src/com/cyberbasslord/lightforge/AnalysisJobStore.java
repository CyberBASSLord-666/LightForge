package com.cyberbasslord.lightforge;

import org.json.JSONObject;
import org.json.JSONArray;
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
    static synchronized JSONObject prepare(File files,String projectId,String appVersion) throws Exception {
        requireIdle(files);
        File dir=project(files,projectId),source=new File(dir,"project.json");
        JSONObject request=read(source,ProjectStore.MAX_PROJECT_BYTES);
        if(!new File(dir,"audio.wav").isFile())throw new IOException("This project's audio is missing.");
        JSONObject meta=ProjectStore.describe(new File(files,"projects"),projectId);
        request.put("projectId",projectId).put("name",meta.getString("name")).put("duration",meta.getDouble("duration")).put("analysisAppVersion",appVersion);
        // Only explicit generation reaches here; reading old compiled projects is unchanged.
        // Incomplete saved music must be re-analyzed instead of failing every Resume.
        if(!request.optBoolean("needAnalysis",true)){
            try{validateCheckpoint(request.optJSONObject("music"),meta.getDouble("duration"));}
            catch(Exception incomplete){request.put("needAnalysis",true);}
        }
        String sourceHash=hash(source),analysisIdentity=analysisIdentity(dir,projectId,request);
        request.put("analysisIdentity",analysisIdentity);
        // Names, save timestamps and choreography edits do not invalidate audio analysis.
        // The separate source hash still protects the final project commit from conflicts.
        JSONObject old=status(files);
        File checkpoint=new File(directory(files),"checkpoint.json");
        // The renderer stores stage checkpoints in OPFS. They are intentionally
        // separate from the small Java checkpoint.json, so a process kill can
        // leave useful resumable work even when no complete music object has
        // crossed the bridge yet. Preserve that UI signal for matching jobs.
        boolean priorResume=old!=null&&old.optBoolean("resumeAvailable")&&projectId.equals(old.optString("projectId"))
            &&analysisIdentity.equals(old.optString("analysisIdentity"));
        boolean reuse=old!=null&&!"completed".equals(old.optString("state"))&&projectId.equals(old.optString("projectId"))
            &&analysisIdentity.equals(old.optString("analysisIdentity"))&&checkpoint.isFile();
        if(reuse){
            // A torn or damaged checkpoint must not trap every retry in the same failure.
            try{if(!hash(checkpoint).equals(old.optString("checkpointSHA256")))throw new IOException("Analysis checkpoint changed.");
                JSONObject music=read(checkpoint,ProjectStore.MAX_PROJECT_BYTES);validateCheckpoint(music,meta.getDouble("duration"));
                request.put("music",music).put("needAnalysis",false);
            }catch(Exception damaged){reuse=false;}
        }
        if(!reuse)Files.deleteIfExists(checkpoint.toPath());
        write(new File(directory(files),"request.json"),request,ProjectStore.MAX_PROJECT_BYTES);
        JSONObject job=new JSONObject().put("id",UUID.randomUUID().toString()).put("projectId",projectId)
            .put("name",meta.getString("name")).put("sourceSHA256",sourceHash).put("analysisIdentity",analysisIdentity).put("state","queued")
            .put("stage",reuse?"Restoring completed analysis":"Preparing background analysis").put("progress",0)
            .put("createdAt",System.currentTimeMillis()).put("updatedAt",System.currentTimeMillis()).put("hasCheckpoint",reuse)
            .put("resumeAvailable",reuse||priorResume);
        if(reuse)job.put("checkpointSHA256",old.getString("checkpointSHA256"));
        persist(files,job);return job;
    }
    static String analysisIdentity(File dir,String projectId,JSONObject request)throws Exception {
        JSONObject settings=request.optJSONObject("settings");if(settings==null)settings=new JSONObject();
        String quality="balanced".equals(settings.optString("analysisQuality"))?"balanced":"precision";
        double sensitivity=settings.optDouble("sensitivity",.82),bpm=settings.optDouble("bpmOverride",0);
        if(!Double.isFinite(sensitivity)||!Double.isFinite(bpm))throw new IOException("Invalid analysis settings.");
        File analysis=new File(dir,"analysis.wav");
        String input="bounded-analysis-v2|"+request.optString("analysisAppVersion")+"|"+projectId+"|"+hash(new File(dir,"audio.wav"))+"|"+(analysis.isFile()?hash(analysis):"")+"|"+quality+"|"+sensitivity+"|"+bpm;
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        byte[] bytes=digest.digest(input.getBytes(StandardCharsets.UTF_8));
        StringBuilder out=new StringBuilder();for(byte b:bytes)out.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return out.toString();
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
        return progress(files,id,progress,stage,null);
    }
    static synchronized JSONObject progress(File files,String id,double progress,String stage,JSONObject info) throws Exception {
        JSONObject job=matching(files,id,true);
        if(!Double.isFinite(progress))throw new IOException("Invalid analysis progress.");
        String detail=limited(stage,240);long now=System.currentTimeMillis();
        if(progress>job.optDouble("progress")||!detail.equals(job.optString("stage")))job.put("progressAt",now);
        job.put("state","running").put("progress",Math.max(job.optDouble("progress"),Math.min(.999,Math.max(0,progress))))
            .put("stage",detail).put("elapsedMs",Math.max(0,now-job.optLong("createdAt",now)));
        if(info!=null){
            // Only bounded display facts cross the WebView bridge; never arbitrary job fields.
            if(info.has("stage")&&!info.optString("stage").equals(job.optString("analysisStage"))){
                for(String key:new String[]{"passageIndex","passageCount","passagesCompleted","restoredPassages"})job.remove(key);
            }
            for(String key:new String[]{"passageIndex","passageCount","passagesCompleted","restoredPassages","completedStages","restoredStages"}){
                if(info.has(key)){double value=info.optDouble(key);
                    if(!Double.isFinite(value)||value<0||value>1000000||value!=Math.rint(value))throw new IOException("Invalid analysis progress detail.");
                    job.put(key,(int)value);
                }
            }
            if(info.has("stage"))job.put("analysisStage",limited(info.optString("stage"),120));
            if(info.optBoolean("checkpointSaved")){job.put("resumeAvailable",true).put("checkpointAt",now);}
        }
        persist(files,job);return job;
    }
    static synchronized void checkpoint(File files,String id,String contents) throws Exception {
        JSONObject job=matching(files,id,true),music=parse(contents);
        JSONObject request=read(new File(directory(files),"request.json"),ProjectStore.MAX_PROJECT_BYTES);
        validateCheckpoint(music,request.getDouble("duration"));
        File checkpoint=new File(directory(files),"checkpoint.json");write(checkpoint,music,ProjectStore.MAX_PROJECT_BYTES);
        job.put("hasCheckpoint",true).put("resumeAvailable",true).put("checkpointAt",System.currentTimeMillis()).put("checkpointSHA256",hash(checkpoint));persist(files,job);
    }
    static void validateCheckpoint(JSONObject music,double sourceDuration)throws IOException {
        if(music==null)throw new IOException("Analysis checkpoint is incomplete.");
        double duration=music.optDouble("duration"),bpm=music.optDouble("bpm");int version=music.optInt("analysisVersion");
        if((version!=5&&version!=6)||!Double.isFinite(duration)||duration<=0||duration>14400||!Double.isFinite(sourceDuration)||Math.abs(duration-sourceDuration)>1e-7
            ||!Double.isFinite(bpm)||bpm<0||bpm>400)throw new IOException("Analysis checkpoint does not match the source audio.");
        numericArray(music,"beats",false,0,duration);numericArray(music,"downbeats",false,0,duration);
        numericArray(music,"waveform",true,0,1);numericArray(music,"energy",true,0,1);
        JSONArray sections=array(music,"sections");if(sections.length()==0)throw new IOException("Analysis sections are missing.");
        double previous=0;
        for(int i=0;i<sections.length();i++){
            JSONObject section=sections.optJSONObject(i);if(section==null)throw new IOException("Invalid analysis section.");
            double start=section.optDouble("start"),end=section.optDouble("end"),energy=section.optDouble("energy");
            if(!Double.isFinite(start)||!Double.isFinite(end)||!Double.isFinite(energy)||start<0||end<=start||end>duration+1e-7||Math.abs(start-previous)>1e-7||energy<0||energy>1)throw new IOException("Analysis sections do not cover the audio.");
            previous=end;
        }
        if(Math.abs(previous-duration)>1e-7)throw new IOException("Analysis sections do not cover the audio.");
        for(String key:new String[]{"onsets","bassNotes"})objects(music,key);
        JSONArray warnings=array(music,"warnings");for(int i=0;i<warnings.length();i++)if(!(warnings.opt(i) instanceof String))throw new IOException("Invalid analysis warning.");
        JSONObject engine=music.optJSONObject("engine"),voice=music.optJSONObject("vocals"),bass=music.optJSONObject("bassAnalysis");
        if(engine==null||!engine.optBoolean("neural")||engine.optString("name").isEmpty()||voice==null||bass==null)throw new IOException("Analysis model or musical-role results are missing.");
        for(String key:new String[]{"phrases","accents","notes"})objects(voice,key);
        numericArray(voice,"envelope",false,0,1);objects(bass,"phrases");numericArray(bass,"envelope",false,0,1);
        if(version==6){
            JSONObject transcription=voice.optJSONObject("transcription"),roles=music.optJSONObject("roleAnalysis"),separation=engine.optJSONObject("separationModel");
            if(transcription==null||transcription.optString("model").isEmpty()||roles==null||!roles.optBoolean("sourceSeparated")||separation==null||!separation.optBoolean("sourceSeparated")||separation.optString("modelId").isEmpty())throw new IOException("Studio analysis did not complete every model stage.");
            objects(transcription,"notes");
        }
    }
    static JSONArray array(JSONObject value,String key)throws IOException {
        JSONArray array=value.optJSONArray(key);if(array==null)throw new IOException("Analysis checkpoint is missing "+key+".");return array;
    }
    static void objects(JSONObject value,String key)throws IOException {
        JSONArray array=array(value,key);for(int i=0;i<array.length();i++)if(array.optJSONObject(i)==null)throw new IOException("Analysis checkpoint contains invalid "+key+".");
    }
    static void numericArray(JSONObject value,String key,boolean nonempty,double minimum,double maximum)throws IOException {
        JSONArray array=array(value,key);if(nonempty&&array.length()==0)throw new IOException("Analysis checkpoint is missing "+key+".");
        for(int i=0;i<array.length();i++){
            Object item=array.opt(i);double number=item instanceof Number?((Number)item).doubleValue():Double.NaN;
            if(!Double.isFinite(number)||number<minimum||number>maximum)throw new IOException("Analysis checkpoint contains invalid "+key+" values.");
        }
    }
    static synchronized JSONObject complete(File files,String id,String contents) throws Exception {
        JSONObject job=matching(files,id,true),value=parse(contents);
        String projectId=job.getString("projectId");
        if(!projectId.equals(value.optString("projectId"))||value.optJSONObject("music")==null||value.optJSONObject("compiled")==null||value.optBoolean("needAnalysis",true))
            throw new IOException("The completed show is incomplete or belongs to another project.");
        validateCheckpoint(value.getJSONObject("music"),read(new File(directory(files),"request.json"),ProjectStore.MAX_PROJECT_BYTES).getDouble("duration"));
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
        if(!"cancelling".equals(job.optString("state")))job.put("lastStage",job.optString("stage"));
        long now=System.currentTimeMillis();
        job.put("state",state).put("stage",limited(message,500)).put("elapsedMs",Math.max(0,now-job.optLong("createdAt",now)));
        if(!"cancelling".equals(state))job.put("stoppedAt",now);
        persist(files,job);return job;
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
        if("cancelling".equals(job.optString("state")))return finish(files,job.getString("id"),"cancelled","Analysis cancelled. Your saved show is intact.");
        return finish(files,job.getString("id"),"interrupted","Android stopped the previous analysis. Resume checks saved passages and continues from verified progress. Your saved show is intact.");
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
