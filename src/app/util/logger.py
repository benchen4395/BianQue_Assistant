from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
import os
import inspect
import time
import uuid

class LevelFilter:
    """Custom filter that only allows logs of a specific level to pass through"""
    def __init__(self, level):
        """
        Initialize the filter.

        Args:
            level: the log level allowed to pass through
        """
        self.level = level
    
    def filter(self, record):
        """
        Filter log records.

        Args:
            record: log record object

        Returns:
            bool: True means allowed, False means filtered out
        """
        return record.levelno == self.level

def setup_logging(app=None, debug_mode=False):
    """Configure and return the global logger"""
    
    # Create root logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if debug_mode else logging.INFO)

    logger.handlers.clear()

    # Create log directory
    log_dir = 'logs'
    subdirs = ['request_prompt', 'raw_request', 'raw_response']

    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    # Create subdirectories
    for subdir in subdirs:
        subdir_path = os.path.join(log_dir, subdir)
        if not os.path.exists(subdir_path):
            os.makedirs(subdir_path, exist_ok=True)

    # Set up logging format
    formatter = logging.Formatter(
        '%(asctime)s | %(name)-25s | %(levelname)-8s | %(message)s [%(filename)s:%(lineno)d]'
    )
    
    # 1. DEBUG log handler (only enabled in debug_mode)
    if debug_mode:
        debug_handler = RotatingFileHandler(
            os.path.join(log_dir, 'debug.log'),
            maxBytes=100*1024*1024,  # 100MB
            backupCount=5,
            encoding='utf-8'
        )
        debug_handler.setLevel(logging.DEBUG)
        debug_handler.addFilter(LevelFilter(logging.DEBUG))
        debug_handler.setFormatter(formatter)
        logger.addHandler(debug_handler)
    
    # 2. INFO log handler
    info_handler = RotatingFileHandler(
        os.path.join(log_dir, 'info.log'),
        maxBytes=1024*1024*1024,  # 1GB
        backupCount=5,
        encoding='utf-8'
    )
    info_handler.setLevel(logging.INFO)
    info_handler.addFilter(LevelFilter(logging.INFO))
    info_handler.setFormatter(formatter)
    logger.addHandler(info_handler)
    
    # 3. Business log handler
    business_handler = RotatingFileHandler(
        os.path.join(log_dir, 'business.log'),
        maxBytes=1024*1024*1024,  # 1GB
        backupCount=10,
        encoding='utf-8'
    )
    business_handler.setLevel(logging.WARNING)
    business_handler.addFilter(LevelFilter(logging.WARNING))
    business_handler.setFormatter(formatter)
    logger.addHandler(business_handler)
    
    # 4. ERROR log handler
    error_handler = RotatingFileHandler(
        os.path.join(log_dir, 'error.log'),
        maxBytes=1024*1024*1024,  # 1GB
        backupCount=10,  # Error logs keep more backups
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.addFilter(LevelFilter(logging.ERROR))
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)
    
    # 5. All-level log handler (for comprehensive review)
    all_handler = TimedRotatingFileHandler(
        os.path.join(log_dir, 'all.log'),
        when='midnight',  # Rotate daily
        backupCount=7,    # Keep 7 days
        encoding='utf-8'
    )
    all_handler.setLevel(logging.DEBUG if debug_mode else logging.INFO)
    all_handler.setFormatter(formatter)
    logger.addHandler(all_handler)
    
    # 6. Console output (adjust level based on debug_mode)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if debug_mode else logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # If a Flask app is provided, replace its default logger
    if app:
        app.logger = logger
    
    return logger

class Logger:
    """Convenient logging class providing methods for different log levels"""
    
    def __init__(self, logger=None):
        """Initialize the logger instance
        
        Args:
            logger: logger instance; if None, uses the default global logger
        """
        self.logger = logger or logging.getLogger()
    
    def debug(self, message, *args, **kwargs):
        """Log DEBUG level message
        
        Args:
            message: log message
            *args: format arguments
            **kwargs: extra arguments
        """
        self.logger.debug(message, *args, **kwargs)
    
    def info(self, message, *args, **kwargs):
        """Log INFO level message
        
        Args:
            message: log message
            *args: format arguments
            **kwargs: extra arguments
        """
        self.logger.info(message, *args, **kwargs)
    
    def warning(self, message, *args, **kwargs):
        """Log WARNING level message
        
        Args:
            message: log message
            *args: format arguments
            **kwargs: extra arguments
        """
        self.logger.warning(message, *args, **kwargs)
    
    def error(self, message, *args, **kwargs):
        """Log ERROR level message
        
        Args:
            message: log message
            *args: format arguments
            **kwargs: extra arguments
        """
        self.logger.error(message, *args, **kwargs)

