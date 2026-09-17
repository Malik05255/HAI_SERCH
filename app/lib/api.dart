import 'dart:convert';

import 'package:http/http.dart' as http;

import 'models.dart';

class ApiClient {
  const ApiClient();

  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );
  static const String apiKey = String.fromEnvironment('API_TOKEN', defaultValue: '');

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (apiKey.isNotEmpty) 'X-API-Key': apiKey,
      };

  Future<List<SearchJob>> listJobs({String view = 'all'}) async {
    final uri = Uri.parse('$baseUrl/v1/jobs').replace(queryParameters: {'view': view});
    final response = await http.get(uri, headers: _headers);
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
      headers: _headers,
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
    final request = http.MultipartRequest('POST', Uri.parse('$baseUrl/v1/uploads'));
    if (apiKey.isNotEmpty) request.headers['X-API-Key'] = apiKey;
    request.files.add(await http.MultipartFile.fromPath('file', path));
    final streamed = await request.send();
    final response = await http.Response.fromStream(streamed);
    _ensureOk(response);
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<List<SearchResult>> results(String jobId) async {
    final response = await http.get(Uri.parse('$baseUrl/v1/jobs/$jobId/results'), headers: _headers);
    _ensureOk(response);
    final items = jsonDecode(response.body) as List<dynamic>;
    return items.map((e) => SearchResult.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<void> action(String jobId, String action) async {
    final response = await http.post(Uri.parse('$baseUrl/v1/jobs/$jobId/$action'), headers: _headers);
    _ensureOk(response);
  }

  Future<void> deleteJob(String jobId) async {
    final response = await http.delete(Uri.parse('$baseUrl/v1/jobs/$jobId'), headers: _headers);
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
      throw Exception('HTTP ${response.statusCode}');
    }
  }
}
