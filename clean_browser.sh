#!/bin/bash
# Очистка временных файлов Chromium
find /tmp/snap-private-tmp/snap.chromium/tmp/ -name '.org.chromium.Chromium.*' -type d -ctime +1 -exec rm -rf {} \;
# Очистка других временных файлов
find /tmp -type f -ctime +3 -delete
