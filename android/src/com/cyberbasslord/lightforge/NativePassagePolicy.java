package com.cyberbasslord.lightforge;

import java.io.*;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.Arrays;
import java.util.zip.CRC32;

/** Pure, bounded admission for a complete-passage CPU schedule; never executes inference. */
final class NativePassagePolicy {
    static final long EXTRA_CAP_NANOS=360000000000L;
    static final long FOUR_WORKER_HEADROOM=1536L*1024*1024, EIGHT_WORKER_HEADROOM=2048L*1024*1024;
    static final int MAX_BYTES=16384, MAX_PASSAGES=4096;
    private static final long MAX_PASSAGE_NANOS=3600000000000L;
    private static final int MAGIC=0x4c465050, SCHEMA=1;
    enum Action { BASELINE, PAIR, CANDIDATE }

    static final class Plan {
        final Action action;
        final int workers;
        final boolean candidateFirst;
        final long probeBudgetNanos;
        final String reason;
        private Plan(Action action,int workers,boolean first,long budget,String reason){
            this.action=action;this.workers=workers;candidateFirst=first;probeBudgetNanos=budget;this.reason=reason;
        }
    }

    static final class Pair {
        final int ordinal,candidateWorkers;
        final boolean candidateFirst,finite,exact,fullGeometry,coldSessions;
        final long baselineNanos,candidateNanos,extraNanos;
        final String outputSha256;
        Pair(int ordinal,boolean candidateFirst,long baselineNanos,long candidateNanos,long extraNanos,
                String outputSha256,boolean finite,boolean exact,boolean fullGeometry,boolean coldSessions,int candidateWorkers){
            this.ordinal=ordinal;this.candidateFirst=candidateFirst;this.baselineNanos=baselineNanos;
            this.candidateNanos=candidateNanos;this.extraNanos=extraNanos;this.outputSha256=outputSha256;
            this.finite=finite;this.exact=exact;this.fullGeometry=fullGeometry;this.coldSessions=coldSessions;
            this.candidateWorkers=candidateWorkers;
        }
    }

    /** Only a reconstructed, complete qualification can create a seed. */
    static final class Seed {
        final int workers;
        private final String identity;
        private final Pair[] qualification;
        private final Pair recheck;
        private Seed(String identity,int workers,Pair[] qualification,Pair recheck){
            this.identity=identity;this.workers=workers;this.qualification=qualification.clone();this.recheck=recheck;
        }
    }

    private final String identity;
    private final Pair[] qualification=new Pair[3];
    private final long[] recent=new long[3];
    private int workers,qualificationCount,lastOrdinal=-1,activePassages,lease=8,recentCount,pairCount;
    private long extraNanos,projectedAccruedSavingsNanos;
    private boolean seeded,freshRequired,qualified,latched,pending,slow;
    private Pair recheck;
    private Plan previous;
    private String reason="unmeasured";

    NativePassagePolicy(String identity,Seed seed){
        if(!digest(identity))throw new IllegalArgumentException("Invalid passage policy identity.");
        this.identity=identity;
        if(seed!=null&&identity.equals(seed.identity)&&validSeed(seed)){
            workers=seed.workers;System.arraycopy(seed.qualification,0,qualification,0,3);qualificationCount=3;
            recheck=seed.recheck;seeded=true;freshRequired=true;reason="fresh-pair-required";
        }
    }

    /** Screening nominates one schedule and consumes budget; it cannot qualify a schedule. */
    void nominate(int workers,long screeningNanos){
        addExtra(screeningNanos);
        if(latched)return;
        if(!workerCount(workers)||qualificationCount!=0||pending||lastOrdinal>=0||this.workers!=0){
            forceBaseline("invalid-nomination");return;
        }
        this.workers=workers;reason="nominated";
    }

