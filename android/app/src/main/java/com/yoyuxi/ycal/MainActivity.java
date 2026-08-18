package com.yoyuxi.ycal;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Context;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/**
 * 二游活动日历 - Web 套壳
 * 默认连接电脑上的局域网服务(地址首次启动配置,存入 SharedPreferences)。
 * 连接失败自动回退到「连接服务器」页;也可切换到内置离线模式(assets/www)。
 */
public class MainActivity extends Activity {

    private static final String SETTINGS_URL = "file:///android_asset/www/server.html";
    private static final String DEFAULT_SERVER = "http://192.168.50.178:5000";

    private WebView web;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);                  // localStorage 缓存
        s.setAllowFileAccess(true);
        s.setAllowUniversalAccessFromFileURLs(true);   // 连接页需跨域 fetch 探测服务器可用性
        web.addJavascriptInterface(new Bridge(), "YCalNative");
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                // 只处理主文档加载失败(服务器不可达);外链失败不劫持
                if (!request.isForMainFrame()) return;
                String failing = request.getUrl().toString();
                String server = prefs().getString("server", "");
                if (!server.isEmpty() && failing.startsWith(server)) {
                    String desc = String.valueOf(error.getDescription());
                    view.loadUrl(SETTINGS_URL + "?err=" + Uri.encode(desc));
                }
            }
        });
        setContentView(web);

        if (savedInstanceState != null) {
            web.restoreState(savedInstanceState);
        } else {
            String server = prefs().getString("server", "");
            web.loadUrl(server.isEmpty() ? SETTINGS_URL : server);
        }
    }

    private SharedPreferences prefs() {
        return getSharedPreferences("ycal", Context.MODE_PRIVATE);
    }

    /** 桥接:连接页(file://)保存地址;服务器页(http://)切换服务器入口 */
    private class Bridge {
        @JavascriptInterface
        public String getServer() {
            return prefs().getString("server", "");
        }

        @JavascriptInterface
        public String getDefaultServer() {
            return DEFAULT_SERVER;
        }

        @JavascriptInterface
        public void saveServer(String url) {
            // 只允许本地连接页保存地址,防止加载的外部网页篡改
            if (web.getUrl() == null || !web.getUrl().startsWith("file:")) return;
            prefs().edit().putString("server", url).apply();
        }

        @JavascriptInterface
        public void openSettings() {
            runOnUiThread(() -> web.loadUrl(SETTINGS_URL));
        }
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();   // 阅读公告时,返回键先退回日历
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        if (web != null) web.saveState(outState);
    }
}
