import 'package:flutter_test/flutter_test.dart';
import 'package:deep_search/models.dart';

SearchJob job({required String inputType, required bool mediaAvailable}) => SearchJob(
      id: 'job-1',
      query: 'test',
      inputType: inputType,
      status: 'completed',
      progress: 1,
      foundCount: 3,
      targetResults: 10,
      attempts: 5,
      mediaAvailable: mediaAvailable,
    );

void main() {
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
}
