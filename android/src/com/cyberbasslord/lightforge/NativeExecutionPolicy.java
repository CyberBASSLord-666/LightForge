package com.cyberbasslord.lightforge;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.zip.CRC32;

/** Bounded CPU scheduling decisions. This class never runs inference or handles model tensors. */
final class NativeExecutionPolicy {
    static final int MIN_PAIRS=3, MAX_PAIRS=8, MAX_BYTES=8192, TEMPORAL_BANDS=60;
    // The caller subtracts its app reserve and the platform low-memory threshold first.
    static final long FOUR_WORKER_HEADROOM=1536L*1024*1024, EIGHT_WORKER_HEADROOM=2048L*1024*1024;
    private static final int MAGIC=0x4c465031, SCHEMA=2;
    private static final long MAX_TRIAL_NANOS=3600000000000L;
    private NativeExecutionPolicy() {}

    static final class Config {
        final int intraThreads,interThreads,dynamicBlockBase,temporalWorkers,timeBatch;
        final boolean parallel;
        private Config(int intra,int inter,int block,boolean parallel,int workers,int batch){
            intraThreads=intra;interThreads=inter;dynamicBlockBase=block;this.parallel=parallel;temporalWorkers=workers;timeBatch=batch;
        }
        @Override public boolean equals(Object other){
            if(!(other instanceof Config))return false;Config c=(Config)other;
            return intraThreads==c.intraThreads&&interThreads==c.interThreads&&dynamicBlockBase==c.dynamicBlockBase&&parallel==c.parallel&&temporalWorkers==c.temporalWorkers&&timeBatch==c.timeBatch;
        }
        @Override public int hashCode(){return ((((intraThreads*31+interThreads)*31+dynamicBlockBase)*31+(parallel?1:0))*31+temporalWorkers)*31+timeBatch;}
        String id(){return "cpu-i"+intraThreads+"-j"+interThreads+"-d"+dynamicBlockBase+(parallel?"-parallel":"-sequential")+(temporalWorkers==1?"":"-w"+temporalWorkers+"-b"+timeBatch);}
    }
    static Config baseline(int cores){return new Config(Math.max(1,Math.min(4,cores)),1,0,false,1,4);}
    static Config[] candidates(int cores){
        Config four=new Config(baseline(cores).intraThreads,1,4,false,1,4),two=new Config(Math.max(1,Math.min(2,cores)),1,4,false,1,4);
        if(cores>=6)return new Config[]{four,two,new Config(6,1,4,false,1,4)};
        return four.equals(two)?new Config[]{four}:new Config[]{four,two};
    }
    private static Config temporalConfig(int workers){return new Config(1,1,0,false,workers,1);}
    /** Include every geometry allowed by the observed free-memory snapshot, in stable order. */
    static Config[] temporalCandidates(Key key,long availableBytes){
        if(key.cores<4||availableBytes<FOUR_WORKER_HEADROOM)return new Config[0];
        if(key.cores>=8&&availableBytes>=EIGHT_WORKER_HEADROOM)return new Config[]{temporalConfig(4),temporalConfig(8)};
        return new Config[]{temporalConfig(4)};
    }
    /** Cached candidates still require a fresh memory check before every graph. */
    static boolean temporalAllowed(Config config,Key key,long availableBytes){
        return baseline(key.cores).equals(config)||index(temporalCandidates(key,availableBytes),config)>=0;
    }
    /** A memory-limited cache remains safe, but must be expanded when a new geometry becomes affordable. */
    static boolean temporalNeedsExpansion(Decision decision,Key key,long availableBytes){
        if(decision==null||!decision.complete||!decision.temporalFamily||key.cores<4)return false;
        for(Config allowed:temporalCandidates(key,availableBytes)){
            boolean measured=false;
            if(decision.trials!=null)for(Candidate trial:decision.trials)if(allowed.equals(trial.config)){measured=true;break;}
            if(!measured)return true;
        }
        return false;
    }
    /** Identity is retained only as a digest; no raw device, OS, model or runtime string is saved. */
    static final class Key {
        final int cores;
        private final byte[] fingerprint;
        Key(String modelId,String runtimeId,String osIdentity,String deviceIdentity,int cores){
            this.cores=Math.max(1,cores);
            try{
                ByteArrayOutputStream bytes=new ByteArrayOutputStream();DataOutputStream out=new DataOutputStream(bytes);
                out.writeInt(SCHEMA);out.writeInt(this.cores);
                for(String value:new String[]{modelId,runtimeId,osIdentity,deviceIdentity}){
                    if(value==null||value.isEmpty()||value.length()>4096)throw new IllegalArgumentException("Missing or oversized execution identity.");
                    byte[] encoded=value.getBytes(StandardCharsets.UTF_8);out.writeInt(encoded.length);out.write(encoded);
                }
                out.flush();fingerprint=MessageDigest.getInstance("SHA-256").digest(bytes.toByteArray());
            }catch(IOException|java.security.NoSuchAlgorithmException impossible){throw new AssertionError(impossible);}
        }
    }
    static final class Sample {
        final long baselineNanos,candidateNanos;
        final boolean candidateFirst,finite,exact;
        final int temporalBands;
        Sample(long baselineNanos,long candidateNanos,boolean candidateFirst,boolean finite,boolean exact){this(baselineNanos,candidateNanos,candidateFirst,finite,exact,0);}
        Sample(long baselineNanos,long candidateNanos,boolean candidateFirst,boolean finite,boolean exact,int temporalBands){
            this.baselineNanos=baselineNanos;this.candidateNanos=candidateNanos;this.candidateFirst=candidateFirst;this.finite=finite;this.exact=exact;this.temporalBands=temporalBands;
        }
    }
    static final class Candidate {
        final Config config;
        private final Sample[] samples;
        Candidate(Config config,Sample[] samples){this.config=config;this.samples=samples==null?null:samples.clone();}
    }
    static final class Decision {
        final Config config;
        final boolean complete,eligible;
        final int pairCount;
        final long baselineMedianNanos,candidateMedianNanos;
        final String reason;
        private final boolean temporalFamily;
        private final long availableBytes;
        private final Candidate[] trials;
        private Decision(Config config,boolean complete,boolean eligible,int pairs,long baseline,long candidate,String reason,boolean temporal,long availableBytes,Candidate[] trials){
            this.config=config;this.complete=complete;this.eligible=eligible;pairCount=pairs;baselineMedianNanos=baseline;candidateMedianNanos=candidate;this.reason=reason;
            temporalFamily=temporal;this.availableBytes=availableBytes;this.trials=trials==null?null:trials.clone();
        }
    }
    static final class Calibration {
        final Decision temporal,frequency;
        Calibration(Decision temporal,Decision frequency){if(temporal==null||frequency==null)throw new IllegalArgumentException("Missing family decision.");this.temporal=temporal;this.frequency=frequency;}
        boolean complete(){return temporal.complete&&frequency.complete;}
    }
    static Calibration defaults(Key key){return new Calibration(unmeasured(key.cores,true),unmeasured(key.cores,false));}
    private static Decision unmeasured(int cores,boolean temporal){return new Decision(baseline(cores),false,false,0,0,0,"unmeasured",temporal,0,null);}
    /** Only immutable CPU incapability is cacheable without trials; temporary low memory is not. */
    static Decision retainedTemporal(Key key){
        return key.cores<4?new Decision(baseline(key.cores),true,false,0,0,0,"insufficient-cores",true,0,new Candidate[0]):unmeasured(key.cores,true);
    }

