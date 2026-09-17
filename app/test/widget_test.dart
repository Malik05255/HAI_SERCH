import 'package:deep_search/models.dart';
import 'package:flutter_test/flutter_test.dart';

SearchResult _result(Map<String, dynamic> evidence) => SearchResult(
      rank: 1,
      title: 'نتيجة',
      url: 'https://example.com',
      summary: '',
      score: 80,
      evidence: evidence,
    );

SearchJob _job({String status = 'queued', String? lastError}) => SearchJob.fromJson({
      'id': 'job-1',
      'query': 'اختبار',
      'input_type': 'text',
      'status': status,
      'progress': 0,
      'found_count': 0,
      'target_results': 10,
      'attempts': 1,
      'media_available': false,
      'last_error': lastError,
    });

void main() {
  test('sanity', () {
    expect(1 + 1, 2);
  });

  test('media-only jobs have useful Arabic titles', () {
    final image = SearchJob.fromJson({
      'id': '1',
      'query': '',
      'input_type': 'image',
      'status': 'queued',
      'progress': 0,
      'found_count': 0,
      'target_results': 10,
      'attempts': 0,
      'media_available': true,
    });
    final video = SearchJob.fromJson({
      'id': '2',
      'query': '',
      'input_type': 'video',
      'status': 'queued',
      'progress': 0,
      'found_count': 0,
      'target_results': 10,
      'attempts': 0,
      'media_available': true,
    });

    expect(image.title, 'بحث بالصورة');
    expect(video.title, 'بحث بالفيديو');
  });

  test('job retry diagnostics are translated without exposing raw backend errors', () {
    final vision = _job(lastError: 'visual_analysis_unavailable');
    final context = _job(status: 'needs_context', lastError: 'insufficient_context');
    final generic = _job(lastError: 'ConnectError: secret backend detail');

    expect(vision.userErrorLabel, 'التحليل البصري غير متاح حاليًا، وسيعاد المحاولة تلقائيًا');
    expect(context.userErrorLabel, 'الأدلة الحالية غير كافية لإكمال البحث');
    expect(generic.userErrorLabel, 'تعذرت آخر محاولة، وسيعاد البحث تلقائيًا');
    expect(generic.userErrorLabel, isNot(contains('secret')));
  });

  test('terminal diagnostics do not promise another retry', () {
    final visionFailed = _job(status: 'failed', lastError: 'visual_analysis_unavailable');
    final searchFailed = _job(status: 'failed', lastError: 'RuntimeError: search_backend_unavailable');

    expect(visionFailed.userErrorLabel, 'تعذر التحليل البصري بعد عدة محاولات');
    expect(searchFailed.userErrorLabel, 'تعذر الوصول إلى محرك البحث بعد عدة محاولات');
  });

  test('temporary search backend outage explains automatic retry', () {
    final job = _job(lastError: 'RuntimeError: search_backend_unavailable');
    expect(job.userErrorLabel, 'محرك البحث غير متاح مؤقتًا، وسيعاد المحاولة تلقائيًا');
  });

  test('empty retry error is treated as no error', () {
    expect(_job(lastError: '   ').lastError, isNull);
    expect(_job(lastError: null).userErrorLabel, isNull);
  });

  test('result keeps server id for secure thumbnail capability routing', () {
    final result = SearchResult.fromJson({
      'id': 42,
      'rank': 1,
      'title': 'نتيجة',
      'url': 'https://example.com/item',
      'summary': 'ملخص',
      'match_score': 91,
      'image_url': null,
      'evidence': <String, dynamic>{},
    });

    expect(result.id, 42);
    expect(result.toJson()['id'], 42);
  });

  test('strong visual evidence is explained to the user', () {
    expect(
      _result({'visual_match': true, 'visual_score': 96}).evidenceLabel,
      'تطابق بصري قوي جدًا',
    );
    expect(
      _result({'visual_match': true, 'visual_score': 72}).evidenceLabel,
      'تطابق بصري قوي',
    );
  });

  test('speech and vision evidence has a combined explanation', () {
    expect(
      _result({'vision_used': true, 'speech_used': true}).evidenceLabel,
      'المشهد والحوار يدعمان النتيجة',
    );
  });

  test('verified_page only reports real source-page verification', () {
    expect(_result({'verified_page': true}).pageVerified, isTrue);
    expect(_result({'verified_page': false}).pageVerified, isFalse);
    expect(_result({}).pageVerified, isFalse);
  });
}
