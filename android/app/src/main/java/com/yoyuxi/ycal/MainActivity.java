package com.yoyuxi.ycal;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
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
        // 外部链接与 window.open 一律交系统浏览器,防止在 WebView 内顶掉 App 页面导致无法返回
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onCreateWindow(WebView view, boolean isDialog, boolean isUserGesture, android.os.Message resultMsg) {
                WebView newWeb = new WebView(MainActivity.this);
                newWeb.getSettings().setJavaScriptEnabled(true);
                WebView.WebViewTransport transport = (WebView.WebViewTransport) resultMsg.obj;
                transport.setWebView(newWeb);
                resultMsg.sendToTarget();
                return true;
            }
        });
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri u = request.getUrl();
                // 空白名单:只有与当前页面同源(scheme+host+端口)才在 WebView 内加载,其余一律外抛
                // 爬虫模式(未配置服务器)时页面是 file://,除 file: 内置页面外全部外抛
                if (!isSameOrigin(u, view.getUrl())) {
                    openExternal(u.toString());
                    return true;
                }
                return false;
            }

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

    /** 与当前页面同源判定:scheme 与 host 必须相同,端口按默认端口(80/443)归一后比较 */
    private static boolean isSameOrigin(Uri u, String current) {
        if (u == null || current == null) return false;
        String scheme = u.getScheme();
        if (scheme == null) return false;
        Uri cur;
        try {
            cur = Uri.parse(current);
        } catch (Exception e) {
            return false;
        }
        String curScheme = cur.getScheme();
        if ("file".equalsIgnoreCase(scheme) || "file".equalsIgnoreCase(curScheme)) {
            // 内置页面:同 scheme 且在 assets/www 内即视为同源
            return "file".equalsIgnoreCase(scheme) && "file".equalsIgnoreCase(curScheme);
        }
        String host = u.getHost();
        if (host == null || !scheme.equalsIgnoreCase(curScheme)) return false;
        String curHost = cur.getHost();
        if (curHost == null || !host.equalsIgnoreCase(curHost)) return false;
        return port(u) == port(cur);
    }

    /** 端口归一:未写端口时 http=80 / https=443,便于与显式写了同一端口的链接比较 */
    private static int port(Uri u) {
        int p = u.getPort();
        if (p != -1) return p;
        return "https".equalsIgnoreCase(u.getScheme()) ? 443 : 80;
    }

    private SharedPreferences prefs() {
        return getSharedPreferences("ycal", Context.MODE_PRIVATE);
    }

    /** 站外链接:交系统浏览器打开(原帖在新窗口,App 页面保留,返回键直接回日历) */
    private void openExternal(String url) {
        if (url == null || url.isEmpty()) return;
        try {
            Uri uri = Uri.parse(url);
            String scheme = uri.getScheme();
            if (!"http".equalsIgnoreCase(scheme) && !"https".equalsIgnoreCase(scheme)) return;
            Intent i = new Intent(Intent.ACTION_VIEW, uri);
            runOnUiThread(() -> startActivity(i));
        } catch (Exception e) {
            // 无浏览器等异常:静默忽略
        }
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

        @JavascriptInterface
        public void openExternal(String url) {
            MainActivity.this.openExternal(url);
        }
    }

    @Override
    public void onBackPressed() {
        // 先关掉弹层(JS 层已处理),WebView 有内部历史则回退,否则退回桌面/上一页
        if (web != null && web.canGoBack()) {
            web.goBack();
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