    /** remainingUseful includes this passage; -1 means unknown and never permits a probe. */
    Plan plan(int ordinal,int remainingUseful,long headroom,int cores){
        if(pending){forceBaseline("unfinished-pair");return baseline();}
        if(ordinal<0||ordinal>=MAX_PASSAGES||ordinal<=lastOrdinal||remainingUseful< -1||remainingUseful>MAX_PASSAGES){
            forceBaseline("invalid-plan");return baseline();
        }
        lastOrdinal=ordinal;
        if(latched)return baseline();
        if(remainingUseful== -1){forceBaseline("unknown-work");return baseline();}
        if(workers==0){reason="unmeasured";return baseline();}
        if(!allowed(workers,headroom,cores)){forceBaseline("memory-ineligible");return baseline();}
        if(!qualified){
            if(freshRequired){
                if(remainingUseful<8){forceBaseline("short-job");return baseline();}
                if(!canFundProbe()){forceBaseline("probe-budget");return baseline();}
                if(!payback(remainingUseful-1,3,lastOrdinal,estimatedExtra())){
                    forceBaseline("payback-unavailable");return baseline();
                }
                return pair(recheck==null?!qualification[2].candidateFirst:!recheck.candidateFirst,"fresh-pair-required");
            }
            if(qualificationCount==0){
                if(ordinal!=0||remainingUseful<24){forceBaseline("short-job");return baseline();}
                return pair(false,"initial-pair");
            }
            int due=qualificationCount*4;
            if(ordinal<due){reason="qualification-wait";return baseline();}
            if(ordinal!=due){forceBaseline("missed-qualification");return baseline();}
            if(!payback(remainingUseful,qualificationCount,lastOrdinal-1)||!canFundProbe()){
                forceBaseline("payback-unavailable");return baseline();
            }
            return pair((qualificationCount&1)!=0,"qualification-pair");
        }
        boolean renewal=slow||activePassages>=lease;
        if(renewal){
            if(remainingUseful<4){forceBaseline("short-renewal");return baseline();}
            if(!canFundProbe()){forceBaseline("probe-budget");return baseline();}
            if(!payback(remainingUseful-1,3,lastOrdinal,estimatedExtra())){forceBaseline("payback-unavailable");return baseline();}
            boolean first=recheck==null?!qualification[2].candidateFirst:!recheck.candidateFirst;
            return pair(first,slow?"slow-passage-recheck":"lease-recheck");
        }
        reason="qualified-lease";
        previous=new Plan(Action.CANDIDATE,workers,false,0,reason);return previous;
    }

    /** remainingUseful counts useful passages AFTER this completed paired passage. */
    void recordPair(Pair pair,int remainingUseful){
        if(pair!=null)addExtra(pair.extraNanos);
        boolean expected=pending&&previous!=null&&pair!=null&&pair.ordinal==lastOrdinal
            &&pair.candidateWorkers==workers&&pair.candidateFirst==previous.candidateFirst;
        pending=false;
        if(latched)return;
        if(!expected||remainingUseful<0||remainingUseful>MAX_PASSAGES||!validPair(pair,workers)){
            if(expected&&recordable(pair,workers))recheck=pair;
            forceBaseline("invalid-pair");return;
        }
        pairCount++;
        if(!faster(pair,95)){recheck=pair;forceBaseline("pair-regression");return;}
        boolean newLease=!qualified;
        if(freshRequired){
            recheck=pair;freshRequired=false;qualified=true;
        }else if(!qualified){
            if(pair.ordinal!=qualificationCount*4||pair.candidateFirst!=((qualificationCount&1)!=0)){
                forceBaseline("invalid-pair-order");return;
            }
            qualification[qualificationCount++]=pair;
            if(qualificationCount==3){
                if(!qualifiedMedians(qualification)){forceBaseline("median-regression");return;}
                qualified=true;
            }
        }else recheck=pair;
        lease=newLease?8:12;
        if(!payback(remainingUseful,qualificationCount,pair.ordinal)){
            forceBaseline("payback-unavailable");return;
        }
        activePassages=0;recentCount=0;slow=false;
        reason=qualified?"measured-passage-improvement":"qualification-pending";
    }

    /** Observe the selected ordinary path only; its duration is not a paired speedup measurement. */
    void recordOrdinary(long wallNanos){
        if(pending){forceBaseline("unfinished-pair");return;}
        if(!timing(wallNanos)){forceBaseline("invalid-timing");return;}
        if(latched||previous==null||previous.action!=Action.CANDIDATE)return;
        activePassages++;
        long projected=Math.max(0,Math.min(minSaving(),minBaseline()-wallNanos));
        projectedAccruedSavingsNanos+=projected;
        recent[recentCount%3]=wallNanos;recentCount++;
        if(recentCount>=3){
            long reference=candidateMedian();int slower=0;
            for(long value:recent)if(value*100>reference*125)slower++;
            slow=slower>=2;
        }
        previous=null;
    }

    /** Caller reports completed extra work after retiring native resources at a safe checkpoint. */
    void probeAborted(String reason,long extraNanos){
        addExtra(extraNanos);pending=false;forceBaseline(safeReason(reason,"probe-aborted"));
    }

