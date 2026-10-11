import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';
import 'package:webview_flutter_wkwebview/webview_flutter_wkwebview.dart';

/// Address of the command center's doctor view. Override at build time:
///   flutter run --dart-define=SEVARO_URL=http://192.168.1.20:5173/m
const String sevaroUrl = String.fromEnvironment('SEVARO_URL', defaultValue: 'http://10.0.2.2:5173/m');

// Brand colours, matching the web command center.
const Color navy = Color(0xFF123D56);
const Color teal = Color(0xFF087E8B);
const Color canvas = Color(0xFFF3F7F9);

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(statusBarColor: navy, statusBarIconBrightness: Brightness.light));
  runApp(const SevaroDoctorApp());
}

class SevaroDoctorApp extends StatelessWidget {
  const SevaroDoctorApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Sevaro Doctor',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorScheme: ColorScheme.fromSeed(seedColor: teal, primary: teal), scaffoldBackgroundColor: canvas, useMaterial3: true),
      home: const DoctorShell(),
    );
  }
}

/// Hosts the doctor view full-screen. Offers, approvals and AI-assisted calls all come from the command center,
/// so the phone shows exactly what the clinical lead approved. No patient information is ever sent to the phone.
class DoctorShell extends StatefulWidget {
  const DoctorShell({super.key});

  @override
  State<DoctorShell> createState() => _DoctorShellState();
}

class _DoctorShellState extends State<DoctorShell> {
  late final WebViewController _controller;
  int _progress = 0;
  String? _error;

  @override
  void initState() {
    super.initState();
    // The AI-assisted call can listen for "yes" or "no"; ask for the microphone up front.
    Permission.microphone.request();

    final PlatformWebViewControllerCreationParams params = WebViewPlatform.instance is WebKitWebViewPlatform
        ? WebKitWebViewControllerCreationParams(allowsInlineMediaPlayback: true, mediaTypesRequiringUserAction: const <PlaybackMediaTypes>{})
        : const PlatformWebViewControllerCreationParams();

    _controller = WebViewController.fromPlatformCreationParams(
      params,
      onPermissionRequest: (WebViewPermissionRequest request) => request.grant(),
    )
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(canvas)
      ..setNavigationDelegate(NavigationDelegate(
        onProgress: (p) => setState(() => _progress = p),
        onPageStarted: (_) => setState(() => _error = null),
        onWebResourceError: (e) {
          if (e.isForMainFrame ?? true) setState(() => _error = e.description);
        },
      ))
      ..loadRequest(Uri.parse(sevaroUrl));

    if (_controller.platform is AndroidWebViewController) {
      // Let the call ringtone and voice play without an extra tap.
      (_controller.platform as AndroidWebViewController).setMediaPlaybackRequiresUserGesture(false);
    }
  }

  Future<void> _retry() async {
    setState(() => _error = null);
    await _controller.loadRequest(Uri.parse(sevaroUrl));
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) async {
        if (!didPop && await _controller.canGoBack()) _controller.goBack();
      },
      child: Scaffold(
        body: SafeArea(
          child: Stack(children: [
            RefreshIndicator(
              color: teal,
              onRefresh: () => _controller.reload(),
              child: WebViewWidget(controller: _controller),
            ),
            if (_progress < 100 && _error == null) LinearProgressIndicator(value: _progress / 100, color: teal, backgroundColor: Colors.transparent),
            if (_error != null) _Offline(message: _error!, onRetry: _retry),
          ]),
        ),
      ),
    );
  }
}

class _Offline extends StatelessWidget {
  const _Offline({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: canvas,
      padding: const EdgeInsets.all(24),
      child: Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.wifi_off_rounded, size: 48, color: navy),
          const SizedBox(height: 16),
          const Text("Can't reach the command center", style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600, color: navy)),
          const SizedBox(height: 8),
          Text('Check that the server is running and this phone is on the same network.\n$message',
              textAlign: TextAlign.center, style: const TextStyle(color: Color(0xFF334155))),
          const SizedBox(height: 20),
          FilledButton(onPressed: onRetry, style: FilledButton.styleFrom(backgroundColor: teal), child: const Text('Try again')),
        ]),
      ),
    );
  }
}
