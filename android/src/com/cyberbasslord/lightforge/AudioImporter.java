package com.cyberbasslord.lightforge;

import android.media.*;
import java.io.*;
import java.nio.*;

/** Uses Android's actual media decoders; never renames compressed audio as WAV. */
final class AudioImporter {
    interface Progress {void update(double fraction,String message);void check() throws IOException;}
    static double convert(File input,File audio,File analysis,Progress progress) throws Exception {
        Double direct=readWave(input,audio,analysis,progress);
        if(direct!=null) return direct;
        MediaExtractor extractor=new MediaExtractor(); MediaCodec codec=null; WavConverter converter=null;
        try {
            extractor.setDataSource(input.getAbsolutePath());
            int track=-1; MediaFormat format=null;
            for(int i=0;i<extractor.getTrackCount();i++) {
                MediaFormat f=extractor.getTrackFormat(i);String mime=f.getString(MediaFormat.KEY_MIME);
                if(mime!=null && mime.startsWith("audio/")) {track=i;format=f;break;}
            }
            if(track<0) throw new IOException("No readable audio track was found. Choose an unprotected audio file.");
            long duration=format.containsKey(MediaFormat.KEY_DURATION)?format.getLong(MediaFormat.KEY_DURATION):0;
            if(duration>4L*3600*1000000) throw new IOException("Tesla shows can be at most four hours long.");
            extractor.selectTrack(track);
            // An advisory request; Android returns the actual encoding in the
            // output format. Preserve high resolution sources until the final
            // 16-bit Tesla WAV conversion when the device supports float output.
            format.setInteger(MediaFormat.KEY_PCM_ENCODING,4);
            codec=MediaCodec.createDecoderByType(format.getString(MediaFormat.KEY_MIME));
            codec.configure(format,null,null,0);codec.start();
            boolean inputEnd=false,outputEnd=false;
            int rate=format.getInteger(MediaFormat.KEY_SAMPLE_RATE),channels=format.getInteger(MediaFormat.KEY_CHANNEL_COUNT),encoding=2;
            if(channels<1 || channels>8) throw new IOException("This audio channel layout is not supported.");
            MediaCodec.BufferInfo info=new MediaCodec.BufferInfo(); long lastOutput=System.nanoTime();
            PcmFrames decoded=null;int loops=0;
            while(!outputEnd) {
                progress.check();
                if(!inputEnd) {
                    int index=codec.dequeueInputBuffer(10000);
                    if(index>=0) {
                        ByteBuffer in=codec.getInputBuffer(index);
                        if(in==null) throw new IOException("The device's audio decoder did not provide an input buffer.");
                        in.clear();
                        int sampleFlags=extractor.getSampleFlags();
                        if(sampleFlags>=0 && (sampleFlags&MediaExtractor.SAMPLE_FLAG_ENCRYPTED)!=0)
                            throw new IOException("This music is copy-protected. Choose an unprotected audio file.");
                        int size=extractor.readSampleData(in,0);
                        if(size<0) {codec.queueInputBuffer(index,0,0,0,MediaCodec.BUFFER_FLAG_END_OF_STREAM);inputEnd=true;}
                        else {codec.queueInputBuffer(index,0,size,extractor.getSampleTime(),0);extractor.advance();}
                    }
                }
                int index=codec.dequeueOutputBuffer(info,10000);
                if(index==MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    MediaFormat output=codec.getOutputFormat();
                    int newRate=output.getInteger(MediaFormat.KEY_SAMPLE_RATE);
                    if(converter!=null && rate!=newRate) throw new IOException("Audio changes sample rate mid-track. Convert it to WAV first.");
                    rate=newRate;channels=output.getInteger(MediaFormat.KEY_CHANNEL_COUNT);
                    encoding=output.containsKey(MediaFormat.KEY_PCM_ENCODING)?output.getInteger(MediaFormat.KEY_PCM_ENCODING):2;
                    if(decoded!=null) decoded.finish();
                    int channelMask=output.containsKey(MediaFormat.KEY_CHANNEL_MASK)?output.getInteger(MediaFormat.KEY_CHANNEL_MASK)>>>2:0;
                    decoded=new PcmFrames(channels,encoding,channelMask);
                } else if(index>=0) {
                    lastOutput=System.nanoTime();
                    if(info.size>0 && (info.flags&MediaCodec.BUFFER_FLAG_CODEC_CONFIG)==0) {
                        if(converter==null) converter=new WavConverter(audio,analysis,rate);
                        if(decoded==null) decoded=new PcmFrames(channels,encoding);
                        ByteBuffer output=codec.getOutputBuffer(index);
                        if(output==null || info.offset<0 || info.size>output.capacity()-info.offset)
                            throw new IOException("The device's audio decoder returned an invalid audio buffer.");
                        ByteBuffer pcm=output.duplicate().order(ByteOrder.nativeOrder());
                        pcm.clear();
                        pcm.position(info.offset);pcm.limit(info.offset+info.size);
                        decoded.accept(pcm,converter);
                    }
                    outputEnd=(info.flags&MediaCodec.BUFFER_FLAG_END_OF_STREAM)!=0;
                    codec.releaseOutputBuffer(index,false);
                    if(++loops%12==0) progress.update(duration>0?Math.min(.99,info.presentationTimeUs/(double)duration):.2,"Preparing clean 44.1 kHz audio");
                }
                if(System.nanoTime()-lastOutput>30_000_000_000L) throw new IOException("The device's audio decoder stopped responding. Try a WAV or MP3 copy.");
            }
            if(converter==null) throw new IOException("The selected file contains no decoded audio.");
            if(decoded!=null) decoded.finish();
            double seconds=converter.finish();
            if(seconds<1) throw new IOException("Choose a track that is at least one second long.");
            return seconds;
        } finally {
            if(converter!=null) converter.close();
            if(codec!=null) {try{codec.stop();}catch(Exception ignored){}codec.release();}
            extractor.release();
        }
    }

