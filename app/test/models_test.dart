import 'package:flutter_test/flutter_test.dart';
import 'package:deep_search/models.dart';

SearchJob job({
  required String inputType,
  required bool mediaAvailable,
  String status = 'completed',
}) =>
    SearchJob(
      id: 'job-1',
      query: 'test',
      inputType: inputType,
      status: status,
      progress: 1,
      foundCount: 3,
      targetResults: 10,
      attempts: 5,
      mediaAvailable: mediaAvailable,
    );

void main() {
  sourceUriTests();
  test('text jobs can continue without media', () {
    expect(job(inputType: 'text', mediaAvailable: false).canContinue, isTrue);
  });

  test('completed media jobs cannot continue after temporary upload purge', () {
    expect(job(inputType: 'image', mediaAvailable: false).canContinue, isFalse);
    expect(job(inputType: 'video', mediaAvailable: false).canContinue, isFalse);
  });

  test('media jobs can continue while their temporary upload still exists', () {
    expect(job(inputType: 'image', mediaAvailable: true).canContinue, isTrue);
  });

  test('completed purged media jobs hide clue actions', () {
    expect(job(inputType: 'video', mediaAvailable: false).canAddClue, isFalse);
  });

  test('active media and completed text jobs still accept clues', () {
    expect(job(inputType: 'video', mediaAvailable: true, status: 'running').canAddClue, isTrue);
    expect(job(inputType: 'text', mediaAvailable: false).canAddClue, isTrue);
  });
}


void sourceUriTests() {
  test('result sources include primary and unique safe supporting URLs', () {
    final result = SearchResult(
      rank: 1,
      title: 'Example',
      url: 'https://primary.example/item',
      summary: '',
      score: 90,
      evidence: const {
        'supporting_sources': [
          {'url': 'https://primary.example/item', 'domain': 'primary.example'},
          {'url': 'https://second.example/page', 'domain': 'second.example'},
          {'url': 'javascript:alert(1)', 'domain': 'bad.example'},
        ],
      },
    );

    expect(
      result.sourceUris.map((uri) => uri.toString()).toList(),
      [
        'https://primary.example/item',
        'https://second.example/page',
      ],
    );
    expect(result.supportingSourceCount, 2);
  });
}
