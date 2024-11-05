# bokeh_launcher module

This script launches a Bokeh server application based on the provided configuration.

Global Variables:
: LOGGER: Global logger instance.
  CONFIG: Global configuration dictionary.

Usage:
: python bokeh_launcher.py <config_file> <server_key>

Arguments:
: config_file: Path to the configuration file.
  server_key: Key to identify the server configuration in the config file.

Modules:
: sys: Provides access to some variables used or maintained by the interpreter.
  os: Provides a way of using operating system dependent functionality.
  functools.partial: Allows partial function application.
  importlib.import_module: Imports a module programmatically.
  bokeh.server.server.Server: Bokeh server class to create and manage Bokeh applications.
  colorama: Cross-platform colored terminal text.
  helao.helpers.print_message: Custom print message function.
  helao.helpers.logging: Custom logging utilities.
  helao.helpers.config_loader: Configuration loader utility.

Functions:
: makeApp: Function to create a Bokeh application, imported dynamically based on the server configuration.

Execution:
: - Initializes colorama for colored terminal output.
  - Loads the configuration file.
  - Sets up logging based on the configuration.
  - Imports the Bokeh application creation function dynamically.
  - Starts the Bokeh server with the specified host, port, and application.
  - Optionally launches a browser to display the Bokeh application.