    void forceBaseline(String reason){
        if(!latched)this.reason=safeReason(reason,"external-baseline");
        latched=true;qualified=false;pending=false;previous=null;
    }

    Seed qualifiedSeed(){
        if(!qualified||latched||pending||freshRequired||qualificationCount!=3)return null;
        Seed seed=new Seed(identity,workers,qualification,recheck);return validSeed(seed)?seed:null;
    }

    String[] evidenceRecords(){
        String[] records=new String[1+qualificationCount+(recheck==null?0:1)];
        records[0]="schema=native-passage-policy-v1 state="+(latched?"baseline":qualified?"qualified":"provisional")
            +" workers="+workers+" reason="+reason+" extraNanos="+extraNanos+" extraCapNanos="+EXTRA_CAP_NANOS
            +" projectedAccruedSavingsNanos="+projectedAccruedSavingsNanos
            +" qualificationPairs="+qualificationCount+" currentJobPairs="+pairCount+" seeded="+seeded
            +" activePassages="+activePassages+" leasePassages="+lease+" paybackScope=projected-not-measured";
        for(int i=0;i<qualificationCount;i++)records[i+1]=record("qualification",i,qualification[i]);
        if(recheck!=null)records[records.length-1]=record("recheck",0,recheck);
        return records;
    }

    private Plan baseline(){previous=new Plan(Action.BASELINE,0,false,0,reason);return previous;}
    private Plan pair(boolean first,String reason){
        if(extraNanos>=EXTRA_CAP_NANOS){forceBaseline("probe-budget");return baseline();}
        this.reason=reason;pending=true;
        previous=new Plan(Action.PAIR,workers,first,EXTRA_CAP_NANOS-extraNanos,reason);return previous;
    }
    private void addExtra(long value){
        if(value<0){forceBaseline("invalid-timing");return;}
        extraNanos=value>Long.MAX_VALUE-extraNanos?Long.MAX_VALUE:extraNanos+value;
        if(extraNanos>EXTRA_CAP_NANOS)forceBaseline("probe-budget");
    }
    private boolean canFundProbe(){long extra=estimatedExtra();return extra>0&&extraNanos<=EXTRA_CAP_NANOS-extra;}

