from functools import wraps


def handle_errors(func):
    """
    Decorator that automatically logs errors and re-raises them.
    
    For class methods:
    - Uses self.logger if available
    - Logs full exception stack trace
    - Re-raises the exception for caller to handle
    
    Preserves function metadata using functools.wraps.
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception as error:
            if hasattr(self, 'logger'):
                self.logger.exception(
                    f"Error in {func.__name__}: {error}"
                )
            raise

    return wrapper


def handle_errors_silent(func):
    """
    Decorator that logs errors but doesn't re-raise them.
    
    Useful for non-critical operations where failure shouldn't propagate.
    Returns None if exception occurs.
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception as error:
            if hasattr(self, 'logger'):
                self.logger.warning(
                    f"Error in {func.__name__} (non-critical): {error}"
                )
            return None

    return wrapper


def handle_errors_with_fallback(fallback_value):
    """
    Decorator factory that logs errors and returns a fallback value.
    
    Usage: @handle_errors_with_fallback(fallback_value={})
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except Exception as error:
                if hasattr(self, 'logger'):
                    self.logger.exception(
                        f"Error in {func.__name__}: {error}"
                    )
                return fallback_value

        return wrapper
    return decorator
