#!/usr/bin/env python3
"""Translate a practical subset of GCC/G++ command lines to MSVC cl.exe.

Windows-only runner. It discovers VS 2022 Build Tools, creates a VS developer
environment, prints the translated command, and optionally executes it.

Examples:
  py gcc2cl.py --arch x64 -- "g++ -std=c++17 -O2 -Iinclude -DAPP=1 -c src\\main.cpp -o build\\main.obj"
  py gcc2cl.py --arch x64_x86 --command "gcc main.c -o app.exe -Llib -lfoo"
  py gcc2cl.py --dry-run -- "g++ -Wall -Werror main.cpp -o app.exe"
"""
from __future__ import annotations
import argparse, datetime, os, re, shlex, subprocess, sys
from pathlib import Path


def split_command(s: str) -> list[str]:
    # Windows command-line quoting is close enough to this for normal compiler
    # commands; response files are expanded separately below.
    return shlex.split(s, posix=False)


def expand_response_files(args: list[str]) -> list[str]:
    out = []
    for a in args:
        if a.startswith('@') and len(a) > 1:
            p = Path(a[1:].strip('"'))
            if p.exists():
                out.extend(expand_response_files(split_command(p.read_text(encoding='utf-8', errors='replace'))))
            else:
                out.append(a)
        else:
            out.append(a)
    return out


def take_value(args: list[str], i: int, prefix: str):
    a = args[i]
    if a == prefix:
        if i + 1 >= len(args): raise ValueError(f"{prefix} needs a value")
        return args[i + 1], i + 2
    return a[len(prefix):], i + 1


