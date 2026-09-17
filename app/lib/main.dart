import 'dart:async';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'api.dart';
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
    const seed = Color(0xFF2357D9);
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'البحث العميق',
      themeMode: mode,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: seed, brightness: Brightness.light),
        useMaterial3: true,
        scaffoldBackgroundColor: const Color(0xFFF7F8FA),
        inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder()),
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
  final api = const ApiClient();
  int index = 0;

  @override
  Widget build(BuildContext context) {
    final pages = [
      SearchPage(api: api),
      HistoryPage(api: api),
      SettingsPage(api: api, dark: widget.dark, onThemeChanged: widget.onThemeChanged),
    ];
    return Scaffold(
      appBar: AppBar(
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
          NavigationDestination(icon: Icon(Icons.history_rounded), label: 'السجل'),
          NavigationDestination(icon: Icon(Icons.tune_rounded), label: 'الإعدادات'),
        ],
      ),
    );
  }
}

class SearchPage extends StatefulWidget {
  const SearchPage({super.key, required this.api});
  final ApiClient api;

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
  List<SearchJob> jobs = const [];
  Timer? timer;

  @override
  void initState() {
    super.initState();
    refresh();
    timer = Timer.periodic(const Duration(seconds: 15), (_) => refresh(silent: true));
  }

  @override
  void dispose() {
    timer?.cancel();
    controller.dispose();
    super.dispose();
  }

  Future<void> refresh({bool silent = false}) async {
    if (!silent && mounted) setState(() => loading = true);
    try {
      final data = await widget.api.listJobs();
      if (mounted) setState(() => jobs = data);
    } catch (_) {
      if (!silent && mounted) _message('تعذر الاتصال');
    } finally {
      if (!silent && mounted) setState(() => loading = false);
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
      String? inputUrl;
      var inputType = mode;
      if (filePath != null && mode != 'text') {
        final upload = await widget.api.upload(filePath!);
        inputUrl = upload['input_url'] as String?;
        inputType = (upload['input_type'] as String?) ?? mode;
      }
      await widget.api.createJob(query: query, inputType: inputType, inputUrl: inputUrl);
      controller.clear();
      setState(() {
        filePath = null;
        fileName = null;
        mode = 'text';
      });
      await refresh(silent: true);
    } catch (_) {
      _message('لم يبدأ البحث');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  void _message(String text) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  @override
  Widget build(BuildContext context) {
    final active = jobs.where((j) => !['completed', 'partial'].contains(j.status)).take(8).toList();
    return RefreshIndicator(
      onRefresh: refresh,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
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
            minLines: 2,
            maxLines: 5,
            decoration: InputDecoration(
              hintText: 'وش تبي أبحث عنه؟',
              suffixIcon: mode == 'text'
                  ? null
                  : IconButton(onPressed: pickFile, icon: const Icon(Icons.attach_file_rounded)),
            ),
          ),
          if (fileName != null) ...[
            const SizedBox(height: 8),
            InputChip(label: Text(fileName!, overflow: TextOverflow.ellipsis), onDeleted: () => setState(() { fileName = null; filePath = null; })),
          ],
          const SizedBox(height: 10),
          FilledButton.icon(
            onPressed: busy ? null : submit,
            icon: busy
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.manage_search_rounded),
            label: const Padding(padding: EdgeInsets.symmetric(vertical: 13), child: Text('ابدأ البحث')),
          ),
          const SizedBox(height: 24),
          if (loading)
            const Center(child: CircularProgressIndicator())
          else if (active.isNotEmpty) ...[
            const Text('الآن', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            ...active.map((job) => JobCard(job: job, api: widget.api, onChanged: refresh)),
          ],
        ],
      ),
    );
  }
}

class HistoryPage extends StatefulWidget {
  const HistoryPage({super.key, required this.api});
  final ApiClient api;

  @override
  State<HistoryPage> createState() => _HistoryPageState();
}

class _HistoryPageState extends State<HistoryPage> {
  List<SearchJob> jobs = const [];
  bool loading = true;

  @override
  void initState() {
    super.initState();
    refresh();
  }

  Future<void> refresh() async {
    try {
      final data = await widget.api.listJobs();
      if (mounted) setState(() => jobs = data);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (loading) return const Center(child: CircularProgressIndicator());
    return RefreshIndicator(
      onRefresh: refresh,
      child: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: jobs.length,
        itemBuilder: (_, index) => JobCard(job: jobs[index], api: widget.api, onChanged: refresh),
      ),
    );
  }
}

class JobCard extends StatelessWidget {
  const JobCard({super.key, required this.job, required this.api, required this.onChanged});
  final SearchJob job;
  final ApiClient api;
  final Future<void> Function() onChanged;

  String get statusLabel => switch (job.status) {
        'queued' => 'بانتظار البحث',
        'running' => 'يبحث',
        'completed' => 'مكتمل',
        'partial' => 'جزئي',
        'stopped' => 'متوقف',
        'needs_context' => 'يحتاج وصف',
        'failed' => 'تعذر',
        _ => job.status,
      };

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => ResultsPage(api: api, job: job))),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Expanded(child: Text(job.title, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w700))),
              const SizedBox(width: 8),
              Chip(label: Text(statusLabel)),
            ]),
            const SizedBox(height: 10),
            LinearProgressIndicator(value: job.progress.clamp(0, 1)),
            const SizedBox(height: 7),
            Row(children: [
              Text('${job.foundCount}/${job.targetResults}', style: Theme.of(context).textTheme.bodySmall),
              const Spacer(),
              if (job.status == 'running' || job.status == 'queued')
                TextButton(
                  onPressed: () async { await api.action(job.id, 'stop'); await onChanged(); },
                  child: const Text('إيقاف'),
                )
              else if (job.status == 'stopped')
                TextButton(
                  onPressed: () async { await api.action(job.id, 'resume'); await onChanged(); },
                  child: const Text('متابعة'),
                ),
            ]),
          ]),
        ),
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
              child: ListView.builder(
                padding: const EdgeInsets.all(16),
                itemCount: results.length,
                itemBuilder: (_, index) {
                  final item = results[index];
                  return Card(
                    margin: const EdgeInsets.only(bottom: 12),
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
                          Text(item.summary, maxLines: 6, overflow: TextOverflow.ellipsis),
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
                },
              ),
            ),
    );
  }
}

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key, required this.api, required this.dark, required this.onThemeChanged});
  final ApiClient api;
  final bool dark;
  final ValueChanged<bool> onThemeChanged;

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
          leading: const Icon(Icons.system_update_alt_rounded),
          title: const Text('التحديثات'),
          trailing: checkingUpdate ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.chevron_left_rounded),
          onTap: checkingUpdate ? null : checkUpdate,
        ),
      ],
    );
  }
}
