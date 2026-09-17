import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

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

  Future<Directory> _pendingRoot() async {
    final root = await _root();
    final dir = Directory('${root.path}${Platform.pathSeparator}pending');
    await dir.create(recursive: true);
    return dir;
  }

  Future<Directory> _archiveRoot() async {
    final root = await _root();
    final dir = Directory('${root.path}${Platform.pathSeparator}archive');
    await dir.create(recursive: true);
    return dir;
  }

  String _extension(String name) {
    final index = name.lastIndexOf('.');
    if (index < 0 || index == name.length - 1) return '';
    final value = name.substring(index).toLowerCase();
    return value.length <= 10 ? value : '';
  }

  Future<void> rememberSource(String jobId, String sourcePath, String originalName) async {
    final source = File(sourcePath);
    if (!await source.exists()) return;
    final root = await _pendingRoot();
    final dir = Directory('${root.path}${Platform.pathSeparator}$jobId');
    await dir.create(recursive: true);
    final ext = _extension(originalName.isEmpty ? source.path : originalName);
    final target = File('${dir.path}${Platform.pathSeparator}source$ext');
    await source.copy(target.path);
    await File('${dir.path}${Platform.pathSeparator}media.json').writeAsString(
      jsonEncode({'name': originalName, 'file': target.uri.pathSegments.last}),
      flush: true,
    );
  }

  Future<({File? file, String? name})> _pendingMedia(String jobId) async {
    final root = await _pendingRoot();
    final dir = Directory('${root.path}${Platform.pathSeparator}$jobId');
    if (!await dir.exists()) return (file: null, name: null);
    String? name;
    final meta = File('${dir.path}${Platform.pathSeparator}media.json');
    if (await meta.exists()) {
      try {
        final data = jsonDecode(await meta.readAsString()) as Map<String, dynamic>;
        name = data['name'] as String?;
      } catch (_) {}
    }
    final files = await dir.list().where((e) => e is File && !e.path.endsWith('media.json')).cast<File>().toList();
    return (file: files.isEmpty ? null : files.first, name: name);
  }

  Future<bool> hasPendingMedia(String jobId) async {
    final pending = await _pendingMedia(jobId);
    return pending.file != null && await pending.file!.exists();
  }

  Future<void> archiveJob(SearchJob job, List<SearchResult> results) async {
    final pending = await _pendingMedia(job.id);
    if (job.inputType != 'text' && (pending.file == null || !await pending.file!.exists())) {
      throw StateError('media-not-on-this-device');
    }

    final root = await _archiveRoot();
    final dir = Directory('${root.path}${Platform.pathSeparator}${job.id}');
    await dir.create(recursive: true);

    String? mediaFileName;
    if (pending.file != null && await pending.file!.exists()) {
      mediaFileName = pending.file!.uri.pathSegments.last;
      await pending.file!.copy('${dir.path}${Platform.pathSeparator}$mediaFileName');
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
      'media_name': pending.name,
      'results': results.map((r) => r.toJson()).toList(),
    };
    await File('${dir.path}${Platform.pathSeparator}archive.json').writeAsString(jsonEncode(payload), flush: true);
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
    final root = await _pendingRoot();
    final dir = Directory('${root.path}${Platform.pathSeparator}$jobId');
    if (await dir.exists()) await dir.delete(recursive: true);
  }

  Future<void> deleteArchive(String jobId) async {
    final root = await _archiveRoot();
    final dir = Directory('${root.path}${Platform.pathSeparator}$jobId');
    if (await dir.exists()) await dir.delete(recursive: true);
  }

  Future<void> restoreArchive(String jobId) async {
    final root = await _archiveRoot();
    final dir = Directory('${root.path}${Platform.pathSeparator}$jobId');
    if (!await dir.exists()) return;

    final meta = File('${dir.path}${Platform.pathSeparator}archive.json');
    if (await meta.exists()) {
      try {
        final data = jsonDecode(await meta.readAsString()) as Map<String, dynamic>;
        final mediaFile = data['media_file'] as String?;
        if (mediaFile != null) {
          final source = File('${dir.path}${Platform.pathSeparator}$mediaFile');
          if (await source.exists()) {
            final pendingRoot = await _pendingRoot();
            final pendingDir = Directory('${pendingRoot.path}${Platform.pathSeparator}$jobId');
            await pendingDir.create(recursive: true);
            await source.copy('${pendingDir.path}${Platform.pathSeparator}$mediaFile');
            await File('${pendingDir.path}${Platform.pathSeparator}media.json').writeAsString(
              jsonEncode({'name': data['media_name'], 'file': mediaFile}),
              flush: true,
            );
          }
        }
      } catch (_) {}
    }
    await dir.delete(recursive: true);
  }
}
