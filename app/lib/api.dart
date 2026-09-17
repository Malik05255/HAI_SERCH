import 'dart:convert';
import 'dart:io';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

import 'models.dart';

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
  }

  Future<Map<String, String>> _headers() async {
    await init();
    return {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer $_token',
    };
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
    final response = await http.post(Uri.parse('$baseUrl/v1/auth/pair-code'), headers: await _headers());
    _ensureOk(response);
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<List<Map<String, dynamic>>> devices() async {
    final response = await http.get(Uri.parse('$baseUrl/v1/auth/devices'), headers: await _headers());
    _ensureOk(response);
    final items = jsonDecode(response.body) as List<dynamic>;
    return items.map((e) => Map<String, dynamic>.from(e as Map)).toList();
  }

  Future<void> revokeDevice(String deviceId) async {
    final response = await http.delete(Uri.parse('$baseUrl/v1/auth/devices/$deviceId'), headers: await _headers());
    _ensureOk(response);
  }

  Future<List<SearchJob>> listJobs({String view = 'all'}) async {
    final uri = Uri.parse('$baseUrl/v1/jobs').replace(queryParameters: {'view': view});
    final response = await http.get(uri, headers: await _headers());
    _ensureOk(response);
    final items = jsonDecode(response.body) as List<dynamic>;
    return items.map((e) => SearchJob.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<SearchJob> createJob({
    required String query,
    required String inputType,
    String? uploadId,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/v1/jobs'),
      headers: await _headers(),
      body: jsonEncode({
        'query': query,
        'input_type': inputType,
        'upload_id': uploadId,
        'target_results': 10,
      }),
    );
    _ensureOk(response);
    return SearchJob.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
  }

  Future<Map<String, dynamic>> upload(String path) async {
    await init();
    final request = http.MultipartRequest('POST', Uri.parse('$baseUrl/v1/uploads'));
    request.headers['Authorization'] = 'Bearer $_token';
    request.files.add(await http.MultipartFile.fromPath('file', path));
    final streamed = await request.send();
    final response = await http.Response.fromStream(streamed);
    _ensureOk(response);
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<List<SearchResult>> results(String jobId) async {
    final response = await http.get(Uri.parse('$baseUrl/v1/jobs/$jobId/results'), headers: await _headers());
    _ensureOk(response);
    final items = jsonDecode(response.body) as List<dynamic>;
    return items.map((e) => SearchResult.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<void> action(String jobId, String action) async {
    final response = await http.post(Uri.parse('$baseUrl/v1/jobs/$jobId/$action'), headers: await _headers());
    _ensureOk(response);
  }

  Future<void> deleteJob(String jobId) async {
    final response = await http.delete(Uri.parse('$baseUrl/v1/jobs/$jobId'), headers: await _headers());
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
