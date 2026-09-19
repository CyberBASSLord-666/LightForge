package android.app;

import java.io.File;

public class Application {
    public static File cacheDirectory;
    public void onCreate() {}
    public File getCacheDir() { return cacheDirectory; }
}
