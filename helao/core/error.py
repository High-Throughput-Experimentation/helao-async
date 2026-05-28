"""Enumeration of error codes returned by HELAO drivers and action servers."""

__all__ = ["ErrorCodes"]

from enum import Enum


class ErrorCodes(str, Enum):
    """Error codes recorded on actions and driver responses.

    Members:
        none: No error.
        critical: Generic critical error.
        critical_error: Critical error variant kept for backward compatibility.
        start_timeout: Action failed to start within the configured time.
        continue_timeout: Action failed to make progress within the timeout.
        done_timeout: Action failed to complete within the timeout.
        in_progress: Operation is still running (reported as a status hint).
        not_available: Requested resource is unavailable.
        ssh_error: SSH transport failure.
        not_initialized: Driver/resource not yet initialized.
        bug: Internal logic bug.
        cmd_error: Underlying command/driver returned an error.
        no_sample: Operation required a sample that was not provided.
        unspecified: Unspecified failure.
        estop: Emergency stop triggered.
        stop: Normal stop requested.
        timeout: Generic timeout.
        setup: Setup/configuration failure.
        numerical: Numerical/math failure.
        motor: Motor/motion failure.
        http: HTTP transport failure.
        not_allowed: Operation is not allowed in the current state.
    """

    none = "none"
    critical = "critical"
    critical_error = "critical_error"
    start_timeout = "start_timeout"
    continue_timeout = "continue_timeout"
    done_timeout = "done_timeout"
    in_progress = "in_progress"
    not_available = "not_available"
    ssh_error = "ssh_error"
    not_initialized = "not_initialized"
    bug = "bug"
    cmd_error = "cmd_error"
    no_sample = "no_sample"
    unspecified = "unspecified"
    estop = "estop"
    stop = "stop"
    timeout = "timeout"
    setup = "setup"
    numerical = "numerical"
    motor = "motor"
    http = "http"
    not_allowed = "not_allowed"
