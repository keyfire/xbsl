@echo off
rem The pre-release LSP: serves the CHECKOUT engine instead of the installed wheel.
rem Point the VS Code setting "xbsl.lsp.command" at this file and reload the window;
rem the status bar then reports the checkout's engine version. Remove (or comment out)
rem the setting and reload to return to the installed engine. PYTHONPATH outranks
rem site-packages, so the checkout wins from any working directory; the interpreter
rem needs the [lsp] extra (pygls) and, for the naming rules, [morph].
set PYTHONPATH=%~dp0..
python -m xbsl.lsp %*
