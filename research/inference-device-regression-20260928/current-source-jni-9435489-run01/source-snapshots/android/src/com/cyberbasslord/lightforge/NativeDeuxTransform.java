package com.cyberbasslord.lightforge;

import java.io.*;
import java.nio.*;
import java.util.Arrays;

/** Source-clock-identical port of separator-deux.js. No Android or ONNX dependency. */
final class NativeDeuxTransform {
    static final int RATE=44100, NFFT=2048, HOP=441, FRAMES=1301, SAMPLES=573300;
    static final int SPECTRUM_FLOATS=2050*FRAMES*2;
    interface Check { void check() throws IOException; }
    private final double[] re=new double[NFFT], im=new double[NFFT], window=new double[NFFT];
    private final double[] norm=new double[SAMPLES+NFFT];
    private final FFT fft=new FFT(NFFT);

    NativeDeuxTransform() {
        for(int i=0;i<NFFT;i++)window[i]=.5-.5*Math.cos(2*Math.PI*i/NFFT);
        for(int f=0;f<FRAMES;f++)for(int i=0;i<NFFT;i++)norm[f*HOP+i]+=window[i]*window[i];
    }

    /** PCM16 stereo WAVE, including RIFF ancillary chunks; absent source samples are zero. */
    static float[][] readStereo(File file,long startSample,Check check) throws IOException {
        if(startSample < -SAMPLES || startSample > RATE*14401L)throw new IOException("Invalid studio passage position.");
        float[][] result=new float[2][SAMPLES];
        try(RandomAccessFile in=new RandomAccessFile(file,"r")) {
            if(in.length()<44 || in.readInt()!=0x52494646)throw new IOException("Studio analysis requires a PCM WAVE source.");
            long riffEnd=8+u32(in);
            if(in.readInt()!=0x57415645 || riffEnd>in.length() || riffEnd<44)throw new IOException("The source WAVE header is invalid.");
            boolean format=false;long offset=-1,bytes=0;
            while(in.getFilePointer()+8<=riffEnd) {
                check.check();int id=in.readInt();long size=u32(in),begin=in.getFilePointer();
                if(size>riffEnd-begin)throw new IOException("The source WAVE is truncated.");
                if(id==0x666d7420) {
                    if(size<16 || u16(in)!=1 || u16(in)!=2 || u32(in)!=RATE || u32(in)!=RATE*4L || u16(in)!=4 || u16(in)!=16)
                        throw new IOException("Studio analysis requires 44,100 Hz, 16-bit stereo PCM.");
                    format=true;
                } else if(id==0x64617461 && offset<0) {offset=begin;bytes=size;}
                long next=begin+size+(size&1);
                if(next>riffEnd)throw new IOException("The source WAVE chunk padding is invalid.");
                in.seek(next);
            }
            if(!format || offset<0 || bytes%4!=0)throw new IOException("The source WAVE has no valid stereo audio.");
            long first=Math.max(0,startSample),last=Math.min(bytes/4,startSample+SAMPLES);
            if(last<=first)return result;
            in.seek(offset+first*4);byte[] buffer=new byte[32768];
            while(first<last) {
                check.check();int count=(int)Math.min(buffer.length/4,last-first);in.readFully(buffer,0,count*4);
                int dst=(int)(first-startSample);
                for(int i=0;i<count;i++)for(int c=0;c<2;c++) {
                    int at=i*4+c*2;short value=(short)((buffer[at]&255)|((buffer[at+1]&255)<<8));
                    result[c][dst+i]=value/32768f;
                }
                first+=count;
            }
        }
        return result;
    }

    void encode(float[][] stereo,FloatBuffer spectrum,Check check) throws IOException {
        if(stereo.length!=2 || stereo[0].length!=SAMPLES || stereo[1].length!=SAMPLES || spectrum.capacity()!=SPECTRUM_FLOATS)
            throw new IOException("Studio separation requires a complete stereo passage.");
        for(int c=0;c<2;c++)for(int f=0;f<FRAMES;f++) {
            if((f&31)==0)check.check();int start=f*HOP-NFFT/2;
            for(int i=0;i<NFFT;i++) {
                int at=start+i;if(at<0)at=-at;if(at>=SAMPLES)at=2*SAMPLES-at-2;
                float value=stereo[c][at];if(!Float.isFinite(value))throw new IOException("Invalid studio source audio.");
                re[i]=value*window[i];im[i]=0;
            }
            fft.run(re,im,false);
            for(int b=0;b<=NFFT/2;b++) {int at=((b*2+c)*FRAMES+f)*2;spectrum.put(at,(float)re[b]);spectrum.put(at+1,(float)im[b]);}
        }
    }

