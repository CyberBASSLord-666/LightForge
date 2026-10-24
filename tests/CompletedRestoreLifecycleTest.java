package com.cyberbasslord.lightforge;

import java.util.ArrayList;
import java.util.List;

/** Production monitor with a deterministic clock; not Android/device evidence. */
public final class CompletedRestoreLifecycleTest {
    private static int checks;
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);checks++;}
    private static final class Fixture implements CompletedRestoreMonitor.Clock,CompletedRestoreMonitor.Scheduler,CompletedRestoreMonitor.Host {
        long now,due;Runnable task;int probes,recoveries;boolean responsive,recoveryUsed;
        final List<CompletedRestoreMonitor.ProbeCallback> callbacks=new ArrayList<>();
        final CompletedRestoreMonitor monitor=new CompletedRestoreMonitor(this,this,this);
        public long now(){return now;}
        public void postDelayed(Runnable next,long delay){task=next;due=now+delay;}
        public void removeCallbacks(Runnable next){if(task==next)task=null;}
        public void requestProbe(String job,String nonce,CompletedRestoreMonitor.ProbeCallback callback){
            probes++;callbacks.add(callback);
            if(responsive)callback.receive(new CompletedRestoreMonitor.Probe(true,true,true,false,job,nonce,"worker-started",0,0,false,0));
        }
        public boolean recoveryAlreadyUsed(String job){return recoveryUsed;}
        public void recover(String job,String nonce,String reason){recoveries++;recoveryUsed=true;}
        public void diagnostic(String message){}
        void advance(long elapsed){
            long target=now+elapsed;int guard=0;
            while(task!=null&&due<=target){
                if(++guard>1000)throw new AssertionError("Monitor failed to yield");
                now=due;Runnable ready=task;task=null;ready.run();
            }
            now=target;
        }
        void begin(){check(monitor.begin("job","nonce",0),"Lease rejected");advance(0);}
        void startup(){
            check(monitor.pulse("job","nonce","worker-started",1,0),"Start rejected");
            check(monitor.pulse("job","nonce","worker-verified",2,0),"Verification rejected");
            check(monitor.pulse("job","nonce","show-adopted",3,0),"Adoption rejected");
            check(monitor.pulse("job","nonce","preview-starting",4,0),"Preview start rejected");
        }
    }
    private static void callbackDoesNotExpireWhileHidden(){
        Fixture f=new Fixture();f.begin();f.advance(1000);
        CompletedRestoreMonitor.ProbeCallback stale=f.callbacks.get(0);
        f.monitor.setForeground(false);check(f.task==null,"Hidden monitor retained a timer");
        f.advance(600_000);check(f.probes==1&&f.recoveries==0,"Background time consumed recovery");
        stale.receive(new CompletedRestoreMonitor.Probe(true,true,true,true,"job","nonce","failed",1,0,false,0));
        check(f.monitor.active(),"Suspended callback cleared the active lease");
        f.monitor.setForeground(true);f.advance(500);
        check(f.probes==2,"Resume did not issue a fresh probe");
        stale.receive(new CompletedRestoreMonitor.Probe(true,true,true,false,"job","nonce","worker-verified",2,0,false,0));
        f.advance(CompletedRestoreMonitor.CALLBACK_BUDGET_MS-1);
        check(f.recoveries==0,"Old callback budget leaked across resume");
        f.advance(1);check(f.recoveries==1,"Resumed unresponsive renderer escaped callback budget");
    }
    private static void startupKeepsRemainingBudgetAcrossRepeatedPauses(){
        Fixture f=new Fixture();f.begin();f.startup();f.advance(10_000);
        f.monitor.setForeground(false);f.advance(500_000);
        f.monitor.setForeground(false);f.advance(500_000);
        f.monitor.setForeground(true);f.monitor.setForeground(true);f.advance(10_000);
        f.monitor.setForeground(false);f.advance(500_000);f.monitor.setForeground(true);
        f.advance(CompletedRestoreMonitor.PREVIEW_STARTUP_BUDGET_MS-20_000-1);
        check(f.recoveries==0&&f.probes==1,"Background time shortened preview-startup grace");
        f.advance(1);check(f.recoveries==1,"Repeated resume reset the foreground deadline");
    }
    private static void leaseCanBeginAndAdvanceWhileHidden(){
        Fixture f=new Fixture();f.monitor.setForeground(false);f.advance(600_000);f.begin();f.startup();
        check(f.probes==0&&f.task==null,"Hidden lease scheduled a probe");
        f.advance(600_000);f.monitor.setForeground(true);
        f.advance(CompletedRestoreMonitor.PREVIEW_STARTUP_BUDGET_MS-1);
        check(f.recoveries==0,"Hidden progress retained a wall-clock deadline");
        check(f.monitor.pulse("job","nonce","preview-first-render",5,0),"First render rejected after resume");
        check(!f.monitor.terminal("job","nonce",6,0),"Resume fabricated visual proof");
        check(f.monitor.pulse("job","nonce","preview-visual-commit",6,0),"Visual proof rejected");
        check(f.monitor.terminal("job","nonce",7,0),"Terminal rejected");
        check(f.monitor.ackCommitted("job","nonce"),"ACK rejected");
        f.monitor.setForeground(false);f.advance(600_000);f.monitor.setForeground(true);f.advance(600_000);
        check(f.recoveries==0&&f.task==null,"Terminal lease rearmed after resume");
    }
    private static void phaseDeadlineAndRecoveryCapRemainBounded(){
        Fixture f=new Fixture();f.responsive=true;f.begin();f.advance(12_000);
        f.monitor.setForeground(false);f.advance(600_000);f.monitor.setForeground(true);
        f.advance(CompletedRestoreMonitor.BOOTSTRAP_PHASE_BUDGET_MS-12_000-1);
        check(f.recoveries==0,"Hidden time counted toward bootstrap deadline");
        f.advance(1);check(f.recoveries==1,"Responsive stalled phase escaped original foreground deadline");
        f.monitor.replacementStarted();check(f.monitor.begin("job","replacement",0),"Replacement lease rejected");
        f.advance(CompletedRestoreMonitor.BOOTSTRAP_PHASE_BUDGET_MS);
        check(f.recoveries==1,"Pause/resume bypassed persistent recovery cap");
        f.monitor.close();f.monitor.setForeground(false);f.monitor.setForeground(true);f.advance(600_000);
        check(f.task==null&&!f.monitor.active(),"Closed monitor resumed");
    }
    public static void main(String[] args){
        callbackDoesNotExpireWhileHidden();startupKeepsRemainingBudgetAcrossRepeatedPauses();
        leaseCanBeginAndAdvanceWhileHidden();phaseDeadlineAndRecoveryCapRemainBounded();
        System.out.println("PASS: "+checks+" production completed-restore lifecycle checks");
    }
}
