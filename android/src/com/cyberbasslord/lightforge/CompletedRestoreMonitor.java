package com.cyberbasslord.lightforge;

/**
 * Native liveness supervision for the very narrow window in which a completed
 * background analysis is being restored into a newly-opened Studio.  This is
 * deliberately not a general JavaScript timeout: ordinary foreground work
 * never opens a lease, and a lease makes progress only through request-scoped,
 * monotonically ordered restore events.
 */
final class CompletedRestoreMonitor {
    static final long PROBE_INTERVAL_MS=1500L;
    static final long CALLBACK_BUDGET_MS=6500L;
    static final long MIN_PHASE_BUDGET_MS=15000L;
    static final long MAX_PHASE_BUDGET_MS=120000L;
    static final long BOOTSTRAP_PHASE_BUDGET_MS=45000L;
    private static final long BYTES_PER_BUDGET_STEP=512L*1024L;
    private static final long BUDGET_STEP_MS=1000L;

    interface Clock {long now();}
    interface Scheduler {
        void postDelayed(Runnable task,long delayMs);
        void removeCallbacks(Runnable task);
    }
    interface ProbeCallback {void receive(Probe probe);}
    interface Host {
        void requestProbe(String jobId,String nonce,ProbeCallback callback);
        boolean recoveryAlreadyUsed(String jobId);
        void recover(String jobId,String nonce,String reason);
        void diagnostic(String message);
    }
    static final class Probe {
        final boolean booted,backgroundApplying,backgroundPending,failed;
        final String jobId,nonce,phase;
        final long sequence,bytes,previewFrames;
        final boolean previewLoaded;
        Probe(boolean booted,boolean backgroundApplying,boolean backgroundPending,boolean failed,
              String jobId,String nonce,String phase,long sequence,long bytes,
              boolean previewLoaded,long previewFrames){
            this.booted=booted;this.backgroundApplying=backgroundApplying;this.backgroundPending=backgroundPending;
            this.failed=failed;this.jobId=jobId==null?"":jobId;this.nonce=nonce==null?"":nonce;this.phase=phase==null?"":phase;
            this.sequence=Math.max(0,sequence);this.bytes=Math.max(0,bytes);
            this.previewLoaded=previewLoaded;this.previewFrames=Math.max(0,previewFrames);
        }
    }

    private final Clock clock;
    private final Scheduler scheduler;
    private final Host host;
    private final Runnable tickTask=this::tick;
    private String jobId,nonce,phase,terminalJobId,terminalNonce;
    private long sequence,bytes,lastAdvanceAt,nextProbeAt,callbackStartedAt;
    // Probe tickets prevent a late callback from an earlier same-lease probe
    // from satisfying a newer probe after a direct bridge pulse supersedes it.
    private long probeTicket,awaitingProbeTicket;
    private boolean awaitingCallback,recoveryRequested,disposed,workerStarted,workerVerified,showAdopted,previewFirstRender,visualCommitted;

    CompletedRestoreMonitor(Clock clock,Scheduler scheduler,Host host){
        this.clock=clock;this.scheduler=scheduler;this.host=host;
    }

    synchronized boolean begin(String nextJobId,String nextNonce,long initialBytes){
        if(disposed||!valid(nextJobId)||!valid(nextNonce))return false;
        // Only an explicitly current WebView may open a lease (enforced by
        // MainActivity's bridge generation). Never replace an active lease.
        // A token for the same durable job remains exclusive until its browser
        // ACK is confirmed. A *different* completed job may retire an old,
        // unconfirmed token: its persisted recovery cap deliberately remains
        // armed, and a late old ACK can no longer match this monitor. Without
        // this narrow handoff, a transient post-ACK bridge failure for job A
        // would wedge a later completed job B in the same Activity.
        if(jobId!=null)return false;
        if(terminalJobId!=null){
            if(terminalJobId.equals(nextJobId))return false;
            host.diagnostic("completed-restore retired unconfirmed terminal token job="+terminalJobId+" for later completed job="+nextJobId);
            clearTerminalProof();
        }
        long now=clock.now();
        jobId=nextJobId;nonce=nextNonce;phase="bootstrap";sequence=0;bytes=Math.max(0,initialBytes);
        lastAdvanceAt=now;nextProbeAt=now;callbackStartedAt=0;awaitingCallback=false;awaitingProbeTicket=0;
        workerStarted=false;workerVerified=false;showAdopted=false;previewFirstRender=false;visualCommitted=false;
        // A completed job is allowed one native replacement across every
        // WebView instance in this Activity/process.  A replacement creates a
        // fresh nonce, so consult the durable cap for each begin.
        recoveryRequested=host.recoveryAlreadyUsed(nextJobId);
        arm(0);
        host.diagnostic("completed-restore lease begin job="+nextJobId+" nonce="+shortNonce(nextNonce));
        return true;
    }

