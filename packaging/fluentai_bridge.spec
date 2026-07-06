# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata


ROOT = Path(SPECPATH).resolve().parent

datas = []
binaries = []
hiddenimports = []

datas.append((str(ROOT / "fluent_ai" / "curriculum"), "fluent_ai/curriculum"))


def add_collect_all(package):
    package_datas, package_binaries, package_hiddenimports = collect_all(package, include_py_files=False)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)


def add_collect_package(package, *, submodule_filter=lambda name: True):
    datas.extend(collect_data_files(package, include_py_files=False))
    binaries.extend(collect_dynamic_libs(package))
    hiddenimports.extend(collect_submodules(package, filter=submodule_filter))


def keep_hidden_import(name):
    excluded_prefixes = (
        "annotated_types.test_cases",
        "anyio.pytest_plugin",
        "openai.cli",
        "openai.helpers",
        "pydantic.mypy",
        "pydantic.v1._hypothesis_plugin",
        "pydantic.v1.mypy",
        "sniffio._tests",
        "tqdm.dask",
        "tqdm.gui",
        "tqdm.keras",
        "tqdm.notebook",
        "tqdm.rich",
        "tqdm.tk",
        "tqdm.contrib.discord",
        "tqdm.contrib.slack",
        "tqdm.contrib.telegram",
    )
    return not any(name == prefix or name.startswith(f"{prefix}.") for prefix in excluded_prefixes)


# This is the installed OpenAI SDK dependency closure used by fluent_ai.openai_provider.
# Optional OpenAI helper extras that require numpy/pandas/sounddevice are excluded below.
add_collect_package("openai", submodule_filter=keep_hidden_import)

for package in (
    "anyio",
    "distro",
    "httpx",
    "jiter",
    "pydantic",
    "sniffio",
    "tqdm",
    "idna",
    "certifi",
    "httpcore",
    "annotated_types",
    "pydantic_core",
    "typing_inspection",
    "h11",
):
    add_collect_all(package)

hiddenimports.append("typing_extensions")

for distribution in (
    "openai",
    "anyio",
    "distro",
    "httpx",
    "jiter",
    "pydantic",
    "sniffio",
    "tqdm",
    "typing-extensions",
    "idna",
    "certifi",
    "httpcore",
    "annotated-types",
    "pydantic-core",
    "typing-inspection",
    "h11",
):
    datas.extend(copy_metadata(distribution, recursive=False))

datas = list(dict.fromkeys(datas))
binaries = list(dict.fromkeys(binaries))
hiddenimports = sorted({name for name in hiddenimports if keep_hidden_import(name)})

excludes = [
    "IPython",
    "PIL",
    "matplotlib",
    "numpy",
    "openai.cli",
    "openai.helpers",
    "pandas",
    "pytest",
    "sounddevice",
    "tests",
    "tkinter",
    "unittest",
]

a = Analysis(
    [str(ROOT / "packaging" / "bridge_entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="fluentai-bridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="fluentai-bridge",
)
