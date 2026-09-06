package com.cyberbasslord.lightforge;

import java.io.File;
import org.json.JSONObject;

/** Playback-only proxy selection; canonical audio and export URLs stay intact. */
final class ProjectPreview {
    static JSONObject metadata(JSONObject value,File audio) throws Exception {
        boolean proxy=audio.length()>Integer.MAX_VALUE;
        value.put("sizeBytes",audio.length())
                .put("previewUrl",value.getString(proxy?"analysisUrl":"audioUrl"))
                .put("previewSampleRate",proxy?22050:44100)
                .put("previewChannels",proxy?1:2)
                .put("previewDownsampled",proxy);
        return value;
    }
}
