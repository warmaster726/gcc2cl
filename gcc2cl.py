#!/usr/bin/env python3
"""Translate common GCC/MinGW compiler invocations to MSVC cl.exe.

This translates command-line conventions; it cannot convert GCC-only source
extensions, ABIs, object files, archives, or libraries. Use --dry-run to audit
the generated command and warnings before enabling it as a PATH shim.
"""
from __future__ import annotations
import argparse
import datetime
import os
import shlex
import subprocess
import sys
from pathlib import Path

CPP_SUFFIXES = {'.cc', '.cpp', '.cxx', '.c++', '.ii'}
MSVC_SYSTEM_LIBS = {
    'ws2_32', 'advapi32', 'user32', 'gdi32', 'shell32', 'ole32',
    'oleaut32', 'uuid', 'bcrypt', 'crypt32', 'comdlg32', 'imm32',
    'version', 'winmm', 'shlwapi', 'setupapi', 'iphlpapi', 'psapi',
}
def split_command(s: str) -> list[str]:
    """Parse a normal Windows compiler command sufficiently for quoted paths."""
    return shlex.split(s, posix=False)


def expand_response_files(args: list[str], base: Path | None = None, seen=None) -> list[str]:
    """Expand GCC @response files, resolving nested files relative to the cwd."""
    seen = set() if seen is None else seen
    result: list[str] = []
    for arg in args:
        if not arg.startswith('@') or len(arg) == 1:
            result.append(arg)
            continue
        raw = arg[1:].strip('"')
        path = Path(raw)
        if not path.is_absolute() and base:
            path = base / path
        path = path.resolve()
        if path in seen:
            raise ValueError(f'cyclic response file: {path}')
        if not path.is_file():
            result.append(arg)
            continue
        seen.add(path)
        text = path.read_text(encoding='utf-8', errors='replace')
        result.extend(expand_response_files(split_command(text), path.parent, seen))
        seen.remove(path)
    return result


def take_value(args: list[str], i: int, prefix: str) -> tuple[str, int]:
    arg = args[i]
    if arg == prefix:
        if i + 1 >= len(args):
            raise ValueError(f'{prefix} needs a value')
        return args[i + 1], i + 2
    return arg[len(prefix):], i + 1


def compiler_basename(value: str) -> str:
    value = value.strip('"').replace('\\', '/')
    return Path(value).name.lower().removesuffix('.exe')


def add_library(value: str, link: list[str], warnings: list[str]) -> None:
    value = value.strip('"')
    name = value[2:] if value.startswith('-l') else value
    low = name.lower()
    if low == 'm' or low in {'mingw32', 'mingwex', 'gcc', 'gcc_s', 'gcc_eh', 'msvcrt'}:
        warnings.append(f'-l{name}: omitted; supplied by MSVC/Windows runtime')
    elif low == 'stdc++':
        warnings.append('-lstdc++ cannot be converted: rebuild the C++ library as an MSVC .lib')
    elif low in MSVC_SYSTEM_LIBS:
        link.append(name + '.lib')
    elif low.endswith('.lib'):
        link.append(name)
    elif low.endswith(('.a', '.o')):
        warnings.append(f'{value}: GNU archive/object is incompatible with MSVC; rebuild it as .lib/.obj')
        link.append(value)
    else:
        link.append(name + '.lib')


def translate_linker_option(value: str, link: list[str], warnings: list[str]) -> None:
    """Translate common -Wl,foo linker options."""
    value = value.strip()
    if value.startswith('--subsystem,'):
        link.append('/SUBSYSTEM:' + value.split(',', 1)[1].upper())
    elif value.startswith('--out-implib,'):
        link.append('/IMPLIB:' + value.split(',', 1)[1])
    elif value.startswith('--out-implib='):
        link.append('/IMPLIB:' + value.split('=', 1)[1])
    elif value.startswith('--entry,'):
        link.append('/ENTRY:' + value.split(',', 1)[1])
    elif value.startswith('--entry='):
        link.append('/ENTRY:' + value.split('=', 1)[1])
    elif value in ('--debug', '-g'):
        link.append('/DEBUG')
    elif value in ('-s', '--strip-all'):
        link.append('/RELEASE')
    elif value in ('--enable-auto-import', '--enable-runtime-pseudo-reloc'):
        warnings.append(f'{value}: GNU linker behavior is not needed/available in MSVC; omitted')
    elif value.startswith('-Map,'):
        link.append('/MAP:' + value.split(',', 1)[1])
    elif value.startswith('--whole-archive'):
        link.append('/WHOLEARCHIVE')
    elif value.startswith('--no-whole-archive'):
        warnings.append(f'{value}: MSVC has no global inverse switch; library order may need adjustment')
    elif value.startswith('-z'):
        warnings.append(f'{value}: GNU ld option is not translated')
    else:
        warnings.append(f'-Wl,{value}: GNU linker option is not translated')


