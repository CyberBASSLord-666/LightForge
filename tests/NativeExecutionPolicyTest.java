package com.cyberbasslord.lightforge;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.zip.CRC32;

public final class NativeExecutionPolicyTest {
    private static int checks;
    private static void require(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    private static NativeExecutionPolicy.Key key(int cores){return new NativeExecutionPolicy.Key("model-digest-private","runtime-private","os-private","device-private",cores);}
    private static NativeExecutionPolicy.Sample[] samples(long[] base,long[] candidate,boolean exact,boolean finite){
        NativeExecutionPolicy.Sample[] result=new NativeExecutionPolicy.Sample[base.length];
        for(int i=0;i<base.length;i++)result[i]=new NativeExecutionPolicy.Sample(base[i],candidate[i],(i&1)==1,finite,exact);
        return result;
    }
    private static NativeExecutionPolicy.Candidate candidate(NativeExecutionPolicy.Config config,long[] values){return new NativeExecutionPolicy.Candidate(config,samples(new long[]{1000,1000,1000},values,true,true));}
    private static NativeExecutionPolicy.Decision choose(NativeExecutionPolicy.Key key,long[] first,long[] second){
        NativeExecutionPolicy.Config[] c=NativeExecutionPolicy.candidates(key.cores);
        return NativeExecutionPolicy.select(key,new NativeExecutionPolicy.Candidate[]{candidate(c[0],first),candidate(c[1],second)});
    }
    private static NativeExecutionPolicy.Candidate temporalCandidate(NativeExecutionPolicy.Config config,long[] values){
        NativeExecutionPolicy.Sample[] samples=new NativeExecutionPolicy.Sample[values.length];
        for(int i=0;i<values.length;i++)samples[i]=new NativeExecutionPolicy.Sample(1000,values[i],(i&1)==1,true,true,60);
        return new NativeExecutionPolicy.Candidate(config,samples);
    }
    private static NativeExecutionPolicy.Decision temporalChoice(NativeExecutionPolicy.Key key,long memory,long[]... values){
        NativeExecutionPolicy.Config[] configs=NativeExecutionPolicy.temporalCandidates(key,memory);
        NativeExecutionPolicy.Candidate[] trials=new NativeExecutionPolicy.Candidate[values.length];
        for(int i=0;i<trials.length;i++)trials[i]=temporalCandidate(configs[i],values[i]);
        return NativeExecutionPolicy.selectTemporal(key,memory,configs,trials);
    }
    private static void putInt(byte[] bytes,int offset,int value){for(int i=3;i>=0;i--){bytes[offset+i]=(byte)value;value>>>=8;}}
    private static void rewriteChecksum(byte[] payload){CRC32 crc=new CRC32();crc.update(payload,8,payload.length-8);long sum=crc.getValue();for(int i=7;i>=0;i--){payload[i]=(byte)sum;sum>>>=8;}}
    public static void main(String[] args)throws Exception {
        File directory=Files.createTempDirectory("lightforge-policy-").toFile(),file=new File(directory,"policy.bin");
        try{
            NativeExecutionPolicy.Key key=key(4);NativeExecutionPolicy.Config baseline=NativeExecutionPolicy.baseline(8);
            require(baseline.intraThreads==4&&baseline.interThreads==1&&baseline.dynamicBlockBase==0&&!baseline.parallel,"baseline retains existing scheduling");
            require(NativeExecutionPolicy.candidates(1).length==1&&NativeExecutionPolicy.candidates(2).length==1,"deduplicate low-core devices");
            require(NativeExecutionPolicy.candidates(3)[0].intraThreads==3&&NativeExecutionPolicy.candidates(3)[1].intraThreads==2,"cap candidates at actual available cores");
            require(NativeExecutionPolicy.baseline(0).intraThreads==1,"invalid core count stays safe");
            require(NativeExecutionPolicy.candidates(5).length==2&&NativeExecutionPolicy.candidates(6).length==3,"six-thread candidate requires six available cores");
            NativeExecutionPolicy.Config[] high=NativeExecutionPolicy.candidates(8);
            NativeExecutionPolicy.Decision six=NativeExecutionPolicy.select(key(8),new NativeExecutionPolicy.Candidate[]{candidate(high[0],new long[]{1000,1000,1000}),candidate(high[1],new long[]{1000,1000,1000}),candidate(high[2],new long[]{750,750,750})});
            require(six.eligible&&six.config.intraThreads==6,"six threads admitted only through measured exact-output improvement");

            require(baseline.equals(NativeExecutionPolicy.baseline(8))&&baseline.hashCode()==NativeExecutionPolicy.baseline(8).hashCode(),"config value identity");
            require("cpu-i4-j1-d0-sequential".equals(baseline.id()),"bounded diagnostic config identity");
            require(!NativeExecutionPolicy.load(file,key).complete(),"missing file is an unmeasured baseline");
            NativeExecutionPolicy.Decision good=choose(key,new long[]{900,900,900},new long[]{850,850,850});
            require(good.complete&&good.eligible&&good.config.intraThreads==2,"best consistent >=10 percent gain selected");
            require(good.pairCount==3&&good.baselineMedianNanos==1000&&good.candidateMedianNanos==850,"observed decision evidence retained");
            NativeExecutionPolicy.Decision boundary=choose(key,new long[]{950,900,900},new long[]{1000,1000,1000});
            require(boundary.eligible&&boundary.candidateMedianNanos==900,"10 percent median and 5 percent every pair are inclusive");
            NativeExecutionPolicy.Decision noisy=choose(key,new long[]{951,800,800},new long[]{901,901,901});
            require(noisy.complete&&!noisy.eligible&&noisy.config.equals(baseline),"one weak pair or insufficient median gain retains baseline");
            NativeExecutionPolicy.Config[] candidates=NativeExecutionPolicy.candidates(4);
            for(boolean nonfinite:new boolean[]{false,true}){
                NativeExecutionPolicy.Candidate bad=new NativeExecutionPolicy.Candidate(candidates[0],samples(new long[]{1000,1000,1000},new long[]{1,1,1},nonfinite,!nonfinite));
                NativeExecutionPolicy.Decision rejected=NativeExecutionPolicy.select(key,new NativeExecutionPolicy.Candidate[]{bad,candidate(candidates[1],new long[]{1000,1000,1000})});
                require(rejected.complete&&!rejected.eligible,"nonfinite or nonidentical output is never selected");
            }
            NativeExecutionPolicy.Sample[] wrongOrder=samples(new long[]{1000,1000,1000},new long[]{500,500,500},true,true);
            wrongOrder[1]=new NativeExecutionPolicy.Sample(1000,500,false,true,true);
            require(!NativeExecutionPolicy.select(key,new NativeExecutionPolicy.Candidate[]{new NativeExecutionPolicy.Candidate(candidates[0],wrongOrder),candidate(candidates[1],new long[]{500,500,500})}).complete,"nonalternating comparisons are not cacheable");
            require(!NativeExecutionPolicy.select(key,new NativeExecutionPolicy.Candidate[]{candidate(candidates[0],new long[]{500,500,500})}).complete,"partial shortlist cannot publish a cache");
            NativeExecutionPolicy.Candidate one=candidate(candidates[0],new long[]{500,500,500});
            require(!NativeExecutionPolicy.select(key,new NativeExecutionPolicy.Candidate[]{one,one}).complete,"duplicate candidate cannot fake shortlist completion");
            NativeExecutionPolicy.Sample[] shortTrials=samples(new long[]{1000,1000},new long[]{1,1},true,true);
            require(!NativeExecutionPolicy.select(key,new NativeExecutionPolicy.Candidate[]{new NativeExecutionPolicy.Candidate(candidates[0],shortTrials),candidate(candidates[1],new long[]{500,500,500})}).complete,"fewer than three pairs rejected");
            NativeExecutionPolicy.Sample[] invalid=samples(new long[]{1000,0,1000},new long[]{1,1,1},true,true);
            require(!NativeExecutionPolicy.select(key,new NativeExecutionPolicy.Candidate[]{new NativeExecutionPolicy.Candidate(candidates[0],invalid),candidate(candidates[1],new long[]{500,500,500})}).complete,"invalid clock sample rejected");
            long fourMemory=NativeExecutionPolicy.FOUR_WORKER_HEADROOM,eightMemory=NativeExecutionPolicy.EIGHT_WORKER_HEADROOM;
            require(baseline.temporalWorkers==1&&baseline.timeBatch==4,"baseline preserves original B4 geometry");
            require(NativeExecutionPolicy.temporalCandidates(key(3),Long.MAX_VALUE).length==0,"fewer than four cores never use outer parallelism");
            require(NativeExecutionPolicy.temporalCandidates(key(8),-1).length==0,"unknown memory defaults to original geometry");
            require(NativeExecutionPolicy.temporalCandidates(key(8),fourMemory-1).length==0,"four workers require their full headroom");
            NativeExecutionPolicy.Config[] fourOnly=NativeExecutionPolicy.temporalCandidates(key(8),fourMemory);
            require(fourOnly.length==1&&fourOnly[0].temporalWorkers==4,"memory-limited shortlist keeps four workers");
            require(NativeExecutionPolicy.temporalCandidates(key(7),eightMemory).length==1,"eight workers require eight available cores");
            NativeExecutionPolicy.Config[] both=NativeExecutionPolicy.temporalCandidates(key(8),eightMemory);
            require(both.length==2&&both[1].temporalWorkers==8&&both[1].intraThreads==1&&both[1].interThreads==1&&both[1].dynamicBlockBase==0&&!both[1].parallel&&both[1].timeBatch==1,"parallel geometry has no nested thread pools or altered ONNX execution mode");
            require("cpu-i1-j1-d0-sequential-w8-b1".equals(both[1].id()),"parallel diagnostic config identifies complete geometry");
            for(int workers:new int[]{4,8}){
                NativeExecutionPolicy.Config frequency=NativeExecutionPolicy.parallelFrequency(workers);
                require(frequency.intraThreads==1&&frequency.interThreads==1&&frequency.dynamicBlockBase==0&&!frequency.parallel
                    &&frequency.temporalWorkers==workers&&frequency.timeBatch==16,"frequency companion uses B16 independent frame batches without nested pools");
                require(("cpu-i1-j1-d0-sequential-w"+workers+"-b16").equals(frequency.id()),"frequency profile identifies both worker count and frame batch");
                require(frequency.equals(NativeExecutionPolicy.parallelFrequency(workers))&&frequency.hashCode()==NativeExecutionPolicy.parallelFrequency(workers).hashCode(),"frequency config retains value identity");
                require(!frequency.equals(both[workers==4?0:1]),"frequency companion cannot alias B1 temporal geometry");
                require(!NativeExecutionPolicy.temporalAllowed(frequency,key(8),Long.MAX_VALUE),"factory does not bypass temporal admission or expand the existing temporal shortlist");
                require(!NativeExecutionPolicy.select(key,new NativeExecutionPolicy.Candidate[]{candidate(frequency,new long[]{500,500,500}),candidate(candidates[1],new long[]{500,500,500})}).complete,"legacy warmed frequency evidence cannot authorize the complete-passage companion");
            }
            for(int workers:new int[]{Integer.MIN_VALUE,-1,0,1,2,3,5,6,7,9,Integer.MAX_VALUE}){
                try{NativeExecutionPolicy.parallelFrequency(workers);throw new AssertionError("unsupported frequency worker geometry accepted");}
                catch(IllegalArgumentException expected){checks++;}
            }
            require(!both[0].equals(both[1])&&both[0].hashCode()!=both[1].hashCode(),"outer-worker geometry participates in config identity");
            require(!NativeExecutionPolicy.temporalAllowed(both[1],key(8),eightMemory-1),"cached eight-worker config rejected when memory falls");
            require(NativeExecutionPolicy.temporalAllowed(both[0],key(8),eightMemory),"qualified four-worker config remains safe with extra headroom");
            require(!NativeExecutionPolicy.temporalAllowed(candidates[0],key,Long.MAX_VALUE),"frequency config cannot enter temporal execution");
            require(NativeExecutionPolicy.temporalAllowed(baseline,key,0),"original geometry remains available under low memory");
            require(!NativeExecutionPolicy.retainedTemporal(key).complete,"temporary memory shortage is never cached as final baseline");
            NativeExecutionPolicy.Decision lowCore=NativeExecutionPolicy.retainedTemporal(key(2));
            require(lowCore.complete&&!lowCore.eligible&&lowCore.pairCount==0&&"insufficient-cores".equals(lowCore.reason),"immutable low-core limitation can be cached without fake trials");
            require(!NativeExecutionPolicy.defaults(key(2)).temporal.complete,"a low-core cache miss still differs from a completed decision");
            NativeExecutionPolicy.Decision temporal=temporalChoice(key,fourMemory,new long[]{800,800,800});
            require(temporal.complete&&temporal.eligible&&temporal.config.temporalWorkers==4,"full sixty-band exact trials admit a consistent candidate");
            NativeExecutionPolicy.Decision eight=temporalChoice(key(8),eightMemory,new long[]{850,850,850},new long[]{700,700,700});
            require(eight.eligible&&eight.config.temporalWorkers==8,"best complete memory-eligible geometry selected");
            NativeExecutionPolicy.Decision fourWins=temporalChoice(key(8),eightMemory,new long[]{700,700,700},new long[]{850,850,850});
            require(fourWins.config.temporalWorkers==4,"more workers cannot bypass measurement when four are faster");
            require(!NativeExecutionPolicy.selectTemporal(key(8),eightMemory,fourOnly,new NativeExecutionPolicy.Candidate[]{temporalCandidate(fourOnly[0],new long[]{500,500,500})}).complete,"memory snapshot prevents silently omitting an eligible configuration");
            require(!NativeExecutionPolicy.selectTemporal(key(8),fourMemory,both,new NativeExecutionPolicy.Candidate[]{temporalCandidate(both[0],new long[]{500,500,500}),temporalCandidate(both[1],new long[]{500,500,500})}).complete,"extra geometry above the measured memory budget rejected");
            require(!NativeExecutionPolicy.selectTemporal(key,fourMemory,NativeExecutionPolicy.temporalCandidates(key,fourMemory),new NativeExecutionPolicy.Candidate[]{candidate(temporal.config,new long[]{500,500,500})}).complete,"per-batch or missing sixty-band evidence cannot qualify temporal scheduling");
            NativeExecutionPolicy.Sample[] partialBand=new NativeExecutionPolicy.Sample[3];
            for(int i=0;i<3;i++)partialBand[i]=new NativeExecutionPolicy.Sample(1000,500,(i&1)==1,true,true,i==1?59:60);
            require(!NativeExecutionPolicy.selectTemporal(key,fourMemory,NativeExecutionPolicy.temporalCandidates(key,fourMemory),new NativeExecutionPolicy.Candidate[]{new NativeExecutionPolicy.Candidate(temporal.config,partialBand)}).complete,"each trial needs all sixty bands");
            for(boolean exact:new boolean[]{false,true}){
                NativeExecutionPolicy.Sample[] badOutputs=new NativeExecutionPolicy.Sample[3];
                for(int i=0;i<3;i++)badOutputs[i]=new NativeExecutionPolicy.Sample(1000,100,(i&1)==1,!exact,exact,60);
                NativeExecutionPolicy.Decision rejected=NativeExecutionPolicy.selectTemporal(key,fourMemory,NativeExecutionPolicy.temporalCandidates(key,fourMemory),new NativeExecutionPolicy.Candidate[]{new NativeExecutionPolicy.Candidate(temporal.config,badOutputs)});
                require(rejected.complete&&!rejected.eligible,"nonfinite or changed complete temporal output cannot qualify");
            }
            NativeExecutionPolicy.Decision temporalNoisy=temporalChoice(key,fourMemory,new long[]{951,700,700});
            require(temporalNoisy.complete&&!temporalNoisy.eligible&&temporalNoisy.config.temporalWorkers==1,"one weak temporal pair retains original geometry");
            NativeExecutionPolicy.Calibration valid=new NativeExecutionPolicy.Calibration(temporal,noisy);
            NativeExecutionPolicy.save(file,key,valid);byte[] original=Files.readAllBytes(file.toPath());
            require(original.length<NativeExecutionPolicy.MAX_BYTES,"bounded persisted record");
            String serialized=new String(original,StandardCharsets.ISO_8859_1);
            require(!serialized.contains("private")&&!serialized.contains("device")&&!serialized.contains("model"),"raw identifying strings absent from storage");
            NativeExecutionPolicy.Calibration loaded=NativeExecutionPolicy.load(file,key);
            require(loaded.complete()&&loaded.temporal.config.equals(temporal.config)&&loaded.frequency.config.equals(baseline),"independent family decisions survive restart");
            require(loaded.temporal.eligible&&!loaded.frequency.eligible,"completed baseline outcome distinguishable from cache miss");
            require(!NativeExecutionPolicy.load(file,key(8)).complete(),"available core change invalidates cache");
            require(!NativeExecutionPolicy.load(file,new NativeExecutionPolicy.Key("changed","runtime-private","os-private","device-private",4)).complete(),"model change invalidates cache");
            require(!NativeExecutionPolicy.load(file,new NativeExecutionPolicy.Key("model-digest-private","changed","os-private","device-private",4)).complete(),"runtime change invalidates cache");
            require(!NativeExecutionPolicy.load(file,new NativeExecutionPolicy.Key("model-digest-private","runtime-private","changed","device-private",4)).complete(),"OS change invalidates cache");
            require(!NativeExecutionPolicy.load(file,new NativeExecutionPolicy.Key("model-digest-private","runtime-private","os-private","changed",4)).complete(),"device change invalidates cache");
            try{NativeExecutionPolicy.save(file,key,new NativeExecutionPolicy.Calibration(temporal,NativeExecutionPolicy.defaults(key).frequency));throw new AssertionError("partial cache persisted");}
            catch(IOException expected){checks++;}
            require(Arrays.equals(original,Files.readAllBytes(file.toPath())),"incomplete calibration preserves committed cache");
            Files.write(new File(file.getPath()+".tmp").toPath(),new byte[]{1,2,3});
            require(NativeExecutionPolicy.load(file,key).complete(),"uncommitted temporary data does not replace committed decision");
            byte[] corrupt=original.clone();corrupt[corrupt.length-1]^=1;Files.write(file.toPath(),corrupt);
            require(!NativeExecutionPolicy.load(file,key).complete(),"checksum failure defaults safely");
            byte[] unapproved=original.clone();putInt(unapproved,61,64);rewriteChecksum(unapproved);Files.write(file.toPath(),unapproved);
            require(!NativeExecutionPolicy.load(file,key).complete(),"unknown config rejected even with valid checksum");
            byte[] wrongFamily=original.clone();wrongFamily[48]=0;rewriteChecksum(wrongFamily);Files.write(file.toPath(),wrongFamily);
            require(!NativeExecutionPolicy.load(file,key).complete(),"cache family cannot be changed even with valid checksum");
            byte[] wrongBatch=original.clone();putInt(wrongBatch,78,4);rewriteChecksum(wrongBatch);Files.write(file.toPath(),wrongBatch);
            require(!NativeExecutionPolicy.load(file,key).complete(),"unqualified temporal geometry cannot be loaded");
            byte[] missingBands=original.clone();putInt(missingBands,105,4);rewriteChecksum(missingBands);Files.write(file.toPath(),missingBands);
            require(!NativeExecutionPolicy.load(file,key).complete(),"reload revalidates complete sixty-band evidence");
            byte[] weakPair=original.clone();putInt(weakPair,98,951);rewriteChecksum(weakPair);Files.write(file.toPath(),weakPair);
            NativeExecutionPolicy.Calibration reconsidered=NativeExecutionPolicy.load(file,key);
            require(reconsidered.complete()&&!reconsidered.temporal.eligible&&reconsidered.temporal.config.equals(baseline),"reload recomputes every-pair floor rather than trusting cached winner");
            try{NativeExecutionPolicy.save(file,key,new NativeExecutionPolicy.Calibration(good,noisy));throw new AssertionError("frequency decision entered temporal cache");}
            catch(IOException expected){checks++;}
            try{NativeExecutionPolicy.save(file,key,new NativeExecutionPolicy.Calibration(temporal,temporal));throw new AssertionError("temporal decision entered frequency cache");}
            catch(IOException expected){checks++;}
            byte[] forged=original.clone();forged[13]=1;rewriteChecksum(forged);Files.write(file.toPath(),forged);
            require(!NativeExecutionPolicy.load(file,key).complete(),"unknown schema defaults safely");
            Files.write(file.toPath(),new byte[NativeExecutionPolicy.MAX_BYTES+1]);
            require(!NativeExecutionPolicy.load(file,key).complete(),"oversized input is not parsed");
            Files.write(file.toPath(),Arrays.copyOf(original,50));
            require(!NativeExecutionPolicy.load(file,key).complete(),"truncated input defaults safely");
            NativeExecutionPolicy.save(file,key,valid);
            require(NativeExecutionPolicy.load(file,key).complete()&&!new File(file.getPath()+".tmp").exists(),"atomic replacement restores valid cache and removes temporary");
            NativeExecutionPolicy.Key small=key(2);
            NativeExecutionPolicy.Decision smallFrequency=NativeExecutionPolicy.select(small,new NativeExecutionPolicy.Candidate[]{candidate(NativeExecutionPolicy.candidates(2)[0],new long[]{1000,1000,1000})});
            NativeExecutionPolicy.save(file,small,new NativeExecutionPolicy.Calibration(lowCore,smallFrequency));
            NativeExecutionPolicy.Calibration lowCoreLoaded=NativeExecutionPolicy.load(file,small);
            require(lowCoreLoaded.complete()&&lowCoreLoaded.temporal.pairCount==0&&!lowCoreLoaded.temporal.eligible,"low-core frequency calibration persists without synthetic temporal trials");
            require(!NativeExecutionPolicy.load(file,key).complete(),"low-core capability cache cannot transfer to four cores");
            NativeExecutionPolicy.save(file,key(8),new NativeExecutionPolicy.Calibration(eight,six));
            NativeExecutionPolicy.Calibration allLoaded=NativeExecutionPolicy.load(file,key(8));
            require(allLoaded.complete()&&allLoaded.temporal.config.temporalWorkers==8&&allLoaded.frequency.config.intraThreads==6,"full dual geometry and frequency shortlist evidence survives restart");
            require(Files.size(file.toPath())<NativeExecutionPolicy.MAX_BYTES,"all candidate evidence remains bounded");
            require(!NativeExecutionPolicy.temporalNeedsExpansion(allLoaded.temporal,key(8),Long.MAX_VALUE),"full measured shortlist never repeats calibration for higher memory");
            require(!NativeExecutionPolicy.temporalNeedsExpansion(allLoaded.temporal,key(8),fourMemory),"falling headroom never requires shortlist expansion");
            for(long[] result:new long[][]{new long[]{800,800,800},new long[]{1000,1000,1000}}){
                NativeExecutionPolicy.Decision restricted=temporalChoice(key(8),fourMemory,result);
                NativeExecutionPolicy.save(file,key(8),new NativeExecutionPolicy.Calibration(restricted,six));
                NativeExecutionPolicy.Decision cached=NativeExecutionPolicy.load(file,key(8)).temporal;
                require(cached.complete,"memory-restricted measured result reloads");
                require(NativeExecutionPolicy.temporalNeedsExpansion(cached,key(8),eightMemory),"winning or baseline four-only cache expands when eight workers become affordable");
                require(!NativeExecutionPolicy.temporalNeedsExpansion(cached,key(8),eightMemory-1),"unchanged eligible shortlist does not repeat calibration");
                require(!NativeExecutionPolicy.temporalNeedsExpansion(cached,key(8),fourMemory-1),"less memory does not expand the shortlist");
                require(cached.pairCount==3,"expansion request does not manufacture new measurements");
            }
            require(!NativeExecutionPolicy.temporalNeedsExpansion(temporal,key,Long.MAX_VALUE),"four-core device has no additional geometry to qualify");
            require(!NativeExecutionPolicy.temporalNeedsExpansion(lowCoreLoaded.temporal,small,Long.MAX_VALUE),"immutable low-core capability does not need expansion");
            require(!NativeExecutionPolicy.temporalNeedsExpansion(NativeExecutionPolicy.defaults(key(8)).temporal,key(8),Long.MAX_VALUE),"unmeasured decisions remain in the original calibration flow");
            require(!NativeExecutionPolicy.temporalNeedsExpansion(six,key(8),Long.MAX_VALUE),"frequency decisions cannot request temporal expansion");
            System.out.println("PASS: "+checks+" bounded native execution policy checks");
        }finally{
            for(File child:directory.listFiles())Files.deleteIfExists(child.toPath());Files.deleteIfExists(directory.toPath());
        }
    }
}
