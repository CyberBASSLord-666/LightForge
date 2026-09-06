package com.cyberbasslord.lightforge;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;

/** File responses for Android WebView's intercepted-request stream loader. */
final class WebViewFileTransport {
    /**
     * One policy for the app document, workers, WASM and local project audio.
     * Isolation permits shared WASM memory on supporting WebViews; callers
     * must still feature-detect it and retain their single-thread fallback.
     * The same-origin resource policy never grants access to outside origins.
     */
    static Map<String,String> responseHeaders(long length, String range) {
        Map<String,String> headers=new HashMap<>();
        headers.put("Cache-Control","no-store");
        headers.put("Accept-Ranges","bytes");
        headers.put("Vary","Range");
        headers.put("Cross-Origin-Opener-Policy","same-origin");
        headers.put("Cross-Origin-Embedder-Policy","require-corp");
        headers.put("Cross-Origin-Resource-Policy","same-origin");
        headers.put("X-Content-Type-Options","nosniff");
        if(length>=0)headers.put("Content-Length",Long.toString(length));
        if(range!=null)headers.put("Content-Range",range);
        return headers;
    }

    static final class Response {
        final int status;
        final String reason, contentRange;
        final long length;
        final InputStream body;
        Response(int status, String reason, long length, String contentRange, InputStream body) {
            this.status=status; this.reason=reason; this.length=length;
            this.contentRange=contentRange; this.body=body;
        }
    }

    static Response open(File file, String rangeHeader) throws IOException {
        long size=file.length(), start=0, end=size-1;
        // WebView's range calculation and generated Content-Length use signed
        // 32-bit available(). Long tracks preview their <=635 MB mono analysis
        // WAV instead; native ZIP export reads the full stereo WAV directly.
        if(size>Integer.MAX_VALUE)return new Response(413,"Content Too Large",0,null,new ByteArrayInputStream(new byte[0]));
        boolean partial=rangeHeader!=null;
        if(partial) {
            String value=rangeHeader.trim();
            if(!value.regionMatches(true,0,"bytes=",0,6)) return unsatisfied(size);
            String bounds=value.substring(6).trim();
            int dash=bounds.indexOf('-');
            if(dash<0 || dash!=bounds.lastIndexOf('-') || bounds.indexOf(',')>=0) return unsatisfied(size);
            String left=bounds.substring(0,dash).trim(), right=bounds.substring(dash+1).trim();
            try {
                if(left.isEmpty()) {
                    long count=unsigned(right);
                    if(count==0) return unsatisfied(size);
                    start=Math.max(0,size-count);
                } else {
                    start=unsigned(left);
                    if(!right.isEmpty()) end=Math.min(end,unsigned(right));
                }
            } catch(IllegalArgumentException invalid) {return unsatisfied(size);}
            if(size==0 || start>=size || end<start) return unsatisfied(size);
        }

        FileInputStream input=new FileInputStream(file);
        try {
            /*
             * Chromium AndroidStreamReaderURLLoader parses the ORIGINAL Range
             * request, then InputStreamReader.Seek calls skip(start) on this
             * stream. Returning an already sliced stream skips the start TWICE.
             * Leave the file at byte zero and bound its end; WebView performs
             * the single start seek. This also serves media-element seek reads.
             */
            InputStream body=new BoundedInput(input,end+1);
            return new Response(partial?206:200,partial?"Partial Content":"OK",end-start+1,
                    partial?"bytes "+start+"-"+end+"/"+size:null,body);
        } catch(Throwable error) {
            try {input.close();} catch(IOException ignored) {}
            throw error;
        }
    }

    private static long unsigned(String value) {
        if(value.isEmpty()) throw new IllegalArgumentException("Empty byte bound");
        for(int i=0;i<value.length();i++) if(value.charAt(i)<'0'||value.charAt(i)>'9') throw new IllegalArgumentException("Invalid byte bound");
        return Long.parseLong(value);
    }

    private static Response unsatisfied(long size) {
        return new Response(416,"Range Not Satisfiable",0,"bytes */"+size,new ByteArrayInputStream(new byte[0]));
    }

    /** Direct delegation keeps the bound correct for every Java read overload. */
    static final class BoundedInput extends InputStream {
        private final InputStream input;
        private long remaining;
        private boolean closed;

        BoundedInput(InputStream input, long length) {
            if(input==null) throw new NullPointerException("input");
            if(length<0) throw new IllegalArgumentException("Negative length");
            this.input=input; this.remaining=length;
        }
        private void checkOpen() throws IOException {if(closed)throw new IOException("Stream is closed");}
        @Override public int read() throws IOException {
            checkOpen(); if(remaining==0)return -1;
            int value=input.read(); if(value>=0)remaining--; else remaining=0;
            return value;
        }
        @Override public int read(byte[] buffer) throws IOException {return read(buffer,0,buffer.length);}
        @Override public int read(byte[] buffer,int offset,int length) throws IOException {
            if(buffer==null)throw new NullPointerException("buffer");
            if(offset<0||length<0||offset>buffer.length-length)throw new IndexOutOfBoundsException();
            checkOpen(); if(length==0)return 0; if(remaining==0)return -1;
            int read=input.read(buffer,offset,(int)Math.min(remaining,length));
            if(read>0)remaining-=read; else if(read<0)remaining=0;
            return read;
        }
        @Override public long skip(long count) throws IOException {
            checkOpen(); if(count<=0||remaining==0)return 0;
            long skipped=input.skip(Math.min(Math.min(count,remaining),Integer.MAX_VALUE));
            if(skipped>0)remaining-=skipped;
            return skipped;
        }
        @Override public int available() throws IOException {
            checkOpen();
            return (int)Math.min(remaining,input.available());
        }
        @Override public void close() throws IOException {
            if(!closed){closed=true;remaining=0;input.close();}
        }
        @Override public boolean markSupported(){return false;}
        @Override public synchronized void reset() throws IOException {throw new IOException("Mark/reset is not supported");}
    }
}
