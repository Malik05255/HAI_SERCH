import 'package:deep_search/updates.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('version comparison only upgrades to newer semantic versions', () {
    expect(compareVersions('1.2.3', '1.2.2'), greaterThan(0));
    expect(compareVersions('1.2.3', '1.2.3'), 0);
    expect(compareVersions('1.2.2', '1.2.3'), lessThan(0));
    expect(compareVersions('2.0.0+12', '1.9.9'), greaterThan(0));
  });

  test('sha256 parser accepts standard checksum files', () {
    const hash = '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef';
    expect(parseSha256('$hash  deep-search-android.apk\n'), hash);
    expect(parseSha256(hash.toUpperCase()), hash);
  });

  test('sha256 parser rejects malformed checksum content', () {
    expect(parseSha256(''), isNull);
    expect(parseSha256('not-a-hash  file.apk'), isNull);
    expect(parseSha256('abc123'), isNull);
  });
}
