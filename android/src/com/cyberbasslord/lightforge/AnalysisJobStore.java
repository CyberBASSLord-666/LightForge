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
        return prepare(files,projectId,appVersion,false);
    }
    static synchronized JSONObject prepare(File files,String projectId,String appVersion,boolean requestFresh) throws Exception {
        requireIdle(files);
        File dir=project(files,projectId),source=new File(dir,"project.json");
        JSONObject request=read(source,ProjectStore.MAX_PROJECT_BYTES);
        // Execution lineage is trusted job metadata, never editable project data.
        // In particular a restored project cannot select or collide with an
        // analysis cache namespace.
        request.remove("analysisRunObservation");
        request.remove("analysisExecutionMode");
        request.remove("analysisRefreshEpoch");
        request.remove("analysisEffectiveExecution");
        request.remove("analysisNativeFallbackReason");
        request.remove("analysisNativeAttemptedExecution");
        request.remove("analysisJobId");
        request.remove("forceFreshAnalysis");
        if(!new File(dir,"audio.wav").isFile())throw new IOException("This project's audio is missing.");
        JSONObject meta=ProjectStore.describe(new File(files,"projects"),projectId);
        request.put("projectId",projectId).put("name",meta.getString("name")).put("duration",meta.getDouble("duration")).put("analysisAppVersion",appVersion);
        // Only a real JSON boolean false may skip analysis. Malformed/restored
        // values fail closed to new analysis rather than bypassing the cache
        // and checkpoint contract.
        Object rawNeedAnalysis=request.opt("needAnalysis");
        boolean needAnalysis=rawNeedAnalysis instanceof Boolean?(Boolean)rawNeedAnalysis:true;
        request.put("needAnalysis",needAnalysis);
        if(!needAnalysis){
            try{validateCheckpoint(request.optJSONObject("music"),meta.getDouble("duration"));}
            catch(Exception incomplete){request.put("needAnalysis",true);}
        }
        String sourceHash=hash(source),analysisIdentity=analysisIdentity(dir,projectId,request);
        request.put("analysisIdentity",analysisIdentity);
        JSONObject old=status(files);
        File checkpoint=new File(directory(files),"checkpoint.json");
        boolean matchingPrior=old!=null&&!"completed".equals(old.optString("state"))
            &&projectId.equals(old.optString("projectId"))&&analysisIdentity.equals(old.optString("analysisIdentity"));
        String priorMode=matchingPrior?normalizedExecutionMode(old):null;
        // AUTO resumes an interrupted explicit-fresh namespace exactly. An
        // explicit fresh request always creates a new namespace, including when
        // a previous fresh attempt exists.
        boolean priorFresh=!requestFresh&&"fresh".equals(priorMode);
        String executionMode=priorFresh||requestFresh?"fresh":"resume";
        String refreshEpoch=priorFresh?canonicalRefreshEpoch(old.optString("analysisRefreshEpoch")):(requestFresh?UUID.randomUUID().toString():null);
        // A native failure is persisted before WASM retry. Matching interrupted
        // work must keep that effective runtime so its OPFS checkpoint identity
        // remains deterministic across process death.
        boolean forceWasm=!requestFresh&&matchingPrior&&priorMode!=null&&"wasm-v1".equals(old.optString("analysisEffectiveExecution"));
        String nativeFallbackReason=forceWasm?old.optString("analysisNativeFallbackReason"):null;
        String nativeAttemptedExecution=!requestFresh&&matchingPrior?nativeFallbackExecution(old,request):null;
        if("fresh".equals(executionMode)){
            // Project.json is not the fresh request; always rebuild unless a
            // matching validated Java checkpoint is restored below.
            request.put("needAnalysis",true).remove("music");
        }
        request.put("analysisExecutionMode",executionMode);
        if(refreshEpoch!=null)request.put("analysisRefreshEpoch",refreshEpoch);else request.remove("analysisRefreshEpoch");
        if(forceWasm)request.put("analysisEffectiveExecution","wasm-v1").put("analysisNativeFallbackReason",nativeFallbackReason)
            .put("analysisNativeAttemptedExecution",nativeAttemptedExecution);
        boolean reuse=!requestFresh&&priorMode!=null&&matchingPrior&&checkpoint.isFile();
        if(reuse){
            try{
                if(!hash(checkpoint).equals(old.optString("checkpointSHA256")))throw new IOException("Analysis checkpoint changed.");
                JSONObject music=read(checkpoint,ProjectStore.MAX_PROJECT_BYTES);
                validateCheckpoint(music,meta.getDouble("duration"));
                request.put("music",music).put("needAnalysis",false);
            }catch(Exception damaged){reuse=false;}
        }
        if(!reuse)Files.deleteIfExists(checkpoint.toPath());
        String jobId=UUID.randomUUID().toString();
        request.put("analysisJobId",jobId);
        JSONObject job=new JSONObject().put("id",jobId).put("projectId",projectId)
            .put("name",meta.getString("name")).put("sourceSHA256",sourceHash).put("analysisIdentity",analysisIdentity)
            .put("analysisExecutionMode",executionMode).put("requestId",jobId).put("state","preparing")
            .put("stage",reuse?"Restoring completed analysis":"Preparing background analysis").put("progress",0)
            .put("createdAt",System.currentTimeMillis()).put("updatedAt",System.currentTimeMillis()).put("hasCheckpoint",reuse)
            .put("resumeAvailable",reuse||(matchingPrior&&priorMode!=null));
        if(refreshEpoch!=null)job.put("analysisRefreshEpoch",refreshEpoch);
        if(forceWasm)job.put("analysisEffectiveExecution","wasm-v1").put("analysisNativeFallbackReason",nativeFallbackReason)
            .put("analysisNativeAttemptedExecution",nativeAttemptedExecution);
        if(reuse)job.put("checkpointSHA256",old.getString("checkpointSHA256"));
        // No service can start until this method returns. Persist lineage before
        // publishing its frozen request, then atomically expose the queued job.
        // A process death at either boundary leaves only a non-active
        // "preparing" record; the next prepare reconstructs the same trusted
        // fresh epoch or intentionally creates a new one.
        persist(files,job);
        write(new File(directory(files),"request.json"),request,ProjectStore.MAX_PROJECT_BYTES);
        job.put("state","queued");
        persist(files,job);
        return job;
    }
    private static String canonicalRefreshEpoch(String value){
        return validRefreshEpoch(value)?value.toLowerCase(java.util.Locale.ROOT):null;
    }
    private static String normalizedExecutionMode(JSONObject value){
        if(value==null)return null;
        boolean hasMode=value.has("analysisExecutionMode"),hasEpoch=value.has("analysisRefreshEpoch");
        String mode=value.optString("analysisExecutionMode"),epoch=canonicalRefreshEpoch(value.optString("analysisRefreshEpoch"));
        // Legacy jobs without either field are the ordinary resume namespace.
        if(!hasMode&&!hasEpoch)return "resume";
        if("resume".equals(mode)&&!hasEpoch)return "resume";
        if("fresh".equals(mode)&&hasEpoch&&epoch!=null)return "fresh";
        return null;
    }
    private static boolean validRefreshEpoch(String value){
        return value!=null&&value.matches("^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[1-5][a-fA-F0-9]{3}-[89aAbB][a-fA-F0-9]{3}-[a-fA-F0-9]{12}$");
    }
    private static boolean validNativeFallbackReason(String value){
        return "native-deux-fallback".equals(value)||"native-mdx-fallback".equals(value)||"native-game-fallback".equals(value);
    }
    private static String legacyNativeExecution(String reason){
        return "native-deux-fallback".equals(reason)?"native-deux-v1":"native-mdx-fallback".equals(reason)?"native-mdx-v1":null;
    }
    private static void validateNativeAttempt(String reason,String execution,JSONObject request)throws IOException{
        if(!validNativeFallbackReason(reason)||execution==null)throw new IOException("Invalid native fallback lineage.");
        boolean deux="native-deux-v1".equals(execution)||"native-deux-v1+native-game-v1".equals(execution);
        boolean mdx="native-mdx-v1".equals(execution)||"native-mdx-v1+native-game-v1".equals(execution);
        boolean game="native-game-v1".equals(execution)||"native-deux-v1+native-game-v1".equals(execution)||"native-mdx-v1+native-game-v1".equals(execution);
        JSONObject settings=request.optJSONObject("settings");
        boolean balanced=settings!=null&&"balanced".equals(settings.optString("analysisQuality"));
        if((!deux&&!mdx&&!game)||(deux&&balanced)||(mdx&&!balanced)
            ||("native-deux-fallback".equals(reason)&&!deux)||("native-mdx-fallback".equals(reason)&&!mdx)
            ||("native-game-fallback".equals(reason)&&!game))throw new IOException("Native fallback does not match its execution or quality mode.");
    }
    /** Validate every field; only old separator-only records may omit the attempted execution. */
    private static String nativeFallbackExecution(JSONObject lineage,JSONObject request)throws IOException{
        boolean effective=lineage.has("analysisEffectiveExecution"),reason=lineage.has("analysisNativeFallbackReason"),attempted=lineage.has("analysisNativeAttemptedExecution");
        if(!effective&&!reason&&!attempted)return null;
        if(!effective||!reason||!"wasm-v1".equals(lineage.opt("analysisEffectiveExecution"))
            ||!(lineage.opt("analysisNativeFallbackReason") instanceof String)
            ||(attempted&&!(lineage.opt("analysisNativeAttemptedExecution") instanceof String)))
            throw new IOException("The persisted native fallback lineage is incomplete.");
        String fallbackReason=lineage.optString("analysisNativeFallbackReason");
        String execution=attempted?lineage.optString("analysisNativeAttemptedExecution"):legacyNativeExecution(fallbackReason);
        validateNativeAttempt(fallbackReason,execution,request);
        return execution;
    }
        static String analysisIdentity(File dir,String projectId,JSONObject request)throws Exception {
        JSONObject settings=request.optJSONObject("settings");if(settings==null)settings=new JSONObject();
        String quality="balanced".equals(settings.optString("analysisQuality"))?"balanced":"precision";
        double sensitivity=settings.optDouble("sensitivity",.82),bpm=settings.optDouble("bpmOverride",0);
        if(!Double.isFinite(sensitivity)||!Double.isFinite(bpm))throw new IOException("Invalid analysis settings.");
        File analysis=new File(dir,"analysis.wav");
        String input="bounded-analysis-v3|"+request.optString("analysisAppVersion")+"|"+projectId+"|"+hash(new File(dir,"audio.wav"))+"|"+(analysis.isFile()?hash(analysis):"")+"|"+quality+"|"+sensitivity+"|"+bpm;
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        byte[] bytes=digest.digest(input.getBytes(StandardCharsets.UTF_8));
        StringBuilder out=new StringBuilder();for(byte b:bytes)out.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return out.toString();
    }
    static synchronized JSONObject request(File files,String id) throws Exception {
        JSONObject job=matching(files,id,true),request=read(new File(directory(files),"request.json"),ProjectStore.MAX_PROJECT_BYTES);
        // New jobs bind the immutable request to the durable job id. Legacy
        // in-flight jobs without requestId remain readable for upgrade safety.
        if(job.has("requestId")&&!id.equals(request.optString("analysisJobId")))throw new IOException("The analysis request binding is invalid.");
        String jobMode=normalizedExecutionMode(job),requestMode=normalizedExecutionMode(request);
        if(jobMode==null||requestMode==null||!jobMode.equals(requestMode)
            ||!job.optString("projectId").equals(request.optString("projectId"))
            ||!job.optString("analysisIdentity").equals(request.optString("analysisIdentity")))
            throw new IOException("The analysis request lineage is invalid.");
        if("fresh".equals(jobMode)&&!canonicalRefreshEpoch(job.optString("analysisRefreshEpoch")).equals(canonicalRefreshEpoch(request.optString("analysisRefreshEpoch"))))
            throw new IOException("The analysis refresh epoch does not match its job.");
        String jobAttempt=nativeFallbackExecution(job,request),requestAttempt=nativeFallbackExecution(request,request);
        if((jobAttempt==null)!=(requestAttempt==null))throw new IOException("The effective analysis runtime does not match its job.");
        if(jobAttempt!=null&&(!jobAttempt.equals(requestAttempt)
            ||job.has("analysisNativeAttemptedExecution")!=request.has("analysisNativeAttemptedExecution")
            ||!job.optString("analysisNativeFallbackReason").equals(request.optString("analysisNativeFallbackReason"))))
            throw new IOException("The native fallback lineage does not match its job.");
        return request;
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
    static synchronized boolean markAnalysisWasmFallback(File files,String id,String reason) throws Exception {
        String execution=legacyNativeExecution(reason);
        if(execution==null)throw new IOException("An exact attempted execution is required for this native fallback.");
        return markAnalysisWasmFallback(files,id,reason,execution);
    }
    static synchronized boolean markAnalysisWasmFallback(File files,String id,String reason,String attemptedExecution) throws Exception {
        JSONObject job=matching(files,id,true),request=request(files,id);
        validateNativeAttempt(reason,attemptedExecution,request);
        String prior=nativeFallbackExecution(job,request);
        if(prior!=null&&(!prior.equals(attemptedExecution)||!reason.equals(job.optString("analysisNativeFallbackReason"))))
            throw new IOException("A conflicting native fallback was already persisted.");
        // Persist the job lineage first. A crash before the frozen request is
        // republished is still recoverable: prepare() reconstructs this marker
        // from the matching nonterminal job before any runner can start.
        job.put("analysisEffectiveExecution","wasm-v1").put("analysisNativeFallbackReason",reason)
            .put("analysisNativeAttemptedExecution",attemptedExecution);
        persist(files,job);
        request.put("analysisEffectiveExecution","wasm-v1").put("analysisNativeFallbackReason",reason)
            .put("analysisNativeAttemptedExecution",attemptedExecution);
        write(new File(directory(files),"request.json"),request,ProjectStore.MAX_PROJECT_BYTES);
        return true;
    }
    static synchronized void checkpoint(File files,String id,String contents) throws Exception {
        JSONObject job=matching(files,id,true),music=parse(contents);
        JSONObject request=read(new File(directory(files),"request.json"),ProjectStore.MAX_PROJECT_BYTES);
        validateCheckpoint(music,request.getDouble("duration"));
        File checkpoint=new File(directory(files),"checkpoint.json");write(checkpoint,music,ProjectStore.MAX_PROJECT_BYTES);
        job.put("hasCheckpoint",true).put("resumeAvailable",true).put("checkpointAt",System.currentTimeMillis()).put("checkpointSHA256",hash(checkpoint));persist(files,job);
    }
    /**
     * Clear only a prior supplementary app-run observation before a fresh
     * analysis starts.  The project source hash is refreshed only after the
     * durable project commit succeeds, so completion still rejects real edits.
     */
    static synchronized void clearRunObservation(File files,String id) throws Exception {
        JSONObject job=matching(files,id,true);
        // Fresh requests created by current builds are already scrubbed in
        // prepare(). Rewriting here is a defence in depth repair for an
        // in-flight or legacy request that was frozen before that rule existed.
        // Do this before touching the durable project so a conflict cannot
        // leave an exposed worker request behind.
        clearFrozenRequestRunObservation(files);
        String sourceHash=ProjectStore.clearAnalysisRunObservation(
            new File(files,"projects"),job.getString("projectId"),job.getString("sourceSHA256"));
        job.put("sourceSHA256",sourceHash);
        persist(files,job);
    }
    private static void clearFrozenRequestRunObservation(File files) throws Exception {
        File frozen=new File(directory(files),"request.json");
        if(!frozen.isFile())return; // Legacy terminal jobs may have no request.
        JSONObject request=read(frozen,ProjectStore.MAX_PROJECT_BYTES);
        if(request.has("analysisRunObservation")){
            request.remove("analysisRunObservation");
            write(frozen,request,ProjectStore.MAX_PROJECT_BYTES);
        }
    }
    static void validateCheckpoint(JSONObject music,double sourceDuration)throws IOException {
        if(music==null)throw new IOException("Analysis checkpoint is incomplete.");
        double duration=music.optDouble("duration"),bpm=music.optDouble("bpm");int version=music.optInt("analysisVersion");
        if((version!=5&&version!=6&&version!=8)||!Double.isFinite(duration)||duration<=0||duration>14400||!Double.isFinite(sourceDuration)||Math.abs(duration-sourceDuration)>1e-7
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
        if(version>=6){
            JSONObject transcription=voice.optJSONObject("transcription"),roles=music.optJSONObject("roleAnalysis"),separation=engine.optJSONObject("separationModel");
            if(transcription==null||transcription.optString("model").isEmpty()||roles==null||!roles.optBoolean("sourceSeparated")||separation==null||!separation.optBoolean("sourceSeparated")||separation.optString("modelId").isEmpty())throw new IOException("Studio analysis did not complete every model stage.");
            objects(transcription,"notes");
        }
        if(version==8)validateCanonicalSemantics(music,duration);
    }
    static String semanticTier(double score){return score>=.90?"climax":score>=.76?"structural":score>=.60?"phrase":score>=.42?"primary":score>=.25?"secondary":"micro";}
    static String salienceTier(double score){return score>=.90?"climax":score>=.78?"structural":score>=.62?"phrase":score>=.52?"primary":score>=.32?"secondary":"micro";}
    static boolean knownTier(String tier){return "micro".equals(tier)||"secondary".equals(tier)||"primary".equals(tier)||"phrase".equals(tier)||"structural".equals(tier)||"climax".equals(tier);}
    static void validateCanonicalSemantics(JSONObject music,double duration)throws IOException {
        JSONObject timeline=music.optJSONObject("semanticTimeline"),salience=music.optJSONObject("musicSalience");
        if(timeline==null||timeline.optInt("schemaVersion",-1)!=2||!"original-decoded-audio".equals(timeline.optString("clock"))||!Double.isFinite(timeline.optDouble("duration",Double.NaN))||Math.abs(timeline.optDouble("duration",Double.NaN)-duration)>1e-7)throw new IOException("Canonical semantic timeline is missing or uses the wrong clock.");
        JSONArray timelineEvents=array(timeline,"events");java.util.HashSet<String> timelineIds=new java.util.HashSet<>();double previous=-1;
        for(int index=0;index<timelineEvents.length();index++){
            JSONObject event=objectAt(timelineEvents,index,"Invalid canonical semantic event.");
            String id=event.optString("id"),type=event.optString("type"),source=event.optString("source"),tier=event.optString("tier");
            double time=event.optDouble("time",Double.NaN),eventDuration=event.optDouble("duration",Double.NaN),eventSalience=event.optDouble("salience",Double.NaN);
            if(!id.matches("[A-Za-z0-9._:-]{1,160}")||!timelineIds.add(id)||type.isEmpty()||source.isEmpty()||!knownTier(tier)||!Double.isFinite(time)||time<0||time>duration||time<previous||!Double.isFinite(eventDuration)||eventDuration<0||time+eventDuration>duration+1e-6||!Double.isFinite(eventSalience)||eventSalience<0||eventSalience>1||!semanticTier(eventSalience).equals(tier))throw new IOException("Canonical semantic timeline is inconsistent.");
            if(event.has("salienceCap")){double cap=event.optDouble("salienceCap",Double.NaN);if(!Double.isFinite(cap)||cap<0||cap>1||eventSalience>cap+1e-9)throw new IOException("Canonical semantic salience cap is inconsistent.");}
            previous=time;
        }
        if(salience==null||salience.optInt("schemaVersion",-1)!=1||!"1.0.0".equals(salience.optString("engineVersion"))||salience.optInt("timelineSchemaVersion",-1)!=2||!salience.optString("timelineFingerprint").matches("[0-9a-f]{8}")||!"original-decoded-audio".equals(salience.optString("clock"))||!Double.isFinite(salience.optDouble("duration",Double.NaN))||Math.abs(salience.optDouble("duration",Double.NaN)-duration)>1e-7)throw new IOException("Canonical music salience is missing or uses the wrong clock.");
        JSONArray ranked=array(salience,"events");JSONObject summary=salience.optJSONObject("summary");if(summary==null||ranked.length()!=timelineEvents.length()||summary.optInt("eventCount",-1)!=ranked.length())throw new IOException("Canonical music salience does not cover the semantic timeline.");
        java.util.HashSet<String> rankedIds=new java.util.HashSet<>();java.util.HashSet<Integer> ranks=new java.util.HashSet<>();java.util.HashMap<String,Integer> counts=new java.util.HashMap<>();JSONObject[] byRank=new JSONObject[ranked.length()];double[] scoresByRank=new double[ranked.length()],timesByRank=new double[ranked.length()];String[] idsByRank=new String[ranked.length()];for(String tier:new String[]{"micro","secondary","primary","phrase","structural","climax"})counts.put(tier,0);
        for(int index=0;index<ranked.length();index++){
            JSONObject entry=objectAt(ranked,index,"Invalid canonical salience event."),timelineEvent=objectAt(timelineEvents,index,"Invalid canonical semantic event.");
            String id=entry.optString("id"),tier=entry.optString("tier");Object rankValue=entry.opt("rank");double rawRank=rankValue instanceof Number?((Number)rankValue).doubleValue():Double.NaN,score=entry.optDouble("score",Double.NaN);boolean integralRank=Double.isFinite(rawRank)&&rawRank==Math.rint(rawRank)&&rawRank>=1&&rawRank<=ranked.length();int rank=integralRank?(int)rawRank:-1;
            if(!timelineIds.contains(id)||!rankedIds.add(id)||!id.equals(timelineEvent.optString("id"))||!Double.isFinite(score)||score<0||score>1||!salienceTier(score).equals(tier)||rank<1||rank>ranked.length()||!ranks.add(rank))throw new IOException("Canonical music salience is not a one-to-one ranking.");
            byRank[rank-1]=entry;scoresByRank[rank-1]=score;timesByRank[rank-1]=timelineEvent.optDouble("time",Double.NaN);idsByRank[rank-1]=id;counts.put(tier,counts.get(tier)+1);
        }
        for(int rank=1;rank<=ranked.length();rank++)if(!ranks.contains(rank)||byRank[rank-1]==null)throw new IOException("Canonical music salience ranks are not contiguous.");
        for(int rank=1;rank<ranked.length();rank++){
            int scoreOrder=Double.compare(scoresByRank[rank-1],scoresByRank[rank]),timeOrder=Double.compare(timesByRank[rank-1],timesByRank[rank]);
            // Timeline identifiers are ASCII by schema, matching the producer's compareText tie break.
            if(scoreOrder<0||(scoreOrder==0&&(timeOrder>0||(timeOrder==0&&idsByRank[rank-1].compareTo(idsByRank[rank])>0))))throw new IOException("Canonical music salience rank order is inconsistent.");
        }
        JSONObject countByTier=summary.optJSONObject("countByTier");if(countByTier==null)throw new IOException("Canonical music salience summary is missing.");for(String tier:counts.keySet())if(countByTier.optInt(tier,-1)!=counts.get(tier))throw new IOException("Canonical music salience summary is inconsistent.");
        JSONObject context=summary.optJSONObject("context");if(context==null||!("vocal-led".equals(context.optString("profile"))||"low-end-led".equals(context.optString("profile"))||"rhythm-led".equals(context.optString("profile"))||"balanced".equals(context.optString("profile"))||"sparse".equals(context.optString("profile")))||!Double.isFinite(context.optDouble("eventDensity",Double.NaN))||context.optDouble("eventDensity",Double.NaN)<0)throw new IOException("Canonical music salience context is invalid.");
        JSONObject evidence=context.optJSONObject("evidence"),priorities=context.optJSONObject("sourcePriorities"),weights=context.optJSONObject("weights");if(evidence==null||priorities==null||weights==null)throw new IOException("Canonical music salience context is incomplete.");
        for(String key:new String[]{"vocal","bass","rhythm","percussion","structural"}){double value=evidence.optDouble(key,Double.NaN);if(!Double.isFinite(value)||value<0||value>1)throw new IOException("Canonical music salience evidence is invalid.");}
        for(String key:new String[]{"vocals","bass","rhythm","drums","mix","structure"}){double value=priorities.optDouble(key,Double.NaN);if(!Double.isFinite(value)||value<0||value>1)throw new IOException("Canonical music salience priorities are invalid.");}
        double total=0;for(String key:new String[]{"baseline","confidence","intensity","structural","rhythmic","transition","crossStem","recurrence","sourcePriority"}){double value=weights.optDouble(key,Double.NaN);if(!Double.isFinite(value)||value<0)throw new IOException("Canonical music salience weights are invalid.");total+=value;}if(Math.abs(total-1)>1e-6)throw new IOException("Canonical music salience weights do not sum to one.");
        JSONArray highlights=array(summary,"highlights"),topIds=array(summary,"topEventIds");int expectedHighlights=Math.min(32,ranked.length());if(highlights.length()!=expectedHighlights||topIds.length()!=expectedHighlights)throw new IOException("Canonical music salience highlights are incomplete.");
        for(int index=0;index<expectedHighlights;index++){
            JSONObject highlight=objectAt(highlights,index,"Canonical music salience highlight is invalid."),matching=byRank[index];if(!(topIds.opt(index) instanceof String)||!((String)topIds.opt(index)).equals(matching.optString("id"))||!highlight.optString("id").equals(matching.optString("id")))throw new IOException("Canonical music salience highlights are out of rank order.");
            if(highlight.optDouble("score",Double.NaN)!=matching.optDouble("score",Double.NaN)||!highlight.optString("tier").equals(matching.optString("tier"))||highlight.optInt("rank",-1)!=index+1)throw new IOException("Canonical music salience highlight is stale.");
            JSONArray drivers=highlight.optJSONArray("drivers");if(drivers==null)throw new IOException("Canonical music salience highlight drivers are missing.");for(int driver=0;driver<drivers.length();driver++)if(!(drivers.opt(driver) instanceof String))throw new IOException("Canonical music salience highlight driver is invalid.");
        }
    }
    static JSONObject objectAt(JSONArray value,int index,String error)throws IOException {
        JSONObject object=value.optJSONObject(index);if(object==null)throw new IOException(error);return object;
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
        // A crash in prepare() can leave a durable lineage record before the
        // frozen request becomes runnable. Expose it as a resumable interrupt,
        // preserving its epoch/effective-runtime marker for the next prepare.
        if(job!=null&&"preparing".equals(job.optString("state"))){
            job.put("state","interrupted").put("stage","Analysis preparation was interrupted. Resume continues from its verified namespace.").put("stoppedAt",System.currentTimeMillis());
            persist(files,job);return job;
        }
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
