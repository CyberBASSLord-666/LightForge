package com.cyberbasslord.lightforge;
import java.io.*;
import java.nio.file.*;
import java.util.zip.*;
import org.json.*;

/** Round-trip the real browser-generated show through shipped Java restoration. */
public final class ExportRestoreTest {
    public static void main(String[] args)throws Exception {
        File backup=new File(args[0]),root=new File(args[1]);root.mkdirs();
        JSONObject expected;
        try(ZipFile z=new ZipFile(backup)) {
            ByteArrayOutputStream b=new ByteArrayOutputStream();
            try(InputStream in=z.getInputStream(z.getEntry("Review/LightForge_Project.json"))){byte[] buf=new byte[65536];int n;while((n=in.read(buf))!=-1)b.write(buf,0,n);}
            expected=new JSONObject(new String(b.toByteArray(),"UTF-8"));
            File fseq=new File(root,"exported.fseq"),wav=new File(root,"exported.wav");
            for(String[] pair:new String[][]{{"LightShow/lightshow.fseq",fseq.getPath()},{"LightShow/lightshow.wav",wav.getPath()}})
                try(InputStream in=z.getInputStream(z.getEntry(pair[0]));OutputStream out=new FileOutputStream(pair[1])){byte[] buf=new byte[131072];int n;while((n=in.read(buf))!=-1)out.write(buf,0,n);}
            MainActivity.verifySequence(fseq,wav);
        }
        JSONObject meta=ProjectStore.restore(root,backup,new AudioImporter.Progress(){public void update(double v,String s){}public void check(){}});
        File directory=new File(root,meta.getString("id"));
        JSONObject actual=new JSONObject(new String(Files.readAllBytes(new File(directory,"project.json").toPath()),"UTF-8"));
        if(!actual.getJSONObject("settings").similar(expected.getJSONObject("settings")))throw new AssertionError("Creative settings changed");
        if(actual.getJSONObject("music").getDouble("bpm")!=expected.getJSONObject("music").getDouble("bpm"))throw new AssertionError("Music analysis changed");
        if(actual.optBoolean("needAnalysis"))throw new AssertionError("Restored complete project should not require reanalysis");
        if(!java.util.Arrays.equals(Files.readAllBytes(new File(directory,"audio.wav").toPath()),Files.readAllBytes(new File(root,"exported.wav").toPath())))throw new AssertionError("Playback samples changed");
        System.out.println(new JSONObject().put("result","PASS").put("realUiExportNativeValidation",true).put("backupRestored",true).put("settingsPreserved",true).put("analysisPreserved",true).put("audioByteExact",true).put("duration",meta.getDouble("duration")).toString());
    }
}
