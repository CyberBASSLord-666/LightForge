package com.cyberbasslord.lightforge;

import java.io.*;

/** Streaming stereo conversion with a 48-tap, 1024-phase windowed-sinc filter. */
public final class WavConverter implements Closeable {
    public interface Check { void check() throws IOException; }
    private final Sink audio, analysis;
    private final Resampler full, mono;
    private long sourceFrames;
    private final int sourceRate;
    private boolean finished;

    public WavConverter(File audioFile, File analysisFile, int sourceRate) throws IOException {
        if(sourceRate<8000 || sourceRate>384000) throw new IOException("Unsupported sample rate: "+sourceRate);
        this.sourceRate=sourceRate;
        audio=new Sink(audioFile,44100,2); analysis=new Sink(analysisFile,22050,1);
        full=new Resampler(sourceRate,44100,audio); mono=new Resampler(sourceRate,22050,analysis);
    }
    public void accept(float[] stereo,int frames) throws IOException {
        if(sourceFrames+frames>(long)sourceRate*4*3600) throw new IOException("Tesla shows can be at most four hours long.");
        full.accept(stereo,frames); mono.accept(stereo,frames); sourceFrames+=frames;
    }
    public double finish() throws IOException {
        if(!finished) { full.finish(); mono.finish(); audio.finish(); analysis.finish(); finished=true; }
        return audio.frames/44100.0;
    }
    public void close() throws IOException { audio.close(); analysis.close(); }
    public static void le16(OutputStream out,int v) throws IOException { out.write(v&255);out.write((v>>>8)&255); }
    public static void le32(OutputStream out,long v) throws IOException { le16(out,(int)v);le16(out,(int)(v>>>16)); }
    static int sample(float value) { if(!Float.isFinite(value)) return 0; return Math.max(-32768,Math.min(32767,Math.round(value*32768f))); }

    private static final class Sink implements Closeable {
        final File file; final int rate, channels; final OutputStream out; long frames;
        boolean closed;
        Sink(File f,int rate,int channels) throws IOException {
            this.file=f;this.rate=rate;this.channels=channels;
            out=new BufferedOutputStream(new FileOutputStream(f),131072);
            out.write(new byte[44]);
        }
        void frame(float left,float right) throws IOException {
            if(channels==1) le16(out,sample((left+right)*.5f));
            else { le16(out,sample(left));le16(out,sample(right)); }
            frames++;
        }
        void finish() throws IOException {
            close(); long data=frames*channels*2;
            if(data>0xffffffffL-36) throw new IOException("Audio exceeds the WAV file-size limit.");
            try(RandomAccessFile r=new RandomAccessFile(file,"rw")) {
                ByteArrayOutputStream b=new ByteArrayOutputStream(44);
                b.write(new byte[]{'R','I','F','F'});le32(b,data+36);
                b.write(new byte[]{'W','A','V','E','f','m','t',' '});le32(b,16);
                le16(b,1);le16(b,channels);le32(b,rate);le32(b,(long)rate*channels*2);
                le16(b,channels*2);le16(b,16);b.write(new byte[]{'d','a','t','a'});le32(b,data);
                r.seek(0);r.write(b.toByteArray());r.getFD().sync();
            }
        }
        public void close() throws IOException { if(!closed) {out.close();closed=true;} }
    }
    private static final class Resampler {
        static final int HALF=24,TAPS=48,PHASES=1024,CAP=32768;
        final double ratio; final Sink sink; final boolean direct;
        final float[] left=new float[CAP],right=new float[CAP];
        final float[][] weights; long count, emitted;
        Resampler(int source,int target,Sink sink) {
            ratio=source/(double)target; this.sink=sink;direct=source==target;
            weights=direct?null:new float[PHASES][TAPS];
            if(!direct) {
                double cutoff=Math.min(1,target/(double)source)*.94;
                for(int p=0;p<PHASES;p++) {
                    double sum=0, frac=p/(double)PHASES;
                    for(int k=0;k<TAPS;k++) {
                        double x=k-(HALF-1)-frac;
                        double sinc=Math.abs(x)<1e-12?cutoff:Math.sin(Math.PI*cutoff*x)/(Math.PI*x);
                        double window=.5+.5*Math.cos(Math.PI*x/HALF);
                        weights[p][k]=(float)(sinc*window);sum+=weights[p][k];
                    }
                    for(int k=0;k<TAPS;k++) weights[p][k]/=sum;
                }
            }
        }
        void accept(float[] values,int frames) throws IOException {
            if(direct) {for(int i=0;i<frames;i++) sink.frame(values[i*2],values[i*2+1]);count+=frames;return;}
            for(int offset=0;offset<frames;) {
                int size=Math.min(4096,frames-offset);
                for(int i=0;i<size;i++) {int q=(int)(count%CAP);left[q]=values[(offset+i)*2];right[q]=values[(offset+i)*2+1];count++;}
                emit(false);offset+=size;
            }
        }
        void emit(boolean end) throws IOException {
            long total=Math.round(count/ratio);
            while(true) {
                double pos=emitted*ratio;long center=(long)pos;
                if(end ? emitted>=total : center+HALF>=count) break;
                int phase=Math.min(PHASES-1,(int)((pos-center)*PHASES));
                float l=0,r=0;float[] w=weights[phase];
                for(int k=0;k<TAPS;k++) {
                    long ix=center-(HALF-1)+k;
                    if(ix>=0 && ix<count) {
                        if(ix<count-CAP) throw new IOException("Resampler buffer overflow.");
                        int q=(int)(ix%CAP);l+=left[q]*w[k];r+=right[q]*w[k];
                    }
                }
                sink.frame(l,r);emitted++;
            }
        }
        void finish() throws IOException {if(!direct) emit(true);}
    }
}
