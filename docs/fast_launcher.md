# fast_launcher module

This script is the entry point for launching a Helao server using Uvicorn.

Modules:
: sys: Provides access to some variables used or maintained by the interpreter.
  os: Provides a way of using operating system dependent functionality.
  importlib: Provides the implementation of the import statement.
  uvicorn.config: Provides configuration for Uvicorn.
  uvicorn: ASGI server for Python.
  colorama: Cross-platform colored terminal text.
  helao.helpers.print_message: Custom print message helper.
  helao.helpers.logging: Custom logging helper.
  helao.helpers.config_loader: Custom configuration loader.

Global Variables:
: LOGGER: Global logger instance.
  CONFIG: Global configuration dictionary.

Functions:
: main: The main function that initializes and starts the Uvicorn server.

Usage:
: This script is intended to be run as a standalone script. It requires two command-line arguments:
  1. Configuration argument (confArg)
  2. Server key (server_key)
  <br/>
  Example:
  : python fast_launcher.py <confArg> <server_key>
