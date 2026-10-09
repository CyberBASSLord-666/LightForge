package com.cyberbasslord.lightforge;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

/** Visible, separate diagnostic application. It cannot open user audio or replace LightForge. */
public final class ProbeActivity extends Activity {
    private static final int EXPORT = 41;
    private final Handler main = new Handler(Looper.getMainLooper());
    private ProbeRunner runner;
    private TextView status;
    private Button run, cancel, export;
    private boolean choosingExport;
    private String exportSnapshot;
    private final Runnable refresh = new Runnable() {
        @Override public void run() {
            if (runner == null) return;
            status.setText(runner.status());
            boolean active = runner.isRunning();
            run.setEnabled(!active); cancel.setEnabled(active);
            export.setEnabled(!active && runner.hasReceipt());
            if (active) getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            main.postDelayed(this, 1000);
        }
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        runner = ProbeRunner.get(getApplicationContext());
        if (state != null) { choosingExport = state.getBoolean("choosingExport"); exportSnapshot = state.getString("exportSnapshot"); }
        LinearLayout content = new LinearLayout(this); content.setOrientation(LinearLayout.VERTICAL);
        int pad = (int)(20 * getResources().getDisplayMetrics().density); content.setPadding(pad, pad, pad, pad);
        TextView title = new TextView(this); title.setTextSize(23); title.setText("DEVELOPMENT — inference diagnostic"); content.addView(title);
        TextView explanation = new TextView(this);
        explanation.setText("This separate app tests the corrected CPU engine using only a bundled licensed Falcon excerpt. It reads LightForge's installed model assets; projects, settings and user audio are not opened.\n\n"
            + "Run schedules 35 complete benchmark passages with the real Android admission policy. The repeated short excerpt is not a full-song quality test. Expect tens of minutes, about 1 GB temporary disk use, sustained CPU/memory use and battery drain. Keep this screen visible. Leaving it cancels the run; rotation retains it. Severe thermal status also cancels.\n\n"
            + "A completed receipt is evidence, not a speedup or release approval. Baseline fallback is a valid observed outcome. Export contains source/model identities, performance, device/power observations and output hashes; no audio.\n\n"
            + "Fixture: The Easton Ellises — Falcon 69, MUSDB18 seven-second excerpt, CC BY-NC-SA 3.0. Noncommercial diagnostic use; see bundled provenance.\n");
        content.addView(explanation);
        run = button(content, "Run 35-passage diagnostic", view -> {
            runner.start(); run.setEnabled(false); export.setEnabled(false); cancel.setEnabled(true);
        });
        cancel = button(content, "Cancel and retire inference", view -> runner.cancel("user-cancelled"));
        export = button(content, "Export JSON receipt", view -> {
            if (runner.isRunning()) return;
            exportSnapshot = runner.receipt(); choosingExport = true;
            Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                .setType("application/json").putExtra(Intent.EXTRA_TITLE, "lightforge-inference-probe.json");
            try { startActivityForResult(intent, EXPORT); }
            catch (RuntimeException error) { choosingExport = false; status.setText("No document exporter is available."); }
        });
        status = new TextView(this); status.setTextIsSelectable(true); content.addView(status);
        ScrollView scroll = new ScrollView(this); scroll.addView(content); setContentView(scroll);
    }
    private Button button(LinearLayout parent, String label, View.OnClickListener action) {
        Button result = new Button(this); result.setText(label); result.setOnClickListener(action); parent.addView(result); return result;
    }
    @Override protected void onStart() { super.onStart(); main.removeCallbacks(refresh); main.post(refresh); }
    @Override protected void onStop() {
        main.removeCallbacks(refresh);
        if (!isChangingConfigurations() && !choosingExport && runner != null) runner.cancel("activity-not-visible");
        super.onStop();
    }
    @Override protected void onSaveInstanceState(Bundle out) {
        out.putBoolean("choosingExport", choosingExport); out.putString("exportSnapshot", exportSnapshot); super.onSaveInstanceState(out);
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request != EXPORT) return;
        choosingExport = false;
        if (result != RESULT_OK || data == null || data.getData() == null || exportSnapshot == null) return;
        final Uri uri = data.getData(); final String text = exportSnapshot; exportSnapshot = null;
        new Thread(() -> {
            try (OutputStream stream = getContentResolver().openOutputStream(uri, "wt")) {
                if (stream == null) throw new java.io.IOException();
                stream.write(text.getBytes(StandardCharsets.UTF_8)); stream.flush();
                main.post(() -> status.setText("Receipt exported."));
            } catch (Exception error) { main.post(() -> status.setText("Receipt export failed; the private copy remains available.")); }
        }, "probe-receipt-export").start();
    }
}
