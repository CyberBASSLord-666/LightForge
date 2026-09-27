package android.content;
/** Compile-only Android boundary; no Android lifecycle simulation. */
public final class Context {
    public Context getApplicationContext(){return this;}
    public android.content.res.AssetManager getAssets(){throw new AssertionError("Android API called");}
    public java.io.File getCacheDir(){throw new AssertionError("Android API called");}
}
