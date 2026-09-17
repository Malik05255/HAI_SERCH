String? _safeResultImageUrl(dynamic value) {
  final raw = value is String ? value.trim() : '';
  if (raw.isEmpty) return null;
  final uri = Uri.tryParse(raw);
  if (uri == null || !const {'http', 'https'}.contains(uri.scheme)) return null;
  if (!uri.path.startsWith('/v1/result-images/')) return null;
  return raw;
}

class SearchJob {
  const SearchJob({
    required this.id,
    required this.query,
    required this.inputType,
    required this.status,
    required this.progress,
    required this.foundCount,
    required this.targetResults,
    required this.attempts,
    required this.mediaAvailable,
    this.queuePosition,
    this.lastError,
  });

  final String id;
  final String query;
  final String inputType;
  final String status;
  final double progress;
  final int foundCount;
  final int targetResults;
  final int attempts;
  final bool mediaAvailable;
  final int? queuePosition;
  final String? lastError;

  factory SearchJob.fromJson(Map<String, dynamic> json) => SearchJob(
        id: json['id'] as String,
        query: (json['query'] as String?) ?? '',
        inputType: (json['input_type'] as String?) ?? 'text',
        status: (json['status'] as String?) ?? 'queued',
        progress: (json['progress'] as num?)?.toDouble() ?? 0,
        foundCount: (json['found_count'] as num?)?.toInt() ?? 0,
        targetResults: (json['target_results'] as num?)?.toInt() ?? 10,
        attempts: (json['attempts'] as num?)?.toInt() ?? 0,
        mediaAvailable: json['media_available'] == true,
        queuePosition: (json['queue_position'] as num?)?.toInt(),
        lastError: (json['last_error'] as String?)?.trim().isEmpty == true
            ? null
            : json['last_error'] as String?,
      );

  String get title => query.trim().isEmpty
      ? (inputType == 'video' ? 'بحث بالفيديو' : 'بحث بالصورة')
      : query.trim();

  bool get isActive => const {'queued', 'running', 'stopped'}.contains(status);

  bool get canContinue {
    if (!const {'completed', 'partial', 'failed', 'needs_context'}.contains(status)) {
      return false;
    }
    return inputType == 'text' || mediaAvailable;
  }

  bool get canAddClue {
    if (status == 'cancelled') return false;
    if (isActive) return true;
    return inputType == 'text' || mediaAvailable;
  }

  String? get userErrorLabel {
    if (lastError == null) return null;
    if (lastError == 'visual_analysis_unavailable') {
      return status == 'failed'
          ? 'تعذر التحليل البصري بعد عدة محاولات'
          : 'التحليل البصري غير متاح حاليًا، وسيعاد المحاولة تلقائيًا';
    }
    if (lastError == 'insufficient_context') {
      return 'الأدلة الحالية غير كافية لإكمال البحث';
    }
    if (lastError!.contains('search_backend_unavailable')) {
      return status == 'failed'
          ? 'تعذر الوصول إلى محرك البحث بعد عدة محاولات'
          : 'محرك البحث غير متاح مؤقتًا، وسيعاد المحاولة تلقائيًا';
    }
    if (status == 'failed') return 'تعذر إكمال آخر محاولة للبحث';
    return 'تعذرت آخر محاولة، وسيعاد البحث تلقائيًا';
  }
}

class SearchResult {
  const SearchResult({
    this.id = 0,
    required this.rank,
    required this.title,
    required this.url,
    required String summary,
    required this.score,
    required this.evidence,
    this.imageUrl,
  }) : _summary = summary;

  final int id;
  final int rank;
  final String title;
  final String url;
  final String _summary;
  final double score;
  final String? imageUrl;
  final Map<String, dynamic> evidence;

  factory SearchResult.fromJson(Map<String, dynamic> json) => SearchResult(
        id: (json['id'] as num?)?.toInt() ?? 0,
        rank: (json['rank'] as num?)?.toInt() ?? 0,
        title: (json['title'] as String?) ?? '',
        url: (json['url'] as String?) ?? '',
        summary: (json['summary'] as String?) ?? '',
        score: (json['match_score'] as num?)?.toDouble() ?? (json['score'] as num?)?.toDouble() ?? 0,
        imageUrl: _safeResultImageUrl(json['image_url']),
        evidence: json['evidence'] is Map
            ? Map<String, dynamic>.from(json['evidence'] as Map)
            : const <String, dynamic>{},
      );

  bool get visualMatch => evidence['visual_match'] == true;
  bool get visionUsed => evidence['vision_used'] == true;
  bool get speechUsed => evidence['speech_used'] == true;
  bool get ocrUsed => evidence['ocr_used'] == true;
  bool get pageVerified => evidence['verified_page'] == true;
  double get visualScore => (evidence['visual_score'] as num?)?.toDouble() ?? 0;

  List<Uri> get sourceUris {
    final values = <String>[url];
    final raw = evidence['supporting_sources'];
    if (raw is List) {
      for (final item in raw) {
        if (item is Map && item['url'] is String) {
          values.add(item['url'] as String);
        }
      }
    }

    final seen = <String>{};
    final uris = <Uri>[];
    for (final value in values) {
      final uri = Uri.tryParse(value.trim());
      if (uri == null || !const {'http', 'https'}.contains(uri.scheme)) continue;
      final normalized = uri.toString();
      if (seen.add(normalized)) uris.add(uri);
    }
    return uris;
  }

  int get supportingSourceCount => sourceUris.length;

  String? get evidenceLabel {
    if (visualMatch && visualScore >= 90) return 'تطابق بصري قوي جدًا';
    if (visualMatch) return 'تطابق بصري قوي';
    if (visionUsed && speechUsed) return 'المشهد والحوار يدعمان النتيجة';
    if (visionUsed && ocrUsed) return 'المشهد والنص الظاهر يدعمان النتيجة';
    if (visionUsed) return 'المشهد يدعم النتيجة';
    if (speechUsed) return 'الحوار يدعم النتيجة';
    if (ocrUsed) return 'النص الظاهر يدعم النتيجة';
    return null;
  }

  String get rawSummary => _summary;

  String get summary {
    final label = evidenceLabel;
    if (label == null) return _summary;
    if (_summary.isEmpty) return label;
    return '$label\n$_summary';
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'rank': rank,
        'title': title,
        'url': url,
        'summary': _summary,
        'match_score': score,
        'image_url': imageUrl,
        'evidence': evidence,
      };
}
