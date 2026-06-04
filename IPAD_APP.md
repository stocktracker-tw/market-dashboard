# 用 iPad（Swift Playgrounds）把網站做成 iOS App

不用 Mac、不用 Xcode。**Swift Playgrounds 4 以上（含 5）可以直接在 iPad 上做 App、甚至上架 App Store。**
做法：用一個 `WKWebView` 把現有網站包起來，再套上 iOS 26 的 **Liquid Glass** 控制列。

---

## 要花錢嗎？

| 你想做的 | 費用 |
|---|---|
| **自己 iPad 上用** | **免費**（免費 Apple ID 即可；免費簽的 App 約 7 天過期，用 Swift Playgrounds 重跑一次就續上） |
| **放上 App Store 給別人下載** | **Apple Developer Program US$99／年**（無法避開） |

> 還沒收入／粉絲少時：先別花 $99。用下面的 App 自己跑，或直接「加到主畫面」(PWA) 就有 App 體驗，零成本。

---

## 步驟（都在 iPad 上）

1. 開 **Swift Playgrounds** → 右上「＋」→ **App** → 取名 `Stock Tracker`。
2. 它會自動產生兩個檔：一個有 `@main`、一個 `ContentView`。
3. **保留 `@main` 那個檔不動**（確認裡面是 `ContentView()`）。
4. 把 **`ContentView` 那個檔整段換成下面的程式碼**。
5. 按 **▶︎ 執行** → 網站就在 App 裡跑起來（含液態玻璃控制列、下拉刷新、左右滑返回、載入進度條）。

### 上架（可選，需 $99/年）
Swift Playgrounds 專案設定 → **App Store Connect** → 直接從 iPad 上傳送審。
⚠️ 過審注意 Guideline 4.2「最低功能性」：純 WebView 殼可能被打回。本版已含下拉刷新／手勢／玻璃控制列；之後可再加**原生推播（每日分數）**最穩。

---

## 程式碼（貼進 `ContentView` 檔）

```swift
import SwiftUI
import WebKit

enum WebAction { case back, reload, home }

struct ContentView: View {
    private let home = URL(string: "https://stocktracker-tw.github.io/market-dashboard/")!
    @State private var progress = 0.0
    @State private var loading = false
    @State private var pending: WebAction?

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            WebView(home: home, progress: $progress, loading: $loading, pending: $pending)
                .ignoresSafeArea()

            // 浮動液態玻璃控制列（放左下，不會撞到網站自己置中的玻璃膠囊）
            HStack(spacing: 20) {
                btn("chevron.backward") { pending = .back }
                btn("arrow.clockwise")  { pending = .reload }
                btn("house.fill")       { pending = .home }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 12)
            .glassEffect()                       // ← iOS 26 Liquid Glass
            .padding([.leading, .bottom], 16)
        }
        .preferredColorScheme(.dark)
        .overlay(alignment: .top) {
            if loading && progress < 1 {
                ProgressView(value: progress).tint(.cyan).padding(.horizontal)
            }
        }
    }

    private func btn(_ icon: String, _ tap: @escaping () -> Void) -> some View {
        Button(action: tap) {
            Image(systemName: icon)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(.white)
                .frame(width: 28, height: 28)
        }
        .buttonStyle(.plain)
    }
}

struct WebView: UIViewRepresentable {
    let home: URL
    @Binding var progress: Double
    @Binding var loading: Bool
    @Binding var pending: WebAction?

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> WKWebView {
        let web = WKWebView()
        web.allowsBackForwardNavigationGestures = true
        web.navigationDelegate = context.coordinator
        let refresh = UIRefreshControl()
        refresh.addTarget(context.coordinator, action: #selector(Coordinator.pull(_:)), for: .valueChanged)
        web.scrollView.refreshControl = refresh
        context.coordinator.web = web
        context.coordinator.obs = web.observe(\.estimatedProgress, options: .new) { w, _ in
            DispatchQueue.main.async { progress = w.estimatedProgress }
        }
        web.load(URLRequest(url: home))
        return web
    }

    func updateUIView(_ web: WKWebView, context: Context) {
        guard let act = pending else { return }
        switch act {
        case .back:   if web.canGoBack { web.goBack() }
        case .reload: web.reload()
        case .home:   web.load(URLRequest(url: home))
        }
        DispatchQueue.main.async { pending = nil }
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        let parent: WebView
        weak var web: WKWebView?
        var obs: NSKeyValueObservation?
        init(_ p: WebView) { parent = p }
        @objc func pull(_ s: UIRefreshControl) { web?.reload(); s.endRefreshing() }
        func webView(_ w: WKWebView, didStartProvisionalNavigation n: WKNavigation!) { parent.loading = true }
        func webView(_ w: WKWebView, didFinish n: WKNavigation!) { parent.loading = false }
        func webView(_ w: WKWebView, didFail n: WKNavigation!, withError e: Error) { parent.loading = false }
    }
}
```

---

## 注意

- **`.glassEffect()`** 是 iOS 26 的 Liquid Glass，需要 **iPadOS 26+**。
  若該行紅字報錯（系統較舊），把它換成毛玻璃：
  ```swift
  .background(.ultraThinMaterial, in: Capsule())
  ```
- 控制列放左下角，不會撞到網站本身置中的玻璃導覽列。
- App 圖示／名稱在 Swift Playgrounds 的專案設定裡改；圖示可用 repo 的 `icon-512.png`。
