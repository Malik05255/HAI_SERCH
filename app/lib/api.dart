import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

import 'models.dart';
import 'notification_service.dart';

class ApiClient {
  ApiClient({this.enableRealtime = true});

  final bool enableRealtime;

  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );
  static const String _tokenKey = 'deep_search_device_token';
  static const String _deviceIdKey = 'deep_search_device_id';
  static const String _revokedKey = 'deep_search_auth_revoked';

  static const FlutterSecureStorage _storage = FlutterSecureStorage();
  final StreamController<void> _jobChanges = StreamController<void>.broadcast();
  String? _token;
  bool _initialized = false;
  bool _authRevoked = false;
  bool _connectingRealtime = false;
  bool _realtimeUnauthorized = false;
  WebSocket? _socket;
  Timer? _reconnectTimer;
  Timer? _pingTimer;

  Stream<void> get jobChanges => _jobChanges.stream;
  bool get authorizationRevoked => _authRevoked;

  String get deviceName {
    if (Platform.isWindows) return 'Windows';
    if (Platform.isAndroid) return 'Android';
    return 'Device';
  }

  Uri get _webSocketUri {
    final base = Uri.parse(baseUrl);
    return base.replace(
      scheme: base.scheme == 'https' ? 'wss' : 'ws',
      path: '/v1/ws',
      query: null,
      fragment: null,
    );
  }

  Future<void> init() async {
    if (_initialized) return;
    if (!_authRevoked) {
      _authRevoked = await _storage.read(key: _revokedKey) == '1';
    }
    if (_authRevoked) throw StateError('device authorization revoked');

    _token = await _storage.read(key: _tokenKey);
    if (_token == null || _token!.isEmpty) {
      await _register();
    }
    _initialized = true;
    await NotificationService.initialize();
    if (enableRealtime) unawaited(_ensureRealtime());
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
    if (_token != null && _token != token) {
      await _stopRealtime();
    }
    _token = token;
    _authRevoked = false;
    _realtimeUnauthorized = false;
    await _storage.delete(key: _revokedKey);
    await _storage.write(key: _tokenKey, value: token);
    final id = payload['device_id'] as String?;
    if (id != null) await _storage.write(key: _deviceIdKey, value: id);
    await NotificationService.refreshRegistration();
  }

  Future<void> _markAuthRevoked() async {
    if (_authRevoked) return;
    _authRevoked = true;
    _realtimeUnauthorized = true;
    await _storage.write(key: _revokedKey, value: '1');
    await _stopRealtime();
    _token = null;
    _initialized = false;
    await _storage.delete(key: _tokenKey);
    await _storage.delete(key: _deviceIdKey);
    if (!_jobChanges.isClosed) _jobChanges.add(null);
  }

  Future<void> _stopRealtime() async {
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    _pingTimer?.cancel();
    _pingTimer = null;
    final socket = _socket;
    _socket = null;
    if (socket != null) {
      try {
        await socket.close();
      } catch (_) {}
    }
  }

  void _scheduleRealtimeReconnect() {
    if (!enableRealtime || !_initialized || _authRevoked || _realtimeUnauthorized || _reconnectTimer?.isActive == true) {
      return;
    }
    _reconnectTimer = Timer(const Duration(seconds: 3), () {
      _reconnectTimer = null;
      unawaited(_ensureRealtime());
    });
  }

  void _handleRealtimeMessage(dynamic message) {
    if (message is! String) return;
    try {
      final data = jsonDecode(message);
      if (data is Map && data['type'] == 'jobs.changed') {
        _jobChanges.add(null);
      }
    } catch (_) {}
  }

  Future<void> _ensureRealtime() async {
    if (!enableRealtime ||
        !_initialized ||
        _authRevoked ||
        _realtimeUnauthorized ||
        _connectingRealtime ||
        _socket != null ||
        _token == null ||
        _token!.isEmpty) {
      return;
    }

    _connectingRealtime = true;
    final tokenAtConnect = _token!;
    try {
      final socket = await WebSocket.connect(
        _webSocketUri.toString(),
        headers: {HttpHeaders.authorizationHeader: 'Bearer $tokenAtConnect'},
      ).timeout(const Duration(seconds: 8));

      if (!_initialized || _token != tokenAtConnect) {
        await socket.close();
        return;
      }

      _socket = socket;
      _pingTimer?.cancel();
      _pingTimer = Timer.periodic(const Duration(seconds: 25), (_) {
        try {
          _socket?.add('ping');
        } catch (_) {}
      });

      socket.listen(
        _handleRealtimeMessage,
        onDone: () {
          if (identical(_socket, socket)) {
            _socket = null;
            _pingTimer?.cancel();
            _pingTimer = null;
          }
          if (socket.closeCode == 4401) {
            unawaited(_markAuthRevoked());
            return;
          }
          _scheduleRealtimeReconnect();
        },
        onError: (_) {
          if (identical(_socket, socket)) {
            _socket = null;
            _pingTimer?.cancel();
            _pingTimer = null;
          }
          _scheduleRealtimeReconnect();
        },
        cancelOnError: true,
      );
    } catch (_) {
      _scheduleRealtimeReconnect();
    } finally {
      _connectingRealtime = false;
    }
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
    final response = await request(await _headers());
    if (response.statusCode == 401) {
      await _markAuthRevoked();
      throw StateError('device authorization revoked');
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
    if (enableRealtime) unawaited(_ensureRealtime());
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

  Future<void> addClue(String jobId, String text) async {
    final clue = text.trim();
    if (clue.isEmpty) return;
    final response = await _authorized(
      (headers) => http.post(
        Uri.parse('$baseUrl/v1/jobs/$jobId/clues'),
        headers: headers,
        body: jsonEncode({'text': clue}),
      ),
    );
    _ensureOk(response);
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
    final response = await _uploadOnce(path);
    if (response.statusCode == 401) {
      await _markAuthRevoked();
      throw StateError('device authorization revoked');
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
    await init();
    final client = http.Client();
    try {
      final request = http.Request('GET', Uri.parse('$baseUrl/v1/jobs/$jobId/media'));
      request.headers['Authorization'] = 'Bearer $_token';
      final response = await client.send(request);

      if (response.statusCode == 401) {
        await response.stream.drain<void>();
        await _markAuthRevoked();
        throw StateError('device authorization revoked');
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
