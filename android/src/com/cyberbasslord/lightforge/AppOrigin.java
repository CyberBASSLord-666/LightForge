package com.cyberbasslord.lightforge;

/** Exact authority for the private, intercepted WebView origin. */
final class AppOrigin {
    private AppOrigin() {}
    static boolean trusted(String scheme, String encodedAuthority) {
        // No user-info, alternative ports, encoded delimiters or suffix hosts.
        // Keep this identical for navigation, assets and private native results.
        return "https".equals(scheme) && "appassets.androidplatform.net".equals(encodedAuthority);
    }
}
