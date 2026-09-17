import 'dart:convert';
import 'dart:io';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

import 'models.dart';
import 'notification_service.dart';

class ApiClient {
  ApiClient();

  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );

  static const FlutterSecureStorage _storage = FlutterSecureStorage();
  String? _token;
  bool _initialized = false;

  String get deviceName {
    if (Platform.isWindows) return 'Windows';
    if (Platform.isAndroid) return 'Android';
    return 'Device';
  }

  Future<void> init() async {
    if (_initialized) return;
    _token = await _storage.read(key: 'deep_search_device_token');
    if (_token == null || _token!.isEmpty) {
      await _register();
    }
    _initialized = true;
    await NotificationService.initialize();
  }

  Future<void> _register() async {
    final response = await http.post(
      Uri.parse('$baseUrl/v1/auth/register'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'name': deviceName}),
    );
    _ensureOk(response);
    await _saveAuth(jsonDecode(response.body) as Map<String, dynamic>);
  }

  Future<void> _saveAuth(Map<String, dynamic> payload) async {
    final token = payload['token'] as String?;
    if (token == null || token.isEmpty) throw Exception('missing device token');
    _token = token;
    await _storage.write(key: 'deep_search_device_token', value: token);
    final id = payload['device_id'] as String?;
    if (id != null) await _storage.write(key: 'deep_search_device_id', value: id);
    await NotificationService.refreshRegistration();
  }

  Future<void> _recoverAuth() async {
    _token = null;
    _initialized = false;
    await _storage.delete(key: 'deep_search_device_token');
    await _storage.delete(key: 'deep_search_device_id');
    await init();
  }

  Future<Map<String, String>> _headers() async {
    await init();
    return {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer $_token',
    };
  }

  Future<http.Response> _authorized(
    Future<http.Response> Function(Map<String, String> headers) request,
  ) async {
    var response = await request(await _headers());
    if (response.statusCode == 401) {
      await _recoverAuth();
      response = await request(await _headers());
    }
    return response;
  }

  Future<void> pair(String code) async {
    final response = await http.post(
      Uri.parse('$baseUrl/v1/auth/pair'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'code': code, 'name': deviceName}),
    );
    _ensureOk(response);
    await _saveAuth(jsonDecode(response.body) as Map<String, dynamic>);
    _initialized = true;
  }

  Future<Map<String, dynamic>> createPairCode() async {
    final response = await _authorized(
      (headers) => http.post(Uri.parse('$baseUrl/v1/auth/pair-code'), headers: headers),
    );
    _ensureOk(response);
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<List<Map<String, dynamic>>> devices() async {
    final response = await _authorized(
      (headers) => http.get(Uri.parse('$baseUrl/v1/auth/devices'), headers: headers),
    );
    _ensureOk(response);
    final items = jsonDecode(response.body) as List<dynamic>;
    return items.map((e) => Map<String, dynamic>.from(e as Map)).toList();
  }

  Future<void> revokeDevice(String deviceId) async {
    final response = await _authorized(
      (headers) => http.delete(Uri.parse('$baseUrl/v1/auth/devices/$deviceId'), headers: headers),
    );
    _ensureOk(response);
  }

  Future<Map<String, dynamic>> storageUsage() async {
    final response = await _authorized(
      (headers) => http.get(Uri.parse('$baseUrl/v1/storage'), headers: headers),
    );
    _ensureOk(response);
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<List<SearchJob>> listJobs({String view = 'all'}) async {
    final uri = Uri.parse('$baseUrl/v1/jobs').replace(queryParameters: {'view': view});
    final response = await _authorized((headers) => http.get(uri, headers: headers));
    _ensureOk(response);
    final items = jsonDecode(response.body) as List<dynamic>;
    return items.map((e) => SearchJob.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<SearchJob> createJob({
    required String query,
    required String inputType,
    String? uploadId,
  }) async {
    final response = await _authorized(
      (headers) => http.post(
        Uri.parse('$baseUrl/v1/jobs'),
        headers: headers,
        body: jsonEncode({
          'query': query,
          'input_type': inputType,
          'upload_id': uploadId,
          'target_results': 10,
        }),
      ),
    );
    _ensureOk(response);
    return SearchJob.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
  }

  Future<http.Response> _uploadOnce(String path) async {
    await init();
    final request = http.MultipartRequest('POST', Uri.parse('$baseUrl/v1/uploads'));
    request.headers['Authorization'] = 'Bearer $_token';
    request.files.add(await http.MultipartFile.fromPath('file', path));
    final streamed = await request.send();
    return http.Response.fromStream(streamed);
  }

  Future<Map<String, dynamic>> upload(String path) async {
    var response = await _uploadOnce(path);
    if (response.statusCode == 401) {
      await _recoverAuth();
      response = await _uploadOnce(path);
    }
    _ensureOk(response);
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<List<SearchResult>> results(String jobId) async {
    final response = await _authorized(
      (headers) => http.get(Uri.parse('$baseUrl/v1/jobs/$jobId/results'), headers: headers),
    );
    _ensureOk(response);
    final items = jsonDecode(response.body) as List<dynamic>;
    return items.map((item) {
      final payload = Map<String, dynamic>.from(item as Map);
      final id = (payload['id'] as num?)?.toInt() ?? 0;
      final originalImage = (payload['image_url'] as String?)?.trim() ?? '';
      final evidence = payload['evidence'] is Map
          ? Map<String, dynamic>.from(payload['evidence'] as Map)
          : <String, dynamic>{};
      final capability = (evidence.remove('image_proxy_token') as String?)?.trim() ?? '';
      payload['evidence'] = evidence;

      // Never hand an external thumbnail URL to Flutter. A result image is
      // rendered only through our server capability endpoint, so Android and
      // Windows do not contact the source website directly.
      if (id > 0 && originalImage.isNotEmpty && capability.isNotEmpty) {
        payload['image_url'] = '$baseUrl/v1/result-images/$id?token=${Uri.encodeQueryComponent(capability)}';
      } else {
        payload['image_url'] = null;
      }
      return SearchResult.fromJson(payload);
    }).toList();
  }

  Future<void> action(String jobId, String action) async {
    final response = await _authorized(
      (headers) => http.post(Uri.parse('$baseUrl/v1/jobs/$jobId/$action'), headers: headers),
    );
    _ensureOk(response);
  }

  Future<File> downloadMedia(String jobId, Directory directory) async {
    for (var attempt = 0; attempt < 2; attempt++) {
      await init();
      final client = http.Client();
      try {
        final request = http.Request('GET', Uri.parse('$baseUrl/v1/jobs/$jobId/media'));
        request.headers['Authorization'] = 'Bearer $_token';
        final response = await client.send(request);

        if (response.statusCode == 401 && attempt == 0) {
          await response.stream.drain<void>();
          await _recoverAuth();
          continue;
        }
        if (response.statusCode < 200 || response.statusCode >= 300) {
          final body = await response.stream.bytesToString();
          throw Exception('HTTP ${response.statusCode}: $body');
        }

        var extension = '';
        final disposition = response.headers['content-disposition'] ?? '';
        final filenameMatch = RegExp(r'filename="?([^";]+)').firstMatch(disposition);
        final filename = filenameMatch?.group(1) ?? '';
        final dot = filename.lastIndexOf('.');
        if (dot >= 0 && filename.length - dot <= 12) {
          extension = filename.substring(dot).toLowerCase();
        }

        final target = File('${directory.path}${Platform.pathSeparator}source$extension');
        final sink = target.openWrite();
        try {
          await response.stream.pipe(sink);
        } catch (_) {
          await sink.close();
          if (await target.exists()) await target.delete();
          rethrow;
        }
        return target;
      } finally {
        client.close();
      }
    }
    throw Exception('authentication failed');
  }

  Future<void> deleteCloudMedia(String jobId) async {
    final response = await _authorized(
      (headers) => http.delete(Uri.parse('$baseUrl/v1/jobs/$jobId/media'), headers: headers),
    );
    _ensureOk(response);
  }

  Future<void> deleteJob(String jobId) async {
    final response = await _authorized(
      (headers) => http.delete(Uri.parse('$baseUrl/v1/jobs/$jobId'), headers: headers),
    );
    _ensureOk(response);
  }

  Future<bool> health() async {
    try {
      final response = await http.get(Uri.parse('$baseUrl/health')).timeout(const Duration(seconds: 6));
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  void _ensureOk(http.Response response) {
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception('HTTP ${response.statusCode}: ${response.body}');
    }
  }
}
