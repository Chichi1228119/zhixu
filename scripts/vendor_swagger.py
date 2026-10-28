"""Fetch the pinned Swagger UI assets from official npm, verifying SHA512 first."""
import base64
import hashlib
import io
import json
from pathlib import Path
import tarfile
import urllib.request

VERSION = '5.34.0'
URL = f'https://registry.npmjs.org/swagger-ui-dist/-/swagger-ui-dist-{VERSION}.tgz'
INTEGRITY = 'H6tAIjr3XqE31PbkZl0OFya1ziRLDfTwh3J6OHdumPtPCLfjTnyLeagl/55kFNZcTOz9a9QI9WP0FXldwiGJag=='
DESTINATION = Path(__file__).resolve().parent.parent / 'app' / 'static' / 'swagger'


def main():
    with urllib.request.urlopen(URL, timeout=60) as response:
        content = response.read(8 * 1024 * 1024)
    if hashlib.sha512(content).digest() != base64.b64decode(INTEGRITY):
        raise ValueError('Official archive did not match the pinned npm integrity digest.')
    DESTINATION.mkdir(parents=True, exist_ok=True)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(content), mode='r:gz') as archive:
        for name in ('swagger-ui-bundle.js', 'swagger-ui-bundle.js.LICENSE.txt', 'swagger-ui.css', 'LICENSE', 'NOTICE'):
            member = archive.getmember('package/' + name)
            if not member.isfile() or member.size > 4 * 1024 * 1024:
                raise ValueError('Unexpected asset type or size.')
            stream = archive.extractfile(member)
            payload = stream.read()
            (DESTINATION / name).write_bytes(payload)
            files[name] = {'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
    (DESTINATION / 'provenance.json').write_text(json.dumps({'package': 'swagger-ui-dist', 'version': VERSION,
        'license': 'Apache-2.0', 'source': URL, 'integrity': 'sha512-' + INTEGRITY, 'files': files}, indent=2) + '\n', encoding='utf-8')
    print('Verified and vendored Swagger UI ' + VERSION)


if __name__ == '__main__':
    main()
