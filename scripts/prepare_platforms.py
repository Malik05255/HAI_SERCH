import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "app"
manifest = ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
if manifest.exists():
    text = manifest.read_text(encoding="utf-8")
    marker = '<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
    permissions = (
        '\n    <uses-permission android:name="android.permission.INTERNET" />'
        '\n    <uses-permission android:name="android.permission.REQUEST_INSTALL_PACKAGES" />'
    )
    if "android.permission.INTERNET" not in text:
        text = text.replace(marker, marker + permissions)
    text = text.replace('android:label="deep_search"', 'android:label="البحث العميق"')
    if "android:roundIcon=" not in text:
        text = text.replace(
            'android:icon="@mipmap/ic_launcher"',
            'android:icon="@mipmap/ic_launcher"\n        android:roundIcon="@mipmap/ic_launcher_round"',
            1,
        )
    manifest.write_text(text, encoding="utf-8")

# Keep Android metadata explicit and reproducible for current Flutter/Firebase plugins.
# The package identity is pinned because Android accepts an in-place APK update only
# when applicationId + signing certificate match the installed version.
gradle = ROOT / "android" / "app" / "build.gradle.kts"
if gradle.exists():
    text = gradle.read_text(encoding="utf-8")
    text = text.replace("compileSdk = flutter.compileSdkVersion", "compileSdk = 36")
    text = text.replace("minSdk = flutter.minSdkVersion", "minSdk = 23")
    text = re.sub(r'namespace\s*=\s*"[^"]+"', 'namespace = "com.hai.deep_search"', text, count=1)
    text = re.sub(r'applicationId\s*=\s*"[^"]+"', 'applicationId = "com.hai.deep_search"', text, count=1)

    old = 'signingConfig = signingConfigs.getByName("debug")'
    new = '''signingConfig = signingConfigs.create("release") {
                keyAlias = System.getenv("ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("ANDROID_KEY_PASSWORD")
                storeFile = file(System.getenv("ANDROID_KEYSTORE_PATH") ?: "release.jks")
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
            }'''
    if old in text and (ROOT / "android" / "app" / "release.jks").exists():
        text = text.replace(old, new)
    gradle.write_text(text, encoding="utf-8")

main_cpp = ROOT / "windows" / "runner" / "main.cpp"
if main_cpp.exists():
    text = main_cpp.read_text(encoding="utf-8").replace('L"deep_search"', 'L"البحث العميق"')
    main_cpp.write_text(text, encoding="utf-8")
