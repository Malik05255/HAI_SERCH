import 'dart:async';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:open_filex/open_filex.dart';
import 'package:url_launcher/url_launcher.dart';

import 'api.dart';
import 'local_archive.dart';
import 'models.dart';
import 'updates.dart';

void main() => runApp(const DeepSearchApp());

class DeepSearchApp extends StatefulWidget {
  const DeepSearchApp({super.key});

  @override
  State<DeepSearchApp> createState() => _DeepSearchAppState();
}

class _DeepSearchAppState extends State<DeepSearchApp> {
  ThemeMode mode = ThemeMode.light;

  @override
  Widget build(BuildContext context) {
    const seed = Color(0xFF2458D8);
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'البحث العميق',
      themeMode: mode,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: seed),
        useMaterial3: true,
        scaffoldBackgroundColor: const Color(0xFFF7F8FA),
        cardTheme: const CardThemeData(elevation: 0, margin: EdgeInsets.zero),
      ),
      darkTheme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: seed, brightness: Brightness.dark),
        useMaterial3: true,
      ),
      builder: (context, child) => Directionality(textDirection: TextDirection.rtl, child: child!),
      home: HomeShell(
        dark: mode == ThemeMode.dark,
        onThemeChanged: (value) => setState(() => mode = value ? ThemeMode.dark : ThemeMode.light),
      ),
    );
  }
}

class HomeShell extends StatefulWidget {
  const HomeShell({super.key, required this.dark, required this.onThemeChanged});
  final bool dark;
  final ValueChanged<bool> onThemeChanged;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  final api = ApiClient();
  final archive = LocalArchiveStore();
  int index = 0;
  int archiveRevision = 0;
  int accountRevision = 0;

  void archiveChanged() => setState(() => archiveRevision++);
  void accountChanged() => setState(() => accountRevision++);

  @override
  Widget build(BuildContext context) {
    final pages = [
      SearchPage(
        key: ValueKey('search-$accountRevision'),
        api: api,
        archive: archive,
        onArchiveChanged: archiveChanged,
        onOpenQueue: () => setState(() => index = 1),
      ),
      QueuePage(
        key: ValueKey('queue-$accountRevision'),
        api: api,
        archive: archive,
        onArchiveChanged: archiveChanged,
      ),
      ArchivePage(key: ValueKey(archiveRevision), archive: archive, onArchiveChanged: archiveChanged),
      SettingsPage(
        api: api,
        dark: widget.dark,
        onThemeChanged: widget.onThemeChanged,
        onAccountChanged: accountChanged,
      ),
    ];
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 16,
        title: Row(children: [
          Container(
            width: 38,
            height: 38,
            decoration: BoxDecoration(color: Theme.of(context).colorScheme.primary, borderRadius: BorderRadius.circular(12)),
            child: const Icon(Icons.travel_explore_rounded, color: Colors.white),
          ),
          const SizedBox(width: 10),
          const Text('البحث العميق', style: TextStyle(fontWeight: FontWeight.w700)),
        ]),
      ),
      body: IndexedStack(index: index, children: pages),
      bottomNavigationBar: NavigationBar(
        selectedIndex: index,
        onDestinationSelected: (value) => setState(() => index = value),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.search_rounded), label: 'البحث'),
          NavigationDestination(icon: Icon(Icons.format_list_numbered_rounded), label: 'الطابور'),
          NavigationDestination(icon: Icon(Icons.archive_outlined), label: 'الأرشيف'),
          NavigationDestination(icon: Icon(Icons.tune_rounded), label: 'الإعدادات'),
        ],
      ),
    );
  }
}

class SearchPage extends StatefulWidget {
  const SearchPage({
    super.key,
    required this.api,
    required this.archive,
    required this.onArchiveChanged,
    required this.onOpenQueue,
  });
  final ApiClient api;
  final LocalArchiveStore archive;
  final VoidCallback onArchiveChanged;
  final VoidCallback onOpenQueue;

  @override
  State<SearchPage> createState() => _SearchPageState();
}

class _SearchPageState extends State<SearchPage> {
  final controller = TextEditingController();
  String mode = 'text';
  String? filePath;
  String? fileName;
  bool busy = false;
  bool loading = true;
  List<SearchJob> recent = const [];

