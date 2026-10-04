"""Generate Brutal OP25 logo options with OpenAI's image API.

Run this yourself. The key is read from your environment and never written anywhere:

    PowerShell:   $env:OPENAI_API_KEY = '<your key>'; py -m tools.generate_logo_options
    bash:         OPENAI_API_KEY=<your key> python3 -m tools.generate_logo_options

Images land in ./logo-options (one PNG per concept). Nothing from this project is sent except the
text prompts below. Each image is billed to your OpenAI account.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

STYLE = ("Flat vector-style app logo mark on a plain near-black graphite background (#0d1013). One accent colour only: "
         "blue #4c90f0, plus white and mid-grey. Sharp, geometric, technical and understated, like a defence or "
         "intelligence software product. No text, no letters, no gradients, no glow, centred with generous margin.")
CONCEPTS = {
    'reticle': "A refined targeting reticle: a thin circle with four tick marks and a small centre dot, with a "
               "faint radar sweep wedge. " + STYLE,
    'monogram': "A bold geometric monogram suggesting the letters B and O fused into one angular emblem, "
                "built from straight lines and one blue notch. " + STYLE,
    'tower': "A minimal radio tower silhouette with three concentric signal arcs on one side, drawn as clean "
             "angular strokes inside a thin square frame. " + STYLE,
    'waveform': "A horizontal spectrum / waveform trace forming a single peak inside a thin hexagon outline, "
                "like a signals-intelligence mark. " + STYLE,
}


def generate(key, model, prompt, size):
    body = json.dumps({'model': model, 'prompt': prompt, 'size': size, 'n': 1}).encode()
    request = urllib.request.Request('https://api.openai.com/v1/images/generations', data=body, method='POST',
                                     headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=180) as response:
        item = json.loads(response.read())['data'][0]
    if item.get('b64_json'):
        return base64.b64decode(item['b64_json'])
    with urllib.request.urlopen(item['url'], timeout=60) as response:
        return response.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', default='logo-options')
    parser.add_argument('--model', default='gpt-image-1', help='image model name (default: gpt-image-1)')
    parser.add_argument('--size', default='1024x1024')
    parser.add_argument('--only', choices=sorted(CONCEPTS), help='generate just one concept')
    args = parser.parse_args()
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not key:
        sys.exit('Set OPENAI_API_KEY in your own terminal first (see the top of this file). It is not read from any file.')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, prompt in CONCEPTS.items():
        if args.only and name != args.only:
            continue
        try:
            (out / f'{name}.png').write_bytes(generate(key, args.model, prompt, args.size))
            print('saved', out / f'{name}.png')
        except urllib.error.HTTPError as error:
            # Print the service's own explanation, never the request headers (they hold the key).
            detail = error.read().decode(errors='replace')[:300]
            print(f'{name}: request failed ({error.code}): {detail}')
        except (urllib.error.URLError, OSError, KeyError, ValueError) as error:
            print(f'{name}: failed: {error.__class__.__name__}')


if __name__ == '__main__':
    main()
