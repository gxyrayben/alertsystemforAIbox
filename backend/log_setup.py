"""运行日志落盘:透明捕获 stdout/stderr,把 print 内容按天写入 logs/ 目录。

设计目标(见对话确认):
  - 不改动现有任何 print():在进程启动时把 sys.stdout / sys.stderr 换成 Tee,
    既照常输出到控制台(保证 start.ps1 的重定向、直接运行时的终端显示都不受影响),
    又同时把内容写入日志文件。连报错堆栈、uvicorn 输出都会一起被捕获。
  - 单文件按天轮转:文件名 logs/backend-YYYY-MM-DD.log,每天一个;
    自动清理超过 backup_days 天的旧文件。
  - 日志文件里每行行首补一个时间戳([YYYY-MM-DD HH:MM:SS]),控制台保持原样不加。

日志目录默认解析到「仓库根目录 / logs」(与 start.ps1、.gitignore 的约定一致),
无论后端从哪个 CWD 启动都能定位到同一个 logs/。
"""
import os
import sys
import glob
import time
import datetime
import threading
import logging
import builtins

# 本文件位于 backend/,其上一级即仓库根目录;logs/ 与 start.ps1 约定一致放在根目录下。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(_REPO_ROOT, "logs")


class _DailyWriter:
    """按天切分的日志文件写入器(线程安全)。文件名形如 backend-2026-09-08.log。"""

    def __init__(self, log_dir, prefix="backend", backup_days=30, add_timestamp=True):
        self._dir = log_dir
        self._prefix = prefix
        self._backup_days = backup_days
        self._add_ts = add_timestamp
        self._lock = threading.Lock()
        self._cur_date = None
        self._fh = None
        self._line_start = True  # 当前是否处于某一行的行首(用于补时间戳)
        os.makedirs(log_dir, exist_ok=True)
        self._prune()

    def _path_for(self, date_str):
        return os.path.join(self._dir, f"{self._prefix}-{date_str}.log")

    def _ensure_file(self):
        today = datetime.date.today().strftime("%Y-%m-%d")
        if today != self._cur_date or self._fh is None:
            if self._fh is not None:
                try:
                    self._fh.close()
                except Exception:
                    pass
            # 行缓冲(buffering=1),便于 tail -f / start.ps1 logs 实时跟随
            self._fh = open(self._path_for(today), "a", encoding="utf-8", buffering=1)
            self._cur_date = today
            self._prune()
        return self._fh

    def _apply_timestamp(self, s):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        parts = s.split("\n")
        out = []
        for idx, part in enumerate(parts):
            if self._line_start and part != "":
                out.append(f"[{ts}] {part}")
                self._line_start = False
            else:
                out.append(part)
            if idx < len(parts) - 1:  # 这个分段后面原本有一个换行
                out.append("\n")
                self._line_start = True
        return "".join(out)

    def write(self, s):
        if not s:
            return
        with self._lock:
            try:
                fh = self._ensure_file()
                fh.write(self._apply_timestamp(s) if self._add_ts else s)
            except Exception:
                # 落盘失败绝不能影响主流程(控制台那一路仍然正常)
                pass

    def flush(self):
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.flush()
                except Exception:
                    pass

    def _prune(self):
        """删除超过 backup_days 天的旧日志文件。"""
        if self._backup_days <= 0:
            return
        cutoff = datetime.date.today() - datetime.timedelta(days=self._backup_days)
        for p in glob.glob(os.path.join(self._dir, f"{self._prefix}-*.log")):
            date_part = os.path.basename(p)[len(self._prefix) + 1:-4]  # 去掉 "prefix-" 与 ".log"
            try:
                d = datetime.datetime.strptime(date_part, "%Y-%m-%d").date()
            except ValueError:
                continue  # 不是我们生成的命名,跳过
            if d < cutoff:
                try:
                    os.remove(p)
                except OSError:
                    pass


