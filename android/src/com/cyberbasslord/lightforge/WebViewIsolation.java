package com.cyberbasslord.lightforge;

import android.net.Uri;
import android.os.Looper;
import android.webkit.WebView;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;
import java.util.Collections;

/** Public, provider-gated shared memory for the app's bundled HTTPS origin. */
final class WebViewIsolation {
    static final String ORIGIN="https://appassets.androidplatform.net";
    private WebViewIsolation() {}

    static boolean isTrustedOrigin(Uri uri) {
        return uri!=null&&"https".equals(uri.getScheme())
            &&"appassets.androidplatform.net".equals(uri.getAuthority());
    }

    /** Call on the UI thread before loading either app WebView. */
    static boolean configure(WebView view) {
        if(Looper.myLooper()!=Looper.getMainLooper()) {
            AppDiagnostics.log(view.getContext(),"WARN","webview-isolation","Setup skipped outside the UI thread.");
            return false;
        }
        try {
            boolean profile=WebViewFeature.isFeatureSupported(WebViewFeature.MULTI_PROFILE);
            boolean allowlist=WebViewFeature.isFeatureSupported(WebViewFeature.CROSS_ORIGIN_ISOLATED_ALLOWLIST);
            if(!profile||!allowlist) {
                AppDiagnostics.log(view.getContext(),"INFO","webview-isolation",
                    "Provider does not support shared memory; profile="+profile+"; allowlist="+allowlist);
                return false;
            }
            // Keep the existing default profile and its IndexedDB/OPFS data.
            // Only app-owned assets receive this grant; no wildcard or remote
            // content is eligible. DIP is supplied by the shared asset transport.
            WebViewCompat.getProfile(view).setCrossOriginIsolatedAllowlist(Collections.singleton(ORIGIN));
            AppDiagnostics.log(view.getContext(),"INFO","webview-isolation","Configured the bundled app origin on the existing profile.");
            // The worker still checks crossOriginIsolated and SharedArrayBuffer
            // before selecting threads. A successful setter is not that proof.
            return true;
        } catch(RuntimeException|LinkageError error) {
            AppDiagnostics.record(view.getContext(),"webview-isolation",error);
            return false;
        }
    }
}
