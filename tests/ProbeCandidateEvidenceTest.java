package com.cyberbasslord.lightforge;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import org.json.JSONArray;
import org.json.JSONObject;

/** Actual companion JSON transport with bounded synthetic clocks; no device or inference. */
public final class ProbeCandidateEvidenceTest {
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
    private static NativeInferenceProfile.Snapshot profile(boolean candidate,String outcome){
        NativeInferenceProfile profile=new NativeInferenceProfile();
        profile.noteSchedulerConfiguration("temporal",candidate?"cpu-i1-j1-d0-sequential-w4-b1":"cpu-i4-j1-d0-sequential");
        profile.noteSchedulerConfiguration("frequency",candidate?"cpu-i1-j1-d0-sequential-w4-b16":"cpu-i4-j1-d0-sequential");
        for(int i=0;i<27;i++){
            String graph=i==0?"front":i==25?"head-0":i==26?"head-1":String.format(java.util.Locale.ROOT,"block-%02d-%s",(i-1)/2,(i&1)==1?"time":"frequency");
            int count=i==0?1:i>=25?11:graph.endsWith("time")?(candidate?60:15):(candidate?82:11);
            profile.addModelPrepare(graph,1);profile.addSessionInit(graph,2);profile.addTensorBind(graph,3);
            for(int n=0;n<count;n++)profile.addRun(graph,4);
        }
        return profile.finish(outcome);
    }
    private static NativeInferenceProfile.CandidateEvidence evidence(int ordinal,boolean partial){
        NativeInferenceProfile.ModelSetup before=new NativeInferenceProfile.ModelSetup(27,27,1000000,5,5000);
        NativeInferenceProfile.ModelSetup after=new NativeInferenceProfile.ModelSetup(27,28,1000042,6,5017);
        NativeInferenceProfile.ArmEvidence baseline=partial?null:new NativeInferenceProfile.ArmEvidence("completed",123456789,before,before);
        NativeInferenceProfile.ArmEvidence candidate=new NativeInferenceProfile.ArmEvidence(partial?"cancelled":"completed",partial?-1:98765432,before,partial?after:before);
        return new NativeInferenceProfile.CandidateEvidence(ordinal,4,partial,27,baseline,candidate,profile(true,partial?"cancelled":"completed"));
    }
    private static void rejects(Checked check,String message)throws Exception {
        boolean rejected=false;try{check.run();}catch(IllegalArgumentException|java.io.IOException expected){rejected=true;}
        require(rejected,message);
    }
    private interface Checked {void run()throws Exception;}
    public static void main(String[] args)throws Exception {
        JSONObject complete=ProbeRunner.candidateEvidenceJson(evidence(0,false));
        require(complete.getString("profileWallScope").equals("collector-lifetime-not-arm-clock"),"Collector wall time lost its distinct scope");
        require(complete.getJSONObject("baseline").getLong("armWallNanos")==123456789&&
            complete.getJSONObject("candidate").getLong("armWallNanos")==98765432,"Actual arm clocks were replaced by profile wall time");
        JSONObject setup=complete.getJSONObject("candidate").getJSONObject("modelSetup");
        require(setup.getLong("extractionAttempts")==0&&setup.getLong("existingFileChecksumBytesRead")==0,
            "Prepared-arm deltas are direct zero observations");
        require(!setup.has("cacheModelHits")&&!setup.has("fair"),"Transport fabricated cache hits or cache equivalence");
        JSONObject partial=ProbeRunner.candidateEvidenceJson(evidence(1,true));
        require(partial.isNull("baseline")&&partial.getJSONObject("candidate").isNull("armWallNanos")&&
            partial.getJSONObject("candidate").getString("outcome").equals("cancelled"),"Unstarted baseline or incomplete candidate claimed completion");
        JSONObject delta=partial.getJSONObject("candidate").getJSONObject("modelSetup");
        require(delta.getLong("extractionAttempts")==1&&delta.getLong("extractionBytesRead")==42&&
            delta.getLong("existingFileChecksumAttempts")==1&&delta.getLong("existingFileChecksumBytesRead")==17,
            "Interrupted setup lost directly observed read/attempt deltas");
        JSONArray passages=new JSONArray();NativeInferenceProfile.Snapshot production=profile(false,"completed");
        for(int i=0;i<35;i++){
            JSONObject passage=new JSONObject().put("ordinal",i).put("profile",new JSONArray(Arrays.asList(production.records())));
            passages.put(passage);
            if(i<3)ProbeRunner.appendCandidateEvidence(passages,passage,evidence(i,i==2));
        }
        require(passages.getJSONObject(0).getJSONArray("profile").getString(0).contains("inferenceCount=335 "),
            "Candidate calls contaminated production totals");
        require(passages.getJSONObject(0).getJSONObject("candidateEvidence").getJSONArray("profile").getString(0).contains("inferenceCount=1727 "),
            "Full candidate geometry was omitted");
        rejects(()->ProbeRunner.appendCandidateEvidence(passages,passages.getJSONObject(3),evidence(3,false)),"A fourth candidate profile escaped the fresh-job bound");
        rejects(()->ProbeRunner.appendCandidateEvidence(new JSONArray().put(new JSONObject().put("ordinal",3)),new JSONObject().put("ordinal",2),evidence(3,false)),
            "Candidate evidence was attributed to another passage");
        byte[] serialized=new JSONObject().put("passages",passages).toString(2).getBytes(StandardCharsets.UTF_8);
        require(serialized.length<2*1024*1024,"35 production profiles plus three candidates exceeded the unchanged receipt limit");
        NativeInferenceProfile.CandidateEvidence good=evidence(0,false);
        String[] tooMany=new String[NativeInferenceProfile.MAX_RECORDS+1];Arrays.fill(tooMany,"schema=native-inference-graph-v2 graph=front");
        rejects(()->new NativeInferenceProfile.CandidateEvidence(0,4,false,27,good.baseline,good.candidate,new NativeInferenceProfile.Snapshot(tooMany)),
            "Candidate profile exceeded the existing record bound");
        String[] excessGraphs=new String[28];Arrays.fill(excessGraphs,"schema=native-inference-graph-v2 graph=front");
        rejects(()->ProbeRunner.candidateEvidenceJson(new NativeInferenceProfile.CandidateEvidence(0,4,false,27,good.baseline,good.candidate,new NativeInferenceProfile.Snapshot(excessGraphs))),
            "Candidate profile exceeded the existing graph bound");
        System.out.println("PASS: bounded candidate JSON, partial outcomes, setup deltas, scope and production isolation; bytes="+serialized.length);
    }
}
