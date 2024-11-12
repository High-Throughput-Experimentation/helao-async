__all__ = ["print_message"]


def print_message(logger, server_name=None, *args, **kwargs):
    """
    Logs a message using the specified logger.

    Parameters:
    logger (logging.Logger): The logger instance to use for logging the message.
    server_name (str, optional): The name of the server. Defaults to None.
    *args: Variable length argument list to be joined into the log message.
    **kwargs: Arbitrary keyword arguments to determine the log level. 
              Recognized keys are "error", "warning", "warn", and "info".

    The log level is determined based on the presence of specific keys in kwargs:
    - If "error" is present, the message is logged as an error.
    - If "warning" or "warn" is present, the message is logged as a warning.
    - If "info" is present or no recognized keys are present, the message is logged as info.
    """

    if "error" in kwargs:
        logger_method = logger.error
    elif "warning" in kwargs or "warn" in kwargs:
        logger_method = logger.warning
    elif "info" in kwargs:
        logger_method = logger.info
    else:
        logger_method = logger.info

    logger_method(" ".join(args))
