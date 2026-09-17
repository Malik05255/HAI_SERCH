import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:open_filex/open_filex.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:path_provider/path_provider.dart';

class UpdateInfo {
  const UpdateInfo({required this.version, required this.downloadUrl, required this.fileName});
  final String version;
  final String downloadUrl;
  final String fileName;
}

class UpdateService {
  static const _latestRelease = 'https://api.github.com/repos/Malik05255/HAI_SERCH/releases/latest';

  Future<UpdateInfo?> check() async {
    try {
      final current = await PackageInfo.fromPlatform();
      final response = await http.get(Uri.parse(_latestRelease), headers: {'Accept': 'application/vnd.github+json'});
      if (response.statusCode != 200) return null;
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      final tag = ((data['tag_name'] as String?) ?? '').replaceFirst(RegExp(r'^[vV]'), '');
      if (tag.isEmpty || _compare(tag, current.version) <= 0) return null;

      final wanted = Platform.isAndroid ? 'deep-search-android.apk' : 'deep-search-windows-setup.exe';
      final assets = (data['assets'] as List<dynamic>? ?? const []);
      for (final raw in assets) {
        final asset = raw as Map<String, dynamic>;
        if (asset['name'] == wanted && asset['browser_download_url'] is String) {
          return UpdateInfo(version: tag, downloadUrl: asset['browser_download_url'] as String, fileName: wanted);
        }
      }
    } catch (_) {}
    return null;
  }

  Future<void> install(UpdateInfo update) async {
    final directory = await getTemporaryDirectory();
    final target = File('${directory.path}${Platform.pathSeparator}${update.fileName}');
    final request = http.Request('GET', Uri.parse(update.downloadUrl));
    final response = await http.Client().send(request);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception('download failed');
    }
    final sink = target.openWrite();
    await response.stream.pipe(sink);

    if (Platform.isWindows) {
      await Process.start(target.path, const [], mode: ProcessStartMode.detached);
    } else if (Platform.isAndroid) {
      final result = await OpenFilex.open(target.path, type: 'application/vnd.android.package-archive');
      if (result.type != ResultType.done) throw Exception(result.message);
    }
  }

  int _compare(String a, String b) {
    List<int> parts(String value) => value.split(RegExp(r'[-+]')).first.split('.').map((e) => int.tryParse(e) ?? 0).toList();
    final aa = parts(a);
    final bb = parts(b);
    for (var i = 0; i < 3; i++) {
      final av = i < aa.length ? aa[i] : 0;
      final bv = i < bb.length ? bb[i] : 0;
      if (av != bv) return av.compareTo(bv);
    }
    return 0;
  }
}
