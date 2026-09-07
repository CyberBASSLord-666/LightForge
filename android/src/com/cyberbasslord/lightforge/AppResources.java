package com.cyberbasslord.lightforge;
import android.content.Context;
import android.net.Uri;
import android.webkit.WebResourceResponse;
import java.io.*;
import java.util.*;
import java.nio.charset.StandardCharsets;

/** Identical isolated, bounded asset transport for the screen and background engine. */
final class AppResources {
    private final Context context;
    private final String allowedProject;
    AppResources(Context context,String allowedProject){this.context=context.getApplicationContext();this.allowedProject=allowedProject;}
    WebResourceResponse resource(Uri uri,Map<String,String> requestHeaders) {
        try {
            if(!"https".equals(uri.getScheme())||!"appassets.androidplatform.net".equals(uri.getHost()))return response(403,"Forbidden","text/plain",new ByteArrayInputStream(new byte[0]),0,null);
            String path=uri.getPath();if(path==null||path.contains("..")||path.contains("\\"))throw new FileNotFoundException();
            if(path.startsWith("/project/")) {
                String[] pieces=path.split("/");if(pieces.length!=4)throw new FileNotFoundException();
                if(!Arrays.asList("audio.wav","analysis.wav","project.json","meta.json").contains(pieces[3]))throw new FileNotFoundException();
                if(allowedProject!=null&&!allowedProject.equals(pieces[2]))throw new FileNotFoundException();
                File projectDir=AnalysisJobStore.project(context.getFilesDir(),pieces[2]);
                if("analysis.wav".equals(pieces[3]))ProjectStore.ensureAnalysis(projectDir,null);
                File file=new File(projectDir,pieces[3]);if(!file.isFile())throw new FileNotFoundException();
                String range=null;
                if(requestHeaders!=null)for(Map.Entry<String,String> e:requestHeaders.entrySet())if("Range".equalsIgnoreCase(e.getKey()))range=e.getValue();
                WebViewFileTransport.Response result=WebViewFileTransport.open(file,range);
                return response(result.status,result.reason,mime(path),result.body,result.length,result.contentRange);
            }
            String asset=path.equals("/")?"index.html":path.substring(1);
            InputStream in=context.getAssets().open(asset);
            return response(200,"OK",mime(path),in,-1,null);
        }catch(Exception e){return response(404,"Not Found","text/plain",new ByteArrayInputStream("Not found".getBytes(StandardCharsets.UTF_8)),9,null);}
    }
    static String mime(String path) {
        if(path.endsWith(".html"))return "text/html";if(path.endsWith(".js")||path.endsWith(".mjs"))return "application/javascript";
        if(path.endsWith(".css"))return "text/css";if(path.endsWith(".json"))return "application/json";if(path.endsWith(".wasm"))return "application/wasm";
        if(path.endsWith(".wav"))return "audio/wav";if(path.endsWith(".svg"))return "image/svg+xml";if(path.endsWith(".png"))return "image/png";
        if(path.endsWith(".jpg")||path.endsWith(".jpeg"))return "image/jpeg";if(path.endsWith(".webp"))return "image/webp";
        if(path.endsWith(".glb"))return "model/gltf-binary";if(path.endsWith(".gltf"))return "model/gltf+json";
        if(path.endsWith(".woff2"))return "font/woff2";return "application/octet-stream";
    }
    static WebResourceResponse response(int status,String reason,String mime,InputStream in,long length,String range) {
        Map<String,String> headers=WebViewFileTransport.responseHeaders(length,range);
        return new WebResourceResponse(mime,mime.startsWith("text/")||mime.contains("javascript")||mime.contains("json")?"UTF-8":null,status,reason,headers,in);
    }
}
