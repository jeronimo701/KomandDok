package ru.j701.trips;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.os.Bundle;
import android.webkit.WebView;
import com.chaquo.python.Python;
import org.json.JSONObject;
import java.io.File;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

public final class SmokeRunner extends Instrumentation {
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){
        Bundle result=new Bundle();
        try{
            Activity activity=startActivitySync(new Intent(Intent.ACTION_MAIN)
                    .setClassName(getTargetContext().getPackageName(),"ru.j701.trips.MainActivity")
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            WebView web=(WebView)((android.view.ViewGroup)activity.findViewById(android.R.id.content)).getChildAt(0);
            String status="";
            for(int i=0;i<35;i++){
                CountDownLatch latch=new CountDownLatch(1);
                AtomicReference<String> value=new AtomicReference<>("");
                runOnMainSync(() -> web.evaluateJavascript("document.title+'|'+document.querySelectorAll('#planned input').length+'|'+typeof J701Reply",v->{value.set(v);latch.countDown();}));
                if(latch.await(2,TimeUnit.SECONDS))status=value.get();
                if(status!=null && status.contains("|5|function"))break;
                Thread.sleep(300);
            }
            if(status==null || !status.contains("|5|function"))throw new IllegalStateException("WebView didn't load the local app: "+status);
            File dir=new File(activity.getCacheDir(),"instrument-"+System.nanoTime());
            if(!dir.mkdir())throw new IllegalStateException("No test directory");
            String backend=Python.getInstance().getModule("smoke_mobile").callAttr("check",dir.getAbsolutePath()).toString();
            result.putString("stream","\nWebView: "+status+"\nAndroid runtime: "+backend+"\n");
            finish(Activity.RESULT_OK,result);
        } catch(Throwable error) {
            result.putString("stream","\n"+android.util.Log.getStackTraceString(error)+"\n");
            finish(Activity.RESULT_CANCELED,result);
        }
    }
}
