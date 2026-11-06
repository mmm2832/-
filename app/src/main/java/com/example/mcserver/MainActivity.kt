package com.example.mcserver

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.util.Base64
import android.view.Gravity
import android.view.View
import android.webkit.*
import android.widget.*
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID

class MainActivity : Activity() {
    private val port = 8080
    private lateinit var web: WebView
    private lateinit var home: LinearLayout
    private lateinit var status: TextView
    private var chooser: ValueCallback<Array<Uri>>? = null

    private val token: String
        get() {
            val sp = getSharedPreferences("p", 0)
            return sp.getString("t", null) ?: UUID.randomUUID().toString().replace("-", "")
                .also { sp.edit().putString("t", it).apply() }
        }

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        val root = FrameLayout(this)
        web = WebView(this).apply { visibility = View.GONE }
        home = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER; setPadding(48, 48, 48, 48)
        }
        status = TextView(this).apply { textSize = 16f; gravity = Gravity.CENTER; text = "MC 서버 (Termux 필요)" }
        home.addView(status)
        fun btn(t: String, f: () -> Unit) = Button(this).apply { text = t; setOnClickListener { f() } }.also { home.addView(it) }
        btn("1. 초기 설정 (Python/Java 설치)") { setup() }
        btn("2. 패널 시작") { startPanel() }
        btn("패널 열기") { checkAndShow() }
        root.addView(web); root.addView(home)
        setContentView(root)

        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.webViewClient = WebViewClient()
        web.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(w: WebView, cb: ValueCallback<Array<Uri>>, p: FileChooserParams): Boolean {
                chooser?.onReceiveValue(null); chooser = cb
                startActivityForResult(p.createIntent(), 1); return true
            }
            override fun onJsAlert(v: WebView, u: String, m: String, r: JsResult): Boolean {
                AlertDialog.Builder(this@MainActivity).setMessage(m)
                    .setPositiveButton("확인") { _, _ -> r.confirm() }.setOnCancelListener { r.cancel() }.show()
                return true
            }
            override fun onJsConfirm(v: WebView, u: String, m: String, r: JsResult): Boolean {
                AlertDialog.Builder(this@MainActivity).setMessage(m)
                    .setPositiveButton("확인") { _, _ -> r.confirm() }
                    .setNegativeButton("취소") { _, _ -> r.cancel() }.setOnCancelListener { r.cancel() }.show()
                return true
            }
        }
        checkAndShow()
    }

    override fun onActivityResult(req: Int, res: Int, data: Intent?) {
        if (req == 1) { chooser?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(res, data)); chooser = null }
    }

    private fun termux(script: String, background: Boolean) {
        val i = Intent("com.termux.RUN_COMMAND").setClassName("com.termux", "com.termux.app.RunCommandService")
            .putExtra("com.termux.RUN_COMMAND_PATH", "/data/data/com.termux/files/usr/bin/bash")
            .putExtra("com.termux.RUN_COMMAND_ARGUMENTS", arrayOf("-c", script))
            .putExtra("com.termux.RUN_COMMAND_WORKDIR", "/data/data/com.termux/files/home")
            .putExtra("com.termux.RUN_COMMAND_BACKGROUND", background)
        try {
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(i) else startService(i)
        } catch (e: Exception) {
            status.text = "Termux 실행 실패: ${e.message}\nTermux 설치/권한 설정을 확인하세요."
        }
    }

    private fun setup() {
        status.text = "Termux 창에서 설치가 진행돼요. 끝나면 돌아와서 2번을 누르세요."
        termux("pkg update -y && pkg install -y python openjdk-21; echo; echo 완료. 이 창을 닫고 앱으로 돌아가세요.; sleep 5", false)
    }

    private fun startPanel() {
        val b64 = Base64.encodeToString(assets.open("mcpanel.py").readBytes(), Base64.NO_WRAP)
        val py = "/data/data/com.termux/files/usr/bin/python"
        termux("echo $b64 | base64 -d > ~/mcpanel.py && MCPANEL_TOKEN=$token exec $py ~/mcpanel.py", true)
        status.text = "패널 시작 중…"
        Thread {
            repeat(40) {
                if (alive()) { runOnUiThread { show() }; return@Thread }
                Thread.sleep(1000)
            }
            runOnUiThread { status.text = "패널이 안 켜졌어요. 1번 설정과 Termux 외부 앱 허용을 확인하세요." }
        }.start()
    }

    private fun alive(): Boolean = try {
        (URL("http://127.0.0.1:$port/?t=$token").openConnection() as HttpURLConnection).run {
            connectTimeout = 800; readTimeout = 800; responseCode == 200
        }
    } catch (e: Exception) { false }

    private fun checkAndShow() { Thread { val ok = alive(); runOnUiThread { if (ok) show() else status.text = "패널이 꺼져 있어요. 2번을 누르세요." } }.start() }

    private fun show() {
        home.visibility = View.GONE; web.visibility = View.VISIBLE
        web.loadUrl("http://127.0.0.1:$port/?t=$token")
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (web.visibility == View.VISIBLE && web.canGoBack()) web.goBack() else super.onBackPressed()
    }
}
