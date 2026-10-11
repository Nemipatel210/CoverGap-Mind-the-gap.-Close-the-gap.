# Sevaro Doctor (Flutter)

The off-shift doctor's phone app. It opens the command center's doctor view (`/m`) full-screen, so offers, the AI-assisted call and accept/decline all run on the same backend as the web command center. One codebase for the logic, a real installable app for the doctor.

What the app adds on top of the web view:
- Its own icon and name, opens full-screen with no browser bars.
- Microphone permission for the AI-assisted call (say "yes" or "no").
- Ringtone and voice play without an extra tap on Android.
- Pull to refresh, Android back button, and an offline screen with "Try again".

## Run it

```bash
cd mobile
flutter create . --org org.sevaro --project-name sevaro_doctor   # generates android/ and ios/ folders
flutter pub get
flutter run --dart-define=SEVARO_URL=http://<your-laptop-ip>:5173/m
```

Start the frontend with `npm run dev -- --host` so the phone can reach it. The Android emulator default (`10.0.2.2`) points at your laptop.

### Android: `android/app/src/main/AndroidManifest.xml`

Inside `<manifest>`:
```xml
<uses-permission android:name="android.permission.INTERNET"/>
<uses-permission android:name="android.permission.RECORD_AUDIO"/>
<uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS"/>
```
On `<application>` add `android:usesCleartextTraffic="true"` (the demo server is plain http on your network).

### iOS: `ios/Runner/Info.plist`

```xml
<key>NSMicrophoneUsageDescription</key>
<string>The coverage assistant listens for your yes or no during a shift-offer call.</string>
<key>NSAppTransportSecurity</key>
<dict><key>NSAllowsArbitraryLoads</key><true/></dict>
```
In `ios/Podfile`, add `'PERMISSION_MICROPHONE=1'` to the permission_handler preprocessor definitions.

## Notes
- Voice recognition inside an app web view depends on the platform; if it's unavailable the call shows Accept / Decline buttons, which work everywhere.
- All data is synthetic. No patient information is sent to the phone.