  @override
  void initState() {
    super.initState();
    refresh();
  }

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  Future<void> refresh() async {
    try {
      final hidden = await widget.archive.archivedIds();
      final data = await widget.api.listJobs(view: 'history');
      if (mounted) setState(() => recent = data.where((j) => !hidden.contains(j.id)).take(5).toList());
    } catch (_) {
      // Search remains available when history cannot be loaded.
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> pickFile() async {
    final type = mode == 'video' ? FileType.video : FileType.image;
    final result = await FilePicker.platform.pickFiles(type: type, allowMultiple: false);
    final file = result?.files.single;
    if (file?.path == null) return;
    setState(() {
      filePath = file!.path;
      fileName = file.name;
    });
  }

  Future<void> submit() async {
    final query = controller.text.trim();
    if (query.isEmpty && mode == 'text') return _message('اكتب طلبك');
    if (mode != 'text' && filePath == null) return _message('اختر ملفًا');
    setState(() => busy = true);
    try {
      String? uploadId;
      var inputType = mode;
      if (filePath != null && mode != 'text') {
        final upload = await widget.api.upload(filePath!);
        uploadId = upload['upload_id'] as String?;
        inputType = (upload['input_type'] as String?) ?? mode;
      }
      final job = await widget.api.createJob(query: query, inputType: inputType, uploadId: uploadId);
      if (filePath != null && mode != 'text') {
        await widget.archive.rememberSource(job.id, filePath!, fileName ?? 'media');
      }
      controller.clear();
      setState(() {
        filePath = null;
        fileName = null;
        mode = 'text';
      });
      final position = job.queuePosition ?? 1;
      _message(position == 1 ? 'بدأ البحث' : 'أضيف للدور $position');
      widget.onOpenQueue();
    } catch (error) {
      _message(error.toString().contains('429') ? 'الطابور ممتلئ 5/5' : 'لم يبدأ البحث');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  void _message(String text) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: refresh,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 28),
        children: [
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'text', label: Text('نص'), icon: Icon(Icons.text_fields_rounded)),
              ButtonSegment(value: 'image', label: Text('صورة'), icon: Icon(Icons.image_outlined)),
              ButtonSegment(value: 'video', label: Text('فيديو'), icon: Icon(Icons.play_circle_outline_rounded)),
            ],
            selected: {mode},
            onSelectionChanged: (value) => setState(() {
              mode = value.first;
              filePath = null;
              fileName = null;
            }),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: controller,
            minLines: 3,
            maxLines: 7,
            decoration: InputDecoration(
              hintText: 'وش تبي أبحث عنه؟',
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(16)),
              suffixIcon: mode == 'text' ? null : IconButton(onPressed: pickFile, icon: const Icon(Icons.attach_file_rounded)),
            ),
          ),
          if (fileName != null) ...[
            const SizedBox(height: 8),
            InputChip(
              avatar: Icon(mode == 'video' ? Icons.play_circle_outline : Icons.image_outlined),
              label: Text(fileName!, overflow: TextOverflow.ellipsis),
              onDeleted: () => setState(() {
                fileName = null;
                filePath = null;
              }),
            ),
          ],
          const SizedBox(height: 10),
          FilledButton.icon(
            onPressed: busy ? null : submit,
            icon: busy
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.manage_search_rounded),
            label: const Padding(padding: EdgeInsets.symmetric(vertical: 13), child: Text('ابدأ البحث')),
          ),
          const SizedBox(height: 26),
          if (!loading && recent.isNotEmpty) ...[
            const Text('آخر النتائج', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
            const SizedBox(height: 10),
            ...recent.map((job) => Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: JobCard(
                    job: job,
                    api: widget.api,
                    archive: widget.archive,
                    onArchiveChanged: widget.onArchiveChanged,
                    onChanged: refresh,
                  ),
                )),
          ],
        ],
      ),
    );
  }
}

class QueuePage extends StatefulWidget {
  const QueuePage({super.key, required this.api, required this.archive, required this.onArchiveChanged});
  final ApiClient api;
  final LocalArchiveStore archive;
  final VoidCallback onArchiveChanged;

  @override
  State<QueuePage> createState() => _QueuePageState();
}

class _QueuePageState extends State<QueuePage> {
  List<SearchJob> jobs = const [];
  bool loading = true;
  Timer? timer;

