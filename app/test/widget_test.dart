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
}