# Create global logger
app_logger = setup_logging()
logger = Logger(app_logger)

# Convenience functions using the global logger instance
def debug_log(message, *args, **kwargs):
    """Log DEBUG level message"""
    # Get caller's information
    caller_frame = inspect.currentframe().f_back
    if caller_frame:
        caller_info = inspect.getframeinfo(caller_frame)
        # Create LogRecord with caller info
        record = logging.LogRecord(
            name=logger.logger.name,
            level=logging.DEBUG,
            pathname=caller_info.filename,
            lineno=caller_info.lineno,
            msg=message,
            args=args,
            exc_info=None
        )
        logger.logger.handle(record)
    else:
        logger.debug(message, *args, **kwargs)

def info_log(message, *args, **kwargs):
    """Log INFO level message"""
    # Get caller's information
    caller_frame = inspect.currentframe().f_back
    if caller_frame:
        caller_info = inspect.getframeinfo(caller_frame)
        # Create LogRecord with caller info
        record = logging.LogRecord(
            name=logger.logger.name,
            level=logging.INFO,
            pathname=caller_info.filename,
            lineno=caller_info.lineno,
            msg=message,
            args=args,
            exc_info=None
        )
        logger.logger.handle(record)
    else:
        logger.info(message, *args, **kwargs)

def business_log(message, *args, **kwargs):
    """Log business-related message (WARNING level)"""
    # Get caller's information
    caller_frame = inspect.currentframe().f_back
    if caller_frame:
        caller_info = inspect.getframeinfo(caller_frame)
        # Create LogRecord with caller info
        record = logging.LogRecord(
            name=logger.logger.name,
            level=logging.WARNING,
            pathname=caller_info.filename,
            lineno=caller_info.lineno,
            msg=message,
            args=args,
            exc_info=None
        )
        logger.logger.handle(record)
    else:
        logger.warning(message, *args, **kwargs)

def error_log(message, *args, **kwargs):
    """Log ERROR level message"""
    # Get caller's information
    caller_frame = inspect.currentframe().f_back
    if caller_frame:
        caller_info = inspect.getframeinfo(caller_frame)
        # Create LogRecord with caller info
        record = logging.LogRecord(
            name=logger.logger.name,
            level=logging.ERROR,
            pathname=caller_info.filename,
            lineno=caller_info.lineno,
            msg=message,
            args=args,
            exc_info=None
        )
        logger.logger.handle(record)
    else:
        logger.error(message, *args, **kwargs)

def save_raw_request(req, need_dump : bool = True):
    current_time = int(time.time())
    unique_uuid = uuid.uuid4().hex
    request_id = f"{current_time}-{unique_uuid}"  # Generate a unique ID
    
    if not need_dump:
        return request_id

    sub_dir = os.path.join('logs', 'raw_request')
    if not os.path.isdir(sub_dir):
        return request_id

    print_time = datetime.fromtimestamp(int(current_time)).strftime('%Y-%m-%d %H:%M:%S')
    raw = {
        "id": request_id,
        "time": print_time,
        "args": req.args.to_dict(flat=False),
        "form": req.form.to_dict(flat=False),
        "json": req.get_json(silent=True),
    }

    file_path = os.path.join(sub_dir, f"{request_id}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    return request_id

def save_raw_response(response_ret : str, request_id: str):
    sub_dir = os.path.join('logs', 'raw_response')
    if not os.path.isdir(sub_dir):
        return

    file_path = os.path.join(sub_dir, f"{request_id}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\nBody:\n")
        f.write(response_ret + "\n")

def save_prompt(prompt : str, request_id : str = ""):
    if not request_id:
        return

    sub_dir = os.path.join('logs', 'request_prompt')
    if not os.path.isdir(sub_dir):
        return

    file_path = os.path.join(sub_dir, f"{request_id}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(prompt)