package com.cyberbasslord.lightforge;

import org.json.JSONObject;
import org.json.JSONArray;
import java.io.*;
import java.nio.file.Files;

/** Executes durable job transactions against real project files on the host JVM. */
public final class AnalysisJobStoreTest {
    interface Operation{void run()throws Exception;}
    static void check(boolean ok,String label){if(!ok)throw new AssertionError(label);}
    static void reject(Operation op)throws Exception{try{op.run();}catch(Exception expected){return;}throw new AssertionError("Invalid transaction accepted");}
    static JSONObject read(File file)throws Exception{return AnalysisJobStore.read(file,ProjectStore.MAX_PROJECT_BYTES);}
    static JSONObject eligibleGame(File files,String id)throws Exception {
        long gib=AnalysisResourcePolicy.GIB;
        return AnalysisJobStore.gameParallelism(files,id,7*gib,4*gib,4,true,false);
    }
    static void changeSample(File audio)throws Exception {
        try(RandomAccessFile edit=new RandomAccessFile(audio,"rw")){edit.seek(edit.length()-1);int sample=edit.read();edit.seek(edit.length()-1);edit.write(sample^1);}
    }
    static void gameParallelTests(File files,String projectId,File saved,JSONObject music)throws Exception {
        long gib=AnalysisResourcePolicy.GIB;
        check(AnalysisResourcePolicy.gameParallelism(7*gib,4*gib,4,true,false)==2,"Exact parallel memory/core boundaries rejected");
        check(AnalysisResourcePolicy.gameParallelism(7*gib-1,4*gib,4,true,false)==1,"Below total-memory boundary admitted");
        check(AnalysisResourcePolicy.gameParallelism(7*gib,4*gib-1,4,true,false)==1,"Below available-memory boundary admitted");
        check(AnalysisResourcePolicy.gameParallelism(7*gib,4*gib,3,true,false)==1,"Insufficient cores admitted");
        check(AnalysisResourcePolicy.gameParallelism(7*gib,4*gib,4,false,false)==1,"32-bit process admitted");
        check(AnalysisResourcePolicy.gameParallelism(7*gib,4*gib,4,true,true)==1,"Android low-memory state admitted");
        check(AnalysisResourcePolicy.gameParallelism(7*gib,8*gib,4,true,false)==1,"Inconsistent memory snapshot admitted");
        check(AnalysisResourcePolicy.gameParallelism(-1,-1,4,true,false)==1,"Unavailable memory snapshot admitted");
        JSONObject first=AnalysisJobStore.prepare(files,projectId,"2.2.5");String firstId=first.getString("id");
        String audioIdentity=first.getString("analysisAudioIdentity");
        check(audioIdentity.equals(AnalysisJobStore.request(files,firstId).getString("analysisAudioIdentity"))&&"2.2.5".equals(first.getString("analysisAppVersion")),"GAME guard lost its frozen source/version binding");
        JSONObject small=AnalysisJobStore.gameParallelism(files,firstId,7*gib,4*gib-1,4,true,false);
        check(small.getInt("parallelism")==1&&!AnalysisJobStore.status(files).getBoolean("gameParallelActive"),"Ineligible device acquired parallel lease");
        check(small.getLong("totalBytes")==7*gib&&small.getLong("availableBytes")==4*gib-1&&small.getInt("cores")==4&&small.getBoolean("process64Bit")&&!small.getBoolean("lowMemory"),"Resource decision hid its measured facts");
        AnalysisJobStore.progress(files,firstId,.1,"Serial GAME",new JSONObject().put("workerFallback",true));
        check(!AnalysisJobStore.status(files).getBoolean("gameParallelDisabled"),"Unleased progress disabled parallelism");
        check(eligibleGame(files,firstId).getInt("parallelism")==2&&AnalysisJobStore.status(files).getBoolean("gameParallelActive"),"Fresh memory recheck did not commit lease before admission");
        AnalysisJobStore.progress(files,firstId,.2,"Parallel GAME",new JSONObject().put("workerFallback","true"));
        check(!AnalysisJobStore.status(files).getBoolean("gameParallelDisabled"),"Non-boolean fallback metadata disabled parallelism");
        File status=new File(AnalysisJobStore.directory(files),"job.json");String activeHash=AnalysisJobStore.hash(status);
        reject(()->eligibleGame(files,firstId));reject(()->AnalysisJobStore.gameParallelRelease(files,"wrong-owner"));
        check(activeHash.equals(AnalysisJobStore.hash(status)),"Duplicate or stale owner changed active lease");
        AnalysisJobStore.recover(files);
        check("interrupted".equals(AnalysisJobStore.status(files).getString("state")),"Process death was not recovered before guard reuse");
        JSONObject failed=AnalysisJobStore.prepare(files,projectId,"2.2.5");String failedId=failed.getString("id"),beforeRhythm=failed.getString("analysisIdentity");
        check(failed.getBoolean("gameParallelDisabled")&&!failed.getBoolean("gameParallelActive")&&eligibleGame(files,failedId).getInt("parallelism")==1,"Interrupted lease did not disable parallel retry");
        AnalysisJobStore.finish(files,failedId,"cancelled","Edit rhythm after failed parallelism");
        JSONObject project=read(saved),settings=project.optJSONObject("settings");if(settings==null)settings=new JSONObject();
        settings.put("sensitivity",.53).put("bpmOverride",123);ProjectStore.save(new File(files,"projects"),projectId,project.put("settings",settings));
        JSONObject rhythm=AnalysisJobStore.prepare(files,projectId,"2.2.5");String rhythmId=rhythm.getString("id");
        check(!beforeRhythm.equals(rhythm.getString("analysisIdentity"))&&audioIdentity.equals(rhythm.getString("analysisAudioIdentity"))&&rhythm.getBoolean("gameParallelDisabled"),"Rhythm edit reset crash guard or reused stale rhythm identity");
        check(eligibleGame(files,rhythmId).getInt("parallelism")==1,"Rhythm edit retried failed parallelism");
        AnalysisJobStore.finish(files,rhythmId,"cancelled","Upgrade fixture");
        JSONObject upgrade=AnalysisJobStore.prepare(files,projectId,"2.2.6");String upgradeId=upgrade.getString("id");
        check(!upgrade.getBoolean("gameParallelDisabled")&&eligibleGame(files,upgradeId).getInt("parallelism")==2,"App version did not reset parallel guard");
        activeHash=AnalysisJobStore.hash(status);
        reject(()->AnalysisJobStore.gameParallelRelease(files,firstId));reject(()->eligibleGame(files,firstId));
        check(activeHash.equals(AnalysisJobStore.hash(status)),"Old job affected the replacement job's lease");
        AnalysisJobStore.gameParallelRelease(files,upgradeId);
        check(!AnalysisJobStore.status(files).getBoolean("gameParallelActive"),"Successful GAME completion retained its lease");
        AnalysisJobStore.finish(files,upgradeId,"failed","An unrelated later stage failed");
        JSONObject clean=AnalysisJobStore.prepare(files,projectId,"2.2.6");String cleanId=clean.getString("id");
        check(!clean.getBoolean("gameParallelDisabled")&&eligibleGame(files,cleanId).getInt("parallelism")==2,"Released successful work was treated as a parallel crash");
        AnalysisJobStore.finish(files,cleanId,"cancelling","User cancelled");
        check(!AnalysisJobStore.status(files).getBoolean("gameParallelActive"),"Cancellation did not durably disarm crash lease");
        reject(()->AnalysisJobStore.gameParallelRelease(files,cleanId));
        AnalysisJobStore.recover(files);
        JSONObject cancelled=AnalysisJobStore.prepare(files,projectId,"2.2.6");String cancelledId=cancelled.getString("id");
        check(!cancelled.getBoolean("gameParallelDisabled")&&eligibleGame(files,cancelledId).getInt("parallelism")==2,"User cancellation disabled parallelism");
        AnalysisJobStore.finish(files,cancelledId,"cancelling","Cancel before shutdown error");
        AnalysisJobStore.finish(files,cancelledId,"failed","A cleanup error followed cancellation");
        JSONObject cancelError=AnalysisJobStore.prepare(files,projectId,"2.2.6");String cancelErrorId=cancelError.getString("id");
        check(!cancelError.getBoolean("gameParallelDisabled")&&eligibleGame(files,cancelErrorId).getInt("parallelism")==2,"Cancellation cleanup error was misclassified as a parallel crash");
        AnalysisJobStore.finish(files,cancelErrorId,"failed","Actual active parallel failure");
        JSONObject disabled=AnalysisJobStore.prepare(files,projectId,"2.2.6");String disabledId=disabled.getString("id");
        check(disabled.getBoolean("gameParallelDisabled")&&eligibleGame(files,disabledId).getInt("parallelism")==1,"Failed active parallel work was not guarded");
        AnalysisJobStore.finish(files,disabledId,"cancelled","Replace analysis waveform");
        changeSample(new File(AnalysisJobStore.project(files,projectId),"analysis.wav"));
        JSONObject changed=AnalysisJobStore.prepare(files,projectId,"2.2.6");String changedId=changed.getString("id");
        check(!audioIdentity.equals(changed.getString("analysisAudioIdentity"))&&!changed.getBoolean("gameParallelDisabled")&&eligibleGame(files,changedId).getInt("parallelism")==2,"Changed analysis PCM did not reset byte-bound guard");
        AnalysisJobStore.finish(files,changedId,"cancelled","Direct cancellation after changed audio");
        JSONObject directCancel=AnalysisJobStore.prepare(files,projectId,"2.2.6");
        check(!directCancel.getBoolean("gameParallelDisabled"),"Direct cancellation disabled parallelism");
        String fallbackId=directCancel.getString("id");
        check(eligibleGame(files,fallbackId).getInt("parallelism")==2,"Healthy parallel work was not admitted for fallback test");
        AnalysisJobStore.progress(files,fallbackId,.5,"GAME continued serially",new JSONObject().put("stage","voice").put("workerFallback",true).put("parallelism",1));
        JSONObject fallback=AnalysisJobStore.status(files);
        check(fallback.getBoolean("gameParallelDisabled")&&fallback.getBoolean("gameParallelActive"),"Caught worker fallback did not durably disable future pooling while retaining the active lease");
        AnalysisJobStore.gameParallelRelease(files,fallbackId);
        check(AnalysisJobStore.status(files).getBoolean("gameParallelDisabled")&&!AnalysisJobStore.status(files).getBoolean("gameParallelActive"),"Successful release erased caught worker failure");
        JSONObject completed=read(saved).put("projectId",projectId).put("music",music).put("needAnalysis",false).put("compiled",new JSONObject().put("sha256","host-game-fallback-fixture"));
        AnalysisJobStore.complete(files,fallbackId,completed.toString());
        JSONObject afterFallback=AnalysisJobStore.prepare(files,projectId,"2.2.6");String afterFallbackId=afterFallback.getString("id");
        check(afterFallback.getBoolean("gameParallelDisabled")&&eligibleGame(files,afterFallbackId).getInt("parallelism")==1,"Completed exact serial fallback re-enabled failed parallel work");
        AnalysisJobStore.finish(files,afterFallbackId,"cancelled","Finished GAME resource tests");
    }
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
        reject(()->AnalysisJobStore.prepare(files,"../escape","2.2.1"));
        JSONObject first=AnalysisJobStore.prepare(files,projectId,"2.2.1");String id=first.getString("id");
        reject(()->AnalysisJobStore.prepare(files,projectId,"2.2.1"));
        AnalysisJobStore.progress(files,id,.6,"Separating");AnalysisJobStore.progress(files,id,.2,"Late progress");
        check(AnalysisJobStore.status(files).getDouble("progress")==.6,"Progress went backwards");
        reject(()->AnalysisJobStore.progress(files,id,Double.NaN,"Invalid"));
        JSONObject music=new JSONObject().put("duration",2).put("analysisVersion",6).put("bpm",120)
            .put("beats",new JSONArray("[0,0.5,1,1.5]")).put("downbeats",new JSONArray("[0]"))
            .put("waveform",new JSONArray("[0.2,0.3]")).put("energy",new JSONArray("[0.2,0.3]"))
            .put("sections",new JSONArray().put(new JSONObject().put("start",0).put("end",2).put("energy",.3)))
            .put("onsets",new JSONArray()).put("bassNotes",new JSONArray()).put("warnings",new JSONArray())
            .put("vocals",new JSONObject().put("phrases",new JSONArray()).put("accents",new JSONArray()).put("notes",new JSONArray()).put("envelope",new JSONArray("[0,0]"))
                .put("transcription",new JSONObject().put("model","fixture-game").put("notes",new JSONArray())))
            .put("bassAnalysis",new JSONObject().put("phrases",new JSONArray()).put("envelope",new JSONArray("[0,0]")))
            .put("engine",new JSONObject().put("name","Complete fixture analysis").put("neural",true)
                .put("separationModel",new JSONObject().put("modelId","fixture-separator").put("sourceSeparated",true)))
            .put("roleAnalysis",new JSONObject().put("sourceSeparated",true));
        reject(()->AnalysisJobStore.checkpoint(files,id,new JSONObject().put("duration",2).put("analysisVersion",6).toString()));
        reject(()->AnalysisJobStore.checkpoint(files,id,new JSONObject(music.toString()).put("duration",2.001).toString()));
        reject(()->AnalysisJobStore.checkpoint(files,id,new JSONObject(music.toString()).put("analysisVersion",7).toString()));
        reject(()->AnalysisJobStore.checkpoint(files,id,new JSONObject(music.toString()).put("beats",new JSONObject()).toString()));
        reject(()->AnalysisJobStore.checkpoint(files,id,new JSONObject(music.toString()).put("engine",new JSONObject()).toString()));
        reject(()->AnalysisJobStore.checkpoint(files,id,new JSONObject(music.toString()).put("energy",new JSONArray("[null]")).toString()));
        JSONObject legacy=new JSONObject(music.toString()).put("analysisVersion",5);legacy.remove("roleAnalysis");legacy.getJSONObject("vocals").remove("transcription");legacy.getJSONObject("engine").remove("separationModel");
        AnalysisJobStore.validateCheckpoint(legacy,2);
        for(String file:new String[]{"actual-music-nightowl-mix-analysis.json","actual-music-falcon-mix-analysis.json","actual-music-user-glass-prefix64-analysis.json"}){
            JSONObject historical=read(new File("qa/release-1.6.0",file));AnalysisJobStore.validateCheckpoint(historical,historical.getDouble("duration"));
        }
        reject(()->AnalysisJobStore.checkpoint(files,id,new JSONObject().put("analysisVersion",6).toString()));
        AnalysisJobStore.progress(files,id,.61,"Passage 2 of 12",new JSONObject().put("stage","separation").put("passageIndex",2).put("passageCount",12).put("passagesCompleted",1).put("checkpointSaved",true).put("state","completed"));
        JSONObject display=AnalysisJobStore.status(files);
        check("running".equals(display.getString("state")),"Display metadata changed job ownership");
        check(display.getInt("passageIndex")==2&&display.getBoolean("resumeAvailable"),"Passage recovery progress missing");
        reject(()->AnalysisJobStore.progress(files,id,.7,"Bad count",new JSONObject().put("passageIndex",-1)));
        check(AnalysisJobStore.status(files).getDouble("progress")==.61,"Invalid progress partially persisted");
        AnalysisJobStore.progress(files,id,.62,"Reading voice",new JSONObject().put("stage","voice"));
        check(!AnalysisJobStore.status(files).has("passageCount"),"Old passage counts leaked into another stage");
        AnalysisJobStore.checkpoint(files,id,music.toString());
        AnalysisJobStore.recover(files);
        check("interrupted".equals(AnalysisJobStore.status(files).getString("state")),"Dead process left running status");
        JSONObject retry=AnalysisJobStore.prepare(files,projectId,"2.2.1");String retryId=retry.getString("id");
        check(retry.getBoolean("hasCheckpoint"),"Matching checkpoint was lost");
        check(AnalysisJobStore.request(files,retryId).getJSONObject("music").getInt("analysisVersion")==6,"Checkpoint not reused");
        reject(()->AnalysisJobStore.progress(files,id,.9,"Stale owner"));
        AnalysisJobStore.finish(files,retryId,"cancelling","Cancelling");
        JSONObject result=read(saved).put("projectId",projectId).put("music",music).put("needAnalysis",false).put("compiled",new JSONObject().put("sha256","host-transaction-fixture"));
        reject(()->AnalysisJobStore.complete(files,retryId,result.toString()));
        check(original.equals(AnalysisJobStore.hash(saved)),"Cancelled work overwrote the saved show");
        AnalysisJobStore.finish(files,retryId,"cancelled","Cancelled");
        JSONObject conflict=AnalysisJobStore.prepare(files,projectId,"2.2.1");String conflictId=conflict.getString("id");
        ProjectStore.save(projects,projectId,read(saved).put("name","Newer edit"));String newer=AnalysisJobStore.hash(saved);
        reject(()->AnalysisJobStore.complete(files,conflictId,result.toString()));
        check(newer.equals(AnalysisJobStore.hash(saved)),"Newer edit was overwritten");
        AnalysisJobStore.finish(files,conflictId,"failed","Conflict");
        JSONObject finalJob=AnalysisJobStore.prepare(files,projectId,"2.2.1");String finalId=finalJob.getString("id");
        check(finalJob.getBoolean("hasCheckpoint"),"Renaming invalidated completed analysis");
        reject(()->AnalysisJobStore.complete(files,finalId,new JSONObject(result.toString()).put("projectId","other").toString()));
        result.put("name","Newer edit");AnalysisJobStore.complete(files,finalId,result.toString());
        check(finalId.equals(read(saved).getString("backgroundJobId")),"Completion not durable");
        check("completed".equals(AnalysisJobStore.status(files).getString("state")),"Completion not terminal");
        reject(()->AnalysisJobStore.complete(files,finalId,result.toString()));
        // Reproduce process death after project commit but before the job terminal write.
        JSONObject pending=AnalysisJobStore.status(files).put("state","running");AnalysisJobStore.persist(files,pending);
        check("completed".equals(AnalysisJobStore.recover(files).getString("state")),"Committed result misclassified after crash");
        check(!new File(AnalysisJobStore.directory(files),"checkpoint.json").exists(),"Completed checkpoint leaked");
        // Version, analysis settings and actual audio invalidate completed checkpoints;
        // cosmetic/choreography-only saves preserve them.
        JSONObject retryBase=read(saved).put("needAnalysis",true);
        ProjectStore.save(projects,projectId,retryBase);
        JSONObject identityJob=AnalysisJobStore.prepare(files,projectId,"2.2.1");String identity=identityJob.getString("analysisIdentity");
        String audioIdentity=AnalysisJobStore.request(files,identityJob.getString("id")).getString("analysisAudioIdentity");
        AnalysisJobStore.checkpoint(files,identityJob.getString("id"),music.toString());AnalysisJobStore.finish(files,identityJob.getString("id"),"failed","Interrupted");
        JSONObject settings=read(saved).optJSONObject("settings");if(settings==null)settings=new JSONObject();
        settings.put("style","cinematic").put("vocalFocus",.99);
        ProjectStore.save(projects,projectId,read(saved).put("settings",settings).put("updatedAt",1));
        JSONObject cosmetic=AnalysisJobStore.prepare(files,projectId,"2.2.1");
        check(cosmetic.getBoolean("hasCheckpoint")&&identity.equals(cosmetic.getString("analysisIdentity")),"Choreography edits discarded valid analysis");
        AnalysisJobStore.finish(files,cosmetic.getString("id"),"cancelled","Cancelled");
        settings.put("sensitivity",.61);ProjectStore.save(projects,projectId,read(saved).put("settings",settings));
        JSONObject changed=AnalysisJobStore.prepare(files,projectId,"2.2.1");
        check(!changed.getBoolean("hasCheckpoint")&&!identity.equals(changed.getString("analysisIdentity")),"Analysis setting change reused stale work");
        check(audioIdentity.equals(AnalysisJobStore.request(files,changed.getString("id")).getString("analysisAudioIdentity")),"Rhythm sensitivity discarded unchanged audio model identity");
        AnalysisJobStore.checkpoint(files,changed.getString("id"),music.toString());AnalysisJobStore.finish(files,changed.getString("id"),"failed","Interrupted");
        JSONObject upgraded=AnalysisJobStore.prepare(files,projectId,"2.2.2");
        check(!upgraded.getBoolean("hasCheckpoint"),"App upgrade reused old completed analysis");
        AnalysisJobStore.checkpoint(files,upgraded.getString("id"),music.toString());AnalysisJobStore.finish(files,upgraded.getString("id"),"failed","Interrupted");
        File checkpoint=new File(AnalysisJobStore.directory(files),"checkpoint.json");Files.write(checkpoint.toPath(),"{broken".getBytes("UTF-8"));
        JSONObject repaired=AnalysisJobStore.prepare(files,projectId,"2.2.2");
        check(!repaired.getBoolean("hasCheckpoint")&&!checkpoint.exists(),"Damaged checkpoint caused a retry loop");
        AnalysisJobStore.finish(files,repaired.getString("id"),"failed","Repeat recovery fixture");
        // Reproduce old, syntactically valid but incomplete checkpoints on repeated retries.
        for(String bad:new String[]{"{\"analysisVersion\":6,\"duration\":2}",new JSONObject(music.toString()).put("duration",1).toString()}){
            Files.write(checkpoint.toPath(),bad.getBytes("UTF-8"));
            JSONObject record=AnalysisJobStore.status(files).put("checkpointSHA256",AnalysisJobStore.hash(checkpoint));AnalysisJobStore.persist(files,record);
            JSONObject recovered=AnalysisJobStore.prepare(files,projectId,"2.2.2");
            check(!recovered.getBoolean("hasCheckpoint")&&AnalysisJobStore.request(files,recovered.getString("id")).getBoolean("needAnalysis"),"Incomplete checkpoint caused a repeated retry loop");
            check(!checkpoint.exists(),"Invalid completed checkpoint was not removed");
            AnalysisJobStore.finish(files,recovered.getString("id"),"failed","Repeat recovery fixture");
        }
        ProjectStore.save(projects,projectId,read(saved).put("needAnalysis",false).put("music",new JSONObject().put("analysisVersion",6).put("duration",2)));
        JSONObject incompleteSaved=AnalysisJobStore.prepare(files,projectId,"2.2.2");
        check(AnalysisJobStore.request(files,incompleteSaved.getString("id")).getBoolean("needAnalysis"),"Incomplete saved music was sent straight to choreography");
        AnalysisJobStore.finish(files,incompleteSaved.getString("id"),"cancelled","Recovered incomplete music");
        repaired=AnalysisJobStore.prepare(files,projectId,"2.2.2");
        String beforeAudio=repaired.getString("analysisIdentity");AnalysisJobStore.finish(files,repaired.getString("id"),"cancelling","Cancelling");
        check("cancelled".equals(AnalysisJobStore.recover(files).getString("state")),"Process death reversed a requested cancellation");
        File originalAudio=new File(AnalysisJobStore.project(files,projectId),"audio.wav");
        try(RandomAccessFile edit=new RandomAccessFile(originalAudio,"rw")){edit.seek(edit.length()-1);int sample=edit.read();edit.seek(edit.length()-1);edit.write(sample^1);}
        JSONObject audioChanged=AnalysisJobStore.prepare(files,projectId,"2.2.2");
        check(!beforeAudio.equals(audioChanged.getString("analysisIdentity")),"Changed audio reused prior passage identity");
        check(!audioIdentity.equals(AnalysisJobStore.request(files,audioChanged.getString("id")).getString("analysisAudioIdentity")),"Changed audio reused role-model identity");
        AnalysisJobStore.finish(files,audioChanged.getString("id"),"cancelled","Finished tests");
        gameParallelTests(files,projectId,saved,music);
        System.out.println("PASS: job ownership, monotonic progress, checkpoint reuse, cancellation, conflict preservation, durable completion, damaged checkpoint recovery, version/audio/settings identity, structured progress, crash recovery, GAME memory/core/64-bit admission and durable parallel ownership/crash/cancellation guard");
    }
}