def translate(args: list[str], compiler: str = 'g++') -> tuple[list[str], list[str]]:
    """Return cl arguments and warnings for one GCC/G++ invocation."""
    args = expand_response_files(args[:], Path.cwd())
    actual = compiler_basename(args[0]) if args and not args[0].startswith(('-', '/')) else compiler_basename(compiler)
    if args and not args[0].startswith(('-', '/')):
        args = args[1:]

    out: list[str] = []
    link: list[str] = []
    sources: list[str] = []
    warnings: list[str] = []
    compile_only = False
    output: str | None = None
    language: str | None = 'c++' if actual in {'g++', 'c++', 'clang++'} else None
    end_options = False
    i = 0

    while i < len(args):
        a = args[i]
        if end_options:
            sources.append(a); i += 1; continue
        if a == '--':
            end_options = True; i += 1; continue
        if a == '-c':
            compile_only = True; i += 1; continue
        if a in ('-E',):
            out.append('/P'); i += 1; continue
        if a == '-S':
            out.append('/FA'); warnings.append('-S generates MSVC assembly syntax, not GNU assembly'); i += 1; continue
        if a in ('-v', '--verbose'):
            out.append('/Bv'); i += 1; continue
        if a in ('-shared',):
            link.append('/DLL'); i += 1; continue
        if a in ('-mwindows',):
            link.append('/SUBSYSTEM:WINDOWS'); i += 1; continue
        if a in ('-municode',):
            link.append('/ENTRY:wmainCRTStartup'); i += 1; continue
        if a in ('-static', '-static-libgcc', '-static-libstdc++', '-shared-libgcc'):
            warnings.append(f'{a}: no direct MSVC equivalent; MSVC CRT selection is controlled by /MD, /MDd, /MT, or /MTd'); i += 1; continue
        if a == '-pthread':
            warnings.append('-pthread: Windows thread support is supplied by the CRT/Win32; omitted'); i += 1; continue
        if a in ('-fPIC', '-fpic', '-fPIE', '-fpie', '-fno-PIE', '-fno-pie'):
            i += 1; continue
        if a.startswith('-Wl,'):
            payload = a[4:]
            # These GNU ld options contain a comma-separated value; do not
            # split them into two unrelated options.
            if payload.startswith(('--subsystem,', '--out-implib,', '--entry,', '-Map,')):
                translate_linker_option(payload, link, warnings)
            else:
                for item in payload.split(','):
                    translate_linker_option(item, link, warnings)
            i += 1; continue
        if a == '-Xlinker':
            value, i = take_value(args, i, a); translate_linker_option(value, link, warnings); continue
        if a.startswith(('-I', '/I')):
            value, i = take_value(args, i, '-I' if a.startswith('-I') else '/I'); out.append('/I' + value); continue
        if a == '-isystem':
            value, i = take_value(args, i, a); out.append('/I' + value); warnings.append('-isystem treated as normal /I'); continue
        if a.startswith('-isystem') and len(a) > len('-isystem'):
            out.append('/I' + a[len('-isystem'):]); warnings.append('-isystem treated as normal /I'); i += 1; continue
        if a.startswith('-D'):
            value, i = take_value(args, i, '-D'); out.append('/D' + value); continue
        if a.startswith('-U'):
            value, i = take_value(args, i, '-U'); out.append('/U' + value); continue
        if a == '-include':
            value, i = take_value(args, i, a); out.append('/FI' + value); continue
        if a.startswith('-include') and len(a) > len('-include'):
            out.append('/FI' + a[len('-include'):]); i += 1; continue
        if a in ('-o',):
            output, i = take_value(args, i, a); continue
        if a.startswith('-o') and len(a) > 2:
            output = a[2:]; i += 1; continue
        if a in ('-L',):
            value, i = take_value(args, i, a); link.append('/LIBPATH:' + value); continue
        if a.startswith('-L'):
            value, i = take_value(args, i, '-L'); link.append('/LIBPATH:' + value); continue
        if a == '-l':
            value, i = take_value(args, i, a); add_library(value, link, warnings); continue
        if a.startswith('-l'):
            add_library(a, link, warnings); i += 1; continue
        if a.startswith('-std='):
            std = a.split('=', 1)[1].lower()
            if std in {'c89', 'gnu89', 'c99', 'gnu99', 'c11', 'gnu11', 'c17', 'gnu17'}:
                language = 'c'; out.append('/TC')
                warnings.append(f'{a}: MSVC does not implement GCC C dialects exactly; /TC selects C compilation')
            elif std in {'c++11', 'gnu++11'}:
                language = 'c++'; out.append('/std:c++14'); warnings.append(f'{a}: nearest supported MSVC mode is /std:c++14')
            elif std in {'c++14', 'gnu++14'}:
                language = 'c++'; out.append('/std:c++14')
            elif std in {'c++17', 'gnu++17'}:
                language = 'c++'; out.append('/std:c++17')
            elif std in {'c++20', 'gnu++20'}:
                language = 'c++'; out.append('/std:c++20')
            elif std in {'c++23', 'gnu++23', 'c++latest'}:
                language = 'c++'; out.append('/std:c++latest')
            else:
                warnings.append(f'{a}: unsupported language dialect')
            i += 1; continue
        if a == '-x':
            value, i = take_value(args, i, a)
            if value in ('c', 'c-header'): language = 'c'; out.append('/TC')
            elif value in ('c++', 'c++-header', 'cxx'): language = 'c++'; out.append('/TP')
            elif value == 'none': language = None
            else: warnings.append(f'-x {value}: language selection not translated')
            continue
        if a in ('-O0',): out.append('/Od'); i += 1; continue
        if a in ('-O1', '-Og'): out.append('/O1'); i += 1; continue
        if a in ('-O2', '-O3', '-Ofast', '-Os'): out.append('/O2'); i += 1; continue
        if a in ('-g', '-ggdb', '-g3'): out.append('/Zi'); i += 1; continue
        if a in ('-Wall', '-Wextra'): out.append('/W4'); i += 1; continue
        if a == '-Werror': out.append('/WX'); i += 1; continue
        if a in ('-Wno-unused-result', '-Wno-unused-variable', '-Wno-uninitialized', '-Wno-sign-compare'):
            i += 1; continue
        if a in ('-Wuninitialized', '-Winvalid-pch', '-Winvalid-offsetof'):
            warnings.append(f'{a}: no direct MSVC equivalent; omitted'); i += 1; continue
        if a in ('-fopenmp',): out.append('/openmp'); i += 1; continue
        if a in ('-fexceptions',): out.append('/EHsc'); i += 1; continue
        if a in ('-fno-exceptions',): out.append('/EHs-c-'); i += 1; continue
        if a in ('-frtti',): out.append('/GR'); i += 1; continue
        if a in ('-fno-rtti',): out.append('/GR-'); i += 1; continue
        if a in ('-MD', '-MMD', '-MP', '-MM', '-M'):
            warnings.append(f'{a}: dependency generation is not translated; use /showIncludes with a dependency parser'); i += 1; continue
        if a in ('-MF', '-MT'):
            value, i = take_value(args, i, a); warnings.append(f'{a} {value}: dependency output is not translated'); continue
        if a in ('-MDd',):
            warnings.append('-MDd: not a standard GCC dependency flag; omitted'); i += 1; continue
        if a in ('-m64', '-m32'):
            warnings.append(f'{a}: target architecture is selected by --arch'); i += 1; continue
        if a.startswith(('-f', '-W')):
            warnings.append(f'ignored or unsupported GCC option: {a}'); i += 1; continue
        if a.startswith('-'):
            warnings.append(f'ignored or unsupported GCC option: {a}'); i += 1; continue
        if a.lower().endswith(('.a', '.o')):
            warnings.append(f'{a}: GNU archive/object is incompatible with MSVC; rebuild it as .lib/.obj')
        sources.append(a); i += 1

    if language is None:
        if any(Path(s.strip('"')).suffix.lower() in CPP_SUFFIXES for s in sources): language = 'c++'
        elif actual in {'g++', 'c++', 'clang++'}: language = 'c++'
    # cl defaults to C, so only add /TP when C++ was selected. Remove an
    # accidental opposing switch supplied by the original command.
    if language == 'c++':
        out = [x for x in out if x.upper() != '/TC']
        if not any(x.upper() == '/TP' for x in out): out.append('/TP')
    elif language == 'c':
        out = [x for x in out if x.upper() != '/TP']
        if not any(x.upper() == '/TC' for x in out): out.append('/TC')

    if compile_only: out.append('/c')
    if output and compile_only and len(sources) == 1:
        out.append('/Fo:' + output)
    elif output:
        out.append('/Fe:' + output)
    elif not compile_only:
        warnings.append('no -o output specified; cl will use its default executable name')
    out.extend(sources)
    if link and not compile_only:
        out.append('/link'); out.extend(link)
    return out, warnings


