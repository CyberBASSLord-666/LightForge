package com.cyberbasslord.lightforge;

public final class AppOriginTest {
    public static void main(String[] args) {
        if (!AppOrigin.trusted("https", "appassets.androidplatform.net"))
            throw new AssertionError("Bundled application origin rejected");
        for (String authority : new String[]{null, "", "appassets.androidplatform.net:444",
                "appassets.androidplatform.net:443", "user@appassets.androidplatform.net",
                "appassets.androidplatform.net.attacker.invalid", "appassets.androidplatform.net@attacker.invalid",
                "appassets.androidplatform.net.", "appassets%2eandroidplatform.net",
                "appassets.androidplatform.net%3a444", "appassets.androidplatform.net\\@attacker.invalid"}) {
            if (AppOrigin.trusted("https", authority)) throw new AssertionError("Accepted authority: " + authority);
        }
        for (String scheme : new String[]{null, "http", "file", "content", "data", "javascript", "blob"}) {
            if (AppOrigin.trusted(scheme, "appassets.androidplatform.net"))
                throw new AssertionError("Accepted scheme: " + scheme);
        }
        System.out.println("PASS: exact private WebView origin checks");
    }
}