    /** Conservative projection. Its bounded lease horizon never spends unavailable future probe budget. */
    private boolean payback(int remaining,int measured,int ordinal){
        return payback(remaining,measured,ordinal,0);
    }
    private boolean payback(int remaining,int measured,int ordinal,long immediateExtra){
        if(remaining<=0||measured<=0)return false;
        long baseline=maxBaseline(),saving=minSaving();
        if(baseline<=0||saving<=0)return false;
        int needed=3-measured;
        long probeCost=estimatedExtra(),futureQualification=needed*probeCost;
        if(immediateExtra>EXTRA_CAP_NANOS-extraNanos||futureQualification>EXTRA_CAP_NANOS-extraNanos-immediateExtra)return false;
        int waiting=needed==0?0:Math.max(0,8-ordinal);
        int available=Math.max(0,remaining-waiting);
        if(available==0)return false;
        long committed=extraNanos+futureQualification+immediateExtra;
        int possibleRenewals=(int)Math.min(MAX_PASSAGES,(EXTRA_CAP_NANOS-committed)/probeCost);
        int firstLease=immediateExtra>0&&qualified?12:qualified?lease:8;
        int useful=Math.min(available,firstLease),left=available-useful,renewals=0;
        while(left>=4&&renewals<possibleRenewals){
            left--;renewals++; // The renewed pair produces baseline output, so it earns no accelerated-passage saving.
            int accelerated=Math.min(left,12);useful+=accelerated;left-=accelerated;
        }
        long costs=committed+renewals*probeCost;
        long margin=(remaining*baseline+9)/10;
        // Bounds on remaining and passage clocks make every product here fit in signed long.
        return projectedAccruedSavingsNanos+useful*saving>=costs+margin;
    }
    private long maxBaseline(){
        long value=0;for(int i=0;i<qualificationCount;i++)value=Math.max(value,qualification[i].baselineNanos);
        if(recheck!=null&&validPair(recheck,workers))value=Math.max(value,recheck.baselineNanos);return value;
    }
    private long minBaseline(){
        long value=Long.MAX_VALUE;for(int i=0;i<qualificationCount;i++)value=Math.min(value,qualification[i].baselineNanos);
        if(recheck!=null&&validPair(recheck,workers))value=Math.min(value,recheck.baselineNanos);
        return value==Long.MAX_VALUE?0:value;
    }
    /** Baseline is useful output during a comparison; candidate replay and its validation are extra. */
    private long estimatedExtra(){
        long candidate=0,observed=0;
        for(int i=0;i<qualificationCount;i++){
            candidate=Math.max(candidate,qualification[i].candidateNanos);observed=Math.max(observed,qualification[i].extraNanos);
        }
        if(recheck!=null&&validPair(recheck,workers)){
            candidate=Math.max(candidate,recheck.candidateNanos);observed=Math.max(observed,recheck.extraNanos);
        }
        return Math.max(observed,(candidate*110+99)/100);
    }
    private long minSaving(){
        long value=Long.MAX_VALUE;
        for(int i=0;i<qualificationCount;i++)value=Math.min(value,qualification[i].baselineNanos-qualification[i].candidateNanos);
        if(recheck!=null&&validPair(recheck,workers))value=Math.min(value,recheck.baselineNanos-recheck.candidateNanos);
        return value==Long.MAX_VALUE?0:value;
    }
    private long candidateMedian(){
        if(recheck!=null)return recheck.candidateNanos;
        long[] values=new long[qualificationCount];for(int i=0;i<values.length;i++)values[i]=qualification[i].candidateNanos;
        return median(values);
    }
    private static boolean timing(long value){return value>0&&value<=MAX_PASSAGE_NANOS;}
    private static boolean workerCount(int workers){return workers==4||workers==8;}
    private static boolean allowed(int workers,long memory,int cores){return cores>=workers&&memory>=(workers==8?EIGHT_WORKER_HEADROOM:FOUR_WORKER_HEADROOM);}
    private static boolean digest(String value){return value!=null&&value.matches("[0-9a-f]{64}");}
    private static boolean validPair(Pair p,int workers){
        return recordable(p,workers)&&p.finite&&p.exact&&p.fullGeometry&&p.coldSessions;
    }
    private static boolean recordable(Pair p,int workers){
        return p!=null&&p.ordinal>=0&&p.ordinal<MAX_PASSAGES&&workerCount(workers)&&p.candidateWorkers==workers
            &&timing(p.baselineNanos)&&timing(p.candidateNanos)&&p.extraNanos>=Math.min(p.baselineNanos,p.candidateNanos)
            &&p.extraNanos<=EXTRA_CAP_NANOS&&digest(p.outputSha256);
    }
    private static boolean faster(Pair pair,int percent){return pair.candidateNanos*100<=pair.baselineNanos*percent;}
    private static boolean qualifiedMedians(Pair[] pairs){
        long[] baseline=new long[3],candidate=new long[3];
        for(int i=0;i<3;i++){baseline[i]=pairs[i].baselineNanos;candidate[i]=pairs[i].candidateNanos;}
        return median(candidate)*100<=median(baseline)*85;
    }
    private static long median(long[] values){if(values.length==0)return 0;Arrays.sort(values);return values[values.length/2];}
    private static boolean validSeed(Seed seed){
        if(seed==null||!digest(seed.identity)||!workerCount(seed.workers)||seed.qualification.length!=3)return false;
        long qualificationExtra=0;
        for(int i=0;i<3;i++){
            Pair p=seed.qualification[i];
            if(!validPair(p,seed.workers)||p.ordinal!=i*4||p.candidateFirst!=((i&1)!=0)||!faster(p,95))return false;
            qualificationExtra+=p.extraNanos;
        }
        // All three qualification pairs belong to one job. A later cached-job recheck does not.
        if(qualificationExtra>EXTRA_CAP_NANOS)return false;
        return qualifiedMedians(seed.qualification)&&(seed.recheck==null||(validPair(seed.recheck,seed.workers)&&faster(seed.recheck,95)));
    }
    private static String safeReason(String value,String fallback){
        if(value==null)return fallback;
        switch(value){
            case "invalid-nomination":case "unfinished-pair":case "invalid-plan":case "memory-ineligible":
            case "short-job":case "probe-budget":case "missed-qualification":case "payback-unavailable":
            case "short-renewal":case "invalid-pair":case "pair-regression":case "invalid-pair-order":
            case "median-regression":case "invalid-timing":case "probe-aborted":case "external-baseline":
            case "cancelled":case "memory-fallback":case "thermal-guard":case "output-mismatch":
            case "memory-pressure":case "screen-budget":case "screen-no-win":
            case "runtime-rejected":case "unknown-work":
                return value;
            default:return fallback;
        }
    }
    private static String record(String role,int index,Pair p){
        return "schema=native-passage-pair-v1 role="+role+" index="+index+" ordinal="+p.ordinal
            +" candidateFirst="+p.candidateFirst+" workers="+p.candidateWorkers+" baselineNanos="+p.baselineNanos
            +" candidateNanos="+p.candidateNanos+" extraNanos="+p.extraNanos+" outputSha256="+p.outputSha256
            +" finite="+p.finite+" exact="+p.exact+" fullGeometry="+p.fullGeometry+" coldSessions="+p.coldSessions;
    }

