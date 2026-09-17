import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;
import 'package:open_filex/open_filex.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:path_provider/path_provider.dart';

final RegExp _sha256Pattern = RegExp(r'^[a-fA-F0-9]{64}$');

String? parseSha256(String value) {
  final trimmed = value.trim();
  if (trimmed.isEmpty) return null;
  final token = trimmed.split(RegExp(r'\s+')).first.toLowerCase();
  return _sha256Pattern.hasMatch(token) ? token : null;
}

int compareVersions(String a, String b) {
  List<int> parts(String value) =>
      value.split(RegExp(r'[-+]')).first.split('.').map((e) => int.tryParse(e) ?? 0).toList();
  final aa = parts(a);
  final bb = parts(b);
  for (var i = 0; i < 3; i++) {
    final av = i < aa.length ? aa[i] : 0;
    final bv = i < bb.length ? bb[i] : 0;
    if (av != bv) return av.compareTo(bv);
  }
  return 0;
}

class UpdateInfo {
  const UpdateInfo({
    required this.version,
    required this.downloadUrl,
    required this.checksumUrl,
    required this.fileName,
  });

  final String version;
  final String downloadUrl;
  final String checksumUrl;
  final String fileName;
}

class UpdateService {
  static const _latestRelease = 'https://api.github.com/repos/Malik05255/HAI_SERCH/releases/latest';

  bool lastCheckFailed = false;

  Future<UpdateInfo?> check() async {
    lastCheckFailed = false;
    try {
      final current = await PackageInfo.fromPlatform();
      final response = await http
          .get(Uri.parse(_latestRelease), headers: {'Accept': 'application/vnd.github+json'})
          .timeout(const Duration(seconds: 12));
      if (response.statusCode == 404) return null;
      if (response.statusCode != 200) {
        lastCheckFailed = true;
        return null;
      }

      final data = jsonDecode(response.body) as Map<String, dynamic>;
      final tag = ((data['tag_name'] as String?) ?? '').replaceFirst(RegExp(r'^[vV]'), '');
      if (tag.isEmpty) {
        lastCheckFailed = true;
        return null;
      }
      if (compareVersions(tag, current.version) <= 0) return null;

      final wanted = Platform.isAndroid ? 'deep-search-android.apk' : 'deep-search-windows-setup.exe';
      final checksumName = '$wanted.sha256';
      String? downloadUrl;
      String? checksumUrl;

      for (final raw in (data['assets'] as List<dynamic>? ?? const [])) {
        final asset = raw as Map<String, dynamic>;
        final name = asset['name'] as String?;
        final url = asset['browser_download_url'] as String?;
        if (url == null || url.isEmpty) continue;
        if (name == wanted) downloadUrl = url;
        if (name == checksumName) checksumUrl = url;
      }

      // A newer release without its checksum must never be presented as a
      // successful "latest version" check. It is an incomplete release.
      if (downloadUrl == null || checksumUrl == null) {
        lastCheckFailed = true;
        return null;
      }
      return UpdateInfo(
        version: tag,
        downloadUrl: downloadUrl,
        checksumUrl: checksumUrl,
        fileName: wanted,
      );
    } catch (_) {
      lastCheckFailed = true;
      return null;
    }
  }

  Future<void> install(UpdateInfo update) async {
    final expected = await _fetchExpectedChecksum(update.checksumUrl);
    final directory = await getTemporaryDirectory();
    final target = File('${directory.path}${Platform.pathSeparator}${update.fileName}');
    final partial = File('${target.path}.part');

    if (await partial.exists()) await partial.delete();
    if (await target.exists()) await target.delete();

    final client = http.Client();
    try {
      final request = http.Request('GET', Uri.parse(update.downloadUrl));
      final response = await client.send(request).timeout(const Duration(seconds: 20));
      if (response.statusCode < 200 || response.statusCode >= 300) {
        await response.stream.drain<void>();
        throw Exception('download failed');
      }

      final sink = partial.openWrite();
      try {
        await response.stream.timeout(const Duration(seconds: 30)).pipe(sink);
      } catch (_) {
        await sink.close();
        if (await partial.exists()) await partial.delete();
        rethrow;
      }
    } finally {
      client.close();
    }

    final actual = (await sha256.bind(partial.openRead()).first).toString().toLowerCase();
    if (actual != expected) {
      await partial.delete();
      throw Exception('update checksum mismatch');
    }

    await partial.rename(target.path);

    if (Platform.isWindows) {
      await Process.start(
        target.path,
        const ['/CLOSEAPPLICATIONS'],
        mode: ProcessStartMode.detached,
      );
    } else if (Platform.isAndroid) {
      final result = await OpenFilex.open(target.path, type: 'application/vnd.android.package-archive');
      if (result.type != ResultType.done) throw Exception(result.message);
    }
  }

  Future<String> _fetchExpectedChecksum(String checksumUrl) async {
    final response = await http.get(Uri.parse(checksumUrl)).timeout(const Duration(seconds: 12));
    if (response.statusCode != 200) throw Exception('checksum unavailable');
    final parsed = parseSha256(response.body);
    if (parsed == null) throw Exception('invalid checksum');
    return parsed;
  }
}