    /** Existing frequency shortlist: all configurations need complete alternating trials. */
    static Decision select(Key key,Candidate[] trials){return selectFrom(key,candidates(key.cores),trials,false,0);}
    /** Memory is part of shortlist evidence, so callers cannot silently omit an eligible candidate. */
    static Decision selectTemporal(Key key,long availableBytes,Config[] shortlist,Candidate[] trials){
        Config[] allowed=temporalCandidates(key,availableBytes);
        if(allowed.length==0||!sameSet(allowed,shortlist))return retainedTemporal(key);
        return selectFrom(key,allowed,trials,true,availableBytes);
    }
    private static Decision selectFrom(Key key,Config[] allowed,Candidate[] trials,boolean temporal,long availableBytes){
        if(trials==null||trials.length!=allowed.length)return unmeasured(key.cores,temporal);
        boolean[] seen=new boolean[allowed.length];Config best=null;int pairs=MAX_PAIRS,bestPairs=0;
        long baseMedian=0,candidateMedian=0,bestBase=0,bestCandidate=0;
        for(Candidate trial:trials){
            if(trial==null||trial.config==null)return unmeasured(key.cores,temporal);
            int index=index(allowed,trial.config);
            if(index<0||seen[index]||!validSamples(trial.samples,temporal))return unmeasured(key.cores,temporal);
            seen[index]=true;int count=trial.samples.length;pairs=Math.min(pairs,count);
            long[] baseline=new long[count],candidate=new long[count];boolean eligible=true;
            for(int i=0;i<count;i++){
                Sample sample=trial.samples[i];baseline[i]=sample.baselineNanos;candidate[i]=sample.candidateNanos;
                if(!sample.finite||!sample.exact||!atMost(sample.candidateNanos,sample.baselineNanos,95))eligible=false;
            }
            long bm=median(baseline),cm=median(candidate);baseMedian=bm;candidateMedian=cm;
            eligible&=atMost(cm,bm,90);
            if(eligible&&(best==null||(double)cm/bm<(double)bestCandidate/bestBase)){
                best=trial.config;bestPairs=count;bestBase=bm;bestCandidate=cm;
            }
        }
        return best==null?new Decision(baseline(key.cores),true,false,pairs,baseMedian,candidateMedian,"baseline-retained",temporal,availableBytes,trials):
                new Decision(best,true,true,bestPairs,bestBase,bestCandidate,"measured-improvement",temporal,availableBytes,trials);
    }
    private static boolean validSamples(Sample[] samples,boolean temporal){
        if(samples==null||samples.length<MIN_PAIRS||samples.length>MAX_PAIRS)return false;
        for(int i=0;i<samples.length;i++){
            Sample s=samples[i];if(s==null||s.baselineNanos<=0||s.candidateNanos<=0||s.baselineNanos>MAX_TRIAL_NANOS||s.candidateNanos>MAX_TRIAL_NANOS||s.temporalBands!=(temporal?TEMPORAL_BANDS:0))return false;
            if(i>0&&samples[i-1].candidateFirst==s.candidateFirst)return false;
        }
        return true;
    }
    private static boolean atMost(long candidate,long baseline,int percent){return candidate*100<=baseline*percent;}
    private static long median(long[] values){Arrays.sort(values);int middle=values.length/2;return values.length%2==1?values[middle]:values[middle-1]+(values[middle]-values[middle-1])/2;}
    private static int index(Config[] values,Config value){for(int i=0;i<values.length;i++)if(values[i].equals(value))return i;return -1;}
    private static boolean sameSet(Config[] expected,Config[] actual){
        if(actual==null||actual.length!=expected.length)return false;
        boolean[] seen=new boolean[expected.length];for(Config value:actual){int index=index(expected,value);if(index<0||seen[index])return false;seen[index]=true;}return true;
    }

