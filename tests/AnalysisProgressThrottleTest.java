package com.cyberbasslord.lightforge;

import org.json.JSONObject;

/** Runs the service's actual per-job admission state without constructing an Android Service. */
public final class AnalysisProgressThrottleTest {
    private static int checks;
    private static void check(boolean result,String message){if(!result)throw new AssertionError(message);checks++;}
    private static String phase(String label,String canonical)throws Exception{
        return AnalysisJobStore.analysisStage(new JSONObject().put("stage",label).put("analysisStage",canonical));
    }
    public static void main(String[] args)throws Exception{
        AnalysisService.ProgressThrottle throttle=new AnalysisService.ProgressThrottle();
        throttle.beginJob();
        check(throttle.admit(60000,.2,"separation",false),"First job progress missing");
        check(throttle.diagnostic(60000,false),"First job trace missing");
        check(!throttle.admit(60100,.3,"separation",false),"Repeated progress escaped the one-second throttle");
        check(!throttle.diagnostic(60100,false),"Repeated trace escaped the fifteen-second throttle");

        // Android can reuse one service instance for a new job immediately after stopSelf.
        throttle.beginJob();
        check(throttle.admit(60200,.1,"separation",false),"Previous job suppressed the next job's same-phase progress");
        check(throttle.diagnostic(60200,false),"Previous job suppressed the next job's first trace");
        check(!throttle.admit(60300,.2,phase("Running neural passage","separation"),false),"Human substage caused an extra durable write");
        check(!throttle.admit(60400,.3,phase("Reading separated instruments","separation"),false),"Human substage bypassed the canonical phase throttle");
        check(throttle.admit(60500,.4,phase("Following vocal expression","voice"),false),"Canonical phase boundary was lost");
        check(!throttle.diagnostic(60500,false),"Phase changes bypassed the trace throttle");
        check(!throttle.admit(60600,.5,"",false),"Missing phase metadata created a false phase boundary");
        check(throttle.admit(61500,.5,"voice",false),"One-second progress did not resume");
        check(throttle.admit(61501,.5,"voice",true),"Checkpoint persistence was throttled");
        check(throttle.diagnostic(61501,true),"Checkpoint trace was throttled");
        check(throttle.admit(61502,.96,"voice",false),"Final generation/save progress was throttled");

        throttle.resumeRenderer();
        check(throttle.admit(61503,.5,"voice",false),"Renderer replacement suppressed first resumed progress");
        check(!throttle.diagnostic(61503,false),"Same-job renderer recovery reset the trace interval");
        check(!throttle.admit(61504,.5,"",false),"Renderer recovery discarded the current canonical phase");
        check(throttle.admit(61505,.6,"bass",false),"Renderer recovery lost the next phase transition");
        check(throttle.diagnostic(76501,false),"Fifteen-second trace did not resume");

        throttle.beginJob();
        check(throttle.admit(0,0,"",false),"First progress depends on device uptime");
        check(throttle.diagnostic(0,false),"First trace depends on device uptime");
        check(!throttle.admit(1,0,"",false),"Empty metadata bypassed repeated progress throttle");
        System.out.println("PASS: "+checks+" actual service progress admission checks");
    }
}