    static Seed load(File file,String identity){
        if(!digest(identity))return null;
        try{
            checkPath(file);if(!file.isFile()||file.length()>MAX_BYTES)return null;
            ByteArrayOutputStream bytes=new ByteArrayOutputStream();byte[] buffer=new byte[1024];
            try(InputStream in=new FileInputStream(file)){
                int count;while((count=in.read(buffer))!=-1){if(bytes.size()+count>MAX_BYTES)return null;bytes.write(buffer,0,count);}
            }
            byte[] payload=bytes.toByteArray();if(payload.length<64)return null;
            CRC32 crc=new CRC32();crc.update(payload,8,payload.length-8);
            DataInputStream in=new DataInputStream(new ByteArrayInputStream(payload));
            if(in.readLong()!=crc.getValue()||in.readInt()!=MAGIC||in.readInt()!=SCHEMA)return null;
            String stored=in.readUTF();if(!identity.equals(stored))return null;
            int workers=in.readInt(),count=in.readInt();if(count!=3)return null;
            Pair[] pairs=new Pair[3];for(int i=0;i<3;i++)pairs[i]=readPair(in);
            Pair recheck=in.readBoolean()?readPair(in):null;
            if(in.read()!=-1)return null;
            Seed seed=new Seed(identity,workers,pairs,recheck);return validSeed(seed)?seed:null;
        }catch(IOException|RuntimeException invalid){return null;}
    }
    static void save(File file,String identity,Seed seed)throws IOException{
        if(!digest(identity)||!validSeed(seed)||!identity.equals(seed.identity))throw new IOException("Unqualified passage policy cannot be saved.");
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();DataOutputStream out=new DataOutputStream(bytes);
        out.writeLong(0);out.writeInt(MAGIC);out.writeInt(SCHEMA);out.writeUTF(identity);out.writeInt(seed.workers);out.writeInt(3);
        for(Pair pair:seed.qualification)writePair(out,pair);
        out.writeBoolean(seed.recheck!=null);if(seed.recheck!=null)writePair(out,seed.recheck);out.flush();
        byte[] payload=bytes.toByteArray();if(payload.length>MAX_BYTES)throw new IOException("Passage policy exceeds its storage limit.");
        CRC32 crc=new CRC32();crc.update(payload,8,payload.length-8);long checksum=crc.getValue();
        for(int i=7;i>=0;i--){payload[i]=(byte)checksum;checksum>>>=8;}
        File parent=file.getAbsoluteFile().getParentFile();
        if(!parent.isDirectory()&&!parent.mkdirs())throw new IOException("Passage policy storage unavailable.");
        File temporary=new File(file.getPath()+".tmp");checkPath(file);checkPath(temporary);
        try{
            try(FileOutputStream stream=new FileOutputStream(temporary)){stream.write(payload);stream.getFD().sync();}
            Files.move(temporary.toPath(),file.toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
        }finally{Files.deleteIfExists(temporary.toPath());}
    }
    private static void checkPath(File file)throws IOException{
        if(Files.isSymbolicLink(file.toPath())||(file.exists()&&!file.isFile()))throw new IOException("Unexpected passage policy entry.");
    }
    private static void writePair(DataOutputStream out,Pair p)throws IOException{
        out.writeInt(p.ordinal);out.writeBoolean(p.candidateFirst);out.writeLong(p.baselineNanos);out.writeLong(p.candidateNanos);
        out.writeLong(p.extraNanos);out.writeUTF(p.outputSha256);out.writeBoolean(p.finite);out.writeBoolean(p.exact);
        out.writeBoolean(p.fullGeometry);out.writeBoolean(p.coldSessions);out.writeInt(p.candidateWorkers);
    }
    private static Pair readPair(DataInputStream in)throws IOException{
        return new Pair(in.readInt(),in.readBoolean(),in.readLong(),in.readLong(),in.readLong(),in.readUTF(),
            in.readBoolean(),in.readBoolean(),in.readBoolean(),in.readBoolean(),in.readInt());
    }
}
