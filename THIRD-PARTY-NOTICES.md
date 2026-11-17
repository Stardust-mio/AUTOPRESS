# Third-party notices（第三方元件授權聲明）

AutoPress 本身以 GPL-3.0 授權（全文見 [LICENSE](LICENSE)）。發佈的 `AutoPress.exe`（`AutoPress-<版本>-win64.zip`）內含下列第三方元件；它們沿用各自的上游授權，授權全文放在 [`licenses/`](licenses/) 資料夾。以下內容以英文撰寫，元件名稱與授權條款原文照錄。

AutoPress itself is licensed under the GNU General Public License version 3 (see [LICENSE](LICENSE)). The release build (`AutoPress.exe` with its `_internal` folder) is GPL-3.0 as a whole because it contains PyQt6, which is licensed under GPL-3.0 only.

The release build contains the third-party components below. They keep their own upstream licences (not AutoPress's licence); the full texts are in the [`licenses/`](licenses/) folder. Licence names follow each package's `METADATA` and licence files.

## Components

| Component | Version | Licence | Full text in `licenses/` | Upstream source |
|---|---|---|---|---|
| Python (python.org Windows x64 build; standard library modules collected by PyInstaller) | 3.12.10 | PSF-2.0; components of the Windows build (MSVC runtime, libffi, OpenSSL, bzip2, ...) and software incorporated in `python312.dll` (Mersenne Twister, SipHash, dtoa, HACL*, ...) as listed in the two files | [Python-LICENSE.txt](licenses/Python-LICENSE.txt), [Python-3.12.10-incorporated-software.txt](licenses/Python-3.12.10-incorporated-software.txt) | <https://www.python.org/downloads/release/python-31210/> |
| PyQt6 | 6.12.1 | GPL-3.0-only | [PyQt6-LICENSE.txt](licenses/PyQt6-LICENSE.txt) | <https://pypi.org/project/PyQt6/6.12.1/#files> |
| PyQt6-Qt6 (Qt 6: QtCore, QtGui, QtWidgets, QtSvg; plugins qwindows, qico, qsvg, qsvgicon; translation qtbase_zh_TW) | 6.12.0 | LGPL-3.0 (the package says "LGPL v3"); third-party code inside Qt: see the notices file | [PyQt6-Qt6-LICENSE.txt](licenses/PyQt6-Qt6-LICENSE.txt), [Qt-6.12.0-third-party-notices.txt](licenses/Qt-6.12.0-third-party-notices.txt) | <https://download.qt.io/archive/qt/6.12/6.12.0/> (`submodules/`: `qtbase-everywhere-src-6.12.0.tar.xz`, `qtsvg-everywhere-src-6.12.0.tar.xz`, `qttranslations-everywhere-src-6.12.0.tar.xz`) |
| PyQt6_sip | 13.13.1 | BSD-2-Clause | [PyQt6_sip-LICENSE.txt](licenses/PyQt6_sip-LICENSE.txt) | <https://pypi.org/project/PyQt6-sip/13.13.1/#files> |
| PyInstaller (bootloader and run-time modules in the exe) | 6.22.3 | GPL-2.0-or-later with the Bootloader Exception; the run-time hooks are Apache-2.0 | [PyInstaller-LICENSE.txt](licenses/PyInstaller-LICENSE.txt) | <https://github.com/pyinstaller/pyinstaller/tree/v6.22.3> |
| rapidocr | 3.10.0 | Apache-2.0 | [rapidocr-LICENSE.txt](licenses/rapidocr-LICENSE.txt) | <https://pypi.org/project/rapidocr/3.10.0/#files> |
| PP-OCRv6 small detection and recognition models (`PP-OCRv6_det_small.onnx`, `PP-OCRv6_rec_small.onnx`, shipped in the rapidocr package) | rapidocr 3.10.0 | Apache-2.0; model weights copyright Baidu / the PaddleOCR authors (attribution required) | [rapidocr-MODEL_LICENSES.md](licenses/rapidocr-MODEL_LICENSES.md) | <https://github.com/PaddlePaddle/PaddleOCR> |
| onnxruntime | 1.32.0 | MIT; third-party code inside ONNX Runtime: see ThirdPartyNotices | [onnxruntime-LICENSE.txt](licenses/onnxruntime-LICENSE.txt), [onnxruntime-ThirdPartyNotices.txt](licenses/onnxruntime-ThirdPartyNotices.txt) | <https://pypi.org/project/onnxruntime/1.32.0/#files> |
| opencv-python-headless (OpenCV) | 5.0.0.93 | MIT (packaging scripts); OpenCV Apache-2.0 and the bundled third-party libraries as listed in LICENSE-3RD-PARTY (the FFmpeg plugin is NOT bundled) | [opencv-python-headless-LICENSE.txt](licenses/opencv-python-headless-LICENSE.txt), [opencv-python-headless-LICENSE-3RD-PARTY.txt](licenses/opencv-python-headless-LICENSE-3RD-PARTY.txt) | <https://pypi.org/project/opencv-python-headless/5.0.0.93/#files> |
| numpy | 2.5.5 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0; the bundled OpenBLAS, LAPACK and GCC runtime library are listed in numpy-LICENSE.txt; licences of code vendored inside numpy are in `licenses/numpy/` | [numpy-LICENSE.txt](licenses/numpy-LICENSE.txt), [numpy/](licenses/numpy/) | <https://pypi.org/project/numpy/2.5.5/#files> |
| Pillow | 13.0.0 | MIT-CMU; the bundled image libraries are listed in the same file (the AVIF codec is NOT bundled) | [Pillow-LICENSE.txt](licenses/Pillow-LICENSE.txt) | <https://pypi.org/project/pillow/13.0.0/#files> |
| mss | 10.2.0 | MIT | [mss-LICENSE.txt](licenses/mss-LICENSE.txt) | <https://pypi.org/project/mss/10.2.0/#files> |
| shapely (with GEOS) | 2.2.0 | BSD-3-Clause; the bundled GEOS library is LGPL-2.1; the bundled MSVC runtime is listed in LICENSE_win32 | [shapely-LICENSE.txt](licenses/shapely-LICENSE.txt), [shapely-LICENSE_GEOS.txt](licenses/shapely-LICENSE_GEOS.txt), [shapely-LICENSE_win32.txt](licenses/shapely-LICENSE_win32.txt) | <https://pypi.org/project/shapely/2.2.0/#files> |
| pyclipper (with the Clipper library) | 1.4.0 | MIT (the Clipper C++ library it compiles in is under the Boost Software License 1.0, which needs no notice for object code) | [pyclipper-LICENSE.txt](licenses/pyclipper-LICENSE.txt) | <https://pypi.org/project/pyclipper/1.4.0/#files> |
| omegaconf (with its vendored ANTLR 4 runtime) | 2.4.0 | BSD-3-Clause; ANTLR 4 runtime BSD-3-Clause | [omegaconf-LICENSE.txt](licenses/omegaconf-LICENSE.txt), [omegaconf-LICENSE-antlr4.txt](licenses/omegaconf-LICENSE-antlr4.txt) | <https://pypi.org/project/omegaconf/2.4.0/#files> |
| PyYAML | 6.0.3 | MIT | [PyYAML-LICENSE.txt](licenses/PyYAML-LICENSE.txt) | <https://pypi.org/project/PyYAML/6.0.3/#files> |
| protobuf | 7.36.2 | BSD-3-Clause | [protobuf-LICENSE.txt](licenses/protobuf-LICENSE.txt) | <https://pypi.org/project/protobuf/7.36.2/#files> |
| flatbuffers | 25.12.19 | Apache-2.0 | [flatbuffers-LICENSE-Apache-2.0.txt](licenses/flatbuffers-LICENSE-Apache-2.0.txt) | <https://pypi.org/project/flatbuffers/25.12.19/#files> |
| requests | 2.34.2 | Apache-2.0 | [requests-LICENSE.txt](licenses/requests-LICENSE.txt), [requests-NOTICE.txt](licenses/requests-NOTICE.txt) | <https://pypi.org/project/requests/2.34.2/#files> |
| urllib3 | 2.8.0 | MIT | [urllib3-LICENSE.txt](licenses/urllib3-LICENSE.txt) | <https://pypi.org/project/urllib3/2.8.0/#files> |
| idna | 3.20 | BSD-3-Clause | [idna-LICENSE.md](licenses/idna-LICENSE.md) | <https://pypi.org/project/idna/3.20/#files> |
| certifi | 2026.10.23 | MPL-2.0 | [certifi-LICENSE.txt](licenses/certifi-LICENSE.txt) | <https://pypi.org/project/certifi/2026.10.23/#files> |
| charset-normalizer | 3.5.2 | MIT | [charset_normalizer-LICENSE.txt](licenses/charset_normalizer-LICENSE.txt) | <https://pypi.org/project/charset-normalizer/3.5.2/#files> |
| tqdm | 4.70.1 | MPL-2.0 AND MIT | [tqdm-LICENCE.txt](licenses/tqdm-LICENCE.txt) | <https://pypi.org/project/tqdm/4.70.1/#files> |
| colorlog | 6.12.0 | MIT | [colorlog-LICENSE.txt](licenses/colorlog-LICENSE.txt) | <https://pypi.org/project/colorlog/6.12.0/#files> |
| colorama (required by colorlog on Windows) | 0.4.6 | BSD-3-Clause | [colorama-LICENSE.txt](licenses/colorama-LICENSE.txt) | <https://pypi.org/project/colorama/0.4.6/#files> |
| six | 1.17.0 | MIT | [six-LICENSE.txt](licenses/six-LICENSE.txt) | <https://pypi.org/project/six/1.17.0/#files> |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | [packaging-LICENSE.txt](licenses/packaging-LICENSE.txt), [packaging-LICENSE.APACHE.txt](licenses/packaging-LICENSE.APACHE.txt), [packaging-LICENSE.BSD.txt](licenses/packaging-LICENSE.BSD.txt) | <https://pypi.org/project/packaging/26.3/#files> |

## Where the licence texts come from

Every file in `licenses/` is an unchanged copy (byte for byte) of a file installed with the Python and the packages the release is built with (`.venv`, versions pinned in `requirements.txt`), except:

- `Python-3.12.10-incorporated-software.txt`: the Windows `LICENSE.txt` of Python does not contain the notices of the third-party code compiled into `python312.dll`, so this file holds unchanged excerpts of the CPython sources at tag `v3.12.10` (`Doc/license.rst` from "Licenses and Acknowledgements for Incorporated Software" to the end, plus the HACL* notices); the first lines say exactly where each excerpt comes from.
- `Qt-6.12.0-third-party-notices.txt`: the PyQt6-Qt6 package ships no notices for the third-party code inside Qt, so this file was compiled from the `qt_attribution.json` files of the qtbase 6.12.0 source archive (sha256 checked against download.qt.io) and the licence files they point to, copied unchanged. The qtsvg 6.12.0 sources contain no attribution entries.
- `flatbuffers-LICENSE-Apache-2.0.txt`: the flatbuffers wheel ships no licence file (its `METADATA` says "Apache 2.0"); the file is the Apache License 2.0 text as shipped in the packaging package (`LICENSE.APACHE`). Copyright notice of flatbuffers, from the header of `flatbuffers/builder.py`: `Copyright 2014 Google Inc. All rights reserved.`

## Other notices

- **FreeType** (inside Qt GUI, used under the FreeType License): Portions of this software are copyright © 2026 The FreeType Project (www.freetype.org). All rights reserved.
- **Microsoft Visual C++ runtime** (`vcruntime140*.dll`, `msvcp140*.dll`, `concrt140.dll`; shipped by Python, PyQt6-Qt6, numpy and shapely): Microsoft "Distributable Code" of the Visual C++ Redistributable, not open source, redistributed unchanged together with the packages that ship it; see the "Additional Conditions for this Windows binary build" section of [Python-LICENSE.txt](licenses/Python-LICENSE.txt), [shapely-LICENSE_win32.txt](licenses/shapely-LICENSE_win32.txt) and <https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution>.
- **App icon and templates** (`autopress/resources/`): made for this project (`tools/make_icon.py`, the `*.autopress.json` templates); GPL-3.0 like the source code.
- AutoPress needs no network at run time. `requests`, `urllib3`, `idna`, `certifi` and `charset-normalizer` are in the build only because rapidocr imports them (for optional model downloads that AutoPress never uses: the models are loaded from explicit paths).

## Source code

This repository at the tag of a release (source code, `autopress.spec`, `build.ps1`, `tools/make_icon.py` and `requirements.txt` with the pinned versions) is the Corresponding Source of that release under the GPL. The sources of the third-party components are available from the links in the table.

## Qt and the LGPL-3.0

Qt is licensed under the LGPL-3.0, which is a set of additional permissions on top of the GPL-3.0 (full text in [LICENSE](LICENSE); [PyQt6-LICENSE.txt](licenses/PyQt6-LICENSE.txt) is the same licence). The release uses Qt as shared libraries (`Qt6Core.dll`, `Qt6Gui.dll`, `Qt6Widgets.dll`, `Qt6Svg.dll` in `_internal\PyQt6\Qt6\bin`): you can replace them, or rebuild AutoPress with your own (or modified) Qt / PyQt6 in `.venv` by following the build steps in the [README](README.md#從原始碼執行與打包).
