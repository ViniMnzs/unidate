"""Stub mínimo de Foundation para testar unidate fora do macOS."""
import time


class NSDate:
    def __init__(self, ts):
        self._ts = float(ts)

    @classmethod
    def dateWithTimeIntervalSince1970_(cls, ts):
        return cls(ts)

    @classmethod
    def dateWithTimeIntervalSinceNow_(cls, secs):
        return cls(time.time() + secs)

    def timeIntervalSince1970(self):
        return self._ts

    def __repr__(self):
        return "NSDate(%s)" % self._ts


class _RunLoop:
    def runMode_beforeDate_(self, mode, date):
        return True


class NSRunLoop:
    @staticmethod
    def currentRunLoop():
        return _RunLoop()


NSDefaultRunLoopMode = "kCFRunLoopDefaultMode"
