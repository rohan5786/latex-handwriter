#!/usr/bin/env bash
# downloads the two single-header libraries the renderer uses (public domain / MIT)
cd "$(dirname "$0")" && for f in stb_image.h stb_image_write.h; do
  [ -f $f ] || curl -sSfL -o $f https://raw.githubusercontent.com/nothings/stb/master/$f && echo "ok $f"; done
