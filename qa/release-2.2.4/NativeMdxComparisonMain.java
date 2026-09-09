package com.cyberbasslord.lightforge;

import android.content.Context;
import org.json.JSONObject;
import java.io.File;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.Arrays;
import java.util.Base64;
import java.util.UUID;

/** Actual production NativeMdxTask with host filesystem/Android API adapters.
 * JNI, model validation, transfers, graph session/options and output writer are
 * production code; this runner does not claim Android lifecycle coverage. */
public final class NativeMdxComparisonMain {
    public static void main(String[] args) throws Exception {
        File root=new File(args[0]),work=new File(args[1]);
        String runtime=ai.onnxruntime.OrtEnvironment.getEnvironment().getVersion();
        if(!"1.25.1".equals(runtime))throw new AssertionError("Wrong loaded native runtime: "+runtime);
        String owner=UUID.randomUUID().toString();
        try(NativeMdxTask task=new NativeMdxTask(new Context(new File(work,"host-state"),new File(root,"web")),owner)){
            if(!new JSONObject(task.availability(owner)).getBoolean("available"))throw new AssertionError("Native runtime unavailable");
            for(String polarity:new String[]{"positive","negative"}){
                byte[] bytes=Files.readAllBytes(new File(work,"input-"+polarity+".float32le").toPath());
                String token=new JSONObject(task.begin(owner,bytes.length)).getString("token");
                for(int at=0;at<bytes.length;at+=64*1024){int end=Math.min(bytes.length,at+64*1024);task.append(owner,token,Base64.getEncoder().encodeToString(Arrays.copyOfRange(bytes,at,end)));}
                long clock=System.nanoTime();task.run(owner,token);JSONObject status;
                do{Thread.sleep(10);status=new JSONObject(task.status(owner,token));if((System.nanoTime()-clock)>600_000_000_000L)throw new AssertionError("Native inference timeout");}while("running".equals(status.getString("state")));
                if(!"completed".equals(status.getString("state")))throw new AssertionError(status.toString());
                Files.copy(task.result(owner,token).toPath(),new File(work,"native-"+polarity+".float32le").toPath(),StandardCopyOption.REPLACE_EXISTING);
                System.out.println(new JSONObject().put("polarity",polarity).put("seconds",(System.nanoTime()-clock)/1e9).put("runtime",runtime));
            }
            task.releaseIdle(owner);
        }
    }
}
