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
    required this.archived,
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
  final int? queuePosition;
  final bool archived;

  factory SearchJob.fromJson(Map<String, dynamic> json) => SearchJob(
        id: json['id'] as String,
        query: (json['query'] as String?) ?? '',
        inputType: (json['input_type'] as String?) ?? 'text',
        status: (json['status'] as String?) ?? 'queued',
        progress: (json['progress'] as num?)?.toDouble() ?? 0,
        foundCount: (json['found_count'] as num?)?.toInt() ?? 0,
        targetResults: (json['target_results'] as num?)?.toInt() ?? 10,
        attempts: (json['attempts'] as num?)?.toInt() ?? 0,
        queuePosition: (json['queue_position'] as num?)?.toInt(),
        archived: (json['archived'] as bool?) ?? false,
      );

  String get title => query.trim().isEmpty
      ? (inputType == 'video' ? 'بحث بالفيديو' : 'بحث بالصورة')
      : query.trim();

  bool get isActive => const {'queued', 'running', 'stopped'}.contains(status);
}

class SearchResult {
  const SearchResult({
    required this.rank,
    required this.title,
    required this.url,
    required this.summary,
    required this.score,
    this.imageUrl,
  });

  final int rank;
  final String title;
  final String url;
  final String summary;
  final double score;
  final String? imageUrl;

  factory SearchResult.fromJson(Map<String, dynamic> json) => SearchResult(
        rank: (json['rank'] as num?)?.toInt() ?? 0,
        title: (json['title'] as String?) ?? '',
        url: (json['url'] as String?) ?? '',
        summary: (json['summary'] as String?) ?? '',
        score: (json['match_score'] as num?)?.toDouble() ?? 0,
        imageUrl: json['image_url'] as String?,
      );
}
