package android.content;
import java.io.File;
import android.content.res.AssetManager;
import android.content.pm.PackageManager;
/** Explicit host test adapter; does not emulate Android lifecycle behavior. */
public final class Context {
    public static final String ACTIVITY_SERVICE="activity";
    private final File root,assets;
    public Context(File root,File assets){this.root=root;this.assets=assets;root.mkdirs();}
    public Context getApplicationContext(){return this;}
    public File getFilesDir(){File file=new File(root,"files");file.mkdirs();return file;}
    public File getCacheDir(){File file=new File(root,"cache");file.mkdirs();return file;}
    public AssetManager getAssets(){return new AssetManager(assets);}
    public PackageManager getPackageManager(){return new PackageManager();}
    public String getPackageName(){return "com.cyberbasslord.lightforge";}
    public Object getSystemService(String name){return new android.app.ActivityManager();}
}