class _Tee:
    """把写入同时转发给「控制台原始流」和「日志文件写入器」。

    控制台一路保持原样(不加时间戳);日志文件一路由 _DailyWriter 负责补时间戳与切分。
    """

    def __init__(self, real_stream, writer):
        # 直接写入 __dict__,避免 __getattr__ 在初始化期递归
        self.__dict__["_real"] = real_stream
        self.__dict__["_writer"] = writer

    def write(self, s):
        real = self.__dict__["_real"]
        if real is not None:
            try:
                real.write(s)
            except Exception:
                pass
        self.__dict__["_writer"].write(s)

    def flush(self):
        real = self.__dict__["_real"]
        if real is not None:
            try:
                real.flush()
            except Exception:
                pass
        self.__dict__["_writer"].flush()

    def isatty(self):
        real = self.__dict__["_real"]
        try:
            return bool(real and real.isatty())
        except Exception:
            return False

    def fileno(self):
        return self.__dict__["_real"].fileno()

    def __getattr__(self, name):
        # 其余属性(encoding、buffer、writable 等)透传给真实流,兼容第三方库
        return getattr(self.__dict__["_real"], name)


class _AccessLogErrorsOnly(logging.Filter):
    """uvicorn 访问日志降噪：只保留 4xx/5xx，丢弃成功请求(2xx/3xx)那一行。
    record.args = (client, method, path, http_version, status_code)。
    设环境变量 ALERT_LOG_ACCESS=all 可恢复全量访问日志。"""
    def filter(self, record):
        try:
            return int(record.args[4]) >= 400
        except (TypeError, ValueError, IndexError, KeyError):
            return True  # 非标准访问记录一律放行，避免误伤


_installed = False
_real_print = builtins.print


def _located_print(*args, **kwargs):
    """包装内置 print：在输出行首插入 [文件名:行号 函数名()] 定位前缀。
    仅对写往 stdout/stderr（默认）的 print 生效；显式 file=某文件的 print 保持原样。
    设环境变量 ALERT_PRINT_LOC=off 可关闭定位前缀（恢复原生 print）。"""
    file = kwargs.get("file")
    if file is None or file in (sys.stdout, sys.stderr):
        try:
            fr = sys._getframe(1)
            loc = f"[{os.path.basename(fr.f_code.co_filename)}:{fr.f_lineno} {fr.f_code.co_name}()] "
            args = ((f"{loc}{args[0]}",) + args[1:]) if args else (loc,)
        except Exception:
            pass  # 定位失败绝不影响正常打印
    _real_print(*args, **kwargs)


def setup_run_logging(log_dir=None, prefix="backend", backup_days=30, add_timestamp=True):
    """安装运行日志捕获。应在进程启动最早期调用一次(main.py 顶部)。

    可用环境变量覆盖:
      ALERT_LOG_DIR   —— 日志目录(默认仓库根目录 logs/)
      ALERT_LOG_DAYS  —— 保留天数(默认 30;<=0 表示不清理)
      ALERT_LOG_OFF   —— 设为 1 则完全关闭文件落盘(仅控制台)
    """
    global _installed
    if _installed:
        return
    if os.environ.get("ALERT_LOG_OFF") == "1":
        return

    log_dir = log_dir or os.environ.get("ALERT_LOG_DIR") or LOG_DIR
    try:
        backup_days = int(os.environ.get("ALERT_LOG_DAYS", backup_days))
    except (TypeError, ValueError):
        pass

    writer = _DailyWriter(log_dir, prefix=prefix, backup_days=backup_days, add_timestamp=add_timestamp)
    sys.stdout = _Tee(sys.stdout, writer)
    sys.stderr = _Tee(sys.stderr, writer)
    _installed = True

    # 给全工程 print 追加调用点定位（文件:行号 函数）。ALERT_PRINT_LOC=off 可关闭。
    if os.environ.get("ALERT_PRINT_LOC", "on").lower() != "off":
        builtins.print = _located_print

    # uvicorn 访问日志降噪：默认只保留失败请求(4xx/5xx)。ALERT_LOG_ACCESS=all 恢复全量。
    if os.environ.get("ALERT_LOG_ACCESS", "errors").lower() != "all":
        logging.getLogger("uvicorn.access").addFilter(_AccessLogErrorsOnly())

    # 一条启动分隔线,方便在日志里区分每次进程启动
    print(f"===== 后端运行日志开始 {time.strftime('%Y-%m-%d %H:%M:%S')} "
          f"(pid={os.getpid()}, dir={log_dir}) =====")
