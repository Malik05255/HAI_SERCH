import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import 'api.dart';
import 'models.dart';

class LocalArchiveItem {
  const LocalArchiveItem({
    required this.jobId,
    required this.title,
    required this.inputType,
    required this.status,
    required this.foundCount,
    required this.targetResults,
    required this.archivedAt,
    required this.results,
    this.mediaPath,
    this.mediaName,
  });

  final String jobId;
  final String title;
  final String inputType;
  final String status;
  final int foundCount;
  final int targetResults;
  final DateTime archivedAt;
  final List<SearchResult> results;
  final String? mediaPath;
  final String? mediaName;

  bool get hasMedia => mediaPath != null && File(mediaPath!).existsSync();

  factory LocalArchiveItem.fromJson(Map<String, dynamic> json, String folderPath) {
    final mediaFile = json['media_file'] as String?;
    return LocalArchiveItem(
      jobId: json['job_id'] as String,
      title: (json['title'] as String?) ?? '',
      inputType: (json['input_type'] as String?) ?? 'text',
      status: (json['status'] as String?) ?? 'completed',
      foundCount: (json['found_count'] as num?)?.toInt() ?? 0,
      targetResults: (json['target_results'] as num?)?.toInt() ?? 10,
      archivedAt: DateTime.tryParse((json['archived_at'] as String?) ?? '') ?? DateTime.now(),
      mediaPath: mediaFile == null ? null : '$folderPath${Platform.pathSeparator}$mediaFile',
      mediaName: json['media_name'] as String?,
      results: ((json['results'] as List<dynamic>?) ?? const [])
          .map((item) => SearchResult.fromJson(item as Map<String, dynamic>))
          .toList(),
    );
  }
}

class LocalArchiveStore {
  Future<Directory> _root() async {
    final support = await getApplicationSupportDirectory();
    final dir = Directory('${support.path}${Platform.pathSeparator}deep_search');
    await dir.create(recursive: true);
    return dir;
  }

  Future<Directory> _archiveRoot() async {
    final root = await _root();
    final dir = Directory('${root.path}${Platform.pathSeparator}archive');
    await dir.create(recursive: true);
    return dir;
  }

  // Kept for client compatibility. Source media is intentionally not copied
  // into app storage at upload time; cloud storage is the shared source until
  // the user explicitly archives the task on a device.
  Future<void> rememberSource(String jobId, String sourcePath, String originalName) async {}

  Future<bool> hasPendingMedia(String jobId) async => false;

  Future<void> archiveJob(SearchJob job, List<SearchResult> results) async {
    final root = await _archiveRoot();
    final dir = Directory('${root.path}${Platform.pathSeparator}${job.id}');

    // Build archives atomically enough for user-facing behavior: remove any
    // incomplete previous attempt, recreate the folder, then write metadata last.
    if (await dir.exists()) await dir.delete(recursive: true);
    await dir.create(recursive: true);

    String? mediaFileName;
    String? mediaName;
    try {
      if (job.inputType != 'text') {
        if (!job.mediaAvailable) throw StateError('media-not-available');
        final downloaded = await ApiClient().downloadMedia(job.id, dir);
        mediaFileName = downloaded.uri.pathSegments.last;
        mediaName = job.inputType == 'video' ? 'الفيديو الأصلي' : 'الصورة الأصلية';
      }

      final payload = <String, dynamic>{
        'job_id': job.id,
        'title': job.title,
        'input_type': job.inputType,
        'status': job.status,
        'found_count': job.foundCount,
        'target_results': job.targetResults,
        'archived_at': DateTime.now().toUtc().toIso8601String(),
        'media_file': mediaFileName,
        'media_name': mediaName,
        'results': results.map((r) => r.toJson()).toList(),
      };
      await File('${dir.path}${Platform.pathSeparator}archive.json').writeAsString(
        jsonEncode(payload),
        flush: true,
      );
    } catch (_) {
      if (await dir.exists()) await dir.delete(recursive: true);
      rethrow;
    }
  }

  Future<Set<String>> archivedIds() async {
    final items = await listArchives();
    return items.map((e) => e.jobId).toSet();
  }

  Future<List<LocalArchiveItem>> listArchives() async {
    final root = await _archiveRoot();
    final items = <LocalArchiveItem>[];
    await for (final entity in root.list()) {
      if (entity is! Directory) continue;
      final meta = File('${entity.path}${Platform.pathSeparator}archive.json');
      if (!await meta.exists()) continue;
      try {
        final json = jsonDecode(await meta.readAsString()) as Map<String, dynamic>;
        items.add(LocalArchiveItem.fromJson(json, entity.path));
      } catch (_) {}
    }
    items.sort((a, b) => b.archivedAt.compareTo(a.archivedAt));
    return items;
  }

  Future<void> discardPending(String jobId) async {
    // No pending local copy is created anymore.
  }

  Future<void> deleteArchive(String jobId) async {
    final root = await _archiveRoot();
    final dir = Directory('${root.path}${Platform.pathSeparator}$jobId');
    if (await dir.exists()) await dir.delete(recursive: true);
  }

  Future<void> restoreArchive(String jobId) async {
    // Restoring means removing the local snapshot so the synchronized cloud
    // task appears again in Previous Tasks. Cloud data itself is untouched.
    await deleteArchive(jobId);
  }
}
