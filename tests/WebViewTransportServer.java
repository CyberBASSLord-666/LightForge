package com.cyberbasslord.lightforge;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.*;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;

/** Local QA adapter: actual production file response plus Chromium's implicit seek. */
public final class WebViewTransportServer {
    private static final AtomicInteger ranges=new AtomicInteger();
    public static void main(String[] args)throws Exception {
        if(args.length<3)throw new IllegalArgumentException("port web-root audio.wav");
        File web=new File(args[1]).getCanonicalFile(),audio=new File(args[2]).getCanonicalFile();
        HttpServer server=HttpServer.create(new InetSocketAddress("127.0.0.1",Integer.parseInt(args[0])),0);
        server.setExecutor(Executors.newCachedThreadPool());
        server.createContext("/",exchange->{
            try {
                String path=exchange.getRequestURI().getPath();
                WebViewFileTransport.responseHeaders(-1,null).forEach((key,value)->exchange.getResponseHeaders().set(key,value));
                if(path.equals("/transport-stats.json")) {
                    byte[] data=("{\"productionTransport\":true,\"chromiumSeekAdapter\":true,\"rangeRequests\":"+ranges.get()+"}").getBytes(StandardCharsets.UTF_8);
                    exchange.getResponseHeaders().set("Content-Type","application/json");exchange.sendResponseHeaders(200,data.length);exchange.getResponseBody().write(data);
                } else if(path.equals("/project/fixture/audio.wav")||path.equals("/project/fixture/analysis.wav")) {
                    String range=exchange.getRequestHeaders().getFirst("Range");
                    WebViewFileTransport.Response response=WebViewFileTransport.open(audio,range);
                    exchange.getResponseHeaders().set("Content-Type","audio/wav");
                    exchange.getResponseHeaders().set("Accept-Ranges","bytes");
                    if(response.contentRange!=null)exchange.getResponseHeaders().set("Content-Range",response.contentRange);
                    try(InputStream input=response.body) {
                        if(response.status<400)WebViewTransportTest.chromiumSeek(input,range);
                        exchange.sendResponseHeaders(response.status,response.length==0?-1:response.length);
                        copy(input,exchange.getResponseBody());
                    }
                    if(range!=null)ranges.incrementAndGet();
                } else {
                    File file=new File(web,path.equals("/")?"index.html":path.substring(1)).getCanonicalFile();
                    if(!file.toPath().startsWith(web.toPath())||!file.isFile()){exchange.sendResponseHeaders(404,-1);return;}
                    exchange.getResponseHeaders().set("Content-Type",mime(file.getName()));exchange.sendResponseHeaders(200,file.length());
                    try(InputStream input=Files.newInputStream(file.toPath())){copy(input,exchange.getResponseBody());}
                }
            } catch(Exception error) {System.err.println("Transport request failed: "+error);try{exchange.sendResponseHeaders(500,-1);}catch(Exception ignored){} }
            finally {exchange.close();}
        });
        server.start();System.out.println("WebView production transport QA server listening on "+args[0]);
    }
    private static void copy(InputStream input,OutputStream output)throws IOException {byte[] b=new byte[4096];int count;while((count=input.read(b,0,b.length))>=0)if(count>0)output.write(b,0,count);}
    private static String mime(String name) {
        if(name.endsWith(".js")||name.endsWith(".mjs"))return "application/javascript";
        if(name.endsWith(".css"))return "text/css";if(name.endsWith(".json"))return "application/json";
        if(name.endsWith(".wasm"))return "application/wasm";if(name.endsWith(".wav"))return "audio/wav";
        if(name.endsWith(".woff2"))return "font/woff2";if(name.endsWith(".html"))return "text/html";
        return "application/octet-stream";
    }
}
