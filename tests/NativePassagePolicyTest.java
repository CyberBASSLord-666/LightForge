package com.cyberbasslord.lightforge;

import java.io.*;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.zip.CRC32;

/** Deterministic adversarial admission, bounded-work, sustained-regression and cache tests. */
public final class NativePassagePolicyTest {
    private static final long SECOND=1000000000L, BASE=60*SECOND, FAST=40*SECOND;
    private static final String ID=repeat('1'), HASH=repeat('b');
    private static int checks;
    private static String repeat(char value){char[] chars=new char[64];Arrays.fill(chars,value);return new String(chars);}
    private static void require(boolean ok,String message){checks++;if(!ok)throw new AssertionError(message);}
    private static NativePassagePolicy policy(){NativePassagePolicy p=new NativePassagePolicy(ID,null);p.nominate(4,0);return p;}
    private static NativePassagePolicy.Plan plan(NativePassagePolicy p,int ordinal,int remaining){
        NativePassagePolicy.Plan plan=p.plan(ordinal,remaining,Long.MAX_VALUE,8);compatible(p);return plan;
    }
    private static void compatible(NativePassagePolicy p){
        String[] records=p.evidenceRecords();
        require(Arrays.equals(records,NativeInferenceProfile.decodePassagePolicy(NativeInferenceProfile.encodePassagePolicy(records))),"actual policy evidence survives strict profile roundtrip");
        NativeInferenceProfile profile=new NativeInferenceProfile();profile.notePassagePolicy(records);
        require(profile.finish("completed").records().length==1+records.length,"terminal profile preserves every actual policy record");
    }
    private static NativePassagePolicy.Pair pair(int ordinal,boolean first,long baseline,long candidate,long extra){
        return new NativePassagePolicy.Pair(ordinal,first,baseline,candidate,extra,HASH,true,true,true,true,4);
    }
    private static NativePassagePolicy.Pair workersPair(int ordinal,boolean first,int workers,long baseline,long candidate,long extra){
        return new NativePassagePolicy.Pair(ordinal,first,baseline,candidate,extra,HASH,true,true,true,true,workers);
    }
    private static NativePassagePolicy.Pair good(int ordinal){return pair(ordinal,ordinal==1,BASE,FAST,FAST);}
    private static boolean reason(NativePassagePolicy p,String reason){return p.evidenceRecords()[0].contains("reason="+reason+" ");}
    private static void baseline(NativePassagePolicy p,int ordinal,int remaining,String message){
        require(plan(p,ordinal,remaining).action==NativePassagePolicy.Action.BASELINE,message);
    }
    private static NativePassagePolicy qualified(){
        NativePassagePolicy p=policy();
        for(int ordinal=0;ordinal<3;ordinal++){
            NativePassagePolicy.Plan selected=plan(p,ordinal,35-ordinal);
            require(selected.action==NativePassagePolicy.Action.PAIR,"complete pair at ordinal "+ordinal);
            require(selected.candidateFirst==(ordinal==1),"orders alternate AB/BA/AB without six unused baseline passages");
            p.recordPair(good(ordinal),34-ordinal);
            if(ordinal<2)require(p.qualifiedSeed()==null,"one or two pairs cannot create a complete seed");
        }
        require(p.qualifiedSeed()!=null,"three cold complete pairs qualify");compatible(p);return p;
    }
    private static NativePassagePolicy scenario(long baseline,long candidate,long screening){
        NativePassagePolicy p=new NativePassagePolicy(ID,null);p.nominate(4,screening);
        for(int ordinal=0;ordinal<3;ordinal++){
            NativePassagePolicy.Plan action=plan(p,ordinal,35-ordinal);
            if(action.action!=NativePassagePolicy.Action.PAIR)break;
            p.recordPair(pair(ordinal,ordinal==1,baseline,candidate,candidate),34-ordinal);
        }
        compatible(p);return p;
    }
    private static void writeInt(byte[] bytes,int offset,int value){for(int i=3;i>=0;i--){bytes[offset+i]=(byte)value;value>>>=8;}}
    private static void writeLong(byte[] bytes,int offset,long value){for(int i=7;i>=0;i--){bytes[offset+i]=(byte)value;value>>>=8;}}
    private static void crc(byte[] bytes){CRC32 crc=new CRC32();crc.update(bytes,8,bytes.length-8);writeLong(bytes,0,crc.getValue());}
    private static void forged(File file,byte[] original,int offset,int value,String message)throws Exception{
        byte[] bytes=original.clone();bytes[offset]=(byte)value;crc(bytes);Files.write(file.toPath(),bytes);
        require(NativePassagePolicy.load(file,ID)==null,message);
    }
    public static void main(String[] args)throws Exception{
        try{new NativePassagePolicy("raw-device-name",null);throw new AssertionError("raw identity accepted");}
        catch(IllegalArgumentException expected){checks++;}
        NativePassagePolicy missing=new NativePassagePolicy(ID,null);
        baseline(missing,0,35,"missing screening cannot nominate a schedule");
        require(missing.qualifiedSeed()==null,"missing evidence cannot seed");
        for(int remaining:new int[]{0,1,23}){
            NativePassagePolicy p=policy();baseline(p,0,remaining,"unknown and short work skip initial probes");
            require(reason(p,"short-job"),"short work reason survives");
        }
        NativePassagePolicy unknown=policy();baseline(unknown,0,-1,"unknown work skips all probe spending");
        require(reason(unknown,"unknown-work"),"unknown work has a distinct bounded reason");
        NativePassagePolicy late=policy();baseline(late,1,35,"qualification cannot start at a fabricated later ordinal");
        NativePassagePolicy screen=new NativePassagePolicy(ID,null);screen.nominate(8,SECOND);
        require(screen.qualifiedSeed()==null,"screening never qualifies a schedule");
        NativePassagePolicy.Plan screenPlan=screen.plan(0,35,NativePassagePolicy.EIGHT_WORKER_HEADROOM,8);
        require(screenPlan.action==NativePassagePolicy.Action.PAIR&&screenPlan.workers==8,"eligible nomination only requests a full pair");
        require(screenPlan.probeBudgetNanos==NativePassagePolicy.EXTRA_CAP_NANOS-SECOND,"screening spends hard budget");
        for(long memory:new long[]{-1,0,NativePassagePolicy.FOUR_WORKER_HEADROOM-1}){
            NativePassagePolicy p=policy();require(p.plan(0,35,memory,8).action==NativePassagePolicy.Action.BASELINE,"insufficient memory blocks any candidate");
            baseline(p,1,34,"memory rejection latches baseline after pressure clears");
        }
        NativePassagePolicy lowCores=policy();require(lowCores.plan(0,35,Long.MAX_VALUE,3).action==NativePassagePolicy.Action.BASELINE,"no outer workers beyond available cores");
        NativePassagePolicy eightLow=new NativePassagePolicy(ID,null);eightLow.nominate(8,0);
        require(eightLow.plan(0,35,NativePassagePolicy.EIGHT_WORKER_HEADROOM-1,8).action==NativePassagePolicy.Action.BASELINE,"eight workers require complete native headroom");
        NativePassagePolicy wrongWorkers=new NativePassagePolicy(ID,null);wrongWorkers.nominate(6,0);
        baseline(wrongWorkers,0,35,"unreviewed geometry is never nominated");
        NativePassagePolicy overscreen=new NativePassagePolicy(ID,null);overscreen.nominate(4,NativePassagePolicy.EXTRA_CAP_NANOS+1);
        baseline(overscreen,0,35,"screening cannot exceed total extra cap");
        NativePassagePolicy negativescreen=new NativePassagePolicy(ID,null);negativescreen.nominate(4,-1);
        baseline(negativescreen,0,35,"negative screening time is invalid");

        for(int flaw=0;flaw<9;flaw++){
            NativePassagePolicy p=policy();require(plan(p,0,35).action==NativePassagePolicy.Action.PAIR,"first trial requested");
            NativePassagePolicy.Pair bad=new NativePassagePolicy.Pair(0,false,flaw==4?0:BASE,flaw==5?Long.MAX_VALUE:FAST,
                flaw==6?0:BASE,flaw==7?"bad":HASH,flaw!=0,flaw!=1,flaw!=2,flaw!=3,flaw==8?8:4);
            p.recordPair(bad,34);require(p.qualifiedSeed()==null,"bad full-passage evidence cannot qualify: "+flaw);
            baseline(p,1,34,"bad pair latches baseline: "+flaw);
        }
        NativePassagePolicy mismatch=policy();plan(mismatch,0,35);
        mismatch.recordPair(new NativePassagePolicy.Pair(0,false,BASE,FAST,BASE,HASH,true,false,true,true,4),34);
        require(mismatch.evidenceRecords().length==2&&mismatch.evidenceRecords()[1].contains("exact=false"),"failed exact-output comparison survives outside the rotating trace");
        NativePassagePolicy slow=policy();plan(slow,0,35);slow.recordPair(pair(0,false,BASE,BASE,BASE),34);
        require(reason(slow,"pair-regression"),"equal complete timing rejects fast microbenchmark nomination");
        // Eight wins the temporal screen, but loses its complete passage.
        // Four can be compared only because its own exact screen was eligible.
        NativePassagePolicy alternate=new NativePassagePolicy(ID,null);alternate.nominate(8,4,5*SECOND);
        require(plan(alternate,0,35).workers==8,"micro-screen winner first receives the full comparison");
        alternate.recordPair(workersPair(0,false,8,BASE,65*SECOND,65*SECOND),34);
        require(reason(alternate,"alternate-pending")&&alternate.qualifiedSeed()==null,
            "eight-worker regression cannot qualify the screened four-worker alternate");
        require(alternate.evidenceRecords().length==2&&alternate.evidenceRecords()[1].contains("role=rejected")
            &&alternate.evidenceRecords()[1].contains("workers=8"),"losing full pair remains in bounded durable evidence");
        String[] counterfeit=alternate.evidenceRecords();counterfeit[1]=counterfeit[1].replace("workers=8","workers=4");
        require(NativeInferenceProfile.decodePassagePolicy(NativeInferenceProfile.encodePassagePolicy(counterfeit))==null,
            "diagnostics reject a fabricated four-worker rejected-pair record");
        for(int ordinal=1;ordinal<=3;ordinal++){
            NativePassagePolicy.Plan selected=plan(alternate,ordinal,35-ordinal);
            require(selected.action==NativePassagePolicy.Action.PAIR&&selected.workers==4
                &&selected.candidateFirst==(ordinal==2),"alternate has consecutive, alternating full comparisons");
            alternate.recordPair(workersPair(ordinal,ordinal==2,4,BASE,30*SECOND,30*SECOND),34-ordinal);
            if(ordinal<3)require(alternate.qualifiedSeed()==null,
                "one or two alternate pairs do not authorize production execution");
        }
        require(alternate.qualifiedSeed()!=null&&alternate.evidenceRecords()[0].contains("extraNanos=160000000000 "),
            "all four candidate replays and screening share the original 360-second budget");
        require(plan(alternate,4,31).action==NativePassagePolicy.Action.CANDIDATE,
            "only the three exact four-worker full pairs start a candidate lease");
        alternate.recordOrdinary(30*SECOND);
        NativePassagePolicy noScreenedFour=new NativePassagePolicy(ID,null);noScreenedFour.nominate(8,5*SECOND);
        plan(noScreenedFour,0,35);noScreenedFour.recordPair(workersPair(0,false,8,BASE,65*SECOND,65*SECOND),34);
        baseline(noScreenedFour,1,34,"an unscreened alternate can never be tried");
        NativePassagePolicy losingFour=new NativePassagePolicy(ID,null);losingFour.nominate(8,4,5*SECOND);
        plan(losingFour,0,35);losingFour.recordPair(workersPair(0,false,8,BASE,65*SECOND,65*SECOND),34);
        require(plan(losingFour,1,34).workers==4,"screened alternate receives one bounded comparison");
        losingFour.recordPair(workersPair(1,false,4,BASE,BASE,BASE),33);
        baseline(losingFour,2,33,"a losing alternate never cycles back to either candidate");
        NativePassagePolicy noUnsafeSwitch=new NativePassagePolicy(ID,null);noUnsafeSwitch.nominate(8,4,5*SECOND);
        plan(noUnsafeSwitch,0,35);
        noUnsafeSwitch.recordPair(new NativePassagePolicy.Pair(0,false,BASE,65*SECOND,65*SECOND,HASH,
            true,false,true,true,8),34);
        baseline(noUnsafeSwitch,1,34,"an inexact eight-worker comparison cannot trigger the alternate");
        NativePassagePolicy unaffordableAlternate=new NativePassagePolicy(ID,null);
        unaffordableAlternate.nominate(8,4,250*SECOND);plan(unaffordableAlternate,0,35);
        unaffordableAlternate.recordPair(workersPair(0,false,8,BASE,65*SECOND,65*SECOND),34);
        baseline(unaffordableAlternate,1,34,
            "alternate is skipped when even the first conservative replay cannot fit the shared cap");
        NativePassagePolicy memoryAlternate=new NativePassagePolicy(ID,null);memoryAlternate.nominate(8,4,5*SECOND);
        plan(memoryAlternate,0,35);memoryAlternate.recordPair(workersPair(0,false,8,BASE,65*SECOND,65*SECOND),34);
        require(memoryAlternate.plan(1,34,NativePassagePolicy.FOUR_WORKER_HEADROOM-1,8).action==NativePassagePolicy.Action.BASELINE,
            "fresh memory pressure blocks even a screened alternate");
        NativePassagePolicy badAlternate=new NativePassagePolicy(ID,null);badAlternate.nominate(8,8,0);
        baseline(badAlternate,0,35,"only an independently screened smaller geometry is eligible");
        NativePassagePolicy boundary=policy();plan(boundary,0,35);boundary.recordPair(pair(0,false,1000,950,1000),34);
        require(!reason(boundary,"pair-regression"),"5 percent pair floor is inclusive (payback remains separate)");
        NativePassagePolicy below=policy();plan(below,0,35);below.recordPair(pair(0,false,1000,951,1000),34);
        require(reason(below,"pair-regression"),"under 5 percent pair gain rejects");
        NativePassagePolicy poorPayback=policy();plan(poorPayback,0,35);
        poorPayback.recordPair(pair(0,false,BASE,54*SECOND,BASE),34);
        require(reason(poorPayback,"payback-unavailable"),"kernel win cannot hide whole-job probe overhead");
        NativePassagePolicy representative=scenario(65*SECOND,44*SECOND,10*SECOND);
        require(representative.qualifiedSeed()!=null,"representative32 percent full-passage gain repays real candidate replay and screening");
        NativePassagePolicy moderate=scenario(100*SECOND,70*SECOND,20*SECOND);
        require(moderate.qualifiedSeed()!=null,"removing repeated comparisons allows30 percent gross gain to repay real overhead");
        NativePassagePolicy expensive=scenario(150*SECOND,110*SECOND,20*SECOND);
        require(expensive.qualifiedSeed()==null&&reason(expensive,"payback-unavailable"),"three projected comparisons still must fit360second cap");
        // Historical run01 arm clocks include baseline-only model extraction. They are
        // cache-confounded arithmetic fixtures, not evidence of matched scheduling gain.
        long phoneBase=64104899455L,phoneCandidate=48358257794L,phoneScreen=4849516873L,phoneExtra=48372028159L;
        NativePassagePolicy phone=new NativePassagePolicy(ID,null);phone.nominate(4,phoneScreen);
        require(plan(phone,0,35).action==NativePassagePolicy.Action.PAIR,"historical phone arithmetic fixture starts with a requested pair");
        phone.recordPair(pair(0,false,phoneBase,phoneCandidate,phoneExtra),34);
        require(reason(phone,"qualification-pending")&&phone.qualifiedSeed()==null,"historical cache-confounded24.56percent arm reduction only tests projected affordability and never immediately authorizes a candidate");
        require(plan(phone,1,34).action==NativePassagePolicy.Action.PAIR,"removed replay work permits further qualification under these hypothetical matched timing assumptions");
        phone.recordPair(pair(1,true,57*SECOND,phoneCandidate,phoneExtra),33);
        require(reason(phone,"payback-unavailable")&&phone.qualifiedSeed()==null,"a57second paired baseline must still reject unproven10 percent net savings");
        NativePassagePolicy stablePhone=scenario(phoneBase,phoneCandidate,phoneScreen);
        require(stablePhone.qualifiedSeed()!=null,"three hypothetical stable measured gains would repay consecutive qualification and useful controls");
        NativePassagePolicy conservativePhone=scenario(57*SECOND,48*SECOND,phoneScreen);
        require(reason(conservativePhone,"payback-unavailable")&&conservativePhone.qualifiedSeed()==null,"57to48 does not bypass retained10 percent economic margin");
        NativePassagePolicy overhead=policy();plan(overhead,0,35);
        overhead.recordPair(pair(0,false,BASE,FAST,300*SECOND),34);
        require(reason(overhead,"payback-unavailable"),"future qualification must fit remaining fixed extra budget");
        NativePassagePolicy unfinished=policy();plan(unfinished,0,35);baseline(unfinished,1,34,"new passage cannot conceal unfinished pair");
        NativePassagePolicy outOfOrder=policy();plan(outOfOrder,0,35);outOfOrder.recordPair(good(4),34);
        baseline(outOfOrder,1,34,"unrequested ordinal cannot inject a completed pair");
        NativePassagePolicy reversed=policy();plan(reversed,0,35);reversed.recordPair(pair(0,true,BASE,FAST,BASE),34);
        baseline(reversed,1,34,"unrequested trial order cannot inject a completed pair");
        NativePassagePolicy missed=policy();plan(missed,0,35);missed.recordPair(good(0),34);
        baseline(missed,5,30,"missed scheduled pair cannot silently become sustained evidence");
        NativePassagePolicy abort=policy();plan(abort,0,35);abort.probeAborted("/private/music-title\nsecret",SECOND);
        require(reason(abort,"probe-aborted")&&!Arrays.toString(abort.evidenceRecords()).contains("secret"),"abort reasons never retain user text");
        baseline(abort,1,34,"aborted probe does not retry indefinitely");
        require(abort.qualifiedSeed()==null,"cancelled or partial evidence cannot seed");
        for(String reason:new String[]{"memory-pressure","screen-budget","screen-no-win","runtime-rejected"}){
            NativePassagePolicy rejected=policy();rejected.forceBaseline(reason);require(reason(rejected,reason),"integration reason retained: "+reason);compatible(rejected);
        }
        NativePassagePolicy overflow=policy();overflow.probeAborted("cancelled",Long.MAX_VALUE);overflow.probeAborted("cancelled",Long.MAX_VALUE);
        require(overflow.evidenceRecords()[0].contains("extraNanos="+Long.MAX_VALUE+" "),"extra ledger saturates without arithmetic wrap");
        baseline(overflow,0,35,"overflow cannot reopen a probe budget");
        NativePassagePolicy hugeWork=policy();baseline(hugeWork,0,Integer.MAX_VALUE,"unbounded work count is rejected before multiplication");
        NativePassagePolicy hugeOrdinal=policy();baseline(hugeOrdinal,Integer.MAX_VALUE,35,"unbounded ordinal is rejected");

        NativePassagePolicy p=qualified();
        for(int ordinal=3;ordinal<=10;ordinal++){
            require(plan(p,ordinal,35-ordinal).action==NativePassagePolicy.Action.CANDIDATE,"first complete lease has eight passages");p.recordOrdinary(FAST);
        }
        NativePassagePolicy.Plan renewal=plan(p,11,24);
        require(renewal.action==NativePassagePolicy.Action.CONTROL&&renewal.workers==0&&renewal.probeBudgetNanos==0,"eight-passage lease requires one useful baseline control without replay");
        p.recordControl(40*SECOND);
        require(reason(p,"control-regression")&&p.qualifiedSeed()==null,"candidate no longer faster than current baseline revokes the positive seed");
        compatible(p);
        require(p.evidenceRecords()[4].contains("accepted=false")&&p.evidenceRecords()[4].contains("comparisonScope=unmatched-inputs"),"control regression retained without claiming paired proof");
        baseline(p,12,23,"successful first three pairs never authorize indefinite execution");

        NativePassagePolicy spike=qualified();
        for(int ordinal=3;ordinal<=10;ordinal++){plan(spike,ordinal,35-ordinal);spike.recordOrdinary(FAST);}
        require(plan(spike,11,24).action==NativePassagePolicy.Action.CONTROL,"first lease funds initial control");spike.recordControl(BASE);
        for(int ordinal=12;ordinal<=14;ordinal++){
            require(plan(spike,ordinal,35-ordinal).action==NativePassagePolicy.Action.CANDIDATE,"guard waits for ordinary samples");
            spike.recordOrdinary(ordinal==13?FAST:51*SECOND);
        }
        NativePassagePolicy.Plan triggered=plan(spike,15,20);
        require(triggered.action==NativePassagePolicy.Action.CONTROL&&"slow-passage-control".equals(triggered.reason),"two of last three >125 percent trigger an actual useful baseline control");
        spike.recordControl(BASE);compatible(spike);
        require(spike.qualifiedSeed()!=null,"absolute slowdown alone does not fabricate a regression");
        require(plan(spike,16,19).action==NativePassagePolicy.Action.CANDIDATE,"conservatively accepted control renews the lease");
        spike.recordOrdinary(FAST);
        spike.forceBaseline("memory-fallback");baseline(spike,17,18,"one production memory fallback latches baseline");

        NativePassagePolicy earlySlow=qualified();
        for(int ordinal=3;ordinal<=5;ordinal++){plan(earlySlow,ordinal,35-ordinal);earlySlow.recordOrdinary(51*SECOND);}
        baseline(earlySlow,6,29,"recent slowdown must lower projected future saving before an otherwise useful control");
        require(reason(earlySlow,"payback-unavailable")&&earlySlow.qualifiedSeed()!=null,"economic failure preserves matched evidence without pretending that projected20second savings persist");
        NativePassagePolicy cheaperBaseline=qualified();
        for(int ordinal=3;ordinal<=10;ordinal++){plan(cheaperBaseline,ordinal,35-ordinal);cheaperBaseline.recordOrdinary(FAST);}
        require(plan(cheaperBaseline,11,24).action==NativePassagePolicy.Action.CONTROL,"new baseline timing is observed as useful work");
        cheaperBaseline.recordControl(43*SECOND);compatible(cheaperBaseline);
        require(cheaperBaseline.evidenceRecords()[4].contains("accepted=true")&&reason(cheaperBaseline,"payback-unavailable"),"timing acceptance alone cannot override newly unprofitable projected saving");
        baseline(cheaperBaseline,12,23,"new lower baseline brackets cap future saving without another replay");

        NativePassagePolicy oneSpike=qualified();
        for(int ordinal=3;ordinal<=5;ordinal++){plan(oneSpike,ordinal,35-ordinal);oneSpike.recordOrdinary(ordinal==3?51*SECOND:50*SECOND);}
        require(plan(oneSpike,6,29).action==NativePassagePolicy.Action.CANDIDATE,"one spike and exactly125 percent do not trigger two-of-three guard");
        NativePassagePolicy warming=qualified();
        for(int ordinal=3;ordinal<=10;ordinal++){plan(warming,ordinal,35-ordinal);warming.recordOrdinary(FAST);}
        require(plan(warming,11,24).action==NativePassagePolicy.Action.CONTROL,"warming fixture begins with a valid first lease");warming.recordControl(BASE);
        for(int ordinal=12;ordinal<=23;ordinal++){plan(warming,ordinal,35-ordinal);warming.recordOrdinary((ordinal<22?40:58)*SECOND);}
        require(plan(warming,24,11).action==NativePassagePolicy.Action.CONTROL,"warming causes a control observation after earlier savings cover economics");
        warming.recordControl(100*SECOND);
        require(reason(warming,"control-regression"),"a newly slower baseline cannot bless candidate regression against the previous baseline bracket");
        NativePassagePolicy incompleteControl=qualified();incompleteControl.recordControl(BASE);
        require(reason(incompleteControl,"control-incomplete")&&incompleteControl.qualifiedSeed()==null,"unrequested control cannot renew or retain current evidence");
        NativePassagePolicy unfinishedControl=qualified();
        for(int ordinal=3;ordinal<=10;ordinal++){plan(unfinishedControl,ordinal,35-ordinal);unfinishedControl.recordOrdinary(FAST);}
        require(plan(unfinishedControl,11,24).action==NativePassagePolicy.Action.CONTROL,"control requested before unfinished test");
        baseline(unfinishedControl,12,23,"missing control observation cannot silently extend lease");
        require(reason(unfinishedControl,"unfinished-control"),"unfinished control cause retained");
        NativePassagePolicy shortRenewal=qualified();
        for(int ordinal=3;ordinal<=10;ordinal++){plan(shortRenewal,ordinal,35-ordinal);shortRenewal.recordOrdinary(FAST);}
        baseline(shortRenewal,11,3,"short remaining tail stays on baseline without a renewal");
        require(shortRenewal.qualifiedSeed()!=null,"short tail does not erase completed exact qualification for future fresh validation");
        NativePassagePolicy budget=new NativePassagePolicy(ID,null);budget.nominate(4,200*SECOND);
        for(int ordinal=0;ordinal<3;ordinal++){
            require(plan(budget,ordinal,35-ordinal).action==NativePassagePolicy.Action.PAIR,"large gain qualification remains funded");
            budget.recordPair(pair(ordinal,ordinal==1,90*SECOND,5*SECOND,(ordinal==2?150:5)*SECOND),34-ordinal);
        }
        require(budget.qualifiedSeed()!=null,"large measured gain can repay fully counted screening");
        for(int ordinal=3;ordinal<=10;ordinal++){plan(budget,ordinal,35-ordinal);budget.recordOrdinary(5*SECOND);}
        require(plan(budget,11,24).action==NativePassagePolicy.Action.CONTROL,"useful baseline control requires no extra budget even at360second cap");
        budget.recordControl(90*SECOND);
        require(budget.evidenceRecords()[0].contains("extraNanos=360000000000 "),"baseline control does not masquerade as extra replay work");
        for(int ordinal=12;ordinal<=23;ordinal++){
            require(plan(budget,ordinal,35-ordinal).action==NativePassagePolicy.Action.CANDIDATE,"renewed bounded lease remains useful at the probe cap");budget.recordOrdinary(5*SECOND);
        }
        require(plan(budget,24,11).action==NativePassagePolicy.Action.CONTROL,"second12passage lease ends with another useful baseline control");
        budget.recordControl(90*SECOND);compatible(budget);
        NativePassagePolicy invalidClock=qualified();plan(invalidClock,3,32);invalidClock.recordOrdinary(Long.MAX_VALUE);
        baseline(invalidClock,4,31,"invalid ordinary clock cannot evade sustained guard");
        NativePassagePolicy positive=qualified();
        for(String record:positive.evidenceRecords()){
            require(record.length()<=512&&record.matches("[ -~]+"),"durable records stay bounded ASCII without free text");
        }
        require(positive.evidenceRecords().length==4,"retain all three decisive raw pairs");
        require(positive.evidenceRecords()[0].contains("paybackScope=projected-not-measured"),"net payback estimate is never called measured improvement");

        File directory=Files.createTempDirectory("lightforge-passage-policy-").toFile(),file=new File(directory,"policy.bin");
        try{
            require(NativePassagePolicy.load(file,ID)==null,"missing cache is unqualified");
            try{NativePassagePolicy.save(file,ID,null);throw new AssertionError("provisional saved");}catch(IOException expected){checks++;}
            NativePassagePolicy.save(file,ID,positive.qualifiedSeed());byte[] original=Files.readAllBytes(file.toPath());
            require(original.length<NativePassagePolicy.MAX_BYTES,"qualified cache is bounded below16KiB");
            NativePassagePolicy.save(file,ID,alternate.qualifiedSeed());
            NativePassagePolicy.Seed alternateSeed=NativePassagePolicy.load(file,ID);
            require(alternateSeed!=null&&alternateSeed.workers==4,
                "consecutive alternate qualification is independently revalidated on reload");
            NativePassagePolicy alternateCached=new NativePassagePolicy(ID,alternateSeed);
            require(plan(alternateCached,0,35).action==NativePassagePolicy.Action.PAIR
                &&alternateCached.qualifiedSeed()!=null,"saved alternate still requires a fresh exact pair before use");
            NativePassagePolicy.save(file,ID,positive.qualifiedSeed());
            NativePassagePolicy.Seed seed=NativePassagePolicy.load(file,ID);require(seed!=null&&seed.workers==4,"complete evidence reconstructs the same candidate");
            require(NativePassagePolicy.load(file,repeat('2'))==null,"identity change invalidates old seed");
            require(NativePassagePolicy.load(file,"raw-model-id")==null,"raw identity never matches a cache");
            NativePassagePolicy seeded=new NativePassagePolicy(ID,seed);
            require(seeded.qualifiedSeed()!=null&&seeded.evidenceRecords()[0].contains("state=provisional"),"retained complete seed is distinct from current-job authority");
            NativePassagePolicy.Plan first=plan(seeded,0,35);
            require(first.action==NativePassagePolicy.Action.PAIR&&first.candidateFirst,"positive cache must earn a fresh opposite-order complete pair");
            seeded.recordPair(pair(0,true,BASE,FAST,BASE),34);
            require(seeded.qualifiedSeed()!=null,"fresh exact measured pair renews complete historical qualification");
            for(int ordinal=1;ordinal<=8;ordinal++){require(plan(seeded,ordinal,35-ordinal).action==NativePassagePolicy.Action.CANDIDATE,"cached job starts with an eight-passage lease");seeded.recordOrdinary(FAST);}
            require(plan(seeded,9,26).action==NativePassagePolicy.Action.CONTROL,"cached qualification still requires a useful sustained baseline control");
            seeded.recordControl(BASE);
            compatible(seeded);
            require(seeded.evidenceRecords().length==6,"retain3qualificationpairs,lastfreshpair andlastunmatchedcontrol separately");
            for(int ordinal=10;ordinal<=21;ordinal++){require(plan(seeded,ordinal,35-ordinal).action==NativePassagePolicy.Action.CANDIDATE,"subsequent lease lasts12 passages");seeded.recordOrdinary(FAST);}
            require(plan(seeded,22,13).action==NativePassagePolicy.Action.CONTROL,"renewed twelve-passage lease also expires");
            seeded.recordControl(BASE);
            require(seeded.qualifiedSeed()!=null,"bounded further renewal retains qualification");
            NativePassagePolicy.save(file,ID,seeded.qualifiedSeed());
            require(NativePassagePolicy.load(file,ID)!=null,"complete matched qualification survives persistence independently of unmatched controls");
            NativePassagePolicy nextCached=new NativePassagePolicy(ID,NativePassagePolicy.load(file,ID));
            NativePassagePolicy.Plan nextFresh=plan(nextCached,0,35);
            require(nextFresh.action==NativePassagePolicy.Action.PAIR&&!nextFresh.candidateFirst,"persisted fresh BA pair requires next job AB regardless of intervening controls");
            nextCached.recordPair(pair(0,false,BASE,FAST,FAST),34);
            NativePassagePolicy thirdCached=new NativePassagePolicy(ID,nextCached.qualifiedSeed());
            require(plan(thirdCached,0,35).candidateFirst,"successive fresh job order alternates again");
            NativePassagePolicy stale=new NativePassagePolicy(ID,seed);baseline(stale,0,7,"cached seed cannot trigger costly short-job comparison");
            require(stale.qualifiedSeed()!=null&&stale.evidenceRecords()[0].contains("extraNanos=0 "),"short job preserves prior evidence without spending extra or authorizing a candidate");
            NativePassagePolicy laterLong=new NativePassagePolicy(ID,stale.qualifiedSeed());
            require(plan(laterLong,0,35).action==NativePassagePolicy.Action.PAIR,"next long job must still earn a fresh complete pair from preserved seed");
            laterLong.recordPair(pair(0,true,BASE,FAST,FAST),34);
            require(plan(laterLong,1,34).action==NativePassagePolicy.Action.CANDIDATE,"fresh memory,pair andpayback checks authorize the later job");
            for(String economic:new String[]{"short-renewal","payback-unavailable","probe-budget","unknown-work"}){
                NativePassagePolicy keep=new NativePassagePolicy(ID,seed);keep.forceBaseline(economic);
                require(keep.qualifiedSeed()!=null,"economic state retains complete evidence: "+economic);
                baseline(keep,0,35,"retained evidence never overrides current-job baseline latch");
            }
            for(String unsafe:new String[]{"runtime-rejected","invalid-pair","pair-regression","control-regression","output-mismatch","memory-pressure","cancelled","memory-fallback","memory-ineligible","thermal-guard"}){
                NativePassagePolicy discard=new NativePassagePolicy(ID,seed);discard.forceBaseline(unsafe);
                require(discard.qualifiedSeed()==null,"quality,regression,invalid orruntime failure clears prior evidence: "+unsafe);
            }
            NativePassagePolicy foreign=new NativePassagePolicy(repeat('3'),seed);baseline(foreign,0,35,"seed cannot cross runtime/model/OS identity");
            NativePassagePolicy failedFresh=new NativePassagePolicy(ID,seed);plan(failedFresh,0,35);
            failedFresh.recordPair(pair(0,true,BASE,BASE,BASE),34);
            baseline(failedFresh,1,34,"stale historical speedup cannot override a current regression");
            require(failedFresh.qualifiedSeed()==null,"fresh paired regression discards the historical seed");
            byte[] corrupt=original.clone();corrupt[corrupt.length-1]^=1;Files.write(file.toPath(),corrupt);
            require(NativePassagePolicy.load(file,ID)==null,"corrupt CRC rejects seed");
            forged(file,original,15,1,"previous passage policy schema rejected even with repaired CRC");
            forged(file,original,15,3,"unknown passage policy schema rejected even with repaired CRC");
            forged(file,original,8,0,"old graph-policy magic cannot enter passage cache");
            forged(file,original,89,2,"partial qualification count cannot qualify with repaired CRC");
            forged(file,original,94,1,"nonalternating complete qualification rejected with repaired CRC");
            byte[] spaced=original.clone();writeInt(spaced,193,4);writeInt(spaced,296,8);crc(spaced);Files.write(file.toPath(),spaced);
            require(NativePassagePolicy.load(file,ID)==null,"old spaced qualification cannot enter new cache even after schema/CRC forgery");
            for(int offset:new int[]{185,186,187,188})forged(file,original,offset,0,"nonfinite/inexact/partial/warm-only cache rejected at"+offset);
            forged(file,original,192,8,"different candidate worker geometry rejected");
            byte[] weak=original.clone();writeLong(weak,103,BASE);crc(weak);Files.write(file.toPath(),weak);
            require(NativePassagePolicy.load(file,ID)==null,"reload recomputes every paired performance floor");
            byte[] fakeCost=original.clone();writeLong(fakeCost,111,0);crc(fakeCost);Files.write(file.toPath(),fakeCost);
            require(NativePassagePolicy.load(file,ID)==null,"zero-cost full duplicate cannot forge affordable evidence");
            byte[] excessiveCost=original.clone();for(int offset:new int[]{111,214,317})writeLong(excessiveCost,offset,150*SECOND);crc(excessiveCost);Files.write(file.toPath(),excessiveCost);
            require(NativePassagePolicy.load(file,ID)==null,"three qualification costs cannot exceed their shared job cap even with a valid CRC");
            byte[] badClock=original.clone();writeLong(badClock,95,Long.MAX_VALUE);crc(badClock);Files.write(file.toPath(),badClock);
            require(NativePassagePolicy.load(file,ID)==null,"oversized cache clocks cannot overflow percentage tests");
            byte[] median=original.clone();for(int offset:new int[]{103,206,309})writeLong(median,offset,54*SECOND);crc(median);Files.write(file.toPath(),median);
            require(NativePassagePolicy.load(file,ID)==null,"reload recomputes15 percent qualification median");
            byte[] trailing=Arrays.copyOf(original,original.length+1);crc(trailing);Files.write(file.toPath(),trailing);
            require(NativePassagePolicy.load(file,ID)==null,"trailing payload rejected even with repaired CRC");
            Files.write(file.toPath(),new byte[NativePassagePolicy.MAX_BYTES+1]);require(NativePassagePolicy.load(file,ID)==null,"oversized cache is not parsed");
            Files.write(file.toPath(),Arrays.copyOf(original,70));require(NativePassagePolicy.load(file,ID)==null,"truncated cache defaults to baseline");
            Files.write(new File(file.getPath()+".tmp").toPath(),new byte[]{1});NativePassagePolicy.save(file,ID,positive.qualifiedSeed());
            require(!new File(file.getPath()+".tmp").exists()&&NativePassagePolicy.load(file,ID)!=null,"atomic save retires temporary data");
            byte[] before=Files.readAllBytes(file.toPath());
            try{NativePassagePolicy.save(file,repeat('4'),positive.qualifiedSeed());throw new AssertionError("foreign save accepted");}catch(IOException expected){checks++;}
            require(Arrays.equals(before,Files.readAllBytes(file.toPath())),"rejected save preserves prior qualified bytes");
            File link=new File(directory,"link");Files.createSymbolicLink(link.toPath(),file.toPath());
            require(NativePassagePolicy.load(link,ID)==null,"cache symlink is never followed");
            try{NativePassagePolicy.save(link,ID,positive.qualifiedSeed());throw new AssertionError("symlink written");}catch(IOException expected){checks++;}
        }finally{for(File child:directory.listFiles())Files.deleteIfExists(child.toPath());Files.deleteIfExists(directory.toPath());}
        System.out.println("PASS: "+checks+" bounded complete-passage policy checks");
    }
}
