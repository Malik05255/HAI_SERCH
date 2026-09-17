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
    manifest.write_text(text, encoding="utf-8")

# Latest Flutter templates use build.gradle.kts. Keep compileSdk high enough for
# current AndroidX / Flutter plugin metadata while leaving targetSdk/minSdk under
# Flutter's defaults so runtime behavior does not change just to satisfy compile.
gradle = ROOT / "android" / "app" / "build.gradle.kts"
if gradle.exists():
    text = gradle.read_text(encoding="utf-8")
    text = text.replace("compileSdk = flutter.compileSdkVersion", "compileSdk = 36")

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