    synchronized boolean pulse(String pulseJobId,String pulseNonce,String nextPhase,long nextSequence,long nextBytes){
        if(!matches(pulseJobId,pulseNonce)||nextSequence<=sequence)return false;
        if("worker-started".equals(nextPhase)&&workerStarted)return false;
        if(nextPhase!=null&&nextPhase.startsWith("worker-")&&!"worker-started".equals(nextPhase)&&!workerStarted)return false;
        if("worker-verified".equals(nextPhase)&&(!workerStarted||workerVerified))return false;
        if("show-adopted".equals(nextPhase)&&(!workerStarted||!workerVerified||showAdopted))return false;
        if("preview-first-render".equals(nextPhase)&&(!workerVerified||!showAdopted))return false;
        if("preview-visual-commit".equals(nextPhase)&&(!workerVerified||!showAdopted||!previewFirstRender||visualCommitted))return false;
        long now=clock.now();
        sequence=nextSequence;phase=valid(nextPhase)?nextPhase:"pulse";bytes=Math.max(bytes,Math.max(0,nextBytes));
        if("worker-started".equals(phase))workerStarted=true;
        if("worker-verified".equals(phase))workerVerified=true;
        if("show-adopted".equals(phase))showAdopted=true;
        if("preview-first-render".equals(phase))previewFirstRender=true;
        if("preview-visual-commit".equals(phase))visualCommitted=true;
        lastAdvanceAt=now;
        // An ordered, current bridge pulse is stronger liveness evidence than
        // an older evaluateJavascript probe. Retire only that probe: a fresh
        // ticketed probe still bounds a renderer that dies after this pulse.
        if(awaitingCallback){
            awaitingCallback=false;callbackStartedAt=0;awaitingProbeTicket=0;
            nextProbeAt=now+PROBE_INTERVAL_MS;
            arm(nextDelay(now));
        }
        return true;
    }

    synchronized boolean terminal(String terminalJobId,String terminalNonce,long terminalSequence,long terminalBytes){
        // Browser ACK is permitted only after these direct, ordered bridge
        // proofs.  Eval state is intentionally insufficient for a terminal.
        if(!matches(terminalJobId,terminalNonce)||terminalSequence<=sequence||!workerStarted||!workerVerified||!showAdopted||!previewFirstRender||!visualCommitted)return false;
        bytes=Math.max(bytes,Math.max(0,terminalBytes));
        host.diagnostic("completed-restore terminal job="+jobId+" sequence="+terminalSequence+" phase="+phase);
        // Retain only an exact terminal token until JS has written its own
        // localStorage ACK and confirms that write.  Native never observes or
        // mutates the ACK value.
        this.terminalJobId=jobId;this.terminalNonce=nonce;
        clearLease();
        return true;
    }

    synchronized boolean ackCommitted(String acknowledgedJobId,String acknowledgedNonce){
        if(terminalJobId==null||!terminalJobId.equals(acknowledgedJobId)||terminalNonce==null||!terminalNonce.equals(acknowledgedNonce))return false;
        clearTerminalProof();return true;
    }

    synchronized boolean failed(String failedJobId,String failedNonce,String reason){
        if(!matches(failedJobId,failedNonce))return false;
        host.diagnostic("completed-restore failed job="+jobId+" phase="+phase+" reason="+safe(reason));
        clearLease();
        return true;
    }

    synchronized void close(){disposed=true;clearLease();clearTerminalProof();}

    synchronized boolean active(){return jobId!=null&&!disposed;}

    synchronized String activeJobId(){return jobId;}

    synchronized boolean owns(String candidateJobId,String candidateNonce){return matches(candidateJobId,candidateNonce)&&!disposed;}

    synchronized void rendererGone(){
        if(jobId!=null&&!disposed)requestRecovery("renderer-gone",clock.now());
    }

    synchronized void replacementStarted(){
        if(jobId==null||disposed)return;
        // Invalidate the retired nonce before the new WebView loads.  A late
        // callback or bridge call from the destroyed renderer must never be
        // able to terminally prove the replacement's work.  The persisted
        // per-job cap remains outside this monitor and the fresh WebView must
        // explicitly begin a new nonce before any more observation occurs.
        host.diagnostic("completed-restore retired lease invalidated for WebView replacement job="+jobId);
        clearLease();
    }

    private synchronized void tick(){
        if(disposed||jobId==null)return;
        long now=clock.now();
        if(awaitingCallback){
            if(now-callbackStartedAt>=CALLBACK_BUDGET_MS)requestRecovery("callback-stall",now);
            else arm(Math.max(1,CALLBACK_BUDGET_MS-(now-callbackStartedAt)));
            return;
        }
        long phaseAge=now-lastAdvanceAt;
        long phaseBudget=phaseBudget();
        if(phaseAge>=phaseBudget){requestRecovery("phase-stall:"+phase+":"+phaseAge+"ms",now);return;}
        if(now>=nextProbeAt){
            final long requestedProbeTicket=++probeTicket;
            awaitingCallback=true;awaitingProbeTicket=requestedProbeTicket;callbackStartedAt=now;nextProbeAt=now+PROBE_INTERVAL_MS;
            final String requestedJobId=jobId,requestedNonce=nonce;
            try{host.requestProbe(requestedJobId,requestedNonce,probe->receiveProbe(requestedJobId,requestedNonce,requestedProbeTicket,probe));}
            catch(Throwable failure){host.diagnostic("completed-restore probe dispatch failed: "+safe(failure.getMessage()));requestRecovery("probe-dispatch",now);return;}
        }
        arm(nextDelay(now));
    }