    /** Decoded buffer boundaries need not coincide with a complete PCM frame. */
    static final class PcmFrames {
        final int channels,encoding,align,channelMask;
        final float[] values,stereo=new float[32768];
        final byte[] partial;
        int pending;
        PcmFrames(int channels,int encoding) throws IOException {
            this(channels,encoding,0);
        }
        PcmFrames(int channels,int encoding,int channelMask) throws IOException {
            if(channels<1 || channels>8) throw new IOException("This decoded audio channel layout is not supported.");
            int bytes=encoding==4 || encoding==22?4:encoding==21?3:encoding==3?1:encoding==2?2:0;
            if(bytes==0) throw new IOException("Unsupported decoded PCM format: "+encoding);
            this.channels=channels;this.encoding=encoding;align=bytes*channels;
            this.channelMask=Integer.bitCount(channelMask)==channels?channelMask:0;
            values=new float[channels];partial=new byte[align];
        }
        void accept(ByteBuffer pcm,WavConverter converter) throws IOException {
            if(pending>0) {
                int count=Math.min(align-pending,pcm.remaining());pcm.get(partial,pending,count);pending+=count;
                if(pending<align) return;
                ByteBuffer frame=ByteBuffer.wrap(partial).order(pcm.order());
                for(int c=0;c<channels;c++) values[c]=sample(frame,encoding);
                downmix(values,stereo,0,channelMask);converter.accept(stereo,1);pending=0;
            }
            while(pcm.remaining()>=align) {
                int count=Math.min(stereo.length/2,pcm.remaining()/align);
                for(int i=0;i<count;i++) {
                    for(int c=0;c<channels;c++) values[c]=sample(pcm,encoding);
                    downmix(values,stereo,i*2,channelMask);
                }
                converter.accept(stereo,count);
            }
            if(pcm.hasRemaining()) {pending=pcm.remaining();pcm.get(partial,0,pending);}
        }
        void finish() throws IOException {
            if(pending!=0) throw new IOException("The decoded audio ended in an incomplete sample frame. Choose a complete copy of the track.");
        }
    }
    static float sample(ByteBuffer b,int encoding) throws IOException {
        if(encoding==4) {float f=b.getFloat();return Float.isFinite(f)?f:0;}
        if(encoding==22) return b.getInt()/2147483648f;
        if(encoding==21) {int n=(b.get()&255)|((b.get()&255)<<8)|(b.get()<<16);return n/8388608f;}
        if(encoding==3) return ((b.get()&255)-128)/128f;
        if(encoding==2) return b.getShort()/32768f;
        throw new IOException("Unsupported decoded PCM format: "+encoding);
    }
    static void downmix(float[] input,float[] output,int offset) {
        if(input.length==1) {output[offset]=input[0];output[offset+1]=input[0];return;}
        float l=input[0],r=input[1];
        if(input.length>2) {
            // Canonical interleaved PCM layouts: L/R/C; quad L/R/BL/BR;
            // 5.0 L/R/C/BL/BR; 5.1 L/R/C/LFE/BL/BR; 6.1 adds BC;
            // 7.1 uses L/R/C/LFE/BL/BR/SL/SR. Reserve headroom per side.
            float gain;
            if(input.length==4) {
                l+=input[2]*.5f;r+=input[3]*.5f;gain=1/1.5f;
            } else {
                l+=input[2]*.7071f;r+=input[2]*.7071f;float weight=1.7071f;
                if(input.length==5) {l+=input[3]*.5f;r+=input[4]*.5f;weight+=.5f;}
                if(input.length>=6) {
                    l+=input[3]*.25f;r+=input[3]*.25f;weight+=.25f;
                    if(input.length==7) {
                        l+=input[4]*.5f+input[5]*.5f;r+=input[4]*.5f+input[6]*.5f;weight+=1;
                    } else {
                        l+=input[4]*.5f;r+=input[5]*.5f;weight+=.5f;
                        if(input.length==8) {l+=input[6]*.5f;r+=input[7]*.5f;weight+=.5f;}
                    }
                }
                gain=1/weight;
            }
            l*=gain;r*=gain;
        }
        output[offset]=l;output[offset+1]=r;
    }
    static void downmix(float[] input,float[] output,int offset,int channelMask) {
        if(input.length<=2 || channelMask==0 || Integer.bitCount(channelMask)!=input.length) {
            downmix(input,output,offset);return;
        }
        float left=0,right=0,leftWeight=0,rightWeight=0;int channel=0;
        for(int bit=1;bit!=0 && channel<input.length;bit<<=1) if((channelMask&bit)!=0) {
            float l,r;
            switch(bit) {
                case 1:l=1;r=0;break; // Front left / right.
                case 2:l=0;r=1;break;
                case 4:l=r=.7071f;break; // Front center.
                case 8:l=r=.25f;break; // LFE, retained with headroom.
                case 16:case 64:case 512:case 4096:case 32768:l=.5f;r=0;break;
                case 32:case 128:case 1024:case 16384:case 131072:l=0;r=.5f;break;
                default:l=r=.5f;break; // Center/back/height channels.
            }
            left+=input[channel]*l;right+=input[channel]*r;leftWeight+=l;rightWeight+=r;channel++;
        }
        output[offset]=left/Math.max(1,leftWeight);output[offset+1]=right/Math.max(1,rightWeight);
    }
    static Double readWave(File input,File audio,File analysis,Progress progress) throws Exception {
        try(RandomAccessFile f=new RandomAccessFile(input,"r")) {
            if(f.length()<44) return null;
            byte[] first=new byte[12];f.readFully(first);
            if(!new String(first,0,4,"US-ASCII").equals("RIFF") || !new String(first,8,4,"US-ASCII").equals("WAVE")) return null;
            int format=0,channels=0,rate=0,bits=0,align=0,channelMask=0;long start=0,length=0;
            byte[] h=new byte[8];
            while(f.getFilePointer()+8<=f.length()) {
                f.readFully(h);String id=new String(h,0,4,"US-ASCII");long size=u32(h,4),at=f.getFilePointer();
                if(size>f.length()-at) throw new IOException("The WAV file is incomplete.");
                if(id.equals("fmt ")) {
                    if(size<16 || size>65536) throw new IOException("Invalid WAV format header.");
                    byte[] fmt=new byte[(int)size];f.readFully(fmt);format=u16(fmt,0);channels=u16(fmt,2);
                    rate=(int)u32(fmt,4);align=u16(fmt,12);bits=u16(fmt,14);
                    if(format==65534 && size>=40) {channelMask=(int)u32(fmt,20);format=u16(fmt,24);}
                } else if(id.equals("data")) {start=at;length=size;}
                f.seek(at+size+(size&1));
                if(start>0 && format>0) break;
            }
            if(format!=1 && format!=3) return null;
            if(channels<1||channels>8||rate<8000||rate>384000||start==0) throw new IOException("Unsupported or incomplete WAV file.");
            int encoding=format==3&&bits==32?4:bits==8?3:bits==16?2:bits==24?21:bits==32?22:0;
            if(encoding==0 || (format==3&&bits!=32) || align!=channels*(bits/8)) throw new IOException("Unsupported WAV sample format.");
            if(length%align!=0) throw new IOException("The WAV sample data is incomplete. Choose a complete copy of the track.");
            if(length/align>(long)rate*4*3600) throw new IOException("Tesla shows can be at most four hours long.");
            f.seek(start);byte[] buffer=new byte[4096*align];float[] stereo=new float[8192],samples=new float[channels];
            try(WavConverter converter=new WavConverter(audio,analysis,rate)) {
                long remain=length;int count=0;
                while(remain>=align) {
                    progress.check();int bytes=(int)Math.min(buffer.length,remain);bytes-=bytes%align;
                    f.readFully(buffer,0,bytes);ByteBuffer b=ByteBuffer.wrap(buffer,0,bytes).order(ByteOrder.LITTLE_ENDIAN);
                    int frames=bytes/align;
                    for(int j=0;j<frames;j++) {for(int c=0;c<channels;c++) samples[c]=sample(b,encoding);downmix(samples,stereo,j*2,channelMask);}
                    converter.accept(stereo,frames);remain-=bytes;
                    if(++count%24==0) progress.update(1-remain/(double)length,"Preparing clean 44.1 kHz audio");
                }
                double seconds=converter.finish();if(seconds<1) throw new IOException("Choose a track that is at least one second long.");return seconds;
            }
        }
    }
    static int u16(byte[] b,int o) {return (b[o]&255)|((b[o+1]&255)<<8);}
    static long u32(byte[] b,int o) {return (b[o]&255L)|((b[o+1]&255L)<<8)|((b[o+2]&255L)<<16)|((b[o+3]&255L)<<24);}
}