  @override
  void initState() {
    super.initState();
    refresh();
    timer = Timer.periodic(const Duration(seconds: 8), (_) => refresh(silent: true));
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  Future<void> refresh({bool silent = false}) async {
    if (!silent && mounted) setState(() => loading = true);
    try {
      final hidden = await widget.archive.archivedIds();
      final data = await widget.api.listJobs(view: 'queue');
      if (mounted) setState(() => jobs = data.where((j) => !hidden.contains(j.id)).toList());
    } finally {
      if (!silent && mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: refresh,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Row(children: [
            const Expanded(child: Text('الطابور', style: TextStyle(fontSize: 21, fontWeight: FontWeight.w800))),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
              decoration: BoxDecoration(color: Theme.of(context).colorScheme.primaryContainer, borderRadius: BorderRadius.circular(20)),
              child: Text('${jobs.length}/5', style: const TextStyle(fontWeight: FontWeight.w700)),
            ),
          ]),
          const SizedBox(height: 14),
          if (loading)
            const Center(child: Padding(padding: EdgeInsets.all(30), child: CircularProgressIndicator()))
          else if (jobs.isEmpty)
            const _EmptyState(icon: Icons.inbox_outlined, text: 'الطابور فارغ')
          else
            ...jobs.map((job) => Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: JobCard(
                    job: job,
                    api: widget.api,
                    archive: widget.archive,
                    onArchiveChanged: widget.onArchiveChanged,
                    onChanged: refresh,
                    queueMode: true,
                  ),
                )),
        ],
      ),
    );
  }
}

class ArchivePage extends StatefulWidget {
  const ArchivePage({super.key, required this.archive, required this.onArchiveChanged});
  final LocalArchiveStore archive;
  final VoidCallback onArchiveChanged;

  @override
  State<ArchivePage> createState() => _ArchivePageState();
}

class _ArchivePageState extends State<ArchivePage> {
  List<LocalArchiveItem> items = const [];
  bool loading = true;

  @override
  void initState() {
    super.initState();
    refresh();
  }

  Future<void> refresh() async {
    final data = await widget.archive.listArchives();
    if (mounted) setState(() {
      items = data;
      loading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    if (loading) return const Center(child: CircularProgressIndicator());
    return RefreshIndicator(
      onRefresh: refresh,
      child: items.isEmpty
          ? ListView(children: const [SizedBox(height: 90), _EmptyState(icon: Icons.archive_outlined, text: 'الأرشيف فارغ')])
          : ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: items.length,
              separatorBuilder: (_, __) => const SizedBox(height: 10),
              itemBuilder: (_, index) {
                final item = items[index];
                return Card(
                  child: ListTile(
                    contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                    leading: Icon(item.inputType == 'video'
                        ? Icons.video_file_outlined
                        : item.inputType == 'image'
                            ? Icons.image_outlined
                            : Icons.search_rounded),
                    title: Text(item.title, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w700)),
                    subtitle: Text(item.hasMedia ? '${item.foundCount}/${item.targetResults} · المرفق محفوظ' : '${item.foundCount}/${item.targetResults}'),
                    onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => LocalArchiveResultsPage(item: item))),
                    trailing: PopupMenuButton<String>(
                      onSelected: (value) async {
                        if (value == 'restore') {
                          await widget.archive.restoreArchive(item.jobId);
                        } else if (value == 'delete') {
                          final ok = await showDialog<bool>(
                                context: context,
                                builder: (_) => AlertDialog(
                                  title: const Text('حذف الأرشيف'),
                                  content: const Text('سيتم حذف النسخة المحلية والمرفق المحفوظ من هذا الجهاز فقط.'),
                                  actions: [
                                    TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('رجوع')),
                                    FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('حذف')),
                                  ],
                                ),
                              ) ??
                              false;
                          if (!ok) return;
                          await widget.archive.deleteArchive(item.jobId);
                        }
                        widget.onArchiveChanged();
                        await refresh();
                      },
                      itemBuilder: (_) => const [
                        PopupMenuItem(value: 'restore', child: Text('استرجاع')),
                        PopupMenuItem(value: 'delete', child: Text('حذف من الجهاز')),
                      ],
                    ),
                  ),
                );
              },
            ),
    );
  }
}

