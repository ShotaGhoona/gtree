#!/usr/bin/env python3
"""GTREE の入口。本体は app/ にある（gtree --help で使い方）。

~/bin/gtree のようにシンボリックリンクから呼ばれても app/ が見つかるよう、実体の場所を探す。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    main()