    static Calibration load(File file,Key key){
        try{
            checkPath(file);if(!file.isFile()||file.length()>MAX_BYTES)return defaults(key);
            byte[] bytes=Files.readAllBytes(file.toPath());if(bytes.length<48||bytes.length>MAX_BYTES)return defaults(key);
            CRC32 crc=new CRC32();crc.update(bytes,8,bytes.length-8);DataInputStream in=new DataInputStream(new ByteArrayInputStream(bytes));
            if(in.readLong()!=crc.getValue()||in.readInt()!=MAGIC||in.readInt()!=SCHEMA)return defaults(key);
            byte[] digest=new byte[32];in.readFully(digest);if(!MessageDigest.isEqual(digest,key.fingerprint))return defaults(key);
            Calibration result=new Calibration(readDecision(in,key,true),readDecision(in,key,false));
            return in.read()==-1&&result.complete()?result:defaults(key);
        }catch(IOException|RuntimeException invalid){return defaults(key);}
    }
    static void save(File file,Key key,Calibration value)throws IOException {
        if(value==null||!value.complete())throw new IOException("Incomplete execution calibration cannot be saved.");
        validateDecision(value.temporal,key,true);validateDecision(value.frequency,key,false);
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();DataOutputStream out=new DataOutputStream(bytes);
        out.writeLong(0);out.writeInt(MAGIC);out.writeInt(SCHEMA);out.write(key.fingerprint);
        writeDecision(out,value.temporal);writeDecision(out,value.frequency);out.flush();byte[] payload=bytes.toByteArray();
        if(payload.length>=MAX_BYTES)throw new IOException("Execution calibration exceeded storage limit.");
        CRC32 crc=new CRC32();crc.update(payload,8,payload.length-8);long checksum=crc.getValue();for(int i=7;i>=0;i--){payload[i]=(byte)checksum;checksum>>>=8;}
        File parent=file.getAbsoluteFile().getParentFile();if(!parent.isDirectory()&&!parent.mkdirs())throw new IOException("Execution calibration storage unavailable.");
        File temporary=new File(file.getPath()+".tmp");checkPath(file);checkPath(temporary);
        try{
            try(FileOutputStream stream=new FileOutputStream(temporary)){stream.write(payload);stream.getFD().sync();}
            Files.move(temporary.toPath(),file.toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
        }finally{Files.deleteIfExists(temporary.toPath());}
    }
    private static void checkPath(File file)throws IOException{if(Files.isSymbolicLink(file.toPath())||(file.exists()&&!file.isFile()))throw new IOException("Unexpected execution calibration entry.");}
    /** Retain bounded raw pair evidence rather than trusting only the winning median on reload. */
    private static void writeDecision(DataOutputStream out,Decision d)throws IOException{
        out.writeBoolean(d.temporalFamily);out.writeLong(d.availableBytes);out.writeInt(d.trials.length);
        for(Candidate trial:d.trials){
            Config c=trial.config;out.writeInt(c.intraThreads);out.writeInt(c.interThreads);out.writeInt(c.dynamicBlockBase);out.writeBoolean(c.parallel);out.writeInt(c.temporalWorkers);out.writeInt(c.timeBatch);
            out.writeInt(trial.samples.length);
            for(Sample s:trial.samples){out.writeLong(s.baselineNanos);out.writeLong(s.candidateNanos);out.writeBoolean(s.candidateFirst);out.writeBoolean(s.finite);out.writeBoolean(s.exact);out.writeInt(s.temporalBands);}
        }
    }
    private static Decision readDecision(DataInputStream in,Key key,boolean temporal)throws IOException{
        if(in.readBoolean()!=temporal)throw new IOException("Mismatched execution family.");
        long availableBytes=in.readLong();int count=in.readInt();
        Config[] expected=temporal?temporalCandidates(key,availableBytes):candidates(key.cores);
        if(temporal&&key.cores<4&&availableBytes==0&&count==0)return retainedTemporal(key);
        if((!temporal&&availableBytes!=0)||count==0||count!=expected.length)throw new IOException("Incomplete execution shortlist.");
        Candidate[] trials=new Candidate[count];
        for(int i=0;i<count;i++){
            Config config=new Config(in.readInt(),in.readInt(),in.readInt(),in.readBoolean(),in.readInt(),in.readInt());
            int pairCount=in.readInt();if(pairCount<MIN_PAIRS||pairCount>MAX_PAIRS)throw new IOException("Invalid execution pair count.");
            Sample[] samples=new Sample[pairCount];for(int j=0;j<pairCount;j++)samples[j]=new Sample(in.readLong(),in.readLong(),in.readBoolean(),in.readBoolean(),in.readBoolean(),in.readInt());
            trials[i]=new Candidate(config,samples);
        }
        Decision result=selectFrom(key,expected,trials,temporal,availableBytes);validateDecision(result,key,temporal);return result;
    }
    private static void validateDecision(Decision d,Key key,boolean temporal)throws IOException{
        if(d==null||!d.complete||d.temporalFamily!=temporal)throw new IOException("Invalid execution calibration evidence.");
        if(temporal&&key.cores<4&&d.availableBytes==0&&d.trials!=null&&d.trials.length==0&&!d.eligible&&d.pairCount==0&&d.baselineMedianNanos==0&&d.candidateMedianNanos==0&&d.config.equals(baseline(key.cores)))return;
        Config[] allowed=temporal?temporalCandidates(key,d.availableBytes):candidates(key.cores);
        Decision rebuilt=selectFrom(key,allowed,d.trials,temporal,d.availableBytes);
        if(allowed.length==0||!rebuilt.complete||!rebuilt.config.equals(d.config)||rebuilt.eligible!=d.eligible||rebuilt.pairCount!=d.pairCount||rebuilt.baselineMedianNanos!=d.baselineMedianNanos||rebuilt.candidateMedianNanos!=d.candidateMedianNanos||(!temporal&&d.availableBytes!=0))
            throw new IOException("Unapproved execution scheduling configuration.");
    }
}
