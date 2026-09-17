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
      );

  String get title => query.trim().isEmpty
      ? (inputType == 'video' ? 'بحث بالفيديو' : 'بحث بالصورة')
      : query.trim();

  bool get isActive => const {'queued', 'running', 'stopped'}.contains(status);
  bool get canContinue => const {'completed', 'partial', 'failed', 'needs_context'}.contains(status);
}

class SearchResult {
  const SearchResult({
    required this.rank,
    required this.title,
    required this.url,
    required String summary,
    required this.score,
    required this.evidence,
    this.imageUrl,
  }) : _summary = summary;

  final int rank;
  final String title;
  final String url;
  final String _summary;
  final double score;
  final String? imageUrl;
  final Map<String, dynamic> evidence;

  factory SearchResult.fromJson(Map<String, dynamic> json) => SearchResult(
        rank: (json['rank'] as num?)?.toInt() ?? 0,
        title: (json['title'] as String?) ?? '',
        url: (json['url'] as String?) ?? '',
        summary: (json['summary'] as String?) ?? '',
        score: (json['match_score'] as num?)?.toDouble() ?? (json['score'] as num?)?.toDouble() ?? 0,
        imageUrl: json['image_url'] as String?,
        evidence: json['evidence'] is Map
            ? Map<String, dynamic>.from(json['evidence'] as Map)
            : const <String, dynamic>{},
      );

  bool get visualMatch => evidence['visual_match'] == true;
  bool get visionUsed => evidence['vision_used'] == true;
  bool get speechUsed => evidence['speech_used'] == true;
  bool get ocrUsed => evidence['ocr_used'] == true;
  double get visualScore => (evidence['visual_score'] as num?)?.toDouble() ?? 0;

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
        'rank': rank,
        'title': title,
        'url': url,
        'summary': _summary,
        'match_score': score,
        'image_url': imageUrl,
        'evidence': evidence,
      };
}
