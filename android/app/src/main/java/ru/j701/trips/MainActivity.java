package ru.j701.trips;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.pdf.PdfRenderer;
import android.net.Uri;
import android.os.Bundle;
import android.os.Build;
import android.os.CancellationSignal;
import android.os.ParcelFileDescriptor;
import android.print.PageRange;
import android.print.PrintAttributes;
import android.print.PrintDocumentAdapter;
import android.print.PrintDocumentInfo;
import android.print.PrintManager;
import android.provider.OpenableColumns;
import android.util.Log;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;
import androidx.core.content.FileProvider;
import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final String HOST = "appassets.androidplatform.net";
    private static final String HOME = "https://" + HOST + "/";
    private static final int PICK = 901, EXPORT = 902, NOTIFY = 903;
    private static final int FILE_LIMIT = 50 * 1024 * 1024;
    private static final long TOTAL_LIMIT = 120L * 1024 * 1024;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private WebView web;
    private volatile PyObject engine;
    private int pickerCallback;
    private String pickerTrip;
    private String pickerKind;
    private File exportFile;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(0xff151920);
        getWindow().setNavigationBarColor(0xff151920);
        web = new WebView(this);
        web.setBackgroundColor(0xff101319);
        setContentView(web, new ViewGroup.LayoutParams(-1, -1));
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setDomStorageEnabled(true);
        web.getSettings().setAllowFileAccess(false);
        web.getSettings().setAllowContentAccess(false);
        web.getSettings().setBlockNetworkLoads(true);
        web.addJavascriptInterface(new Bridge(), "J701Native");
        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return !local(request.getUrl());
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                Uri uri=request.getUrl();
                if (!local(uri)) return failed(403,"Недоступно");
                String path=uri.getPath();
                try {
                    if ("/preview".equals(path) || "/page.jpg".equals(path)) return preview(uri);
                    if ("/".equals(path) || "/index.html".equals(path)) return asset("index.html","text/html");
                    if (path != null && path.matches("/static/[a-zA-Z0-9_.-]+")) {
                        String mime=path.endsWith(".js")?"application/javascript":path.endsWith(".css")?"text/css":path.endsWith(".gif")?"image/gif":"image/x-icon";
                        return asset(path.substring(1),mime);
                    }
                } catch(Exception error) { Log.w("J701","Local resource",error); }
                return failed(404,"Файл не найден");
            }
        });
        worker.execute(() -> {
            try {
                synchronized (MainActivity.class) {
                    if (!Python.isStarted()) Python.start(new AndroidPlatform(getApplicationContext()));
                    engine=Python.getInstance().getModule("mobile");
                    engine.callAttr("start",new File(getFilesDir(),"J701").getAbsolutePath());
                }
                runOnUiThread(() -> { if(!isDestroyed()) web.loadUrl(HOME); });
            } catch(Exception error) {
                Log.e("J701","Startup",error);
                runOnUiThread(() -> { if(!isDestroyed()) new AlertDialog.Builder(this).setTitle("КомандДок")
                    .setMessage("Приложение не смогло открыть локальные данные.").setPositiveButton("Закрыть",(d,w)->finish()).show(); });
            }
        });
    }

    private boolean local(Uri u) { return "https".equals(u.getScheme()) && HOST.equals(u.getHost()) && u.getPort()==-1; }
    private WebResourceResponse response(String mime, byte[] payload) {
        return new WebResourceResponse(mime,mime.startsWith("image/")?null:"UTF-8",new ByteArrayInputStream(payload));
    }
    private WebResourceResponse failed(int code,String message) {
        return new WebResourceResponse("text/plain","UTF-8",code,code==403?"Forbidden":"Not found",Collections.emptyMap(),new ByteArrayInputStream(message.getBytes(StandardCharsets.UTF_8)));
    }
    private WebResourceResponse asset(String path,String mime) throws IOException {
        var headers=new HashMap<String,String>();
        headers.put("Content-Security-Policy","default-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-src 'self' about:; connect-src 'none'");
        return new WebResourceResponse(mime,mime.startsWith("image/")?null:"UTF-8",200,"OK",headers,getAssets().open(path));
    }

    private File attachment(String key,String relative) {
        return new File(engine.callAttr("attachment",key,relative).toString());
    }
    private WebResourceResponse preview(Uri uri) throws Exception {
        String key=uri.getQueryParameter("id"), relative=uri.getQueryParameter("path");
        if(key==null || relative==null || !relative.toLowerCase(Locale.ROOT).endsWith(".pdf")) return failed(404,"Нужен PDF");
        try (PdfRenderer pdf=new PdfRenderer(ParcelFileDescriptor.open(attachment(key,relative),ParcelFileDescriptor.MODE_READ_ONLY))) {
            if("/preview".equals(uri.getPath())) {
                StringBuilder html=new StringBuilder("<!doctype html><html lang='ru'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><style>body{background:#333b48;margin:0}img{display:block;width:min(100%,800px);height:auto;margin:0 auto 10px;background:white;min-height:120px}</style>");
                for(int i=0;i<pdf.getPageCount();i++) html.append("<img loading='lazy' alt='Страница ").append(i+1)
                    .append("' src='/page.jpg?id=").append(Uri.encode(key)).append("&amp;path=").append(Uri.encode(relative)).append("&amp;n=").append(i).append("'>");
                return response("text/html",html.toString().getBytes(StandardCharsets.UTF_8));
            }
            int index=Integer.parseInt(uri.getQueryParameter("n"));
            if(index<0 || index>=pdf.getPageCount()) return failed(404,"Страница не найдена");
            synchronized (MainActivity.class) {
                try(PdfRenderer.Page page=pdf.openPage(index)) {
                    double scale=Math.min(1100.0/page.getWidth(),1600.0/page.getHeight());
                    Bitmap image=Bitmap.createBitmap(Math.max(1,(int)(page.getWidth()*scale)),Math.max(1,(int)(page.getHeight()*scale)),Bitmap.Config.ARGB_8888);
                    try {
                        image.eraseColor(Color.WHITE); page.render(image,null,null,PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY);
                        ByteArrayOutputStream out=new ByteArrayOutputStream(); image.compress(Bitmap.CompressFormat.JPEG,89,out);
                        return response("image/jpeg",out.toByteArray());
                    } finally {image.recycle();}
                }
            }
        }
    }

    private void deliver(int call,String payload) {
        runOnUiThread(() -> { if(!isDestroyed()) web.evaluateJavascript("J701Reply("+call+","+JSONObject.quote(payload)+")",null); });
    }
    private String failure(Exception e) {
        try { return new JSONObject().put("ok",false).put("data",new JSONObject().put("error",e.getMessage()==null?"Не удалось выполнить действие.":e.getMessage())).toString(); }
        catch(Exception ignored){return "{\"ok\":false}";}
    }
    private void toast(String text) { runOnUiThread(() -> Toast.makeText(this,text,Toast.LENGTH_LONG).show()); }

    private void pack(int call, String path, String body) {
        PdfPackService.Job job = new PdfPackService.Job() {
            @Override public JSONObject run(PdfPackService.PackProgress progress) {
                try {
                    return new JSONObject(engine.callAttr("dispatch","POST",path,body,"[]",progress).toString());
                } catch (Exception error) {
                    JSONObject data = new JSONObject(Collections.singletonMap("error",
                        Objects.toString(error.getMessage(),"Не удалось собрать PDF.")));
                    Map<String,Object> response = new HashMap<>();
                    response.put("ok",false);
                    response.put("data",data);
                    return new JSONObject(response);
                }
            }
            @Override public void update(int percent, String message) {
                runOnUiThread(() -> {
                    if (!isDestroyed()) web.evaluateJavascript(
                        "J701PackProgress("+call+","+percent+","+JSONObject.quote(message)+")",null);
                });
            }
            @Override public void reply(JSONObject result) {
                deliver(call, result.toString());
            }
        };
        try {
            if (PdfPackService.launch(this,job)) {
                requestNotificationPermission();
            } else {
                worker.execute(() -> job.reply(job.run(new PdfPackService.PackProgress(job::update))));
            }
        } catch (IllegalStateException error) {
            deliver(call, failure(error));
        }
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT < 33 || checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)==PackageManager.PERMISSION_GRANTED) return;
        var preferences = getPreferences(MODE_PRIVATE);
        if (!preferences.getBoolean("asked_for_pdf_notifications",false)) {
            preferences.edit().putBoolean("asked_for_pdf_notifications",true).apply();
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},NOTIFY);
        }
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode,permissions,results);
        if (requestCode==NOTIFY && results.length>0 && results[0]==PackageManager.PERMISSION_GRANTED) {
            PdfPackService.postLatest(this);
        }
    }

    private final class Bridge {
        @JavascriptInterface public void exit() { runOnUiThread(() -> finish()); }
        @JavascriptInterface public void request(int call,String method,String path,String body) {
            if ("POST".equals(method) && path.matches("/api/trips/[a-f0-9]{32}/pack")) {
                runOnUiThread(() -> pack(call,path,body));
                return;
            }
            worker.execute(() -> {
                try {deliver(call,engine.callAttr("dispatch",method,path,body).toString());}
                catch(Exception error) {deliver(call,failure(error));}
            });
        }
        @JavascriptInterface public void pick(int call,String trip,String kind) {
            runOnUiThread(() -> {
                if(!Arrays.asList("upload","signature").contains(kind)){deliver(call,failure(new IOException("Неизвестный тип вложения.")));return;}
                pickerCallback=call;pickerTrip=trip;pickerKind=kind;
                boolean signature="signature".equals(kind);
                Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE);
                intent.putExtra(Intent.EXTRA_MIME_TYPES,signature?new String[]{"image/png","image/jpeg"}:new String[]{"application/pdf","image/*"});
                intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE,!signature);
                try {startActivityForResult(intent,PICK);}
                catch(Exception error){deliver(call,failure(error));}
            });
        }
        @JavascriptInterface public void document(String mode,String trip,String path) {
            if(!Arrays.asList("open","share","print","export").contains(mode))return;
            worker.execute(() -> {
                try {
                    File file=attachment(trip,path);
                    switch(mode){
                        case "print": runOnUiThread(() -> print(file));break;
                        case "export": runOnUiThread(() -> export(file));break;
                        default: share(mode,file);
                    }
                } catch(Exception error){ toast("Файл недоступен: "+error.getMessage()); }
            });
        }
    }

    @Override protected void onActivityResult(int code,int result,Intent data) {
        super.onActivityResult(code,result,data);
        if(code==PICK){
            int call=pickerCallback;String trip=pickerTrip,kind=pickerKind;
            if(result!=RESULT_OK || data==null){deliver(call,"{\"ok\":true,\"data\":null}");return;}
            List<Uri> uris=new ArrayList<>();ClipData clip=data.getClipData();
            if(clip!=null)for(int i=0;i<clip.getItemCount();i++)uris.add(clip.getItemAt(i).getUri());
            else if(data.getData()!=null)uris.add(data.getData());
            worker.execute(() -> upload(call,trip,kind,uris));
        } else if(code==EXPORT){
            File file=exportFile;exportFile=null;
            if(result==RESULT_OK && data!=null && data.getData()!=null && file!=null)worker.execute(() -> {
                try(InputStream in=new FileInputStream(file);OutputStream out=getContentResolver().openOutputStream(data.getData(),"wt")){
                    if(out==null)throw new IOException("Место сохранения недоступно");
                    copy(in,out,Long.MAX_VALUE);toast("Файл сохранён");
                }catch(Exception e){toast("Не удалось сохранить файл: "+e.getMessage());}
            });
        }
    }
    private void upload(int call,String trip,String kind,List<Uri> uris){
        List<File> staged=new ArrayList<>();
        try{
            if(uris.isEmpty()){deliver(call,"{\"ok\":true,\"data\":null}");return;}
            boolean signature="signature".equals(kind);
            if(signature && uris.size()!=1)throw new IOException("Выберите один файл подписи.");
            if(uris.size()>50)throw new IOException("Выберите не больше 50 файлов за раз.");
            JSONArray items=new JSONArray();
            long bytes=0;
            for(Uri uri:uris){
                String name="Вложение";String mime=getContentResolver().getType(uri);
                try(var cursor=getContentResolver().query(uri,new String[]{OpenableColumns.DISPLAY_NAME},null,null,null)){
                    if(cursor!=null && cursor.moveToFirst() && cursor.getString(0)!=null)name=cursor.getString(0);
                }
                if(!name.contains(".") && mime!=null){
                    String ext=android.webkit.MimeTypeMap.getSingleton().getExtensionFromMimeType(mime);
                    if(ext!=null)name+="."+ext;
                }
                File temp=File.createTempFile("receipt-",".tmp",getCacheDir());staged.add(temp);
                try(InputStream in=getContentResolver().openInputStream(uri);OutputStream out=new FileOutputStream(temp)){
                    if(in==null)throw new IOException("Файл недоступен: "+name);
                    bytes+=copy(in,out,signature?10L*1024*1024:Math.min(FILE_LIMIT,TOTAL_LIMIT-bytes));
                }
                items.put(new JSONObject().put("name",name).put("staged",temp.getAbsolutePath()));
            }
            deliver(call,engine.callAttr("dispatch","POST","/api/trips/"+trip+"/"+kind,"",items.toString()).toString());
        }catch(Exception e){deliver(call,failure(e));}
        finally{for(File file:staged)file.delete();}
    }
    private static long copy(InputStream in,OutputStream out,long limit) throws IOException {
        long count=0;byte[] buffer=new byte[32768];int n;
        while((n=in.read(buffer))!=-1){
            count+=n;if(count>limit)throw new IOException("Превышен лимит вложений: 50 МБ на файл, 120 МБ за раз.");
            out.write(buffer,0,n);
        }return count;
    }
    private static String mime(File file){
        String name=file.getName();int dot=name.lastIndexOf('.');
        String type=dot<0?null:android.webkit.MimeTypeMap.getSingleton().getMimeTypeFromExtension(name.substring(dot+1).toLowerCase(Locale.ROOT));
        return type==null?"application/octet-stream":type;
    }
    private void share(String mode,File file) throws IOException{
        File root=new File(getCacheDir(),"exports");
        File[] previous=root.listFiles();
        if(previous!=null)for(File dir:previous)if(dir.isDirectory()&&dir.lastModified()<System.currentTimeMillis()-86400000L){
            File[] files=dir.listFiles();if(files!=null)for(File old:files)old.delete();dir.delete();
        }
        File directory=new File(root,UUID.randomUUID().toString());
        if(!directory.mkdirs())throw new IOException("Не удалось подготовить файл.");
        File exported=new File(directory,file.getName());
        try(InputStream in=new FileInputStream(file);OutputStream out=new FileOutputStream(exported)){copy(in,out,Long.MAX_VALUE);}
        Uri uri=FileProvider.getUriForFile(this,getPackageName()+".files",exported);
        runOnUiThread(() -> {
            Intent intent;
            if("share".equals(mode))intent=new Intent(Intent.ACTION_SEND).setType(mime(exported)).putExtra(Intent.EXTRA_STREAM,uri);
            else intent=new Intent(Intent.ACTION_VIEW).setDataAndType(uri,mime(exported));
            intent.setClipData(ClipData.newRawUri(exported.getName(),uri));intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            try {startActivity(Intent.createChooser(intent,"share".equals(mode)?"Поделиться файлом":"Открыть файл"));}
            catch(Exception e){toast("На телефоне нет приложения для этого файла. Используйте «Сохранить PDF».");}
        });
    }
    private void export(File file){
        exportFile=file;
        Intent intent=new Intent(Intent.ACTION_CREATE_DOCUMENT).setType(mime(file)).addCategory(Intent.CATEGORY_OPENABLE).putExtra(Intent.EXTRA_TITLE,file.getName());
        try{startActivityForResult(intent,EXPORT);}catch(Exception e){exportFile=null;toast("Не удалось открыть диалог сохранения.");}
    }
    private void print(File file) {
        try {
            PrintManager manager=(PrintManager)getSystemService(PRINT_SERVICE);
            if(manager==null)throw new IllegalStateException("Печать недоступна");
            manager.print(file.getName(),new PrintDocumentAdapter(){
                int count;
                @Override public void onLayout(PrintAttributes old,PrintAttributes attrs,CancellationSignal cancel,LayoutResultCallback callback,Bundle extras){
                    if(cancel.isCanceled()){callback.onLayoutCancelled();return;}
                    try(PdfRenderer renderer=new PdfRenderer(ParcelFileDescriptor.open(file,ParcelFileDescriptor.MODE_READ_ONLY))){
                        count=renderer.getPageCount();
                        callback.onLayoutFinished(new PrintDocumentInfo.Builder(file.getName()).setContentType(PrintDocumentInfo.CONTENT_TYPE_DOCUMENT).setPageCount(count).build(),!attrs.equals(old));
                    }catch(Exception e){callback.onLayoutFailed("Не удалось прочитать PDF");}
                }
                @Override public void onWrite(PageRange[] ranges,ParcelFileDescriptor dest,CancellationSignal cancel,WriteResultCallback callback){
                    worker.execute(() -> {
                        File selected=null;
                        try(OutputStream out=new ParcelFileDescriptor.AutoCloseOutputStream(dest)){
                            if(cancel.isCanceled()){callback.onWriteCancelled();return;}
                            boolean all=ranges.length==1 && ranges[0].getStart()==0 && ranges[0].getEnd()>=count-1;
                            File input=file;
                            if(!all){
                                JSONArray subset=new JSONArray();
                                for(PageRange range:ranges)subset.put(new JSONArray().put(range.getStart()).put(range.getEnd()));
                                selected=File.createTempFile("print-",".pdf",getCacheDir());
                                engine.callAttr("print_ranges",file.getAbsolutePath(),selected.getAbsolutePath(),subset.toString());input=selected;
                            }
                            try(InputStream in=new FileInputStream(input)){copy(in,out,Long.MAX_VALUE);out.flush();}
                            if(cancel.isCanceled())callback.onWriteCancelled();else callback.onWriteFinished(ranges);
                        }catch(Exception e){callback.onWriteFailed("Не удалось подготовить PDF");}
                        finally{if(selected!=null)selected.delete();}
                    });
                }
            },new PrintAttributes.Builder().setMediaSize(PrintAttributes.MediaSize.ISO_A4).build());
        }catch(Exception e){toast("Печать недоступна: "+e.getMessage());}
    }
    @Override public void onBackPressed() {
        web.evaluateJavascript("J701Back()",null);
    }
    @Override protected void onDestroy(){
        worker.shutdown();
        if(web!=null){web.removeJavascriptInterface("J701Native");web.destroy();}
        super.onDestroy();
    }
}
