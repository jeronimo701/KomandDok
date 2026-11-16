package ru.j701.trips;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;
import androidx.core.app.NotificationCompat;
import androidx.core.content.ContextCompat;
import org.json.JSONObject;

/** Keeps a user-started PDF assembly running when the app goes to the background. */
public final class PdfPackService extends Service {
    private static final String CHANNEL = "pdf-pack";
    private static final int NOTIFICATION = 1440;
    private static final int RESULT_NOTIFICATION = 1441;
    private static Job pending;
    private static Notification latest;
    private static int latestId;
    private boolean running;

    interface Job {
        JSONObject run(PackProgress progress);
        void update(int percent, String message);
        void reply(JSONObject result);
    }

    /** Called on the main thread. If Android declines background startup, the caller can run locally. */
    static boolean launch(Context context, Job job) {
        if (pending != null) throw new IllegalStateException("Один комплект уже собирается.");
        pending = job;
        try {
            ContextCompat.startForegroundService(context, new Intent(context, PdfPackService.class));
            return true;
        } catch (IllegalStateException | SecurityException error) {
            pending = null;
            Log.w("J701", "Foreground service unavailable", error);
            return false;
        }
    }

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        Job job = pending;
        if (job == null) {
            stopSelf(startId);
            return START_NOT_STICKY;
        }
        if (running) return START_NOT_STICKY;
        running = true;
        Context context = getApplicationContext();
        createChannel(context);
        context.getSystemService(NotificationManager.class).cancel(RESULT_NOTIFICATION);
        latestId = NOTIFICATION;
        latest = progressNotification(context, 0, "Проверяем файлы");
        try {
            startForeground(NOTIFICATION, latest);
        } catch (IllegalStateException | SecurityException error) {
            Log.w("J701", "Foreground promotion unavailable", error);
            stopSelf(startId);
        }
        Handler main = new Handler(Looper.getMainLooper());
        new Thread(() -> {
            PackProgress progress = new PackProgress((percent, message) -> {
                job.update(percent, message);
                main.post(() -> {
                    latest = progressNotification(context, percent, message);
                    postLatest(context);
                });
            });
            JSONObject result = job.run(progress);
            main.post(() -> {
                stopForeground(STOP_FOREGROUND_REMOVE);
                latestId = RESULT_NOTIFICATION;
                latest = resultNotification(context, result);
                postLatest(context);
                pending = null;
                running = false;
                stopSelfResult(startId);
                job.reply(result);
            });
        }, "j701-pdf-pack").start();
        return START_NOT_STICKY;
    }

    static void postLatest(Context context) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (latest == null || !manager.areNotificationsEnabled()) return;
        try {
            manager.notify(latestId, latest);
        } catch (SecurityException ignored) {
            // Permission can change while a pack is running.
        }
    }

    private static void createChannel(Context context) {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel channel = new NotificationChannel(CHANNEL, "Подготовка PDF", NotificationManager.IMPORTANCE_LOW);
            context.getSystemService(NotificationManager.class).createNotificationChannel(channel);
        }
    }

    private static NotificationCompat.Builder notification(Context context) {
        Intent intent = new Intent(context, MainActivity.class)
            .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent open = PendingIntent.getActivity(context, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_pdf_notification).setContentIntent(open)
            .setPriority(NotificationCompat.PRIORITY_LOW).setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setOnlyAlertOnce(true);
    }

    private static Notification progressNotification(Context context, int percent, String message) {
        return notification(context).setContentTitle("Подготовка PDF · "+percent+"%")
            .setContentText(message).setOngoing(true).setProgress(100, percent, false)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE).build();
    }

    private static Notification resultNotification(Context context, JSONObject result) {
        JSONObject data = result.optJSONObject("data");
        if (result.optBoolean("ok") && data != null) {
            return notification(context).setContentTitle("PDF готов")
                .setContentText("Комплект сохранён · страниц: "+data.optInt("pages"))
                .setAutoCancel(true).build();
        }
        String message = data == null ? "Откройте КомандДок и повторите попытку." :
            data.optString("error", "Откройте КомандДок и повторите попытку.");
        return notification(context).setContentTitle("Не удалось собрать PDF")
            .setContentText(message).setStyle(new NotificationCompat.BigTextStyle().bigText(message))
            .setAutoCancel(true).build();
    }

    interface Update {
        void send(int percent, String message);
    }

    /** Public callback used by Chaquopy. Throttling avoids flooding WebView and the status bar. */
    public static final class PackProgress {
        private final Update callback;
        private long last;

        PackProgress(Update callback) { this.callback = callback; }

        @androidx.annotation.Keep
        public void update(int percent, String message) {
            long now = SystemClock.elapsedRealtime();
            if (percent > 7 && percent < 95 && now-last < 250) return;
            last = now;
            callback.send(percent, message);
        }
    }
}