class LocalArchiveResultsPage extends StatelessWidget {
  const LocalArchiveResultsPage({super.key, required this.item});
  final LocalArchiveItem item;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(item.title, maxLines: 1, overflow: TextOverflow.ellipsis)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (item.hasMedia) ...[
            FilledButton.tonalIcon(
              onPressed: () => OpenFilex.open(item.mediaPath!),
              icon: Icon(item.inputType == 'video' ? Icons.play_circle_outline_rounded : Icons.image_outlined),
              label: Text(item.mediaName?.isNotEmpty == true ? item.mediaName! : 'فتح المرفق'),
            ),
            const SizedBox(height: 14),
          ],
          if (item.results.isEmpty)
            const _EmptyState(icon: Icons.search_off_rounded, text: 'لا توجد نتائج محفوظة')
          else
            ...item.results.map((result) => Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: ResultCard(item: result),
                )),
        ],
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.icon, required this.text});
  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(children: [
            Icon(icon, size: 44, color: Theme.of(context).colorScheme.outline),
            const SizedBox(height: 10),
            Text(text, style: TextStyle(color: Theme.of(context).colorScheme.outline)),
          ]),
        ),
      );
}

class JobCard extends StatelessWidget {
  const JobCard({
    super.key,
    required this.job,
    required this.api,
    required this.archive,
    required this.onArchiveChanged,
    required this.onChanged,
    this.queueMode = false,
  });
  final SearchJob job;
  final ApiClient api;
  final LocalArchiveStore archive;
  final VoidCallback onArchiveChanged;
  final Future<void> Function() onChanged;
  final bool queueMode;

  String get statusLabel => switch (job.status) {
        'queued' => 'في الدور',
        'running' => 'يبحث',
        'completed' => 'مكتمل',
        'partial' => 'جزئي',
        'stopped' => 'متوقف',
        'cancelled' => 'ملغي',
        'needs_context' => 'غير كافٍ',
        'failed' => 'تعذر',
        _ => job.status,
      };

  String get queueLabel => job.status == 'running' ? 'يعمل الآن' : (job.queuePosition == null ? statusLabel : 'الدور ${job.queuePosition}');

  Future<bool> _confirm(BuildContext context, String title, String message) async {
    return await showDialog<bool>(
          context: context,
          builder: (_) => AlertDialog(
            title: Text(title),
            content: Text(message),
            actions: [
              TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('رجوع')),
              FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('تأكيد')),
            ],
          ),
        ) ??
        false;
  }

  Future<void> _archiveLocally(BuildContext context) async {
    if (job.inputType != 'text' && !await archive.hasPendingMedia(job.id)) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('المرفق غير موجود على هذا الجهاز. أرشف المهمة من الجهاز الذي أرسل الملف.')));
      }
      return;
    }
    final results = await api.results(job.id);
    await archive.archiveJob(job, results);
    try {
      if (job.isActive) await api.action(job.id, 'cancel');
      await archive.discardPending(job.id);
      onArchiveChanged();
      await onChanged();
    } catch (_) {
      await archive.deleteArchive(job.id);
      rethrow;
    }
  }

  Future<void> _runAction(BuildContext context, String value) async {
    try {
      if (value == 'archive') {
        if (job.isActive) {
          final confirmed = await _confirm(context, 'حفظ في الأرشيف', 'سيتم حفظ المهمة والمرفق على هذا الجهاز ثم إلغاء البحث الحالي.');
          if (!confirmed || !context.mounted) return;
        }
        await _archiveLocally(context);
      } else if (value == 'delete') {
        final confirmed = await _confirm(context, 'حذف المهمة', 'سيتم حذف المهمة ونتائجها من السحابة.');
        if (!confirmed) return;
        if (job.status == 'running') await api.action(job.id, 'cancel');
        await archive.discardPending(job.id);
        await api.deleteJob(job.id);
        await onChanged();
      } else if (value == 'cancel') {
        final confirmed = await _confirm(context, 'إلغاء البحث', 'سيتم إيقاف البحث وحذف المرفق المؤقت من السيرفر وهذا الجهاز.');
        if (!confirmed) return;
        await api.action(job.id, 'cancel');
        await archive.discardPending(job.id);
        await onChanged();
      } else {
        await api.action(job.id, value);
        await onChanged();
      }
    } catch (_) {
      if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('تعذر تنفيذ العملية')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final canOpen = job.foundCount > 0 || const {'completed', 'partial'}.contains(job.status);
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: canOpen ? () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => ResultsPage(api: api, job: job))) : null,
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              if (queueMode && job.queuePosition != null) ...[
                CircleAvatar(radius: 18, child: Text('${job.queuePosition}')),
                const SizedBox(width: 10),
              ],
              Expanded(child: Text(job.title, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w700))),
              PopupMenuButton<String>(
                onSelected: (value) => _runAction(context, value),
                itemBuilder: (_) => [
                  if (job.status == 'running' || job.status == 'queued') const PopupMenuItem(value: 'stop', child: Text('إيقاف مؤقت')),
                  if (job.status == 'stopped') const PopupMenuItem(value: 'resume', child: Text('متابعة')),
                  if (job.isActive) const PopupMenuItem(value: 'cancel', child: Text('إلغاء')),
                  const PopupMenuItem(value: 'archive', child: Text('حفظ في الأرشيف')),
                  const PopupMenuItem(value: 'delete', child: Text('حذف نهائي')),
                ],
              ),
            ]),
            const SizedBox(height: 8),
            Row(children: [
              Text(queueMode ? queueLabel : statusLabel, style: TextStyle(color: Theme.of(context).colorScheme.primary, fontWeight: FontWeight.w600)),
              const Spacer(),
              Text('${job.foundCount}/${job.targetResults}', style: Theme.of(context).textTheme.bodySmall),
            ]),
            if (job.isActive) ...[
              const SizedBox(height: 9),
              LinearProgressIndicator(value: job.progress.clamp(0, 1)),
            ],
          ]),
        ),
      ),
    );
  }
}

