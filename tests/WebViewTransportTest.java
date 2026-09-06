package com.cyberbasslord.lightforge;

import java.io.*;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.*;

/**
 * Executes production transport against the Chromium intercepted-stream
 * lifecycle: available -> range bounds -> skip(start) -> read(buffer,off,len).
 * Host-JVM test, not a substitute for a device WebView integration test.
 */
public final class WebViewTransportTest {
    private static int checks, responses;
    private static long compared;
    private static void check(boolean ok,String message){checks++;if(!ok)throw new AssertionError(message);}
    private static String sha(byte[] data)throws Exception {
        byte[] sum=MessageDigest.getInstance("SHA-256").digest(data);StringBuilder result=new StringBuilder();
        for(byte value:sum)result.append(String.format(Locale.ROOT,"%02x",value&255));return result.toString();
    }
    // Models InputStreamReader::VerifyRequestedRange / SkipToRequestedRange.
    // The response status/Content-Range do NOT disable this implicit seek.
    static void chromiumSeek(InputStream input,String range)throws Exception {
        int available=input.available(); long start=0,end=-1,suffix=-1;
        if(range!=null) {
            String[] bounds=range.substring(range.indexOf('=')+1).trim().split("-",-1);
            if(bounds[0].trim().isEmpty())suffix=Long.parseLong(bounds[1].trim());
            else {start=Long.parseLong(bounds[0].trim());if(!bounds[1].trim().isEmpty())end=Long.parseLong(bounds[1].trim());}
        }
        if(available>0) {
            if(suffix>=0)start=Math.max(0,available-suffix);
            if(start>=available)throw new IOException("Chromium rejected range against available()");
        } else if(suffix>=0)start=0; // Unknown-length suffix has no computed start.
        while(start>0) {
            // Chromium's JNI glue narrows skip's long result to signed int.
            long skipped=(int)input.skip(start);
            if(skipped<=0)throw new IOException("Chromium skip failed");
            start-=skipped;
        }
    }
    private static byte[] chromiumRead(InputStream input)throws Exception {
        ByteArrayOutputStream output=new ByteArrayOutputStream();byte[] buffer=new byte[4102];
        int read;
        while((read=input.read(buffer,3,4096))>=0) {
            if(read==0)throw new IOException("Unexpected zero-byte read");
            output.write(buffer,3,read);
        }
        return output.toByteArray();
    }
    private static byte[] response(File file,String range,long start,long end)throws Exception {
        WebViewFileTransport.Response response=WebViewFileTransport.open(file,range);
        long expected=Math.max(0,end-start+1);
        check(response.status==(range==null?200:206),"Correct HTTP response status");
        check(response.length==expected,"Correct Content-Length");
        check(Objects.equals(response.contentRange,range==null?null:"bytes "+start+"-"+end+"/"+file.length()),"Correct Content-Range");
        byte[] actual;
        try(InputStream input=response.body) {chromiumSeek(input,range);actual=chromiumRead(input);check(input.available()==0,"EOF reports no bytes");}
        check(actual.length==expected,"Exact response length for "+range+": "+actual.length+" vs "+expected);
        byte[] reference=new byte[(int)expected];try(RandomAccessFile input=new RandomAccessFile(file,"r")){input.seek(start);input.readFully(reference);}
        check(Arrays.equals(reference,actual),"Byte-exact response for "+range);
        responses++;compared+=expected;return actual;
    }
    private static void directStreamContract()throws Exception {
        byte[] data={0,1,2,3,4,5,6,7,8,9};
        WebViewFileTransport.BoundedInput input=new WebViewFileTransport.BoundedInput(new ByteArrayInputStream(data),7);
        check(input.available()==7,"Availability obeys limit");
        check(input.read()==0,"Single read");check(input.skip(-10)==0,"Negative skip leaves position alone");
        check(input.skip(2)==2,"Positive skip");byte[] b=new byte[8];
        check(input.read(b)==4&&b[0]==3&&b[3]==6,"read(byte[]) obeys bound");
        check(input.read(b,0,0)==0,"Zero-length read returns zero at EOF");
        check(input.read(b)==-1&&input.read()==-1&&input.skip(1)==0,"All EOF overloads agree");
        check(!input.markSupported(),"No misleading mark/reset support");
        boolean invalid=false;try{input.read(b,-1,1);}catch(IndexOutOfBoundsException expected){invalid=true;}check(invalid,"Invalid bounds checked even at EOF");
        input.close();input.close();invalid=false;try{input.read();}catch(IOException expected){invalid=true;}check(invalid,"Read after close rejected");
    }
    private static void isolationHeaderContract() {
        for(long length:new long[]{-1,0,44,2147483647L}) {
            String range=length==44?"bytes 0-43/123456":null;
            Map<String,String> headers=WebViewFileTransport.responseHeaders(length,range);
            check("same-origin".equals(headers.get("Cross-Origin-Opener-Policy")),"Document keeps same-origin opener isolation");
            check("require-corp".equals(headers.get("Cross-Origin-Embedder-Policy")),"Document and workers require embedded resources to opt in");
            check("same-origin".equals(headers.get("Cross-Origin-Resource-Policy")),"Local assets remain restricted to same-origin callers");
            check("nosniff".equals(headers.get("X-Content-Type-Options")),"Executable responses cannot MIME-sniff");
            check("no-store".equals(headers.get("Cache-Control")),"Project bytes cannot reuse stale cached responses");
            check("bytes".equals(headers.get("Accept-Ranges"))&&"Range".equals(headers.get("Vary")),"Byte ranges retain their response policy");
            check(Objects.equals(headers.get("Content-Length"),length<0?null:Long.toString(length)),"Length remains accurate for unknown, empty and large streams");
            check(Objects.equals(headers.get("Content-Range"),range),"Content-Range remains exact");
            check(!headers.containsKey("Access-Control-Allow-Origin"),"No cross-origin grant is introduced");
            check(!headers.containsKey("Content-Security-Policy"),"Isolation does not alter script security policy");
            headers.put("Cross-Origin-Embedder-Policy","test-mutation");
        }
        check("require-corp".equals(WebViewFileTransport.responseHeaders(-1,null).get("Cross-Origin-Embedder-Policy")),"Response maps cannot mutate another response's isolation");
    }
    private static int reproduceLegacy(File file)throws Exception {
        // Exact v1.0.0 behavior: seek in MainActivity, then WebView seeks again.
        int start=44,length=441000;
        FileInputStream raw=new FileInputStream(file);raw.getChannel().position(start);
        InputStream legacy=new FilterInputStream(raw){long remaining=length;
            public int read()throws IOException{if(remaining<=0)return -1;int v=super.read();if(v>=0)remaining--;return v;}
            public int read(byte[] b,int o,int n)throws IOException{if(remaining<=0)return -1;int count=super.read(b,o,(int)Math.min(n,remaining));if(count>0)remaining-=count;return count;}
            public long skip(long n)throws IOException{long count=super.skip(Math.min(n,remaining));remaining-=count;return count;}};
        byte[] body;try(InputStream input=legacy){chromiumSeek(input,"bytes=44-441043");body=chromiumRead(input);}
        check(body.length==length-start,"Original defect reproduced: first analysis block is 44 bytes short");
        return length-body.length;
    }
    private static void invalidRanges(File file)throws Exception {
        for(String range:Arrays.asList("bytes=-0","bytes=-","bytes=3-2","bytes="+file.length()+"-","bytes=0-1,4-5","bytes=abc-9","bytes=0-999999999999999999999999","bytes=+2-4","items=0-2")) {
            WebViewFileTransport.Response result=WebViewFileTransport.open(file,range);
            try(InputStream input=result.body){check(result.status==416&&result.length==0&&input.read()==-1,"Invalid range rejected: "+range);}
        }
    }
    private static void largeFile(File directory)throws Exception {
        File file=new File(directory,"four-hour-sparse.wav");long size=44100L*4*14400+44;
        try {
            try(RandomAccessFile output=new RandomAccessFile(file,"rw")) {
                output.setLength(size);
                for(long point:new long[]{0,Integer.MAX_VALUE-128L,Integer.MAX_VALUE+256L,size-1024}) {
                    output.seek(point);byte[] data=new byte[1024];for(int i=0;i<data.length;i++)data[i]=(byte)(i*17+point);output.write(data);
                }
            }
            for(String range:Arrays.asList(null,"bytes=2147483903-2147484926","bytes="+(size-1024)+"-","bytes=-1024","bytes=0-43")) {
                WebViewFileTransport.Response result=WebViewFileTransport.open(file,range);
                try(InputStream input=result.body){check(result.status==413&&result.length==0&&input.read()==-1,"Oversized original is not exposed to WebView's 32-bit length path");}
                check(file.length()==size,"Full-quality export audio is preserved");
            }
        } finally {check(file.delete(),"Large sparse fixture removed");}
    }
    public static void main(String[] args)throws Exception {
        if(args.length<2)throw new IllegalArgumentException("audio.wav work-directory [additional.wav...]");
        File work=new File(args[1]);work.mkdirs();File file=new File(args[0]);
        int legacyShortBy=reproduceLegacy(file);
        directStreamContract();isolationHeaderContract();invalidRanges(file);
        List<File> fixtures=new ArrayList<>();fixtures.add(file);for(int i=2;i<args.length;i++)fixtures.add(new File(args[i]));
        List<String> hashes=new ArrayList<>();
        for(File audio:fixtures) {
            byte[] entire=response(audio,null,0,audio.length()-1);hashes.add(sha(entire));
            response(audio,"bytes=0-65535",0,Math.min(audio.length()-1,65535));
            response(audio,"bytes=44-441043",44,441043);
            long stride=441000;
            // Out-of-order seeks cover decoder chunk overlap, playback seek and final PCM frame.
            for(long offset=44;offset<audio.length();offset+=stride) {
                long end=Math.min(audio.length()-1,offset+stride+2819);
                response(audio,"bytes="+offset+"-"+end,offset,end);
            }
            response(audio,"bytes="+(audio.length()-1)+"-",audio.length()-1,audio.length()-1);
            response(audio,"bytes=-4096",audio.length()-4096,audio.length()-1);
            response(audio,"bytes=1000-1999",1000,1999);
        }
        File empty=new File(work,"empty.wav");Files.write(empty.toPath(),new byte[0]);response(empty,null,0,-1);empty.delete();
        largeFile(work);
        System.out.println("{\"status\":\"PASS\",\"checks\":"+checks+",\"byteExactResponses\":"+responses+",\"comparedBytes\":"+compared+",\"legacyFirstChunkShortBy\":"+legacyShortBy+",\"largeFileBoundary\":\"PASS: oversized original protected; separate mono preview retains full-quality export\",\"hostChromiumSemantics\":true,\"androidDeviceTest\":false,\"fullAudioSha256\":[\""+String.join("\",\"",hashes)+"\"]}");
    }
}
