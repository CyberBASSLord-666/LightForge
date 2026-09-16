package com.cyberbasslord.lightforge;

import java.io.*;
import java.nio.file.Files;
import org.json.*;

/** Real job/source/checkpoint transactions; no Android renderer or ML claim. */
public final class AnalysisRendererRecoveryTest {
    private static int checks;
    interface Operation{void run()throws Exception;}
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);checks++;}
    static void reject(Operation operation,String label)throws Exception{
        try{operation.run();}catch(Exception expected){checks++;return;}throw new AssertionError(label);
    }
    static final class Fixture {
        final File files,project;final String id;final JSONObject request;
        Fixture(File parent,String name,boolean fresh)throws Exception{
            files=new File(parent,name);files.mkdirs();File projects=new File(files,"projects");projects.mkdirs();
            File audio=new File(files,"input.wav"),mono=new File(files,"input-mono.wav");
            try(WavConverter writer=new WavConverter(audio,mono,44100)){writer.accept(new float[2*44100*2],2*44100);writer.finish();}
            JSONObject meta;
            try(InputStream in=new FileInputStream(audio)){meta=ProjectStore.importAudio(projects,in,"Recovery fixture",new AudioImporter.Progress(){public void update(double p,String s){}public void check(){}});}
            String projectId=meta.getString("id");project=AnalysisJobStore.project(files,projectId);
            JSONObject source=AnalysisJobStore.read(new File(project,"project.json"),ProjectStore.MAX_PROJECT_BYTES);
            source.put("settings",new JSONObject().put("analysisQuality","precision").put("sensitivity",.82));
            ProjectStore.save(projects,projectId,source);
            JSONObject job=AnalysisJobStore.prepare(files,projectId,"2.2.5",fresh);id=job.getString("id");
            AnalysisJobStore.progress(files,id,.8,"GAME",new JSONObject().put("checkpointSaved",true).put("stage","voice").put("passagesCompleted",2));
            request=AnalysisJobStore.request(files,id);
        }
        JSONObject status()throws Exception{return AnalysisJobStore.status(files);}
        File frozen(){return new File(AnalysisJobStore.directory(files),"request.json");}
    }
    static JSONObject music()throws Exception{
        return new JSONObject().put("duration",2).put("analysisVersion",6).put("bpm",120)
            .put("beats",new JSONArray("[0,0.5,1,1.5]")).put("downbeats",new JSONArray("[0]"))
            .put("waveform",new JSONArray("[0.2,0.3]")).put("energy",new JSONArray("[0.2,0.3]"))
            .put("sections",new JSONArray().put(new JSONObject().put("start",0).put("end",2).put("energy",.3)))
            .put("onsets",new JSONArray()).put("bassNotes",new JSONArray()).put("warnings",new JSONArray())
            .put("vocals",new JSONObject().put("phrases",new JSONArray()).put("accents",new JSONArray()).put("notes",new JSONArray()).put("envelope",new JSONArray("[0,0]"))
                .put("transcription",new JSONObject().put("model","fixture-game").put("notes",new JSONArray())))
            .put("bassAnalysis",new JSONObject().put("phrases",new JSONArray()).put("envelope",new JSONArray("[0,0]")))
            .put("engine",new JSONObject().put("name","Fixture analysis").put("neural",true)
                .put("separationModel",new JSONObject().put("modelId","fixture-separator").put("sourceSeparated",true)))
            .put("roleAnalysis",new JSONObject().put("sourceSeparated",true));
    }
    public static void main(String[] args)throws Exception{
        File root=new File(args[0]);root.mkdirs();Fixture first=new Fixture(root,"first",false);
        check(AnalysisRendererRecovery.eligible(first.status(),false),"Saved partial progress could not recover");
        check(!AnalysisRendererRecovery.eligible(first.status(),true),"Renderer crashes were automatically retried");
        for(String state:new String[]{"preparing","cancelling","cancelled","completed","failed","interrupted"})
            check(!AnalysisRendererRecovery.eligible(first.status().put("state",state),false),"Terminal/cancelling job could recover: "+state);
        check(!AnalysisRendererRecovery.eligible(first.status().put("resumeAvailable",false),false),"Missing resume marker accepted");
        check(!AnalysisRendererRecovery.eligible(first.status().put("checkpointAt",0),false),"No checkpoint progress accepted");
        for(double count:new double[]{-1,.5,2,3})check(!AnalysisRendererRecovery.eligible(first.status().put("rendererRecoveryAttempts",count),false),"Invalid/exhausted recovery budget accepted");
        String requestHash=AnalysisJobStore.hash(first.frozen());
        JSONObject reserved=AnalysisRendererRecovery.reserve(first.files,first.id,false);
        check(reserved.optInt("rendererRecoveryAttempts")==1,"First reservation did not persist its budget");
        check(!AnalysisRendererRecovery.eligible(first.status(),false),"Same checkpoint triggered another recovery");
        AnalysisJobStore.progress(first.files,first.id,.7,"Restored old passage",new JSONObject().put("checkpointSaved",true));
        check(!AnalysisRendererRecovery.eligible(first.status(),false),"A new checkpoint timestamp counted as forward progress");
        JSONObject resumed=AnalysisRendererRecovery.restoreRequest(first.files,first.id);
        check(resumed.getString("id").equals(first.id)&&requestHash.equals(AnalysisJobStore.hash(first.frozen())),"Partial recovery changed the frozen job/request");
        AnalysisJobStore.progress(first.files,first.id,.85,"New GAME passage",new JSONObject().put("checkpointSaved",true));
        check(AnalysisRendererRecovery.reserve(first.files,first.id,false).getInt("rendererRecoveryAttempts")==2,"Genuine progress did not permit final recovery");
        AnalysisJobStore.progress(first.files,first.id,.9,"Further progress",new JSONObject().put("checkpointSaved",true));
        check(AnalysisRendererRecovery.reserve(first.files,first.id,false)==null,"Third automatic attempt accepted");
        check(!AnalysisRendererRecovery.ready(9999,1,true,false)&&AnalysisRendererRecovery.ready(10000,1,true,false),"First backoff boundary changed");
        check(!AnalysisRendererRecovery.ready(29999,2,true,false)&&AnalysisRendererRecovery.ready(30000,2,true,false),"Second backoff boundary changed");
        check(!AnalysisRendererRecovery.ready(30000,1,false,false),"Native cleanup was allowed to overlap replacement");
        check(!AnalysisRendererRecovery.ready(30000,1,true,true),"Low-memory replacement was admitted");
        check(!AnalysisRendererRecovery.ready(120000,1,true,false),"Expired memory/retirement wait was extended");

        Fixture cancelled=new Fixture(root,"cancelled",false);
        AnalysisRendererRecovery.reserve(cancelled.files,cancelled.id,false);
        AnalysisJobStore.finish(cancelled.files,cancelled.id,"cancelling","Cancelled during backoff");
        reject(()->AnalysisRendererRecovery.restoreRequest(cancelled.files,cancelled.id),"Cancellation was lost during recovery");
        check("cancelling".equals(cancelled.status().getString("state")),"Recovery overwrote cancellation");

        Fixture fresh=new Fixture(root,"fresh",true);
        AnalysisJobStore.markAnalysisWasmFallback(fresh.files,fresh.id,"native-deux-fallback");
        JSONObject original=AnalysisJobStore.request(fresh.files,fresh.id);
        AnalysisRendererRecovery.reserve(fresh.files,fresh.id,false);
        AnalysisRendererRecovery.restoreRequest(fresh.files,fresh.id);
        JSONObject restored=AnalysisJobStore.request(fresh.files,fresh.id);
        for(String key:new String[]{"analysisJobId","analysisIdentity","analysisExecutionMode","analysisRefreshEpoch","analysisEffectiveExecution","analysisNativeFallbackReason","analysisAppVersion"})
            check(original.getString(key).equals(restored.getString(key)),"Recovery changed lineage: "+key);
        check(original.getJSONObject("settings").toString().equals(restored.getJSONObject("settings").toString()),"Recovery changed quality/settings");

        Fixture changed=new Fixture(root,"changed-project",false);
        JSONObject changedSource=AnalysisJobStore.read(new File(changed.project,"project.json"),ProjectStore.MAX_PROJECT_BYTES).put("name","New edit");
        AnalysisJobStore.write(new File(changed.project,"project.json"),changedSource,ProjectStore.MAX_PROJECT_BYTES);
        reject(()->AnalysisRendererRecovery.restoreRequest(changed.files,changed.id),"Changed project source was recovered");
        Fixture changedAudio=new Fixture(root,"changed-audio",false);
        try(RandomAccessFile audio=new RandomAccessFile(new File(changedAudio.project,"audio.wav"),"rw")){audio.seek(100);audio.write(1);}
        reject(()->AnalysisRendererRecovery.restoreRequest(changedAudio.files,changedAudio.id),"Changed audio identity was recovered");
        Fixture changedSettings=new Fixture(root,"changed-settings",false);
        changedSettings.request.getJSONObject("settings").put("analysisQuality","balanced");
        AnalysisJobStore.write(changedSettings.frozen(),changedSettings.request,ProjectStore.MAX_PROJECT_BYTES);
        reject(()->AnalysisRendererRecovery.restoreRequest(changedSettings.files,changedSettings.id),"Changed frozen analysis settings were recovered");
        Fixture wrongEpoch=new Fixture(root,"wrong-epoch",true);
        wrongEpoch.request.put("analysisRefreshEpoch",java.util.UUID.randomUUID().toString());
        AnalysisJobStore.write(wrongEpoch.frozen(),wrongEpoch.request,ProjectStore.MAX_PROJECT_BYTES);
        reject(()->AnalysisRendererRecovery.restoreRequest(wrongEpoch.files,wrongEpoch.id),"Mismatched fresh namespace was recovered");

        Fixture checkpoint=new Fixture(root,"checkpoint",true);JSONObject music=music();
        AnalysisJobStore.checkpoint(checkpoint.files,checkpoint.id,music.toString());
        AnalysisRendererRecovery.restoreRequest(checkpoint.files,checkpoint.id);
        JSONObject loaded=AnalysisJobStore.request(checkpoint.files,checkpoint.id);
        check(Boolean.FALSE.equals(loaded.opt("needAnalysis"))&&music.toString().equals(loaded.getJSONObject("music").toString()),"Valid full analysis checkpoint was recomputed or changed");
        check(checkpoint.request.getString("analysisRefreshEpoch").equals(loaded.getString("analysisRefreshEpoch")),"Full checkpoint changed fresh epoch");
        File savedCheckpoint=new File(AnalysisJobStore.directory(checkpoint.files),"checkpoint.json");
        Files.write(savedCheckpoint.toPath(),"{}".getBytes("UTF-8"));
        reject(()->AnalysisRendererRecovery.restoreRequest(checkpoint.files,checkpoint.id),"Damaged checkpoint was accepted");
        System.out.println("PASS: "+checks+" renderer recovery policy and durable source/lineage checks");
    }
}