class ResultCard extends StatelessWidget {
  const ResultCard({super.key, required this.item});
  final SearchResult item;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            CircleAvatar(child: Text('${item.rank}')),
            const SizedBox(width: 10),
            Expanded(child: Text(item.title, style: const TextStyle(fontWeight: FontWeight.w700))),
            Text('${item.score.toStringAsFixed(0)}%'),
          ]),
          if (item.summary.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(item.summary, maxLines: 7, overflow: TextOverflow.ellipsis),
          ],
          const SizedBox(height: 8),
          TextButton.icon(
            onPressed: () => launchUrl(Uri.parse(item.url), mode: LaunchMode.externalApplication),
            icon: const Icon(Icons.open_in_new_rounded),
            label: const Text('المصدر'),
          ),
        ]),
      ),
    );
  }
}

class ResultsPage extends StatefulWidget {
  const ResultsPage({super.key, required this.api, required this.job});
  final ApiClient api;
  final SearchJob job;

  @override
  State<ResultsPage> createState() => _ResultsPageState();
}

class _ResultsPageState extends State<ResultsPage> {
  List<SearchResult> results = const [];
  bool loading = true;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      final data = await widget.api.results(widget.job.id);
      if (mounted) setState(() => results = data);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.job.title, maxLines: 1, overflow: TextOverflow.ellipsis)),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: load,
              child: results.isEmpty
                  ? ListView(children: const [SizedBox(height: 90), _EmptyState(icon: Icons.search_off_rounded, text: 'لا توجد نتائج بعد')])
                  : ListView.separated(
                      padding: const EdgeInsets.all(16),
                      itemCount: results.length,
                      separatorBuilder: (_, __) => const SizedBox(height: 12),
                      itemBuilder: (_, i) => ResultCard(item: results[i]),
                    ),
            ),
    );
  }
}

class SettingsPage extends StatefulWidget {
  const SettingsPage({
    super.key,
    required this.api,
    required this.dark,
    required this.onThemeChanged,
    required this.onAccountChanged,
  });
  final ApiClient api;
  final bool dark;
  final ValueChanged<bool> onThemeChanged;
  final VoidCallback onAccountChanged;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  bool? connected;
  bool checkingUpdate = false;

  @override
  void initState() {
    super.initState();
    checkServer();
  }

  Future<void> checkServer() async {
    final ok = await widget.api.health();
    if (mounted) setState(() => connected = ok);
  }