def translate(args: list[str], compiler: str = 'cl') -> tuple[list[str], list[str]]:
    """Return (cl arguments, warnings). The first argument (gcc/g++) is removed."""
    args = expand_response_files(args[:])
    actual_compiler = args[0].lower() if args and not args[0].startswith(('-', '/')) else compiler.lower()
    if args and not args[0].startswith('-') and not args[0].startswith('/'):
        args = args[1:]

    out, link, warnings = [], [], []
    sources = []
    compile_only = False
    output = None
    object_output = None
    is_cpp = actual_compiler in ('g++', 'c++', 'clang++')
    forced_c = False
    forced_cpp = False
    i = 0
    while i < len(args):
        a = args[i]
        if a in ('-c',): compile_only = True; i += 1; continue
        if a in ('-E',): out.append('/P'); i += 1; continue
        if a in ('-S',): warnings.append('-S (assembly-only) is not supported by cl; use /FA'); out.append('/FA'); i += 1; continue
        if a in ('-v', '--verbose'): out.append('/Bv'); i += 1; continue
        if a in ('-shared',): link.append('/DLL'); i += 1; continue
        if a in ('-static',): warnings.append('-static has no direct MSVC equivalent'); i += 1; continue
        if a in ('-pthread',): warnings.append('-pthread ignored: Windows CRT/thread APIs are linked differently'); i += 1; continue
        if a in ('-fPIC', '-fpic', '-fPIE', '-fpie'): i += 1; continue
        if a.startswith(('-I', '/I')):
            v, i = take_value(args, i, '-I' if a.startswith('-I') else '/I'); out.append('/I' + v); continue
        if a in ('-isystem',):
            v, i = take_value(args, i, a); out.append('/I' + v); warnings.append('GCC system include treated as normal /I'); continue
        if a.startswith('-D'):
            v, i = take_value(args, i, '-D'); out.append('/D' + v); continue
        if a.startswith('-U'):
            v, i = take_value(args, i, '-U'); out.append('/U' + v); continue
        if a == '-include':
            v, i = take_value(args, i, a); out.append('/FI' + v); continue
        if a.startswith('-include') and len(a) > 8: out.append('/FI' + a[8:]); i += 1; continue
        if a in ('-o',):
            output, i = take_value(args, i, a); continue
        if a.startswith('-o') and len(a) > 2: output = a[2:]; i += 1; continue
        if a in ('-MF', '-MT'):
            v, i = take_value(args, i, a); warnings.append(f'{a} dependency output is not translated'); continue
        if a.startswith('-L'):
            v, i = take_value(args, i, '-L'); link.append('/LIBPATH:' + v); continue
        if a == '-l':
            v, i = take_value(args, i, a)
            lib = v[2:] if v.startswith('-l') else v
            if lib.lower() in ('m', 'mingw32', 'mingwex', 'gcc', 'gcc_s', 'gcc_eh', 'msvcrt'):
                # These are supplied by the selected MSVC CRT/toolchain, or
                # libm functionality is already in the Windows CRT.
                warnings.append(f'-l{lib}: omitted; supplied by MSVC/Windows runtime')
            elif lib.lower() in ('ws2_32', 'advapi32', 'user32', 'gdi32', 'shell32', 'ole32', 'oleaut32', 'uuid', 'bcrypt'):
                link.append(lib + '.lib')
            else:
                link.append(lib if lib.lower().endswith('.lib') else lib + '.lib')
            continue
        if a.startswith('-l'):
            lib = a[2:]
            if lib.lower() in ('m', 'mingw32', 'mingwex', 'gcc', 'gcc_s', 'gcc_eh', 'msvcrt'):
                warnings.append(f'{a}: omitted; supplied by MSVC/Windows runtime')
            else:
                link.append(lib if lib.lower().endswith('.lib') else lib + '.lib')
            i += 1; continue
        if a.startswith('-std='):
            std = a.split('=', 1)[1].lower()
            if std in ('c99', 'gnu99', 'c11', 'gnu11', 'c17', 'gnu17'):
                out.append('/TC')
                is_cpp = False
                forced_c = True
                forced_cpp = False
                warnings.append(f'{a}: MSVC uses its own C language mode; /TC selects C compilation')
            elif std in ('c++14', 'gnu++14'):
                out.append('/std:c++14'); is_cpp = True; forced_cpp = True; forced_c = False
            elif std in ('c++17', 'gnu++17'):
                out.append('/std:c++17'); is_cpp = True; forced_cpp = True; forced_c = False
            elif std in ('c++20', 'gnu++20'):
                out.append('/std:c++20'); is_cpp = True; forced_cpp = True; forced_c = False
            elif std in ('c++latest',):
                out.append('/std:c++latest'); is_cpp = True; forced_cpp = True; forced_c = False
            else: warnings.append(f'{a} may not be supported by this cl')
            i += 1; continue
        if a in ('-O0',): out.append('/Od'); i += 1; continue
        if a in ('-O1', '-Og'): out.append('/O1'); i += 1; continue
        if a in ('-O2', '-O3', '-Ofast'): out.append('/O2'); i += 1; continue
        if a in ('-g', '-ggdb'): out.append('/Zi'); i += 1; continue
        if a in ('-Wall',): out.append('/W4'); i += 1; continue
        if a in ('-Wextra',): out.append('/W4'); i += 1; continue
        if a in ('-Werror',): out.append('/WX'); i += 1; continue
        if a in ('-fexceptions',): out.append('/EHsc'); i += 1; continue
        if a in ('-fno-exceptions',): out.append('/EHs-c-'); i += 1; continue
        if a in ('-frtti',): out.append('/GR'); i += 1; continue
        if a in ('-fno-rtti',): out.append('/GR-'); i += 1; continue
        if a in ('-MD', '-MMD', '-MDd', '-MP', '-MM', '-M'):
            warnings.append(f'{a}: GCC dependency generation is not a runtime-library option; dependency emission is not yet translated')
            i += 1; continue
        if a in ('-MT', '-MF'):
            v, i = take_value(args, i, a)
            warnings.append(f'{a} {v}: GCC dependency output is not yet translated')
            continue
        if a in ('-fopenmp',): out.append('/openmp'); i += 1; continue
        if a in ('-m64', '-m32'): warnings.append(f'{a} is selected by --arch, not the command line'); i += 1; continue
        if a.startswith('-f') or a.startswith('-W'):
            warnings.append(f'ignored or unsupported GCC option: {a}'); i += 1; continue
        if a.startswith('-'):
            warnings.append(f'unknown GCC option retained as warning: {a}'); i += 1; continue
        # A linker option in GCC syntax that was not handled above.
        if a.lower().endswith(('.c', '.cc', '.cpp', '.cxx', '.c++', '.cxx', '.i', '.ii', '.s', '.asm', '.obj', '.o', '.a', '.lib')):
            sources.append(a)
        else:
            sources.append(a)  # headers and unusual paths are safest to pass through
        i += 1

    if not forced_c and not forced_cpp:
        # GCC chooses the language from the source suffix when the driver is
        # gcc rather than g++. cl defaults to C, so preserve that behavior.
        if any(Path(s.strip('"')).suffix.lower() in ('.cc', '.cpp', '.cxx', '.c++', '.ii') for s in sources):
            is_cpp = True
    if is_cpp: out.append('/TP')
    # Enforce one language mode even when the original command identifies a
    # C++ compiler but explicitly requests a C standard such as -std=c99.
    # This also protects against a build system supplying /TC or /TP itself.
    has_tc = any(x.lower() == '/tc' for x in out)
    has_tp = any(x.lower() == '/tp' for x in out)
    if has_tc and has_tp:
        if not is_cpp:
            out = [x for x in out if x.lower() != '/tp']
        else:
            out = [x for x in out if x.lower() != '/tc']
    if compile_only: out.append('/c')
    # /Fo is only safe for one source. For a multi-source GCC link command,
    # let cl choose intermediate object names and use /Fe for the executable.
    if compile_only and output:
        object_output = output
    elif output:
        out.append('/Fe:' + output)
    if object_output and len(sources) == 1:
        out.append('/Fo:' + object_output)
    elif object_output and len(sources) > 1:
        warnings.append('GCC -o with -c and multiple sources cannot map to one /Fo; omitted /Fo')
    out.extend(sources)
    if link and not compile_only: out.append('/link'); out.extend(link)
    return out, warnings