    float[] decode(FloatBuffer spectrum,FloatBuffer mask,int[] indices,int[] bandsPerFrequency,FloatBuffer summed,Check check) throws IOException {
        if(mask.capacity()!=indices.length*FRAMES*2 || spectrum.capacity()!=SPECTRUM_FLOATS || summed.capacity()!=SPECTRUM_FLOATS)
            throw new IOException("Studio separator returned an invalid mask.");
        for(int i=0;i<summed.capacity();i++)summed.put(i,0);
        // Deliberately round after every addition, matching Float32Array accumulation.
        for(int j=0;j<indices.length;j++) {
            if((j&63)==0)check.check();int dst=indices[j]*FRAMES*2,src=j*FRAMES*2;
            for(int i=0;i<FRAMES*2;i++)summed.put(dst+i,summed.get(dst+i)+mask.get(src+i));
        }
        float[] pcm=new float[SAMPLES+NFFT];
        for(int c=0;c<2;c++)for(int f=0;f<FRAMES;f++) {
            if((f&31)==0)check.check();Arrays.fill(re,0);Arrays.fill(im,0);
            for(int b=0;b<=NFFT/2;b++) {
                int at=((b*2+c)*FRAMES+f)*2;double d=Math.max(1e-8,bandsPerFrequency[b]);
                double ar=spectrum.get(at),ai=spectrum.get(at+1),mr=summed.get(at)/d,mi=summed.get(at+1)/d;
                double r=ar*mr-ai*mi,v=ar*mi+ai*mr;
                if(!Double.isFinite(r)||!Double.isFinite(v))throw new IOException("Studio separation produced invalid audio.");
                re[b]=r;im[b]=v;if(b>0&&b<NFFT/2){re[NFFT-b]=r;im[NFFT-b]=-v;}
            }
            fft.run(re,im,true);
            for(int i=0;i<NFFT;i++)pcm[f*HOP+i]=(float)(pcm[f*HOP+i]+re[i]*window[i]*.5);
        }
        float[] out=new float[SAMPLES];
        for(int i=0;i<SAMPLES;i++)out[i]=(float)(pcm[i+NFFT/2]/Math.max(1e-12,norm[i+NFFT/2]));
        return out;
    }

    private static int u16(RandomAccessFile in) throws IOException {int a=in.readUnsignedByte();return a|in.readUnsignedByte()<<8;}
    private static long u32(RandomAccessFile in) throws IOException {return (long)u16(in)|((long)u16(in)<<16);}
    private static final class FFT {
        final int n;final int[] rev;final double[] cos,sin;
        FFT(int n) {
            this.n=n;rev=new int[n];cos=new double[n/2];sin=new double[n/2];int bits=Integer.numberOfTrailingZeros(n);
            for(int i=0;i<n;i++)rev[i]=Integer.reverse(i) >>> (32-bits);
            for(int i=0;i<n/2;i++){cos[i]=Math.cos(2*Math.PI*i/n);sin[i]=Math.sin(2*Math.PI*i/n);}
        }
        void run(double[] r,double[] im,boolean inverse) {
            for(int i=0;i<n;i++){int j=rev[i];if(i<j){double t=r[i];r[i]=r[j];r[j]=t;t=im[i];im[i]=im[j];im[j]=t;}}
            for(int len=2;len<=n;len*=2){int half=len/2,step=n/len;
                for(int start=0;start<n;start+=len)for(int j=0;j<half;j++){
                    int k=j*step,a=start+j,b=a+half;double c=cos[k],s=sin[k]*(inverse?1:-1),tr=r[b]*c-im[b]*s,ti=r[b]*s+im[b]*c;
                    r[b]=r[a]-tr;im[b]=im[a]-ti;r[a]+=tr;im[a]+=ti;
                }
            }
            if(inverse)for(int i=0;i<n;i++){r[i]/=n;im[i]/=n;}
        }
    }
}