  Future<void> showPairCode() async {
    try {
      final data = await widget.api.createPairCode();
      if (!mounted) return;
      final code = data['code'] as String? ?? '';
      await showDialog<void>(
        context: context,
        builder: (_) => AlertDialog(
          title: const Text('رمز الربط'),
          content: SelectableText(code, textAlign: TextAlign.center, style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w800, letterSpacing: 3)),
          actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('إغلاق'))],
        ),
      );
    } catch (_) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('تعذر إنشاء رمز الربط')));
    }
  }

  Future<void> enterPairCode() async {
    final controller = TextEditingController();
    final code = await showDialog<String>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('ربط هذا الجهاز'),
        content: TextField(controller: controller, autofocus: true, textCapitalization: TextCapitalization.characters, decoration: const InputDecoration(hintText: 'رمز الربط')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('إلغاء')),
          FilledButton(onPressed: () => Navigator.pop(context, controller.text.trim()), child: const Text('ربط')),
        ],
      ),
    );
    controller.dispose();
    if (code == null || code.isEmpty) return;
    try {
      await widget.api.pair(code);
      if (!mounted) return;
      widget.onAccountChanged();
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('تم ربط الجهاز')));
    } catch (_) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('رمز غير صالح أو منتهي')));
    }
  }

  Future<void> showDevices() async {
    try {
      final devices = await widget.api.devices();
      if (!mounted) return;
      await showModalBottomSheet<void>(
        context: context,
        showDragHandle: true,
        builder: (sheetContext) => SafeArea(
          child: ListView(
            shrinkWrap: true,
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 20),
            children: [
              const ListTile(title: Text('الأجهزة المرتبطة', style: TextStyle(fontWeight: FontWeight.w700))),
              ...devices.map((device) {
                final current = device['current'] == true;
                return ListTile(
                  leading: Icon((device['name'] as String?) == 'Windows' ? Icons.computer_rounded : Icons.smartphone_rounded),
                  title: Text((device['name'] as String?) ?? 'جهاز'),
                  subtitle: current ? const Text('هذا الجهاز') : null,
                  trailing: current
                      ? null
                      : IconButton(
                          icon: const Icon(Icons.link_off_rounded),
                          onPressed: () async {
                            await widget.api.revokeDevice(device['id'] as String);
                            if (sheetContext.mounted) Navigator.pop(sheetContext);
                          },
                        ),
                );
              }),
            ],
          ),
        ),
      );
    } catch (_) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('تعذر تحميل الأجهزة')));
    }
  }

  Future<void> checkUpdate() async {
    setState(() => checkingUpdate = true);
    final update = await UpdateService().check();
    if (!mounted) return;
    setState(() => checkingUpdate = false);
    if (update == null) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('أنت على آخر إصدار')));
      return;
    }
    final install = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('تحديث متوفر'),
        content: Text('الإصدار ${update.version}'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('لاحقًا')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('تحديث')),
        ],
      ),
    );
    if (install == true) {
      try {
        await UpdateService().install(update);
      } catch (_) {
        if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('تعذر تثبيت التحديث')));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        SwitchListTile(
          value: widget.dark,
          onChanged: widget.onThemeChanged,
          title: const Text('الوضع الداكن'),
          secondary: const Icon(Icons.dark_mode_outlined),
        ),
        ListTile(
          leading: Icon(connected == true ? Icons.cloud_done_outlined : Icons.cloud_off_outlined),
          title: const Text('السيرفر'),
          trailing: Text(connected == null ? '...' : connected! ? 'متصل' : 'غير متصل'),
          onTap: checkServer,
        ),
        ListTile(
          leading: const Icon(Icons.qr_code_2_rounded),
          title: const Text('رمز ربط جهاز'),
          onTap: showPairCode,
        ),
        ListTile(
          leading: const Icon(Icons.add_link_rounded),
          title: const Text('إدخال رمز ربط'),
          onTap: enterPairCode,
        ),
        ListTile(
          leading: const Icon(Icons.devices_rounded),
          title: const Text('الأجهزة المرتبطة'),
          onTap: showDevices,
        ),
        const ListTile(
          leading: Icon(Icons.archive_outlined),
          title: Text('الأرشيف'),
          subtitle: Text('محلي على هذا الجهاز فقط'),
        ),
        ListTile(
          leading: const Icon(Icons.system_update_alt_rounded),
          title: const Text('التحديثات'),
          trailing: checkingUpdate
              ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
              : const Icon(Icons.chevron_left_rounded),
          onTap: checkingUpdate ? null : checkUpdate,
        ),
      ],
    );
  }
}
