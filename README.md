# gcc2cl for Visual Studio 2022 Build Tools

`gcc2cl.py` is a Windows-only command translator/runner. It accepts a normal GCC/G++ command, translates common options to Microsoft `cl.exe` options, initializes the VS 2022 Build Tools environment, and executes the result.

## Prerequisites

1. Windows 10/11.
2. Python 3.9 or newer available as `py` or `python`.
3. Visual Studio 2022 Build Tools installed with **Desktop development with C++**, including the MSVC compiler and a Windows SDK.

The script searches the standard VS 2022 locations. If VS is installed elsewhere, set:

```bat
set VSDEVCMD=D:\VS\2022\BuildTools\Common7\Tools\VsDevCmd.bat
```

## Usage

From `cmd.exe` or PowerShell:

```bat
py gcc2cl.py --arch x64 -- "g++ -std=c++17 -O2 -Iinclude -DAPP=1 -c src\main.cpp -o build\main.obj"
py gcc2cl.py --arch x64_x86 -- "gcc main.c -o build\app.exe -Llib -lfoo"
py gcc2cl.py --dry-run -- "g++ -Wall -Werror main.cpp -o app.exe"
```

`--arch x64` creates the equivalent of the **x64 Native Tools Command Prompt** environment: x64 host, x64 target.

`--arch x64_x86` creates the equivalent of the **x64_x86 Cross Tools Command Prompt** environment: x64 host, x86 target.

The translated `cl` command is printed before execution. Any option that cannot be safely translated is printed as a warning. Use `--dry-run` while integrating with a build system.

You can also pass arguments directly:

```bat
py gcc2cl.py --compiler gcc --arch x64 -- gcc -O2 -c hello.c -o hello.obj
```

## Mappings included

- Includes and defines: `-I`, `-isystem`, `-D`, `-U`, `-include` → `/I`, `/D`, `/U`, `/FI`
- Build mode: `-c`, `-E`, `-S`, `-shared` → `/c`, `/P`, `/FA`, `/DLL`
- Output: `-o app.exe` → `/Fe:app.exe`; one-source `-c -o file.obj` → `/Fo:file.obj`
- Libraries: `-Ldir`, `-lfoo` → `/LIBPATH:dir`, `foo.lib`; common Windows libraries such as `-lws2_32` → `ws2_32.lib`; MinGW runtime `-lm` is omitted because its functionality is supplied by the Windows/MSVC runtime
- Linker options: common `-Wl,--subsystem,windows`, `-Wl,--out-implib,name.lib`, `-Wl,--entry,name`, `-Wl,-Map,file.map`, and `-mwindows`
- Language and optimization: `-std=c89/99/11/17`, `-std=c++11/14/17/20/23`, `-O0/1/2/3`, `-g`
- Warnings and compile flags: `-Wall`, `-Wextra`, `-Werror`, selected `-Wno-*`, `-fopenmp`, exception handling, and RTTI flags
- Dependency flags: `-M`, `-MD`, `-MMD`, `-MF`, and `-MT` are detected and warned about rather than incorrectly mapped to MSVC runtime flags
- GCC response files such as `@options.rsp`, including nested response files and cycle detection

## Automated installation and cleanup

Run `Install-Gcc2Cl.ps1` from any location where the deployment files are stored. It requests elevation, installs to `C:\\Program Files\\Gcc2Cl`, creates the compiler shims, and updates PATH. Before installation it interactively cleans known GCC2CL residue from both User and Machine PATH/environment scopes, including the earlier `%USERPROFILE%\\gcc2cl-shims` deployment. It does not remove unrelated PATH entries.

Examples:

```bat
Install-Gcc2Cl.ps1
Install-Gcc2Cl.ps1 -Architecture x64_x86 -EnableLogging
Install-Gcc2Cl.ps1 -PathScope Machine
```

To uninstall from any location:

```bat
Uninstall-Gcc2Cl.ps1 -RemoveSettings -RemoveDirectory
```

The uninstall script requests elevation, removes the known files and both PATH entries, and deletes the installation directory only when it is empty.

## Dynamic interception of MinGW compiler calls

The recommended way to catch compiler calls is a **PATH shim**, not a polling background process. Windows resolves `gcc`, `g++`, and target-prefixed compiler names by searching PATH. A wrapper with the same name, placed earlier in PATH than MinGW, receives the exact original arguments and invokes this translator.