def find_vsdevcmd() -> str:
    candidates = []
    pf86 = os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')
    pf = os.environ.get('ProgramFiles', r'C:\Program Files')
    candidates += [Path(pf86) / 'Microsoft Visual Studio' / '2022' / x / 'Common7' / 'Tools' / 'VsDevCmd.bat' for x in ('BuildTools','Community','Professional','Enterprise')]
    candidates += [Path(pf) / 'Microsoft Visual Studio' / '2022' / x / 'Common7' / 'Tools' / 'VsDevCmd.bat' for x in ('BuildTools','Community','Professional','Enterprise')]
    for p in candidates:
        if p.exists(): return str(p)
    raise FileNotFoundError('VsDevCmd.bat not found. Install VS 2022 Build Tools with C++ tools, or set VSDEVCMD.')


def main() -> int:
    ap = argparse.ArgumentParser(description='Translate and run GCC/G++ commands using VS 2022 cl.exe')
    ap.add_argument('--arch', choices=['x64', 'x64_x86'], default=os.environ.get('GCC2CL_ARCH', 'x64'), help='x64 target, or x64 host targeting x86')
    ap.add_argument('--compiler', default='g++', help='original compiler name: gcc or g++')
    ap.add_argument('--command', help='GCC command as one quoted string')
    ap.add_argument('--dry-run', action='store_true', help='print translation without executing')
    ap.add_argument('rest', nargs=argparse.REMAINDER, help='use -- followed by GCC arguments')
    ns = ap.parse_args()
    raw = split_command(ns.command) if ns.command else ns.rest
    if raw and raw[0] == '--': raw = raw[1:]
    # In PowerShell/cmd, a quoted command after `--` arrives as one argument.
    # Expand that common form, while leaving a real multi-argument invocation intact.
    if not ns.command and len(raw) == 1 and any(c.isspace() for c in raw[0]):
        raw = split_command(raw[0])
    if not raw: ap.error('supply --command "..." or -- gcc/g++ arguments')
    try: translated, warnings = translate(raw, ns.compiler)
    except ValueError as e: ap.error(str(e))
    translated_text = 'cl ' + subprocess.list2cmdline(translated)
    print(translated_text)
    # Optional audit log for PATH-shim deployments. Command lines can contain
    # secrets, so logging is opt-in via GCC2CL_LOG.
    log_path = os.environ.get('GCC2CL_LOG')
    if log_path:
        try:
            with open(log_path, 'a', encoding='utf-8') as log:
                stamp = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
                log.write(f'[{stamp}] {subprocess.list2cmdline(raw)} => {translated_text}\\n')
        except OSError as e:
            print(f'warning: cannot write GCC2CL_LOG: {e}', file=sys.stderr)
    for w in warnings: print('warning: ' + w, file=sys.stderr)
    if ns.dry_run: return 0
    try:
        configured_dev = os.environ.get('VSDEVCMD', '').strip()
        # VSDEVCMD is sometimes stored by users as \"C:\\...\\VsDevCmd.bat\"
        # or as the literal escaped form \\"C:\\...\\\". Normalize both.
        if configured_dev:
            dev = configured_dev.replace('\\"', '"').strip().strip('"')
            if not Path(dev).is_file():
                print(f'warning: VSDEVCMD does not point to a file; ignoring it: {configured_dev}', file=sys.stderr)
                dev = find_vsdevcmd()
        else:
            dev = find_vsdevcmd()
    except FileNotFoundError as e: print('error:', e, file=sys.stderr); return 2
    archarg = '-arch=x64 -host_arch=x64' if ns.arch == 'x64' else '-arch=x86 -host_arch=x64'
    # Let cmd.exe parse the complete command string. Passing this as one /c
    # argument through subprocess' Windows quoting layer can turn quotes into
    # literal backslash-quote characters when the VS path contains spaces.
    command = 'call ' + subprocess.list2cmdline([dev]) + ' ' + archarg + ' >nul && cl ' + subprocess.list2cmdline(translated)
    print('Using VS developer environment: ' + dev)
    return subprocess.call(command, shell=True)

if __name__ == '__main__': raise SystemExit(main())
