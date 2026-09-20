package com.cyberbasslord.lightforge;

import android.app.Application;
import java.io.File;

/** Process-scoped recovery runs before either UI or background-service tasks exist. */
public final class LightForgeApplication extends Application {
    private static boolean passageRecoveryAttempted;

    @Override public void onCreate() {
        super.onCreate();
        AppDiagnostics.initialize(this);
        recoverPassagesAtProcessStart(this,getCacheDir());
    }

    private static synchronized void recoverPassagesAtProcessStart(Application application,File cache) {
        // Never retry from a later component or recreated Application object:
        // the first attempt may now be followed by a live task in this process.
        if(passageRecoveryAttempted)return;
        passageRecoveryAttempted=true;
        NativeGamePassageCleanup.Result result=NativeGamePassageCleanup.recover(cache);
        if(result.failures>0)AppDiagnostics.log(application,"WARN","native-game-cache",
            "Temporary singing passage cleanup was incomplete; failed operations="+result.failures);
    }
}