    private synchronized void receiveProbe(String requestedJobId,String requestedNonce,long requestedProbeTicket,Probe probe){
        // A callback from a retired WebView, or an older same-lease probe,
        // must not satisfy the current callback budget.
        if(disposed||jobId==null||!awaitingCallback||awaitingProbeTicket!=requestedProbeTicket||!matches(requestedJobId,requestedNonce))return;
        awaitingCallback=false;callbackStartedAt=0;awaitingProbeTicket=0;
        long now=clock.now();
        if(probe==null){host.diagnostic("completed-restore probe returned no state job="+jobId);arm(nextDelay(now));return;}
        // Treat page state as belonging to this request only after both lease
        // identifiers match.  In particular, a late old-page `failed` flag
        // must not clear a freshly begun replacement lease.
        if(!matches(probe.jobId,probe.nonce)){
            host.diagnostic("completed-restore probe ignored foreign lease job="+probe.jobId+" nonce="+shortNonce(probe.nonce));
            arm(nextDelay(now));return;
        }
        if(probe.failed){
            host.diagnostic("completed-restore probe observed application failure job="+jobId);
            clearLease();return;
        }
        // The bridge is the authoritative ordered path.  The callback is a
        // liveness observation and a bounded fallback if a renderer delivers
        // state after a bridge call was lost during teardown.
        if(probe.sequence>sequence){
            sequence=probe.sequence;phase=valid(probe.phase)?probe.phase:phase;
            bytes=Math.max(bytes,probe.bytes);lastAdvanceAt=now;
        }
        arm(nextDelay(now));
    }

    private void requestRecovery(String reason,long now){
        if(jobId==null||disposed)return;
        if(recoveryRequested||host.recoveryAlreadyUsed(jobId)){
            recoveryRequested=true;
            host.diagnostic("completed-restore recovery cap reached job="+jobId+" reason="+reason+" phase="+phase+" sequence="+sequence+" bytes="+bytes+"; leaving job pending");
            // Do not continue invoking a dead page.  The durable job and its
            // browser ACK remain untouched, so a later user reopen can retry.
            awaitingCallback=false;callbackStartedAt=0;awaitingProbeTicket=0;nextProbeAt=Long.MAX_VALUE;return;
        }
        recoveryRequested=true;
        awaitingCallback=false;callbackStartedAt=0;awaitingProbeTicket=0;
        host.diagnostic("completed-restore recovery requested job="+jobId+" nonce="+shortNonce(nonce)+" reason="+reason+" phase="+phase+" sequence="+sequence+" bytes="+bytes);
        host.recover(jobId,nonce,reason);
    }

    private long nextDelay(long now){
        long next=Math.min(nextProbeAt,lastAdvanceAt+phaseBudget());
        return Math.max(1,next-now);
    }
    private void arm(long delay){
        scheduler.removeCallbacks(tickTask);
        if(!disposed&&jobId!=null)scheduler.postDelayed(tickTask,Math.max(0,delay));
    }
    private void clearLease(){
        scheduler.removeCallbacks(tickTask);jobId=null;nonce=null;phase=null;sequence=bytes=0;workerStarted=false;workerVerified=false;showAdopted=false;previewFirstRender=false;visualCommitted=false;
        lastAdvanceAt=nextProbeAt=callbackStartedAt=0;awaitingProbeTicket=0;awaitingCallback=false;recoveryRequested=false;
    }
    private void clearTerminalProof(){terminalJobId=null;terminalNonce=null;}
    private boolean matches(String candidateJobId,String candidateNonce){return jobId!=null&&jobId.equals(candidateJobId)&&nonce!=null&&nonce.equals(candidateNonce);}
    private long phaseBudget(){
        if("bootstrap".equals(phase))return Math.max(BOOTSTRAP_PHASE_BUDGET_MS,phaseBudget(bytes));
        return phaseBudget(bytes);
    }
    private static long phaseBudget(long byteCount){
        long steps=(Math.max(0,byteCount)+BYTES_PER_BUDGET_STEP-1)/BYTES_PER_BUDGET_STEP;
        long extra=Math.min(MAX_PHASE_BUDGET_MS-MIN_PHASE_BUDGET_MS,steps*BUDGET_STEP_MS);
        return MIN_PHASE_BUDGET_MS+extra;
    }
    private static boolean valid(String value){return value!=null&&!value.trim().isEmpty()&&value.length()<=160;}
    private static String shortNonce(String value){return value==null?"":value.substring(0,Math.min(16,value.length()));}
    private static String safe(String value){return value==null?"":value.replace('\n',' ').replace('\r',' ').substring(0,Math.min(180,value.length()));}
}