The workspace also contains the required `mingw-shim.cmd` wrapper. Users should run `Install-Gcc2Cl.ps1` or `Uninstall-Gcc2Cl.ps1` from PowerShell. The installer configures PATH automatically. Logging can be enabled interactively or with `-EnableLogging`.

The installer creates shims for `gcc`, `g++`, `x86_64-w64-mingw32-gcc`, `x86_64-w64-mingw32-g++`, and the i686 variants. Put the shim directory before MinGW in the environment used by Visual Studio, CMake, Ninja, Make, or the IDE. Set `GCC2CL_LOG` only if an audit trail is wanted; command lines can contain credentials or other sensitive values.

Verify resolution with:

```bat
where gcc
where g++
```

The first result should be in `%USERPROFILE%\\gcc2cl-shims`. This catches normal PATH-based invocations without a continuously running service.

It cannot intercept a build tool that invokes `C:\\MinGW\\bin\\gcc.exe` by absolute path, nor non-compiler tools such as `ld`, `ar`, `windres`, or `dlltool`. Those require separate adapters. A system-wide process-creation monitor or Image File Execution Options debugger is not recommended: it is race-prone, requires elevated privileges in many cases, can affect unrelated applications, and may create security or recursion problems. For absolute-path calls, configure the build system's compiler variable or use a CMake/compiler-launcher setting.

## Validation

Before committing changes, run the syntax check:

```powershell
python -m py_compile gcc2cl.py
```

Use dry-run commands to inspect the generated MSVC command without invoking Visual Studio:

```powershell
python gcc2cl.py --dry-run -- "gcc -Wuninitialized -std=c99 main.c Task1.c -o Task1 -lm"
python gcc2cl.py --dry-run -- "g++ -std=c++17 -O2 -Wall main.cpp -o app.exe"
```

The first command should omit `m.lib`, because MSVC/Windows supplies the normal C math functions. Actual compilation and linking require Windows, Visual Studio Build Tools, the Windows SDK, compatible source code, and MSVC-compatible libraries. The previous translation test suite was run during development and removed before preparing the release branch.

## Important compatibility boundary

There is no mathematically complete GCC-to-MSVC conversion: GCC and MSVC have different preprocessors, standard libraries, ABIs, linkers, built-in macros, warning sets, attributes, and runtime libraries. This script translates command-line syntax, not source-code incompatibilities.

In particular, it does not automatically convert:

- GCC-only flags, sanitizers, compiler plugins, and target-specific assembly.
- GCC libraries or `.a` archives. They must be rebuilt as MSVC-compatible `.lib` files.
- GCC linker scripts or GNU `ld` options.
- Make/Ninja/CMake files as a whole; invoke this translator per compiler command, or add a build-system adapter.
- Multi-source `-c -o` commands where GCC emits several objects. MSVC's `/Fo` can name only one output in that form.

For a real build integration, capture each compile/link command separately, translate it, log warnings as errors in CI, and maintain an explicit project-specific mapping table for third-party libraries and unusual flags.

## Recommended next step for production use

Use CMake's MSVC generator or a compiler launcher whenever possible. If the input commands come from a fixed build system, add a `rules.json` file for project-specific replacements, then have the translator reject unknown flags rather than silently ignoring them. The current script is intentionally conservative: it warns about unsupported switches and prints the exact command that will run.

## Contributing with a branch and pull request

Do not commit credentials or place a personal access token in a Git URL. Authenticate locally with GitHub CLI, Git Credential Manager, or SSH. From a fresh terminal:

```powershell
gh auth login
git remote -v
git fetch origin
git switch -c improve-mingw-translation
python -m py_compile gcc2cl.py
git diff --check
git status
```

Review the changes, then commit and push the branch:

```powershell
git add README.md gcc2cl.py Install-Gcc2Cl.ps1 Uninstall-Gcc2Cl.ps1 mingw-shim.cmd LICENSE
git commit -m "Expand MinGW to MSVC command translation"
git push --set-upstream origin improve-mingw-translation
```

Create a pull request with GitHub CLI:

```powershell
gh pr create --base main --head improve-mingw-translation --title "Expand MinGW to MSVC command translation" --body "Expands compiler, linker, library, language-mode, response-file, and diagnostic handling. Validation includes py_compile and dry-run command checks."
```

Alternatively, open the repository on GitHub after pushing and select **Compare & pull request**. Check the diff, confirm that no token or machine-specific path is included, and request review before merging.