def find_vsdevcmd() -> str:
    candidates = []
    pf86 = os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')
    pf = os.environ.get('ProgramFiles', r'C:\Program Files')
    for root in (pf86, pf):
        for edition in ('BuildTools', 'Community', 'Professional', 'Enterprise'):
            candidates.append(Path(root) / 'Microsoft Visual Studio' / '2022' / edition / 'Common7' / 'Tools' / 'VsDevCmd.bat')
    for candidate in candidates:
        if candidate.is_file(): return str(candidate)
    raise FileNotFoundError('VsDevCmd.bat not found. Install VS 2022 Build Tools with C++ tools and a Windows SDK, or set VSDEVCMD.')


def main() -> int:
    parser = argparse.ArgumentParser(description='Translate and run GCC/G++ commands using VS 2022 cl.exe')
    parser.add_argument('--arch', choices=['x64', 'x64_x86'], default=os.environ.get('GCC2CL_ARCH', 'x64'))
    parser.add_argument('--compiler', default='g++')
    parser.add_argument('--command')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('rest', nargs=argparse.REMAINDER)
    ns = parser.parse_args()
    raw = split_command(ns.command) if ns.command else ns.rest
    if raw and raw[0] == '--': raw = raw[1:]
    if not ns.command and len(raw) == 1 and any(c.isspace() for c in raw[0]): raw = split_command(raw[0])
    if not raw: parser.error('supply --command "..." or -- gcc/g++ arguments')
    try:
        translated, warnings = translate(raw, ns.compiler)
    except ValueError as exc:
        parser.error(str(exc))
    command_text = 'cl ' + subprocess.list2cmdline(translated)
    print(command_text)
    for warning in warnings: print('warning: ' + warning, file=sys.stderr)
    log_path = os.environ.get('GCC2CL_LOG')
    if log_path:
        try:
            with open(log_path, 'a', encoding='utf-8') as log:
                stamp = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
                log.write(f'[{stamp}] {subprocess.list2cmdline(raw)} => {command_text}\n')
        except OSError as exc:
            print(f'warning: cannot write GCC2CL_LOG: {exc}', file=sys.stderr)
    if ns.dry_run: return 0
    configured = os.environ.get('VSDEVCMD', '').strip().replace('\\"', '"').strip('"')
    try:
        dev = configured if configured and Path(configured).is_file() else find_vsdevcmd()
    except FileNotFoundError as exc:
        print('error: ' + str(exc), file=sys.stderr); return 2
    arch = '-arch=x64 -host_arch=x64' if ns.arch == 'x64' else '-arch=x86 -host_arch=x64'
    print('Using VS developer environment: ' + dev)
    cmd = 'call ' + subprocess.list2cmdline([dev]) + ' ' + arch + ' >nul && cl ' + subprocess.list2cmdline(translated)
    return subprocess.call(cmd, shell=True)


if __name__ == '__main__':
    raise SystemExit(main())
